# Douyin URL And Transcription Workflow

## Purpose

This skill packages a two-stage Douyin content workflow:

1. Search Douyin web with logged-in Chrome and save qualified video URLs.
2. Download each video through the authenticated browser session and transcribe it with `faster-whisper`.

## Browser Session

Use an isolated Chrome profile for Douyin automation, preferably on CDP port `9230`.

Example launch command:

```powershell
Start-Process -FilePath 'C:\Program Files\Google\Chrome\Application\chrome.exe' -ArgumentList @('--remote-debugging-port=9230','--user-data-dir=C:\Users\wumengjuan\AppData\Local\DouyinBrowserAutomation\User Data','--start-maximized','https://www.douyin.com/')
```

The user must log in manually. If Douyin shows a verification challenge, stop automation and ask the user to solve it in the Chrome window.

## Dependencies

Install runtime dependencies if missing:

```powershell
python -m pip install yt-dlp faster-whisper playwright
```

`faster-whisper` uses PyAV and CTranslate2. The verified default is:

```text
model=large-v3
device=cpu
compute_type=int8
language=zh
```

Use `large-v3` for Chinese quality. Only use smaller models when the user explicitly prioritizes speed.

## Collection Command

Default collection:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\probe_douyin_saved_links.py --cdp-url http://127.0.0.1:9230
```

Custom filters:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\probe_douyin_saved_links.py --cdp-url http://127.0.0.1:9230 --within-days 90 --min-likes 1000 --max-followers 20000
```

Low-risk batch example:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\probe_douyin_saved_links.py --cdp-url http://127.0.0.1:9230 --keywords-per-dimension 3 --max-keywords 3 --max-cards 2 --scroll-pages 3
```

## Transcription Commands

Single URL:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\transcribe_douyin_urls.py --cdp-url http://127.0.0.1:9230 --url "https://www.douyin.com/video/7640515300101822443" --title "测试视频"
```

URL file:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\transcribe_douyin_urls.py --cdp-url http://127.0.0.1:9230 --urls-file .\urls.txt
```

Collector JSON:

```powershell
$env:PYTHONIOENCODING='utf-8'; python .\scripts\transcribe_douyin_urls.py --cdp-url http://127.0.0.1:9230 --input-json .\outputs\20260526\douyin_saved_links.json
```

## Outputs

Collector JSON contains:

- `criteria`
- `run_info`
- `selected_keywords`
- `keyword_stats`
- `records`
- `skipped`

Transcript JSON contains:

- `model`
- `device`
- `compute_type`
- `transcribed_count`
- `failed_count`
- `records[].title`
- `records[].video_url`
- `records[].transcript`
- `records[].segments`

## Troubleshooting

If `yt-dlp` says `Fresh cookies are needed`, this is expected for Douyin. Prefer browser media capture.

If no `video/mp4` response is captured, check that:

- The `9230` browser is logged in.
- The video URL opens normally in the browser.
- Douyin is not showing a verification challenge.

If transcript text is very short, inspect whether the video is mostly music, captions, silence, or no speech. Whisper transcribes audio, not OCR text displayed in the video.

If first transcription is slow, remember `large-v3` may need to download and load model files. Later runs should be faster.
