# fav2note

把小红书、抖音的**收藏**整理成本地知识库：视频转文字 → AI 提炼 → 带截图和时间码的 Markdown → Obsidian 直接打开。

> 只处理你自己的收藏，登录态留在本机，不经过任何服务器。

## 它解决什么

刷到好东西，点个收藏，然后再也没看过。fav2note 把这些收藏变成能检索、能回顾的笔记：

- **带截图**：按内容分节，每节配一张当时的画面，不是随便抽帧
- **带时间码**：每条要点标了视频里的位置，想回看直接跳
- **带收尾**：可迁移的原则 + 一段总结，说清"为什么成立、什么时候别用"
- **带关联**：笔记之间自动双链，Obsidian 图谱里能看出主题簇

## 工作方式

```
收藏列表 ──► 下载 ──► 转写 ──► 提炼 ──► 入库 ──► 建链
  │            │        │        │        │
平台适配器   ffmpeg   whisper    LLM     Markdown
```

分三层，互相不耦合：

| 层 | 职责 | 位置 |
|---|---|---|
| `sources/` | 各平台怎么拿收藏、怎么下载 | `xiaohongshu.py`、`douyin.py` |
| `pipeline/` | 转写、截帧、提炼、建链 | `transcribe.py`、`frames.py`、`extract.py`、`link.py` |
| `store/` | 状态账本、知识库落盘 | `state.py`、`vault.py` |

加一个新平台，只要实现 `Source` 的两个方法：`collect()` 返回条目，`fetch()` 下载素材。

## 安装

```bash
git clone https://github.com/KlayPeter/peter-fav2note.git
cd peter-fav2note
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -e ".[all]"
playwright install chromium        # 只有抖音需要
copy .env.example .env             # 填 API Key
```

要求：Python 3.10+、ffmpeg 在 PATH 里（转写用）。

## 用法

一条主线，两个平台都走同一套。

### 1. 准备登录态

**小红书**：浏览器登录 → 收藏页 → 油猴脚本 `userscript/xhs-favorites-export.user.js` → 点「开始滚动」→ 保存 `fav_all.json` 到 `inbox/`。

**抖音**：扫码一次，登录态存本地 profile，几周内不用再扫。

```bash
fav2note login --source douyin
```

### 2. 采集

```bash
fav2note collect                 # 两个平台一起，默认
fav2note collect --source xhs    # 只采小红书
fav2note collect --source douyin # 只采抖音
```

结果合并进 `data/items.json`，已处理过的不会被清掉。

### 3. 处理

```bash
fav2note run --limit 20     # 下载 → 转写 → 提炼 → 入库 → 建链
```

每条都会：下视频 → ffmpeg 抽音轨 → whisper 转写 → LLM 分节提炼 → 按分节截帧 → 写成 Markdown。

### 4. 常驻（可选）

```bash
fav2note daemon --interval 3600 --batch 20
```

每小时自动采集一次，再处理 20 条。想开机自启，用 Windows 计划任务指向这条命令即可。

### 5. 看结果

```bash
fav2note web      # 面板：http://127.0.0.1:7788
fav2note stats    # 命令行统计
```

知识库在 `vault/`，Obsidian「打开本地仓库」选这个目录就能用。

### 其他命令

```bash
fav2note link     # 只重建笔记关联
fav2note stats    # 看处理统计
```

## 桌面端

两种壳，按需选：

| 方式 | 命令 | 体积 | 说明 |
|---|---|---|---|
| 浏览器面板 | `fav2note web` | 0 | 最快，调试用 |
| pywebview 窗口 | `fav2note desktop` | 小 | 依赖 WebView2，纯 Python |
| Electron 外壳 | `cd desktop && npm run dev` | 大 | 有托盘、安装包，接近成品 |

### Electron 开发运行

```bash
cd desktop
npm install
npm run dev
```

`main.js` 会拉起本地后端（开发用仓库里的 `.venv`），等 `127.0.0.1:7788` 就绪后加载面板；退出时自动结束子进程。

### 打包成 exe

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_desktop.ps1
```

分两步：

1. `pyinstaller` 把 Python 后端打成 `dist/backend/`（onedir）
2. `electron-builder` 把它作为 `extraResources` 塞进安装包，产出 `dist/fav2note Setup 0.1.0.exe`

打包后的后端 exe 由 Electron 直接拉起，用户机器上**不需要装 Python**。

## 输出结构

```
vault/
├── 小红书/
│   ├── 技术AI/
│   │   ├── 用 Skill 让 Gemini 做设计.md
│   │   └── assets/用_Skill_让_Gemini_做设计/f01.jpg
│   └── 学习方法/
└── 抖音/
    └── 思维认知/
```

每篇的 frontmatter：

```yaml
title / platform / category / author / density
liked / source_id / url / tags / created
```

## 设计取舍

| 决定 | 原因 |
|---|---|
| 小红书走浏览器导出，不直接调接口 | 不需要在代码里存 Cookie，风控风险最低 |
| 抖音用 Playwright 复用本地 profile | 不接触账号密码，扫码一次可用数周 |
| 截图按分节时间取，不按时长均分 | 均分容易截到片头、转场、空镜 |
| 只做读操作 | 采集只读收藏列表，不点赞、不关注、不评论 |
| 状态存 sqlite | 断点续跑，失败可重试，不会重复花钱 |

## 已知限制

- 图文与无解说视频依赖 **本地 OCR**；没装 `rapidocr-onnxruntime` 时只会生成"仅标题"的薄笔记
- OCR 对表格、手写字、艺术字识别率一般
- 抖音接口结构可能变化，采集器需要跟着更新
- 分类按标题判断，边界内容需要人工复核
- 小红书导出文件里的 `xsec_token` 有时效，隔太久需要重新导出

## 路线图

- [ ] 图文笔记 OCR（PaddleOCR / 多模态模型）
- [ ] 本地 Web 面板：看进度、改分类、提问
- [ ] B 站收藏适配器
- [ ] 定时任务模板（Windows 计划任务 / cron）

## License

MIT
