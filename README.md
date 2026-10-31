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

### 小红书

1. 浏览器登录小红书，打开收藏页
2. 安装 `userscript/xhs-favorites-export.user.js`（Tampermonkey），点「开始滚动」
3. 导出得到 `fav_all.json`

```bash
fav2note collect --source xhs --file fav_all.json --home .
fav2note run --limit 20
```

### 抖音

```bash
fav2note login --source douyin     # 弹出浏览器，扫码，回车保存
fav2note collect --source douyin --limit 200
fav2note run --limit 20
```

登录态存在 `data/cache/douyin_profile/`，不会读取或上传 Cookie。

### 其他

```bash
fav2note link              # 只重建笔记关联
fav2note stats             # 看处理统计
```

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

- 纯图文收藏暂不处理（需要 OCR / 多模态）
- 抖音接口结构可能变化，采集器需要跟着更新
- 无对白视频会被跳过（VAD 判定），这是预期行为
- 分类按标题判断，边界内容需要人工复核

## 路线图

- [ ] 图文笔记 OCR（PaddleOCR / 多模态模型）
- [ ] 本地 Web 面板：看进度、改分类、提问
- [ ] B 站收藏适配器
- [ ] 定时任务模板（Windows 计划任务 / cron）

## License

MIT
