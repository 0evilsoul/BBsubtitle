# Minimal Bilibili Subtitle Fetcher (Python)

仅用于验证：未登录、非国际版，从公开 Web 接口拉取字幕列表并下载为 SRT。

- 解析输入 BV/URL → 调用 `x/web-interface/view` 获取 aid/cid
- 调用 `x/player/wbi/v2?aid=..&cid=..` 获取 `subtitle.subtitles`
- 下载每条字幕的 JSON → 转换为 `.srt`

注意
- 未登录时很多视频没有原生字幕，可能拿不到字幕列表（或仅 AI 字幕但此接口不返回）。本最小实例不处理 App/Intl/登录态。
- 仅做可用性验证，如需更高覆盖面（AI 字幕/登录/国际版），请在此基础上扩展 Provider 与 Auth。

## 使用

安装依赖：
```powershell
pip install -r requirements.txt
```

运行：
```powershell
python main.py --input "https://www.bilibili.com/video/BV1xxxxxxx" --outdir . --lang en,en-US
```
- `--input`：BV 号、URL，或短链（如 `b23.tv/55vWJZV`，自动跟随重定向解析）
- `--outdir`：输出目录（默认当前目录）
- `--lang`：逗号分隔的语言键白名单；支持精确匹配（如 `en`）

示例：只取中文（如果列表中含有 `zh-CN`）：
```powershell
python main.py --input "BV1xxxxxxx" --lang zh-CN
```

若没有任何输出，通常是该视频未对未登录用户提供字幕（或仅有 AI 字幕但此接口不返回），属于预期限制。


