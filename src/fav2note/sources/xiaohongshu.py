"""小红书：从浏览器导出的 JSON 读收藏，并用 curl_cffi 直接下载。

不保存 Cookie：导出文件由仓库自带的油猴脚本生成，
登录态始终留在浏览器里；下载只需要笔记链接里的 xsec_token。
"""

from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path

from ..models import Item, Media
from .base import Source

URL_TEMPLATE = "https://www.xiaohongshu.com/explore/{id}?xsec_token={token}&xsec_source=pc_collect"
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "zh-CN,zh;q=0.9",
}
STATE_PATTERN = re.compile(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>", re.S)


def _count(raw) -> int:
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

    # ---- 下载 ----
    def fetch(self, item: Item, workdir: Path) -> Media:
        workdir.mkdir(parents=True, exist_ok=True)
        note = self._load_note(item)
        if note is None:
            raise RuntimeError("解析笔记失败：链接可能已失效，或需要重新导出")

        video = None
        images: list[Path] = []

        if item.kind == "video":
            url = self._video_url(note)
            if url:
                target = workdir / f"{item.item_id}.mp4"
                self._download(url, target)
                if target.is_file() and target.stat().st_size > 1024:
                    video = target
        if video is None:
            for index, url in enumerate(self._image_urls(note), start=1):
                target = workdir / f"{item.item_id}_{index}.jpg"
                try:
                    self._download(url, target)
                    images.append(target)
                except Exception:  # noqa: BLE001
                    continue

        return Media(item=item, workdir=workdir, video=video, images=images)

    def _load_note(self, item: Item) -> dict | None:
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:  # 退回标准库，成功率低一些
            cffi_requests = None

        if cffi_requests is not None:
            response = cffi_requests.get(
                item.url, impersonate="chrome", headers=HEADERS, timeout=30
            )
            html = response.text
        else:
            request = urllib.request.Request(item.url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=30) as resp:
                html = resp.read().decode("utf-8", "ignore")

        match = STATE_PATTERN.search(html)
        if not match:
            return None
        try:
            state = json.loads(match.group(1).replace("undefined", "null"))
            detail = state["note"]["noteDetailMap"][item.item_id]["note"]
        except (KeyError, ValueError):
            return None

        detail["_type"] = "video" if detail.get("type") == "video" else "image"
        return detail

    @staticmethod
    def _video_url(note: dict) -> str:
        stream = (((note.get("video") or {}).get("media") or {}).get("stream") or {})
        for codec in ("h264", "h265", "av1"):
            variants = stream.get(codec) or []
            if variants:
                return variants[0].get("masterUrl") or variants[0].get("backupUrls", [""])[0]
        return ""

    @staticmethod
    def _image_urls(note: dict) -> list[str]:
        urls = []
        for image in note.get("imageList") or []:
            url = image.get("urlDefault") or image.get("urlPre") or ""
            if url:
                urls.append(url)
        return urls

    @staticmethod
    def _download(url: str, dest: Path) -> None:
        request = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.xiaohongshu.com/"}
        )
        with urllib.request.urlopen(request, timeout=120) as resp:
            dest.write_bytes(resp.read())
