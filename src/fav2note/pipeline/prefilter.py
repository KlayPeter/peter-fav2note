"""采集前的轻量预筛：明显不值得下载的直接跳过，省流量和时间。

只做保守判断，宁可放过也不误杀。
"""

from __future__ import annotations

import re

from ..models import Item

# 标题里出现这些，基本是带货/直播/引流
JUNK_KEYWORDS = re.compile(
    r"直播间|直播预告|带货|下单|链接在|小黄车|橱窗|福利|抽奖|"
    r"优惠券|限时秒杀|拼团|同款|点击购买"
)

MIN_DURATION = 12      # 秒，太短的多为引流片段
MAX_DURATION = 30 * 60  # 秒，超过半小时的多为直播回放/有声书，转写成本极高


def skip_reason(
    item: Item,
    min_duration: int = MIN_DURATION,
    max_duration: int = MAX_DURATION,
) -> str | None:
    """返回跳过原因；不值得跳过时返回 None。"""
    duration = int(item.extra.get("duration") or 0)
    if duration and duration < min_duration:
        return f"时长 {duration}s，过短"
    if duration and duration > max_duration:
        return f"时长 {duration // 60} 分钟，过长"

    if JUNK_KEYWORDS.search(item.title or ""):
        return "标题像带货/直播"

    return None
