from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


WORKSPACE = Path.cwd()
COLLECTOR_DIR = WORKSPACE / "douyin-browser-video-collector"
DEFAULT_OUTPUT_DIR = COLLECTOR_DIR / "transcripts"
DEFAULT_MEDIA_DIR = COLLECTOR_DIR / "downloads"
DEFAULT_MODEL = "large-v3"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download Douyin videos and transcribe them with faster-whisper.")
    parser.add_argument("--input-json", type=Path, default=None, help="Douyin collector JSON. Defaults to the newest outputs/**/douyin_saved_links.json.")
    parser.add_argument("--urls-file", type=Path, default=None, help="Plain text file with one Douyin URL per line.")
    parser.add_argument("--url", default="", help="Transcribe one explicit Douyin URL instead of reading input JSON.")
    parser.add_argument("--title", default="", help="Title to use with --url.")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:9230")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--media-dir", type=Path, default=DEFAULT_MEDIA_DIR)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--keep-media", action="store_true")
    return parser.parse_args()


def today_dir(base: Path) -> Path:
    return base / datetime.now().strftime("%Y%m%d")


def video_id_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    return path.split("/")[-1] if path else "unknown"


def find_latest_collector_json() -> Path:
    candidates = sorted(
        (COLLECTOR_DIR / "outputs").glob("**/douyin_saved_links.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        return candidates[0]
    raise FileNotFoundError("No douyin_saved_links.json found. Pass --input-json, --urls-file, or --url.")


def dedupe_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[str] = set()
    deduped: list[dict[str, object]] = []
    for record in records:
        video_url = str(record.get("video_url") or "").strip()
        if not video_url or video_url in seen:
            continue
        seen.add(video_url)
        deduped.append(record)
    return deduped


def load_records(input_json: Path | None, urls_file: Path | None, explicit_url: str, explicit_title: str) -> tuple[list[dict[str, object]], str]:
    if explicit_url:
        return [{"title": explicit_title or explicit_url, "video_url": explicit_url}], "explicit-url"
    if urls_file:
        records = []
        for line in urls_file.read_text(encoding="utf-8").splitlines():
            line = line.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            records.append({"title": line, "video_url": line})
        return dedupe_records(records), str(urls_file)
    resolved_input = input_json or find_latest_collector_json()
    data = json.loads(resolved_input.read_text(encoding="utf-8"))
    records = data.get("records", [])
    return dedupe_records([record for record in records if record.get("video_url")]), str(resolved_input)


async def export_cookies(cdp_url: str, cookie_file: Path) -> int:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(cdp_url, timeout=60000)
        context = browser.contexts[0]
        cookies = await context.cookies()
        await browser.close()

    lines = ["# Netscape HTTP Cookie File"]
    count = 0
    for cookie in cookies:
        domain = str(cookie.get("domain", ""))
        if "douyin.com" not in domain and "bytedance.com" not in domain and "zijieapi.com" not in domain:
            continue
        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = str(cookie.get("path", "/"))
        secure = "TRUE" if cookie.get("secure") else "FALSE"
        name = str(cookie.get("name", ""))
        if not name:
            continue
        expires = int(cookie.get("expires") or 0)
        if expires < 0:
            expires = 0
        value = str(cookie.get("value", ""))
        lines.append("\t".join([domain, include_subdomains, path, secure, str(expires), name, value]))
        count += 1
    cookie_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return count


def run_yt_dlp(url: str, cookie_file: Path, output_template: Path) -> Path:
    cmd = [
        "yt-dlp",
        "--cookies",
        str(cookie_file),
        "--no-playlist",
        "--no-warnings",
        "--print",
        "after_move:filepath",
        "-o",
        str(output_template),
        url,
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr.strip() or result.stdout.strip()}")
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    if not paths:
        raise RuntimeError("yt-dlp did not report a downloaded filepath.")
    return paths[-1]


async def download_media_with_browser(context, video_url: str, media_path: Path) -> Path:
    page = await context.new_page()
    media_urls: list[str] = []
    audio_urls: list[str] = []

    def on_response(response) -> None:
        content_type = response.headers.get("content-type", "")
        url = response.url.lower()
        if response.status not in (200, 206):
            return
        if "media-audio" in url or "mime_type=audio" in url:
            audio_urls.append(response.url)
        elif "video" in content_type:
            media_urls.append(response.url)

    page.on("response", on_response)
    try:
        await page.goto(video_url, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(12000)
        if not audio_urls and not media_urls:
            raise RuntimeError("No video/audio media response was observed in the browser page.")
        media_url = (audio_urls or media_urls)[0]
        response = await context.request.get(media_url, headers={"Referer": video_url, "Range": "bytes=0-"})
        if response.status not in (200, 206):
            raise RuntimeError(f"Media download failed with HTTP {response.status}.")
        body = await response.body()
        if len(body) < 100_000:
            raise RuntimeError(f"Downloaded media is unexpectedly small: {len(body)} bytes.")
        media_path.write_bytes(body)
        return media_path
    finally:
        await page.close()


def transcribe_media(media_path: Path, model_name: str, device: str, compute_type: str, language: str) -> dict[str, object]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    segments, info = model.transcribe(
        str(media_path),
        language=language or None,
        vad_filter=True,
        beam_size=5,
    )
    segment_items = []
    for segment in segments:
        segment_items.append(
            {
                "start": round(float(segment.start), 3),
                "end": round(float(segment.end), 3),
                "text": segment.text.strip(),
            }
        )
    text = "\n".join(item["text"] for item in segment_items if item["text"])
    return {
        "text": text,
        "segments": segment_items,
        "language": getattr(info, "language", ""),
        "language_probability": getattr(info, "language_probability", None),
        "duration": getattr(info, "duration", None),
    }


def write_outputs(output_json: Path, output_txt: Path, payload: dict[str, object]) -> None:
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        f"模型：{payload['model']}",
        f"保存数量：{payload['transcribed_count']}",
        "",
    ]
    for idx, item in enumerate(payload["records"], 1):
        lines.extend(
            [
                f"{idx}. {item['title']}",
                f"URL：{item['video_url']}",
                "转写：",
                str(item.get("transcript", "")).strip(),
                "",
            ]
        )
    output_txt.write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    args = parse_args()
    started = time.perf_counter()
    records, input_source = load_records(args.input_json, args.urls_file, args.url, args.title)
    if args.max_records:
        records = records[: args.max_records]
    output_dir = today_dir(args.output_dir.resolve())
    media_dir = today_dir(args.media_dir.resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    media_dir.mkdir(parents=True, exist_ok=True)
    cookie_file = output_dir / "douyin_cookies.txt"
    cookie_count = await export_cookies(args.cdp_url, cookie_file)

    results: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(args.cdp_url, timeout=60000)
        context = browser.contexts[0]
        for record in records:
            video_url = str(record["video_url"])
            video_id = video_id_from_url(video_url)
            title = str(record.get("title") or video_id)
            media_path = media_dir / f"{video_id}.mp4"
            try:
                try:
                    media_path = await download_media_with_browser(context, video_url, media_path)
                except Exception as browser_exc:
                    output_template = media_dir / f"{video_id}.%(ext)s"
                    print(f"[WARN] browser media download failed, falling back to yt-dlp: {browser_exc}", flush=True)
                    media_path = run_yt_dlp(video_url, cookie_file, output_template)
                transcription = transcribe_media(media_path, args.model, args.device, args.compute_type, args.language)
                item = {
                    "title": title,
                    "video_url": video_url,
                    "video_id": video_id,
                    "media_path": str(media_path),
                    "transcript": transcription["text"],
                    "segments": transcription["segments"],
                    "detected_language": transcription["language"],
                    "language_probability": transcription["language_probability"],
                    "duration": transcription["duration"],
                }
                results.append(item)
                print(f"[INFO] transcribed: {video_url}", flush=True)
                if not args.keep_media:
                    media_path.unlink(missing_ok=True)
            except Exception as exc:
                failures.append({"title": title, "video_url": video_url, "error": str(exc)})
                print(f"[WARN] failed: {video_url} | {exc}", flush=True)
        await browser.close()

    payload = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "model": args.model,
        "device": args.device,
        "compute_type": args.compute_type,
        "cookie_count": cookie_count,
        "input_source": input_source,
        "transcribed_count": len(results),
        "failed_count": len(failures),
        "records": results,
        "failures": failures,
    }
    output_json = output_dir / "douyin_video_transcripts.json"
    output_txt = output_dir / "douyin_video_transcripts.txt"
    write_outputs(output_json, output_txt, payload)
    print(json.dumps({"transcribed_count": len(results), "failed_count": len(failures), "json": str(output_json), "txt": str(output_txt)}, ensure_ascii=False), flush=True)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
