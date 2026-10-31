"""桌面窗口：把 Web 面板装进原生窗口，供 exe 使用。"""

from __future__ import annotations

import threading
import time
import urllib.request

from ..config import Config


def _wait_ready(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/summary", timeout=1):
                return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def run(config: Config, port: int = 7788) -> None:
    import uvicorn
    try:
        import webview
    except ImportError as error:  # pragma: no cover
        raise SystemExit("桌面模式需要 pywebview：pip install pywebview") from error

    from .web.app import create_app

    config.ensure_dirs()
    server = uvicorn.Server(uvicorn.Config(create_app(config), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    if not _wait_ready(port):
        raise SystemExit("面板启动超时")

    webview.create_window(
        "fav2note",
        f"http://127.0.0.1:{port}",
        width=1120,
        height=760,
        min_size=(900, 600),
    )
    try:
        webview.start()
    finally:
        server.should_exit = True
