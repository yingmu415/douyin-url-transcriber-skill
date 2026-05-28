# douyin-url-transcriber Skill

这是一个 Codex Skill，用于从已登录的抖音网页版搜索页采集“低粉高赞”视频 URL，并通过已登录浏览器会话下载视频媒体，最后使用 `faster-whisper` 在本地转写成文字。

## 适用场景

- 按关键词搜索抖音视频。
- 按发布时间、点赞数、作者粉丝数筛选视频。
- 保存满足条件的视频 URL。
- 将采集到的抖音视频转成本地文字稿。

## 仓库结构

```text
douyin-url-transcriber-skill/
├── README.md
├── requirements.txt
└── douyin-url-transcriber/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    ├── references/
    │   └── workflow.md
    └── scripts/
        ├── probe_douyin_saved_links.py
        └── transcribe_douyin_urls.py
```

真正需要安装到 Codex 的目录是 `douyin-url-transcriber/`。

## 安装给其他用户

1. 安装 Python 依赖：

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

2. 把 `douyin-url-transcriber/` 复制到用户的 Codex skills 目录：

```powershell
Copy-Item -Recurse .\douyin-url-transcriber "$env:USERPROFILE\.codex\skills\douyin-url-transcriber"
```

3. 重启 Codex，或新开一个 Codex 会话，让 skill 列表重新加载。

4. 启动一个已登录抖音的 Chrome CDP 浏览器。推荐单独使用一个抖音自动化 profile，不要和小红书采集共用同一个浏览器实例：

```powershell
Start-Process -FilePath "C:\Program Files\Google\Chrome\Application\chrome.exe" -ArgumentList @(
  "--remote-debugging-port=9230",
  "--user-data-dir=$env:LOCALAPPDATA\DouyinBrowserAutomation\User Data",
  "--start-maximized",
  "https://www.douyin.com/"
)
```

5. 在打开的 Chrome 里手动登录抖音，并确认 `http://127.0.0.1:9230/json/version` 可以访问。

## 给 Codex 的使用方式

安装完成后，可以直接对 Codex 说：

```text
使用 douyin-url-transcriber，帮我采集 10 个抖音低粉高赞视频 URL，并分别把视频转成文字保存。
筛选条件：一年内，点赞超过 100，粉丝低于 20000，搜索关键词使用安全感。
```

筛选条件可以自然语言调整：

- `半年内` -> `--within-days 180`
- `一年内` -> `--within-days 365`
- `点赞超过 500` -> `--min-likes 500`
- `粉丝低于 5000` -> `--max-followers 5000`
- `采集 10 个` -> `--max-saved 10`
- `搜索关键词使用 安全感` -> `--keyword 安全感`

## 手动运行示例

采集 URL：

```powershell
$env:PYTHONIOENCODING='utf-8'
python .\douyin-url-transcriber\scripts\probe_douyin_saved_links.py `
  --cdp-url http://127.0.0.1:9230 `
  --keyword 安全感 `
  --within-days 365 `
  --min-likes 100 `
  --max-followers 20000 `
  --max-saved 10 `
  --output-dir .\outputs\security
```

转写采集结果：

```powershell
$env:PYTHONIOENCODING='utf-8'
python .\douyin-url-transcriber\scripts\transcribe_douyin_urls.py `
  --cdp-url http://127.0.0.1:9230 `
  --input-json .\outputs\security\YYYYMMDD\douyin_saved_links.json `
  --output-dir .\transcripts\security `
  --media-dir .\downloads\security `
  --model large-v3 `
  --device cpu `
  --compute-type int8
```

输出文件通常包括：

- `outputs/.../douyin_saved_links.json`
- `outputs/.../douyin_saved_links.txt`
- `transcripts/.../douyin_video_transcripts.json`
- `transcripts/.../douyin_video_transcripts.txt`

## 发布到 GitHub

方式一：GitHub 网页上传

1. 在 GitHub 新建私有仓库，例如 `douyin-url-transcriber-skill`。
2. 上传本目录下的所有文件。
3. 不要上传 `downloads/`、`outputs/`、`transcripts/`、`__pycache__/`、浏览器 profile、cookies 或本地模型缓存。
4. 把仓库地址发给其他用户，让对方按“安装给其他用户”步骤安装。

方式二：命令行上传

```powershell
git init
git add .
git commit -m "Add douyin url transcriber skill"
git branch -M main
git remote add origin https://github.com/<你的账号>/douyin-url-transcriber-skill.git
git push -u origin main
```

## 注意事项

- 这个 skill 依赖用户自己的已登录抖音浏览器会话，不内置账号、cookies 或绕过验证码能力。
- 如果抖音出现验证码或风控页，需要用户在浏览器里手动处理后再继续。
- `large-v3` 中文转写质量更稳，但 CPU 上较慢；长视频批量转写建议使用 GPU，或在可接受质量下降时改用 `medium`。
- 抖音页面和接口可能变化，若脚本失效，需要根据当前页面结构维护采集逻辑。
