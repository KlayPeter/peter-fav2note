"""账号状态：记录各平台是否可用，供面板提示。

不保存任何凭据，只记「上次检测结果」。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class Accounts:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        if path.is_file():
            try:
                self.data = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                self.data = {}

    def set(self, platform: str, ok: bool, detail: str = "") -> None:
        self.data[platform] = {
            "ok": ok,
            "detail": detail,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, platform: str) -> dict:
        return self.data.get(platform, {"ok": False, "detail": "尚未检测", "checked_at": ""})
