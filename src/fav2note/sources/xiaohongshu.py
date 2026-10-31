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

    def __init__(self, export_file: Path | None = None, profile_dir: Path | None = None) -> None:
        self.export_file = Path(export_file) if export_file else None
        self.profile_dir = Path(profile_dir) if profile_dir else Path("data/cache/xhs_profile")

    # ---- 登录 ----
    def login(self, timeout: int = 600) -> None:
        """打开浏览器扫码；以 /user/me 的 guest 字段为准，确认真的登录了。"""
        import time

        from .douyin import _playwright

        sync_playwright = _playwright()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        me: dict = {}

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(self.profile_dir), headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()

            def on_response(response):
                if "/api/sns/web/v2/user/me" in response.url:
                    try:
                        me.update(response.json().get("data") or {})
                    except Exception:  # noqa: BLE001
                        pass

            page.on("response", on_response)
            page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            page.bring_to_front()

            # 主动点开登录框，省得用户找不到入口
            for label in ("登录", "立即登录"):
                try:
                    button = page.get_by_text(label, exact=True).first
                    if button.is_visible():
                        button.click(timeout=3000)
                        break
                except Exception:  # noqa: BLE001
                    continue

            print(f"浏览器已打开，请扫码登录；脚本会自动检测，最多等 {timeout // 60} 分钟…")

            deadline = time.time() + timeout
            logged = False
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                # 游客态不算登录，必须 guest=false 且有昵称
                if me and me.get("guest") is False and (me.get("nickname") or me.get("user_id")):
                    logged = True
                    break

            print(
                f"登录成功：{me.get('nickname', '')}" if logged
                else "超时：仍是游客态，请重新扫码（登录后页面右上角会显示你的头像）"
            )
            page.wait_for_timeout(1500)
            context.close()
        return logged

    # ---- 浏览器采集 ----
    def collect(self, limit: int = 500, max_scroll: int = 200, **kwargs) -> list[Item]:
        """驱动浏览器打开自己的收藏页，边滚边截接口响应。"""
        from .douyin import _playwright

        sync_playwright = _playwright()
        notes: list[dict] = []
        me: dict = {}

        def on_response(response):
            if "/api/sns/web/v2/user/me" in response.url:
                try:
                    me.update(response.json().get("data") or {})
                except Exception:  # noqa: BLE001
                    pass
            if "/api/sns/web/" not in response.url:
                return
            try:
                data = response.json()
            except Exception:  # noqa: BLE001
                return
            payload = data.get("data") if isinstance(data, dict) else None
            if isinstance(payload, dict) and isinstance(payload.get("notes"), list):
                notes.extend(n for n in payload["notes"] if isinstance(n, dict))

        with sync_playwright() as pw:
            # 小红书会拦无头浏览器（error 300012），必须用有头模式
            context = pw.chromium.launch_persistent_context(
                str(self.profile_dir), headless=False,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", on_response)

            page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            if "website-login/error" in page.url or "error_code=300012" in page.url:
                context.close()
                raise RuntimeError(
                    "小红书风控拦截（IP 风险 300012），请改用导出文件："
                    "浏览器登录后用油猴脚本导出 fav_all.json 放进 inbox/"
                )

            html = page.content()
            match = re.search(r'"userId":"([0-9a-f]{24})"', html)
            user_id = match.group(1) if match else ""

            url = f"https://www.xiaohongshu.com/user/profile/{user_id}?tab=fav" if user_id else page.url
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            last_height, same = 0, 0
            for _ in range(max_scroll):
                page.mouse.wheel(0, 2600)
                page.wait_for_timeout(1300)
                height = page.evaluate("document.body.scrollHeight")
                if height == last_height:
                    same += 1
                else:
                    same, last_height = 0, height
                if same >= 8 or len(notes) >= limit:
                    break

            logged_in = "web_session" in {c.get("name") for c in context.cookies()}
            context.close()

        if me and me.get("guest") is not False:
            raise RuntimeError("小红书未登录（游客态），请先执行：fav2note login --source xhs")
        if not notes and not logged_in:
            raise RuntimeError("小红书登录态已失效，请重新执行：fav2note login --source xhs")
        if not notes:
            raise RuntimeError(
                "小红书收藏页没有加载出列表（自动化环境被限制），"
                "请改用导出文件：浏览器里用油猴脚本导出 fav_all.json 放进 inbox/"
            )

        return self._notes_to_items(notes)

    def _notes_to_items(self, notes: list[dict]) -> list[Item]:
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

    def collect_from_file(self) -> list[Item]:
        """兜底：从浏览器导出的 JSON 读。"""
        if not self.export_file or not self.export_file.is_file():
            return []
        raw = json.loads(self.export_file.read_text(encoding="utf-8", errors="ignore"))
        notes: list[dict] = []
        _walk_notes(raw, notes)
        return self._notes_to_items(notes)

    # ---- 单条链接 ----
    @classmethod
    def from_url(cls, url: str) -> Item:
        """从分享链接构造条目：补全标题、作者、类型、时长。"""
        match = re.search(r"/(?:explore|discovery/item)/[^/]*?([0-9a-f]{24})", url)
        if not match:
            match = re.search(r"([0-9a-f]{24})", url)
        if not match:
            raise ValueError("链接里找不到笔记 ID，请确认是小红书作品链接")
        note_id = match.group(1)

        item = Item(platform=cls.name, item_id=note_id, title=note_id, url=url, kind="video")
        try:
            detail = cls(Path("."))._load_note(item)
        except Exception:  # noqa: BLE001
            detail = None
        if detail:
            item.title = (detail.get("title") or detail.get("desc") or note_id)[:80]
            item.author = ((detail.get("user") or {}).get("nickname") or "")
            item.kind = "video" if detail.get("type") == "video" else "image"
            item.extra["duration"] = int((((detail.get("video") or {}).get("duration")) or 0) / 1000)
        return item

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
