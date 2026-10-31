"""领域模型：平台无关的中间结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class Item:
    """一条待处理的收藏。"""

    platform: str
    item_id: str
    title: str
    author: str = ""
    url: str = ""
    kind: str = "video"  # video | image
    liked: int = 0
    collected_at: datetime | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.platform}:{self.item_id}"


@dataclass
class Media:
    """下载到本地的素材。"""

    item: Item
    workdir: Path
    video: Path | None = None
    images: list[Path] = field(default_factory=list)

    @property
    def has_video(self) -> bool:
        return self.video is not None and self.video.is_file()


@dataclass
class Transcript:
    """转写结果。"""

    text: str
    srt_path: Path | None = None
    segments: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class NoteDraft:
    """AI 提炼出的结构化草稿。"""

    one_liner: str = ""
    summary: str = ""
    category: str = "未分类"
    sections: list[dict] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    pitfalls: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    takeaways: list[str] = field(default_factory=list)
    closing: str = ""
    tags: list[str] = field(default_factory=list)
    density: int = 3
