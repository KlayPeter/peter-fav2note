"""抖音：用 Playwright 复用本地登录态，读取自己的收藏夹。

设计取舍：
- 登录态存在独立 profile 目录，不读、不上传 Cookie；
- 只监听收藏列表接口的响应，不模拟点赞、不写数据；
- 滚动节奏放慢，出验证码就停，不硬刚风控。
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from ..models import Item, Media
from .base import Source

FAV_URL = "https://www.douyin.com/user/self?showTab=favorite_collection"
FAV_API = "/aweme/v1/web/aweme/favorite/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:  # pragma: no cover
        raise SystemExit("需要 Playwright：pip install 'fav2note[browser]' && playwright install chromium") from error
    return sync_playwright


class DouyinSource(Source):
    name = "抖音"

    def __init__(self, profile_dir: Path) -> None:
        self.profile_dir = Path(profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    # ---- 登录 ----
    LOGIN_COOKIES = {"sessionid", "sessionid_ss", "sid_tt", "passport_csrf_token"}

    def login(self, timeout: int = 300) -> None:
        """打开有头浏览器，用户自行扫码；检测到登录态自动保存并关闭。"""
        import time

        sync_playwright = _playwright()
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=False,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto("https://www.douyin.com/", wait_until="domcontentloaded")
            print("浏览器已打开，请扫码登录；脚本会自动检测，最多等 5 分钟…")

            deadline = time.time() + timeout
            logged = False
            while time.time() < deadline:
                names = {c.get("name") for c in context.cookies()}
                if names & {"sessionid", "sessionid_ss", "sid_tt"}:
                    logged = True
                    break
                page.wait_for_timeout(2000)

            print("登录态已保存" if logged else "超时：未检测到登录，可重试")
            page.wait_for_timeout(1500)
            context.close()

    # ---- 采集 ----
    def collect(self, limit: int = 500, max_scroll: int = 200, **kwargs) -> list[Item]:
        sync_playwright = _playwright()
        buckets: list[dict] = []

        def on_response(response):
            if FAV_API not in response.url:
                return
            try:
                data = response.json()
            except Exception:  # noqa: BLE001
                return
            for aweme in data.get("aweme_list") or []:
                buckets.append(aweme)

        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=True,
                user_agent=UA,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.on("response", on_response)
            page.goto(FAV_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            last_height, same = 0, 0
            for _ in range(max_scroll):
                page.mouse.wheel(0, 2400)
                page.wait_for_timeout(1200)
                height = page.evaluate("document.body.scrollHeight")
                if height == last_height:
                    same += 1
                else:
                    same, last_height = 0, height
                if same >= 6 or len(buckets) >= limit:
                    break

            logged_in = "sessionid" in {c.get("name") for c in context.cookies()}
            context.close()

        if not buckets and not logged_in:
            raise RuntimeError("抖音登录态已失效，请重新执行：fav2note login --source douyin")

        return [self._to_item(aweme) for aweme in self._dedupe(buckets)]

    @staticmethod
    def _dedupe(awemes: list[dict]) -> list[dict]:
        seen: set[str] = set()
        unique = []
        for aweme in awemes:
            aweme_id = aweme.get("aweme_id")
            if aweme_id and aweme_id not in seen:
                seen.add(aweme_id)
                unique.append(aweme)
        return unique

    def _to_item(self, aweme: dict) -> Item:
        images = (aweme.get("images") or [])
        video_url = ""
        play_addr = ((aweme.get("video") or {}).get("play_addr") or {}).get("url_list") or []
        if play_addr:
            video_url = play_addr[0]
        return Item(
            platform=self.name,
            item_id=str(aweme.get("aweme_id", "")),
            title=(aweme.get("desc") or "").strip()[:80] or str(aweme.get("aweme_id")),
            author=((aweme.get("author") or {}).get("nickname") or ""),
            url=f"https://www.douyin.com/video/{aweme.get('aweme_id')}",
            kind="image" if images else "video",
            liked=int((aweme.get("statistics") or {}).get("digg_count") or 0),
            extra={
                "video_url": video_url,
                "images": [((img.get("url_list") or [""])[0]) for img in images],
            },
        )

    # ---- 下载 ----
    def fetch(self, item: Item, workdir: Path) -> Media:
        workdir.mkdir(parents=True, exist_ok=True)
        video = None
        # 图文帖的 video_url 往往是一段背景音乐，别当视频下
        if item.kind == "video" and (url := item.extra.get("video_url")):
            target = workdir / f"{item.item_id}.mp4"
            self._download(url, target)
            video = target if target.is_file() and target.stat().st_size > 1024 else None

        images = []
        for index, url in enumerate(item.extra.get("images") or [], start=1):
            if not url:
                continue
            target = workdir / f"{item.item_id}_{index}.jpg"
            try:
                self._download(url, target)
                images.append(target)
            except Exception:  # noqa: BLE001
                continue
        return Media(item=item, workdir=workdir, video=video, images=images)

    @staticmethod
    def _download(url: str, dest: Path) -> None:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.douyin.com/"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            dest.write_bytes(resp.read())
