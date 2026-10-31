"""最小冒烟测试：不依赖网络与模型。"""

from pathlib import Path

from fav2note.models import Item, NoteDraft
from fav2note.pipeline.transcribe import parse_srt, timed_text
from fav2note.store.vault import Vault, safe_name, slug


def test_safe_name_and_slug():
    assert safe_name("a/b:c") == "a b c"
    assert slug("教程来了！Paper + AI coding") == "教程来了_Paper_AI_coding"


def test_parse_srt():
    srt = "1\n00:00:01,000 --> 00:00:03,000\n你好\n\n2\n00:01:05,000 --> 00:01:07,000\n世界\n"
    segments = parse_srt(srt)
    assert segments == [(1, "你好"), (65, "世界")]
    assert timed_text(segments) == "[00:01] 你好\n[01:05] 世界"


def test_vault_render(tmp_path: Path):
    vault = Vault(tmp_path)
    item = Item(platform="小红书", item_id="abc123", title="测试标题", author="作者", url="https://x")
    draft = NoteDraft(
        one_liner="一句话",
        summary="摘要",
        category="技术AI",
        sections=[{"time": "00:10", "title": "开头", "points": ["要点一"]}],
        takeaways=["可以带走"],
        closing="总结一段",
        tags=["tag"],
    )
    path = vault.write(item, draft, [], vault.root)
    text = path.read_text(encoding="utf-8")
    assert "# 测试标题" in text
    assert "## 值得带走的" in text
    assert "category: 技术AI" in text
