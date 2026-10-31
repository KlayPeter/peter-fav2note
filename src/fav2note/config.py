"""配置：从 .env 读取，带默认值。不把密钥写进代码。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_env(path: Path) -> dict[str, str]:
    """极简 .env 解析：KEY=VALUE，忽略注释和空行。"""
    data: dict[str, str] = {}
    if not path.is_file():
        return data
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


@dataclass
class Config:
    """运行期配置。

    优先级：环境变量 > .env > 默认值。
    """

    home: Path = field(default_factory=lambda: Path.cwd())
    api_key: str = ""
    base_url: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-chat"
    asr_model: str = "medium"
    asr_device: str = "auto"
    asr_compute: str = "float16"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    frames_per_note: int = 5
    platform_dir: bool = True

    @classmethod
    def load(cls, home: Path | None = None) -> "Config":
        home = Path(home or Path.cwd())
        env = {**_load_env(home / ".env"), **os.environ}

        def get(key: str, default: str) -> str:
            return env.get(key, default) or default

        device = get("FAV2NOTE_ASR_DEVICE", "auto")
        return cls(
            home=home,
            api_key=get("FAV2NOTE_API_KEY", ""),
            base_url=get("FAV2NOTE_BASE_URL", "https://api.deepseek.com/v1"),
            model=get("FAV2NOTE_MODEL", "deepseek-chat"),
            asr_model=get("FAV2NOTE_ASR_MODEL", "medium"),
            asr_device=device,
            asr_compute=get("FAV2NOTE_ASR_COMPUTE", "float16" if device == "cuda" else "int8"),
            ffmpeg=get("FAV2NOTE_FFMPEG", "ffmpeg"),
            ffprobe=get("FAV2NOTE_FFPROBE", "ffprobe"),
            frames_per_note=int(get("FAV2NOTE_FRAMES", "5")),
        )

    # ---- 目录 ----
    @property
    def vault(self) -> Path:
        return self.home / "vault"

    @property
    def data(self) -> Path:
        return self.home / "data"

    @property
    def inbox(self) -> Path:
        return self.home / "inbox"

    @property
    def cache(self) -> Path:
        return self.data / "cache"

    def ensure_dirs(self) -> None:
        for path in (self.vault, self.data, self.inbox, self.cache):
            path.mkdir(parents=True, exist_ok=True)

    def require_api_key(self) -> str:
        if not self.api_key:
            raise SystemExit("缺少 API Key：请在 .env 里设置 FAV2NOTE_API_KEY（参考 .env.example）")
        return self.api_key
