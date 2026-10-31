"""知识库读写：vault/<平台>/<分类>/<标题>.md + assets/。"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ..models import Item, NoteDraft

ASSETS = "assets"
SOURCE_LINE = "---\n\n来源："


def safe_name(text: str, limit: int = 60) -> str:
    """文件名安全化：去掉 Windows 非法字符，保留中文。"""
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned[:limit] or "未命名").strip(" .")


def slug(text: str, limit: int = 40) -> str:
    """目录名安全化：只留中文/字母/数字/下划线/连字符，保证链接不用转义。"""
    cleaned = re.sub(r"[^\w\u4e00-\u9fa5-]", "_", text or "")
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return (cleaned[:limit] or "note").strip("_")


class Vault:
    """把 NoteDraft 渲染成 Markdown 并落盘。"""

    def __init__(self, root: Path) -> None:
        self.root = root

    def note_path(self, item: Item, category: str) -> Path:
        folder = self.root / item.platform / safe_name(category, 20)
        folder.mkdir(parents=True, exist_ok=True)
        base = folder / f"{safe_name(item.title)}.md"
        if not base.exists():
            return base
        # 同名不同篇：用 id 后缀，避免覆盖
        return folder / f"{safe_name(item.title)} ({item.item_id[-6]}).md"

    def assets_dir(self, item: Item, category: str) -> Path:
        folder = self.root / item.platform / safe_name(category, 20) / ASSETS / slug(item.title)
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def write(self, item: Item, draft: NoteDraft, frames: list[tuple[int, Path]], base: Path | None = None) -> Path:
        path = self.note_path(item, draft.category)
        self.assets_dir(item, draft.category)
        text = self._render(item, draft, frames, path.parent)
        path.write_text(text, encoding="utf-8", newline="\n")
        return path

    # ---- 渲染 ----
    def _render(
        self,
        item: Item,
        draft: NoteDraft,
        frames: list[tuple[int, Path]],
        note_dir: Path,
    ) -> str:
        def bullets(values: list[str], empty: str = "_无_") -> str:
            return "\n".join(f"- {v}" for v in values) if values else empty

        def mmss(seconds: int) -> str:
            return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"

        def frame_for(index: int) -> list[str]:
            hits = [f for f in frames if f[0] == index]
            if not hits:
                return []
            # 图片相对当前笔记所在目录，Obsidian 直接可渲染
            rel = hits[0][1].relative_to(note_dir).as_posix()
            return [f"![{mmss(hits[0][0])}]({rel})", ""]

        head = [
            "---",
            f"title: {json.dumps(item.title, ensure_ascii=False)}",
            f"platform: {item.platform}",
            f"category: {draft.category}",
            f"author: {json.dumps(item.author, ensure_ascii=False)}",
            f"density: {draft.density}",
            f"liked: {item.liked}",
            f"source_id: {item.item_id}",
            f"url: {item.url}",
            f"tags: [{', '.join(json.dumps(t, ensure_ascii=False) for t in draft.tags)}]",
            f"created: {datetime.now():%Y-%m-%d %H:%M}",
            "---",
            "",
            f"# {item.title}",
            "",
        ]
        if draft.one_liner:
            head += [f"> {draft.one_liner}", ""]
        if draft.summary:
            head += ["## 这条讲什么", "", draft.summary, ""]

        body: list[str] = []
        if draft.sections:
            body.append("## 内容分节")
            body.append("")
        for index, section in enumerate(draft.sections):
            body.append(f"### {section.get('time', '')}　{section.get('title', '')}")
            body.append("")
            body.append(bullets([str(p) for p in section.get("points", [])]))
            body.append("")
            body.extend(frame_for(index))

        if draft.steps:
            body += ["## 照着做", "", bullets(draft.steps), ""]
        if draft.tools:
            body += ["## 提到的工具", "", bullets(draft.tools), ""]
        if draft.pitfalls:
            body += ["## 容易踩的坑", "", bullets(draft.pitfalls), ""]
        if draft.quotes:
            body += ["## 原话", "", "\n".join(f"> {q}" for q in draft.quotes), ""]
        if draft.takeaways:
            body += ["## 值得带走的", "", bullets(draft.takeaways), ""]
        if draft.closing:
            body += ["## 总结", "", draft.closing, ""]

        tail = ["---", f"来源：[{item.author} · {item.title}]({item.url})", ""]
        return "\n".join(head + body + tail)
