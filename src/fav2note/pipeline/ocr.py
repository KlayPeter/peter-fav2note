"""本地 OCR：图文笔记和纯 BGM 视频靠它提取屏幕上的文字。

优先用 rapidocr（离线、纯 CPU），没装就返回空字符串，调用方按"无文本"处理。
"""

from __future__ import annotations

from pathlib import Path

_engine = None


def _load():
    global _engine
    if _engine is not None:
        return _engine
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError:
        return None
    _engine = RapidOCR()
    return _engine


def read_text(image: Path) -> str:
    """返回图片里的文字，按行拼起来；引擎不可用时返回空串。"""
    engine = _load()
    if engine is None:
        return ""
    try:
        result, _ = engine(str(image))
    except Exception:  # noqa: BLE001
        return ""
    if not result:
        return ""
    lines = [str(item[1]).strip() for item in result if len(item) > 1]
    return "\n".join(line for line in lines if line)


def read_many(images: list[Path], limit: int = 12) -> str:
    parts = []
    for index, image in enumerate(images[:limit], start=1):
        text = read_text(image)
        if text:
            parts.append(f"[第{index}张]\n{text}")
    return "\n\n".join(parts)
