---
name: douyin-url-transcriber
description: Collect Douyin video URLs from logged-in Douyin web search, filter low-follower high-like videos by configurable likes/followers/time window, download Douyin videos through an authenticated browser session, and transcribe them locally with faster-whisper. Use when the user asks to scrape/collect Douyin URLs, find low-follower high-like Douyin videos, save Douyin video links, download Douyin videos, or convert Douyin video speech to text.
---

# Douyin URL Transcriber

## Overview

Use this skill for a two-stage Douyin workflow:

1. Collect filtered Douyin video URLs from a logged-in browser session.
2. Download those videos and save local transcripts with `faster-whisper`.

Keep the stages separate unless the user explicitly asks for an end-to-end run. Douyin search collection is more likely to hit verification; transcription is slower and model-dependent.

## Requirements

- Require a logged-in Chrome/Chromium session with CDP enabled. Default: `http://127.0.0.1:9230`.
- Prefer the project workspace as the working directory when available.
- Require Python dependencies: `playwright`, `yt-dlp`, and `faster-whisper`.
- Use `faster-whisper` only. Do not use original OpenAI Whisper for this workflow.
- Prefer model `large-v3` for Chinese transcription quality. Use `device=cpu` and `compute_type=int8` unless the user has configured GPU.

## URL Collection

Run `scripts/probe_douyin_saved_links.py` to search Douyin and save filtered URLs.

Map natural-language filters to script parameters:

- Time range -> `--within-days`
- Likes greater than threshold -> `--min-likes`
- Author followers below threshold -> `--max-followers`

Default filters:

- `--within-days 180`
- `--min-likes 100`
- `--max-followers 10000`

Example:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\probe_douyin_saved_links.py --cdp-url http://127.0.0.1:9230 --within-days 180 --min-likes 500 --max-followers 5000
```

The script reads keywords from `xhs-browser-note-collector/keywords.txt` by default when run from the original workspace. If packaging this skill into another project, pass `--keywords-file` explicitly.

Outputs go to `douyin-browser-video-collector/outputs/YYYYMMDD/` when the script is run from the original project structure.

## Video Transcription

Run `scripts/transcribe_douyin_urls.py` to download videos and create transcripts.

Supported inputs:

- `--url`: one explicit Douyin video URL
- `--urls-file`: plain text file with one URL per line
- `--input-json`: collector output JSON containing `records[].video_url`
- No input: use newest `outputs/**/douyin_saved_links.json`

Example single URL:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\transcribe_douyin_urls.py --cdp-url http://127.0.0.1:9230 --url "https://www.douyin.com/video/7640515300101822443" --title "测试视频"
```

Example collector JSON:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\transcribe_douyin_urls.py --cdp-url http://127.0.0.1:9230 --input-json .\outputs\20260526\douyin_saved_links.json
```

Transcription output:

- JSON: `transcripts/YYYYMMDD/douyin_video_transcripts.json`
- Text: `transcripts/YYYYMMDD/douyin_video_transcripts.txt`

Important implementation detail: do not rely on `yt-dlp` Douyin extractor alone. It often reports `Fresh cookies are needed`. The transcription script should first open the Douyin page in the authenticated browser, capture the real `video/mp4` media response, download that media, then transcribe with `faster-whisper`. Keep `yt-dlp` as fallback only.

## Verification And Safety

- If Douyin verification/captcha appears, stop the run, save progress, and ask the user to solve it manually in the logged-in Chrome window.
- Use low-risk collection parameters for broader runs: small keyword batches, shallow scroll depth, and random delays.
- Before claiming completion, run at least:

```powershell
python -m py_compile .\scripts\probe_douyin_saved_links.py .\scripts\transcribe_douyin_urls.py
```

For a real smoke test, run one known URL through transcription and confirm `transcribed_count = 1`, `failed_count = 0`, and `records[0].transcript` is present.

## Detailed Workflow

For operational notes, troubleshooting, output schemas, and common commands, read `references/workflow.md`.
