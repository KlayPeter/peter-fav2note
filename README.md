<div align="center">

<img src="assets/icon.png" alt="fav2note" width="120" />

# fav2note

**把小红书、抖音的收藏，变成你自己的知识库。**

收藏夹不该是黑洞。选中的视频和图文会自动下载、转写、提炼成带截图和时间码的 Markdown，Obsidian 打开即用。

[![License: MIT](https://img.shields.io/badge/License-MIT-2f6f4f.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-6f6f6b.svg)](#)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](#贡献)

</div>

---

## 为什么做这个

刷到好东西，点个收藏，然后再也没看过。

fav2note 把"收藏"变成"知识"：不是存个链接，而是把内容拆开、配上画面、标上时间码，写成一篇你能回头查阅的笔记。

```
收藏 → 采集 → 预筛 → 下载 → 转写/OCR → 提炼 → 入库 → 建链
```

## 特性

- **双平台**：小红书、抖音共用一条流水线，平台只在 frontmatter 里区分
- **全量采集**：抖音走游标翻页（`has_more=false` 为止），不是"最近 N 条"
- **下载前预筛**：时长过短、标题像带货的直接跳过，不浪费流量和转写时间
- **本地转写**：faster-whisper 在本机跑，视频不出你的电脑
- **图文也能读**：RapidOCR 提取图上的文字，图文和纯 BGM 视频同样成篇
- **分节截图**：按内容分节，每节取时间点附近最清晰的一帧，不截片头空镜
- **结构化笔记**：一句话结论、分节要点、可执行步骤、易踩坑、原话、可迁移的原则、收尾总结
- **自动双链**：笔记之间按内容相似度互联，Obsidian 图谱里能看出主题簇
- **三种入口**：桌面 exe、本地 Web 面板、命令行
- **断点续跑**：sqlite 记状态，失败可重试，重跑不重复花钱
- **定时增量**：按间隔自动采集 + 处理未完成条目

## 快速开始

### 方式一：下载安装包

从 [Releases](https://github.com/KlayPeter/peter-fav2note/releases) 下载 `fav2note Setup x.y.z.exe`，双击安装。
内置 Python 运行时，**不需要额外装环境**。

### 方式二：源码运行

```bash
git clone https://github.com/KlayPeter/peter-fav2note.git
cd peter-fav2note
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -e ".[all]"
playwright install chromium                       # 只有抖音需要
cp .env.example .env                              # 填 API Key
```

## 使用

### 1. 准备登录态

**小红书**：浏览器登录 → 收藏页 → 安装 `userscript/xhs-favorites-export.user.js`（Tampermonkey）→ 点「开始滚动」→ 把导出的 `fav_all.json` 放进 `inbox/`。

**抖音**：扫码一次，登录态存在本地 profile，几周内不用重扫。

```bash
fav2note login --source douyin
```

### 2. 采集

```bash
fav2note collect --source douyin   # 或 xhs / both
```

### 3. 处理

```bash
fav2note run --limit 20
# 或只处理勾选的
fav2note run --select "抖音:7702464959280520959,抖音:7702277363007000571"
```

### 4. 查看

```bash
fav2note web        # 面板 http://127.0.0.1:7788
fav2note desktop    # 原生窗口
fav2note stats      # 命令行统计
```

知识库在 `vault/`，Obsidian「打开本地仓库」选这个目录即可。

### 5. 常驻（可选）

```bash
fav2note daemon --interval 3600 --batch 20
```

面板的「设置 → 定时更新」也能开，原理相同：到点采集，只处理未完成的条目。

## 工作方式

```
┌─────────────┐    ┌──────────┐    ┌─────────┐
│ 小红书导出   │    │          │    │         │
│ 抖音 Playwright│──▶│  items   │──▶│ prefilter│
└─────────────┘    │  .json   │    │  时长/标题│
                   └──────────┘    └────┬────┘
                                        │
        ┌───────────────────────────────┘
        ▼
┌────────────┐   ┌──────────────┐   ┌──────────┐   ┌────────┐
│ 下载媒体    │──▶│ whisper/OCR  │──▶│ LLM 提炼  │──▶│  Markdown│
└────────────┘   └──────────────┘   └──────────┘   └────┬───┘
                                                        │
                                                   ┌────▼────┐
                                                   │ 相似度建链│
                                                   └─────────┘
```

分层很薄，加平台只要实现 `Source` 的两个方法：

```python
class Source(ABC):
    def collect(self) -> list[Item]: ...
    def fetch(self, item, workdir) -> Media: ...
```

## 输出结构

```
vault/
├── 技术AI/
│   ├── 3个vibecode技巧.md
│   └── assets/3个vibecode技巧/f01.jpg
├── 学习方法/
├── 思维认知/
├── 职场商业/
├── 科普知识/
├── 技能教程/
├── 习惯自律/
└── 书影推荐/
```

每篇 frontmatter：

```yaml
title: 3个vibecode技巧
platform: 抖音        # 按平台筛选用它：platform:抖音
category: 技术AI
author: xxx
density: 4
liked: 319
source_id: 7702464959280520959
url: https://www.douyin.com/video/...
tags: ["vibecode", "AI编程"]
created: 2026-10-31 18:20
```

## 配置

写在 `.env`（参考 `.env.example`）：

| 变量 | 默认 | 说明 |
|---|---|---|
| `FAV2NOTE_API_KEY` | — | 必填，任何 OpenAI 兼容接口 |
| `FAV2NOTE_BASE_URL` | `https://api.deepseek.com/v1` | 接口地址 |
| `FAV2NOTE_MODEL` | `deepseek-chat` | 模型名 |
| `FAV2NOTE_ASR_MODEL` | `medium` | whisper 模型；中文建议 medium 起 |
| `FAV2NOTE_ASR_DEVICE` | `auto` | `cuda` / `cpu` / `auto` |
| `FAV2NOTE_FRAMES_MIN` | `3` | 每条最少截图数 |
| `FAV2NOTE_FRAMES_MAX` | `10` | 每条最多截图数 |
| `FAV2NOTE_FFMPEG` | `ffmpeg` | 不在 PATH 时填绝对路径 |

## 目录说明

```
src/fav2note/
├── sources/     平台适配器：xiaohongshu.py、douyin.py
├── pipeline/    transcribe / frames / ocr / extract / link / prefilter
├── store/       state（sqlite）/ vault（Markdown）/ accounts
├── web/         FastAPI + 单页面板
├── desktop.py   pywebview 窗口
└── cli.py       命令行入口
```

## 开发

```bash
pip install -e ".[all]"
python -m pytest            # 冒烟测试（需 pip install pytest）
python scripts/clean.py --dry-run   # 看能清多少缓存
```

打包桌面端：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

两步：PyInstaller 打后端 → electron-builder 出安装包，产物在 `dist/`。

## 常见问题

**图片在 Obsidian 里不显示？**
路径是相对笔记的 `assets/...`。若手动挪过文件，跑 `python scripts/clean.py --duplicates` 检查；旧库迁移可用 `scripts/migrate_from_kb.py`。

**抖音采集返回 0 条？**
登录态过期。命令行会明确报错 `登录态已失效`，重新 `fav2note login --source douyin` 即可。

**视频没有字幕/没人声？**
会自动转成"抽帧 + OCR"模式，仍然出笔记；若画面也没字，会退化成只有标题的薄笔记。

**一定要 GPU 吗？**
不必。`auto` 会先试 CUDA，缺库时自动退回 CPU（慢 5–8 倍）。

**会不会重复花钱？**
状态表按条目记录，`done` 的不会重跑；同一篇重复处理会覆盖原文件，不产生副本。

## 路线图

- [ ] 图文合集（多图长文）的版面还原
- [ ] B 站收藏适配器
- [ ] 周报：每周汇总新增笔记
- [ ] 向量检索问答（笔记 > 500 篇后）
- [ ] 应用图标与代码签名（当前为默认签名状态）

## 贡献

欢迎 Issue 和 PR。提交前请：

1. 跑一遍 `python -m pytest`
2. 保持分层：平台相关进 `sources/`，通用处理进 `pipeline/`
3. 提交信息用中文，说清"改了什么、为什么"

## 免责声明

本项目仅用于**个人学习与研究**。请只采集你自己账号的内容，遵守平台用户协议与著作权法；不要用于批量搬运、二次分发或商业用途。因使用不当产生的后果由使用者自行承担。

## License

[MIT](LICENSE) © 2026 KlayPeter
