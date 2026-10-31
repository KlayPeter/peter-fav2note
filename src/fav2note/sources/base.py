"""平台适配器接口。新增平台只要实现一个类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..models import Item, Media


class Source(ABC):
    """所有平台的统一入口。"""

    name: str = "unknown"

    @abstractmethod
    def collect(self, **kwargs) -> list[Item]:
        """拉取收藏列表，返回待处理条目。"""

    @abstractmethod
    def fetch(self, item: Item, workdir: Path) -> Media:
        """把条目的音视频/图片下载到 workdir。"""

    def login(self) -> None:  # 可选：需要登录态的平台覆盖它
        raise NotImplementedError(f"{self.name} 不需要单独登录")
