"""小红书：从浏览器导出的 JSON 读取收藏。

不直接调接口、不保存 Cookie —— 导出文件由随仓库附带的油猴脚本生成，
登录态始终留在浏览器里。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from ..models import Item, Media
from .base import Source

URL_TEMPLATE = "https://www.xiaohongshu.com/explore/{id}?xsec_token={token}&xsec_source=pc_collect"


def _count(raw) -> int:
    """'1万' / '4.8万' / '930' -> int"""
    if raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip().replace("+", "")
    match = re.match(r"^([\d.]+)\s*([万亿]?)$", text)
    if not match:
        return 0
    return int(float(match.group(1)) * {"": 1, "万": 10_000, "亿": 100_000_000}[match.group(2)])


def _walk_notes(node, out: list) -> None:
    """在任意层级的响应结构里找出 notes 列表。"""
    if isinstance(node, list):
        for child in node:
            _walk_notes(child, out)
    elif isinstance(node, dict):
        if isinstance(node.get("notes"), list):
            out.extend(n for n in node["notes"] if isinstance(n, dict))
        for key in ("data", "response", "result"):
            if key in node:
                _walk_notes(node[key], out)
        if "entries" in node and isinstance(node["entries"], list):  # HAR
            for entry in node["entries"]:
                text = ((entry.get("response") or {}).get("content") or {}).get("text")
                if text:
                    try:
                        _walk_notes(json.loads(text), out)
                    except ValueError:
                        continue


class XiaohongshuSource(Source):
    name = "小红书"

    def __init__(self, export_file: Path) -> None:
        self.export_file = Path(export_file)

    def collect(self, **kwargs) -> list[Item]:
        raw = json.loads(self.export_file.read_text(encoding="utf-8", errors="ignore"))
        notes: list[dict] = []
        _walk_notes(raw, notes)
        items: list[Item] = []
        seen: set[str] = set()
        for note in notes:
            note_id = note.get("note_id") or note.get("id")
            token = note.get("xsec_token")
            if not note_id or not token or note_id in seen:
                continue
            seen.add(note_id)
            user = note.get("user") or {}
            items.append(
                Item(
                    platform=self.name,
                    item_id=note_id,
                    title=(note.get("display_title") or "").strip() or note_id,
                    author=user.get("nickname") or "",
                    url=URL_TEMPLATE.format(id=note_id, token=token),
                    kind="video" if note.get("type") == "video" else "image",
                    liked=_count((note.get("interact_info") or {}).get("liked_count")),
                )
            )
        return items

    def fetch(self, item: Item, workdir: Path) -> Media:
        """小红书走外部下载器（XHS-Downloader），这里只负责定位产物。"""
        workdir.mkdir(parents=True, exist_ok=True)
        video = None
        for pattern in ("*.mp4", "*.mov", "*.m4v"):
            found = list(workdir.glob(pattern))
            if found:
                video = found[0]
                break
        images = sorted(workdir.glob("*.jp*g")) + sorted(workdir.glob("*.png"))
        return Media(item=item, workdir=workdir, video=video, images=images)

    def fetch_remote(self, item: Item, workdir: Path, downloader: str = "") -> Media:
        """用外部命令下载（默认调用 XHS-Downloader 的 CLI）。"""
        import subprocess

        if not downloader:
            raise RuntimeError("未配置小红书下载器路径")
        workdir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [downloader, "main.py", "-u", item.url, "-fm", "true", "-nf", "作品ID"],
            check=False,
            timeout=900,
        )
        return self.fetch(item, workdir)


def download_image(url: str, dest: Path) -> Path:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        dest.write_bytes(resp.read())
    return dest
