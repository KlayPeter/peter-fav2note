"""平台适配器。"""

from .base import Source
from .douyin import DouyinSource
from .xiaohongshu import XiaohongshuSource

__all__ = ["Source", "DouyinSource", "XiaohongshuSource"]
