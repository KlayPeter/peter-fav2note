"""笔记关联：按标题+标签+摘要的中文二元组相似度，双向链。"""

from __future__ import annotations

import re
from itertools import combinations
from pathlib import Path

SECTION = "## 相关笔记"


def _grams(text: str) -> set[str]:
    cleaned = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", text).lower()
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def _split(text: str) -> tuple[str, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return "---" + parts[1] + "---", parts[2]
    return "", text


def relink(vault: Path, top: int = 3, threshold: float = 0.06) -> int:
    notes = []
    for path in sorted(vault.rglob("*.md")):
        if "assets" in path.parts:
            continue
        front, body = _split(path.read_text(encoding="utf-8"))
        body = re.sub(rf"\n*{re.escape(SECTION)}\n[\s\S]*?(?=\n## |\Z)", "\n", body)
        notes.append({
            "path": path,
            "front": front,
            "body": body,
            "rel": path.relative_to(vault).with_suffix("").as_posix(),
        })

    grams = [
        _grams(" ".join([n["rel"], n["body"][:600]]))
        for n in notes
    ]

    scores: dict[int, list[tuple[float, int]]] = {i: [] for i in range(len(notes))}
    for i, j in combinations(range(len(notes)), 2):
        if not grams[i] or not grams[j]:
            continue
        score = len(grams[i] & grams[j]) / len(grams[i] | grams[j])
        if score >= threshold:
            scores[i].append((score, j))
            scores[j].append((score, i))

    linked = 0
    for i, note in enumerate(notes):
        ranked = sorted(scores[i], reverse=True)[:top]
        body = note["body"].rstrip()
        if ranked:
            body += f"\n\n{SECTION}\n\n"
            for _, j in ranked:
                body += f"- [[{notes[j]['rel']}]]\n"
            linked += 1
        note["path"].write_text(note["front"] + body, encoding="utf-8", newline="\n")
    return linked
