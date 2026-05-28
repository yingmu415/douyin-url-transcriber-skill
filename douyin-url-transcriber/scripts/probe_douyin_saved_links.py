from __future__ import annotations

import asyncio
import argparse
import json
import random
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from urllib.parse import parse_qs, urlparse


URL = "https://www.douyin.com/jingxuan/search/%E5%86%85%E8%80%97?type=general"
WORKSPACE = Path.cwd()
COLLECTOR_DIR = WORKSPACE / "douyin-browser-video-collector"
OUT_DIR = COLLECTOR_DIR / "outputs"
KEYWORDS_FILE = WORKSPACE / "xhs-browser-note-collector" / "keywords.txt"
MIN_LIKES = 100
MAX_FOLLOWERS = 10_000
WITHIN_DAYS = 180
MAX_CARDS = 8
SCROLL_PAGES = 3
MAX_SAVED = 20
KEYWORD_DELAY = "20,45"
ACTION_DELAY = "3,8"
DETAIL_DELAY = "8,15"
COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)(万|w|W|千|k|K)?")
PUBLISH_DATE_RE = re.compile(r"(\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}月\d{1,2}日|\d+天前|\d+周前|昨天|前天)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe Douyin search cards and save high-like video links.")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9230")
    parser.add_argument("--source-url", default=URL)
    parser.add_argument("--keyword", default="", help="Collect one explicit keyword instead of reading keywords.txt.")
    parser.add_argument("--keywords-file", type=Path, default=KEYWORDS_FILE)
    parser.add_argument("--keywords-per-dimension", type=int, default=3)
    parser.add_argument("--max-keywords", type=int, default=0, help="Optional safety cap across selected keywords. 0 means no cap.")
    parser.add_argument("--min-likes", type=int, default=MIN_LIKES)
    parser.add_argument("--max-followers", type=int, default=MAX_FOLLOWERS)
    parser.add_argument("--within-days", type=int, default=WITHIN_DAYS)
    parser.add_argument("--max-cards", type=int, default=MAX_CARDS)
    parser.add_argument("--scroll-pages", type=int, default=SCROLL_PAGES)
    parser.add_argument("--max-saved", type=int, default=MAX_SAVED, help="Stop after saving this many validated records. Use 0 for no cap.")
    parser.add_argument("--keyword-delay", default=KEYWORD_DELAY, help="Random delay range in seconds between keywords, e.g. 20,45.")
    parser.add_argument("--action-delay", default=ACTION_DELAY, help="Random delay range in seconds between scroll/click actions.")
    parser.add_argument("--detail-delay", default=DETAIL_DELAY, help="Random delay range in seconds before/after opening detail pages.")
    parser.add_argument("--fast", action="store_true", help="Disable low-risk random delays for local debugging only.")
    parser.add_argument("--skip-url-validation", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=OUT_DIR)
    return parser.parse_args()


def parse_delay_range(raw: str) -> tuple[float, float]:
    parts = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if len(parts) == 1:
        value = max(0.0, float(parts[0]))
        return value, value
    if len(parts) != 2:
        raise ValueError(f"Delay range must be one number or two comma-separated numbers: {raw}")
    low = max(0.0, float(parts[0]))
    high = max(0.0, float(parts[1]))
    if low > high:
        low, high = high, low
    return low, high


async def human_delay(delay_range: tuple[float, float], enabled: bool = True) -> None:
    if not enabled:
        return
    low, high = delay_range
    if high <= 0:
        return
    await asyncio.sleep(random.uniform(low, high))


def parse_count(raw: str) -> int | None:
    raw = (raw or "").replace(",", "").strip()
    match = COUNT_RE.search(raw)
    if not match:
        return None
    value = float(match.group(1))
    unit = (match.group(2) or "").lower()
    if unit in {"万", "w"}:
        value *= 10000
    elif unit in {"千", "k"}:
        value *= 1000
    return int(value)


def parse_followers_text(text: str) -> tuple[int | None, str]:
    patterns = [
        r"粉丝\s*(\d+(?:\.\d+)?\s*(?:万|w|W|千|k|K)?)",
        r"(\d+(?:\.\d+)?\s*(?:万|w|W|千|k|K)?)\s*粉丝",
    ]
    for pattern in patterns:
        match = re.search(pattern, text or "")
        if match:
            raw = match.group(1).strip()
            return parse_count(raw), raw
    return None, ""


def parse_card_text(text: str) -> dict[str, object]:
    parts = text.split(" ", 2)
    duration = parts[0] if parts else ""
    likes_text = parts[1] if len(parts) > 1 else ""
    rest = parts[2] if len(parts) > 2 else text
    author = ""
    if "@" in rest:
        author = "@" + rest.split("@", 1)[1].split("·", 1)[0].strip()
    title = rest.split("@", 1)[0].strip()
    publish_date = extract_publish_date(rest)
    return {
        "duration": duration,
        "likes_text": likes_text,
        "likes": parse_count(likes_text),
        "title": title,
        "author": author,
        "publish_date": publish_date,
    }


def today_local() -> date:
    return datetime.now().date()


def extract_publish_date(text: str) -> str:
    match = PUBLISH_DATE_RE.search(text or "")
    return match.group(1) if match else ""


def parse_publish_date(raw: str, today: date | None = None) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None
    today = today or today_local()
    for fmt in ("%Y年%m月%d日",):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})日", value)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        for year in (today.year, today.year - 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate <= today:
                return candidate
        return None
    if value == "昨天":
        return today - timedelta(days=1)
    if value == "前天":
        return today - timedelta(days=2)
    relative = re.fullmatch(r"(\d+)(天前|周前)", value)
    if relative:
        amount = int(relative.group(1))
        if relative.group(2) == "天前":
            return today - timedelta(days=amount)
        return today - timedelta(days=amount * 7)
    return None


def is_publish_within_days(raw: str, within_days: int, today: date | None = None) -> bool:
    parsed = parse_publish_date(raw, today=today)
    if parsed is None:
        return False
    return parsed >= ((today or today_local()) - timedelta(days=within_days))


def has_verification_challenge(frame_urls: list[str]) -> bool:
    return any("verifycenter/captcha" in url or "verify.zijieapi.com" in url for url in frame_urls)


def response_has_verify_check(text: str) -> bool:
    lowered = (text or "").lower()
    return "verify_check" in lowered and ("search_nil_type" in lowered or "verify" in lowered)


def should_inspect_verification_response(url: str, content_type: str) -> bool:
    lowered_url = (url or "").lower()
    lowered_type = (content_type or "").lower()
    if not any(host in lowered_url for host in ("douyin.com", "douyinpic.com", "douyinstatic.com")):
        return False
    if lowered_type and not any(kind in lowered_type for kind in ("json", "text", "javascript")):
        return False
    return "search" in lowered_url or "aweme" in lowered_url or "general" in lowered_url


def parse_keywords_file(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Keywords file does not exist: {path}")
    dimensions: list[dict[str, object]] = []
    current_name: str | None = None
    current_keywords: list[str] = []

    def flush() -> None:
        nonlocal current_name, current_keywords
        if current_name and current_keywords:
            deduped: list[str] = []
            seen: set[str] = set()
            for keyword in current_keywords:
                if keyword and keyword not in seen:
                    deduped.append(keyword)
                    seen.add(keyword)
            if deduped:
                dimensions.append({"name": current_name, "keywords": deduped})
        current_name = None
        current_keywords = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            flush()
            current_name = line[1:-1].strip()
            continue
        if current_name is None:
            raise ValueError("Keyword lines must appear below [dimension] headers.")
        current_keywords.append(line)
    flush()
    return dimensions


def choose_keywords(dimensions: list[dict[str, object]], per_dimension: int, max_keywords: int) -> list[dict[str, str]]:
    selections: list[dict[str, str]] = []
    for dimension in dimensions:
        for keyword in [str(item) for item in dimension["keywords"]][:per_dimension]:
            selections.append({"dimension": str(dimension["name"]), "keyword": keyword})
            if max_keywords and len(selections) >= max_keywords:
                return selections
    return selections


def build_search_url(keyword: str) -> str:
    return f"https://www.douyin.com/jingxuan/search/{quote(keyword)}?type=general"


def dated_output_dir(base: Path) -> Path:
    return base / today_local().strftime("%Y%m%d")


def is_response_verification_blocked(verification_state: dict[str, object] | None) -> bool:
    return bool(verification_state and verification_state.get("blocked"))


async def is_platform_verification_blocked(page, verification_state: dict[str, object] | None = None) -> bool:
    return is_response_verification_blocked(verification_state) or await is_verification_blocked(page)


async def wait_results(page, verification_state: dict[str, object] | None = None) -> bool:
    for _ in range(35):
        if await is_platform_verification_blocked(page, verification_state):
            return False
        text = await page.evaluate("() => document.body?.innerText || ''")
        if "为你找到以下结果" in text or "问问AI" in text:
            return True
        await page.wait_for_timeout(1000)
    return False


async def is_verification_blocked(page) -> bool:
    return has_verification_challenge([frame.url for frame in page.frames])


CARD_SELECTOR_JS = r"""
() => {
  const clean = s => (s || '').trim().replace(/\s+/g, ' ');
  const rows = Array.from(document.querySelectorAll('div, section, article, li, button'))
    .map((el, i) => {
      const r = el.getBoundingClientRect();
      const text = clean(el.innerText || el.textContent);
      return {i, text, x:r.x,y:r.y,w:r.width,h:r.height, cls:String(el.className||'')};
    })
    .filter(c => c.x > 170 && c.y > 100 && c.w > 160 && c.w < 380 && c.h > 180 && c.h < 560)
    .filter(c => c.text.includes('@') && !c.text.includes('相关搜索'))
    .sort((a,b) => (a.y-b.y) || (a.x-b.x));
  const seenPositions = [];
  const seenTexts = new Set();
  const cards = [];
  for (const c of rows) {
    const textKey = c.text.replace(/\d{2}:\d{2}\s+\S+\s+/, '').slice(0, 80);
    const nearExisting = seenPositions.some(p => Math.abs(p.x - c.x) < 4 && Math.abs(p.y - c.y) < 4);
    if (nearExisting || seenTexts.has(textKey)) continue;
    seenPositions.push({x: c.x, y: c.y});
    seenTexts.add(textKey);
    cards.push({text:c.text.slice(0,600), x:c.x,y:c.y,w:c.w,h:c.h, cls:c.cls.slice(0,120)});
  }
  return cards.slice(0, 30);
}
"""


async def extract_cards(page) -> list[dict[str, object]]:
    return await page.evaluate(CARD_SELECTOR_JS)


async def wait_cards(page, action_delay: tuple[float, float], slow: bool) -> list[dict[str, object]]:
    for _ in range(20):
        cards = await extract_cards(page)
        if cards:
            return cards
        await page.mouse.wheel(0, 500)
        await human_delay(action_delay, slow)
    return []


async def collect_search_cards(page, scroll_pages: int, action_delay: tuple[float, float], slow: bool) -> list[dict[str, object]]:
    collected: dict[str, dict[str, object]] = {}
    for _ in range(max(1, scroll_pages)):
        cards = await extract_cards(page)
        for card in cards:
            meta = parse_card_text(str(card["text"]))
            key = "|".join(
                [
                    str(meta.get("title", ""))[:60],
                    str(meta.get("author", "")),
                    str(meta.get("publish_date", "")),
                    str(meta.get("likes_text", "")),
                ]
            )
            if key.strip("|") and key not in collected:
                collected[key] = {**card, **meta}
        await page.mouse.wheel(0, 900)
        await human_delay(action_delay, slow)
    return list(collected.values())


async def locate_matching_card(page, title: str, scroll_pages: int, action_delay: tuple[float, float], slow: bool) -> dict[str, object] | None:
    title_prefix = title[:18]
    for _ in range(max(1, scroll_pages)):
        cards = await extract_cards(page)
        for card in cards:
            if title_prefix and title_prefix in str(card["text"]):
                return card
        await page.mouse.wheel(0, 900)
        await human_delay(action_delay, slow)
    return None


async def click_card(page, card: dict[str, object]) -> None:
    await page.mouse.click(
        float(card["x"]) + float(card["w"]) / 2,
        float(card["y"]) + min(120, float(card["h"]) / 2),
    )


async def click_card_by_title(page, title: str) -> bool:
    title_prefix = (title or "")[:18]
    if not title_prefix:
        return False
    try:
        await page.get_by_text(title_prefix, exact=False).first.click(timeout=6000)
        return True
    except Exception:
        return False


async def extract_followers_from_open_modal(page) -> tuple[int | None, str]:
    text = await page.evaluate("() => document.body?.innerText || ''")
    return parse_followers_text(text)


async def extract_followers_from_video_url(page, video_url: str) -> tuple[int | None, str]:
    await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(6000)
    text = await page.evaluate("() => document.body?.innerText || ''")
    return parse_followers_text(text)


async def open_card_and_extract_link(
    page,
    source_url: str,
    card: dict[str, object],
    scroll_pages: int,
    action_delay: tuple[float, float],
    detail_delay: tuple[float, float],
    slow: bool,
) -> tuple[str, str]:
    await page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
    await wait_results(page)
    current_card = await locate_matching_card(page, str(card["title"]), scroll_pages, action_delay, slow) or card
    await human_delay(action_delay, slow)
    clicked = await click_card_by_title(page, str(card["title"]))
    if not clicked:
        await click_card(page, current_card)
    await human_delay(detail_delay, slow)
    modal_id = parse_qs(urlparse(page.url).query).get("modal_id", [""])[0]
    if not modal_id and clicked:
        await click_card(page, current_card)
        await human_delay(detail_delay, slow)
        modal_id = parse_qs(urlparse(page.url).query).get("modal_id", [""])[0]
    video_url = f"https://www.douyin.com/video/{modal_id}" if modal_id else ""
    return modal_id, video_url


async def validate_video_url(context, video_url: str, modal_id: str) -> dict[str, object]:
    page = await context.new_page()
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)
        title = await page.title()
        text = await page.evaluate("() => document.body?.innerText || ''")
        final_url = page.url
        ok = (
            bool(modal_id)
            and f"/video/{modal_id}" in final_url
            and "抖音" in title
            and "登录后" not in text[:500]
        )
        return {
            "ok": ok,
            "requested_url": video_url,
            "final_url": final_url,
            "title": title,
        }
    except Exception as exc:
        return {
            "ok": False,
            "requested_url": video_url,
            "final_url": "",
            "title": "",
            "error": str(exc),
        }
    finally:
        await page.close()


def build_text_output(records: list[dict[str, object]], criteria: dict[str, object]) -> str:
    lines = [
        f"条件：{criteria['within_days']}天内，点赞 > {criteria['min_likes']}，粉丝 < {criteria['max_followers']}",
        f"保存数量：{len(records)}",
        "",
    ]
    for idx, record in enumerate(records, 1):
        lines.extend(
            [
                f"{idx}. {record['title']}",
                (
                    f"   关键词：{record['keyword']} | 作者：{record['author']} | "
                    f"点赞：{record['likes_text']} | 粉丝：{record['followers_text']} | "
                    f"发布时间：{record['publish_date']}"
                ),
                f"   {record['video_url']}",
                "",
            ]
        )
    return "\n".join(lines)


def write_outputs(
    output_json: Path,
    output_txt: Path,
    criteria: dict[str, object],
    selections: list[dict[str, str]],
    keyword_stats: list[dict[str, object]],
    records: list[dict[str, object]],
    skipped: list[dict[str, object]],
    run_info: dict[str, object],
) -> None:
    payload = {
        "criteria": criteria,
        "run_info": run_info,
        "selected_keywords": selections,
        "keyword_stats": keyword_stats,
        "saved_count": len(records),
        "skipped_count": len(skipped),
        "records": records,
        "skipped": skipped,
    }
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    output_txt.write_text(build_text_output(records, criteria), encoding="utf-8")


async def main() -> int:
    args = parse_args()
    from playwright.async_api import async_playwright
    started_at = datetime.now()
    started_perf = time.perf_counter()
    keyword_delay = parse_delay_range(args.keyword_delay)
    action_delay = parse_delay_range(args.action_delay)
    detail_delay = parse_delay_range(args.detail_delay)
    slow = not args.fast

    if args.keyword.strip():
        selections = [{"dimension": "manual", "keyword": args.keyword.strip()}]
    else:
        selections = choose_keywords(
            parse_keywords_file(args.keywords_file),
            per_dimension=args.keywords_per_dimension,
            max_keywords=args.max_keywords,
        )

    output_dir = dated_output_dir(args.output_dir.resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    output_json = output_dir / "douyin_saved_links.json"
    output_txt = output_dir / "douyin_saved_links.txt"
    criteria = {
        "within_days": args.within_days,
        "min_likes": args.min_likes,
        "max_followers": args.max_followers,
        "max_cards_per_keyword": args.max_cards,
        "scroll_pages": args.scroll_pages,
        "max_saved": args.max_saved,
        "keyword_delay": args.keyword_delay if slow else "disabled",
        "action_delay": args.action_delay if slow else "disabled",
        "detail_delay": args.detail_delay if slow else "disabled",
        "validate_urls": not args.skip_url_validation,
        "cdp_url": args.cdp_url,
    }
    all_records: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    keyword_stats: list[dict[str, object]] = []
    seen_video_urls: set[str] = set()
    run_info: dict[str, object] = {
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": "",
        "elapsed_seconds": 0,
        "blocked": False,
        "blocked_at_keyword_index": None,
        "blocked_at_keyword": "",
        "blocked_reason": "",
        "blocked_source_url": "",
    }
    verification_state: dict[str, object] = {
        "blocked": False,
        "reason": "",
        "source_url": "",
    }

    def refresh_run_info() -> None:
        run_info["elapsed_seconds"] = round(time.perf_counter() - started_perf, 3)
        run_info["finished_at"] = datetime.now().isoformat(timespec="seconds")

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url, timeout=60000)
        context = browser.contexts[0]
        page = await context.new_page()

        async def inspect_verification_response(response) -> None:
            if verification_state["blocked"]:
                return
            try:
                content_type = response.headers.get("content-type", "")
                if not should_inspect_verification_response(response.url, content_type):
                    return
                text = await response.text()
            except Exception:
                return
            if response_has_verify_check(text):
                verification_state["blocked"] = True
                verification_state["reason"] = "search_api_verify_check"
                verification_state["source_url"] = response.url

        page.on("response", lambda response: asyncio.create_task(inspect_verification_response(response)))

        for keyword_index, selection in enumerate(selections, 1):
            if args.max_saved and len(all_records) >= args.max_saved:
                break
            if keyword_index > 1:
                await human_delay(keyword_delay, slow)
            keyword = selection["keyword"]
            source_url = build_search_url(keyword)
            print(f"[INFO] Keyword {keyword_index}/{len(selections)}: {keyword}", flush=True)
            await page.goto(source_url, wait_until="domcontentloaded", timeout=60000)
            await wait_results(page, verification_state)
            if await is_platform_verification_blocked(page, verification_state):
                refresh_run_info()
                run_info["blocked"] = True
                run_info["blocked_at_keyword_index"] = keyword_index
                run_info["blocked_at_keyword"] = keyword
                run_info["blocked_reason"] = str(verification_state.get("reason") or "platform_verification_required")
                run_info["blocked_source_url"] = str(verification_state.get("source_url") or page.url)
                skipped.append(
                    {
                        "keyword": keyword,
                        "keyword_index": keyword_index,
                        "reason": run_info["blocked_reason"],
                        "elapsed_seconds": run_info["elapsed_seconds"],
                        "url": run_info["blocked_source_url"],
                    }
                )
                keyword_stats.append({"keyword": keyword, "cards_seen": 0, "chosen": 0, "blocked": True})
                print("[WARN] Douyin verification challenge detected. Please solve it in the 9230 Chrome window, then rerun.", flush=True)
                write_outputs(output_json, output_txt, criteria, selections, keyword_stats, all_records, skipped, run_info)
                break

            await wait_cards(page, action_delay, slow)
            cards = await collect_search_cards(page, args.scroll_pages, action_delay, slow)
            if not cards:
                skipped.append({"keyword": keyword, "reason": "no_search_cards"})
                keyword_stats.append({"keyword": keyword, "cards_seen": 0, "chosen": 0})
                continue
            chosen: list[dict[str, object]] = []
            for card in cards:
                if not isinstance(card["likes"], int) or card["likes"] <= args.min_likes:
                    skipped.append({"keyword": keyword, "reason": "likes_too_low_or_unknown", "card_text": card["text"]})
                    continue
                if not is_publish_within_days(str(card["publish_date"]), args.within_days):
                    skipped.append({"keyword": keyword, "reason": "publish_date_out_of_range", "card_text": card["text"]})
                    continue
                chosen.append(card)
                if len(chosen) >= args.max_cards:
                    break
            keyword_stats.append({"keyword": keyword, "cards_seen": len(cards), "chosen": len(chosen)})

            for idx, card in enumerate(chosen, 1):
                modal_id, video_url = await open_card_and_extract_link(
                    page,
                    source_url,
                    card,
                    args.scroll_pages,
                    action_delay,
                    detail_delay,
                    slow,
                )
                if not modal_id:
                    skipped.append({"keyword": keyword, "reason": "modal_id_missing", "card_text": card["text"]})
                    print(f"[WARN] skipped no modal: {keyword} | {card['likes_text']} {str(card['title'])[:35]}", flush=True)
                    continue
                if video_url in seen_video_urls:
                    skipped.append({"keyword": keyword, "reason": "duplicate_video_url", "video_url": video_url, "card_text": card["text"]})
                    print(f"[WARN] skipped duplicate url: {video_url}", flush=True)
                    continue
                followers, followers_text = await extract_followers_from_open_modal(page)
                if followers is None and video_url:
                    followers, followers_text = await extract_followers_from_video_url(page, video_url)
                if followers is None:
                    skipped.append({"keyword": keyword, "reason": "followers_unknown", "video_url": video_url, "card_text": card["text"]})
                    print(f"[WARN] skipped followers unknown: {video_url}", flush=True)
                    continue
                if followers >= args.max_followers:
                    skipped.append(
                        {
                            "keyword": keyword,
                            "reason": "followers_too_high",
                            "followers": followers,
                            "followers_text": followers_text,
                            "video_url": video_url,
                            "card_text": card["text"],
                        }
                    )
                    print(f"[WARN] skipped followers high: {followers_text} | {video_url}", flush=True)
                    continue
                record = {
                    "dimension": selection["dimension"],
                    "keyword": keyword,
                    "title": card["title"],
                    "author": card["author"],
                    "duration": card["duration"],
                    "likes_text": card["likes_text"],
                    "likes": card["likes"],
                    "followers": followers,
                    "followers_text": followers_text,
                    "publish_date": card["publish_date"],
                    "modal_id": modal_id,
                    "video_url": video_url,
                    "search_modal_url": page.url,
                    "card_text": card["text"],
                }
                if not args.skip_url_validation:
                    validation = await validate_video_url(context, video_url, modal_id)
                    record["url_validation"] = validation
                    if not validation["ok"]:
                        skipped.append(
                            {
                                "keyword": keyword,
                                "reason": "url_not_openable",
                                "video_url": video_url,
                                "validation": validation,
                                "card_text": card["text"],
                            }
                        )
                        print(f"[WARN] skipped url not openable: {video_url}", flush=True)
                        continue
                all_records.append(record)
                seen_video_urls.add(video_url)
                print(f"[INFO] saved {idx}: {keyword} | {video_url}", flush=True)
                if args.max_saved and len(all_records) >= args.max_saved:
                    break
            refresh_run_info()
            write_outputs(output_json, output_txt, criteria, selections, keyword_stats, all_records, skipped, run_info)

        refresh_run_info()
        write_outputs(output_json, output_txt, criteria, selections, keyword_stats, all_records, skipped, run_info)
        print(json.dumps({"saved_count": len(all_records), "json": str(output_json), "txt": str(output_txt)}, ensure_ascii=False), flush=True)

        await page.close()
        await browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
