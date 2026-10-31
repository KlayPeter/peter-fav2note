"""把旧知识库迁移到本项目的目录结构。

旧结构：vault/<平台>/<分类>/<标题>.md + assets/<slug>/
新结构：一致，仅把 frontmatter 的 note_id 规范为 source_id。

图片按笔记里的相对链接逐个搬运，避免目录名与标题不一致时漏搬。

用法：
    python scripts/migrate_from_kb.py --src F:\\path\\to\\old\\vault --dst vault
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

LINK = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def normalize_front(text: str) -> str:
    return re.sub(r"^note_id:", "source_id:", text, count=1, flags=re.M)


def copy_assets(note_src: Path, note_dst: Path, dry: bool) -> int:
    """按 md 里的相对链接搬运图片，返回搬运数量。"""
    text = note_src.read_text(encoding="utf-8")
    copied = 0
    for match in LINK.finditer(text):
        rel = match.group(1).strip()
        if rel.startswith(("http://", "https://")):
            continue
        source_file = note_src.parent / rel
        if not source_file.is_file():
            continue
        target_file = note_dst.parent / rel
        if dry:
            print(f"[dry] {target_file}")
        else:
            target_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target_file)
        copied += 1
    return copied


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", required=True)
    parser.add_argument("--dst", default="vault")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    src, dst = Path(args.src), Path(args.dst)
    if not src.is_dir():
        raise SystemExit(f"源目录不存在：{src}")

    new_notes = migrated = assets = 0
    for note in sorted(src.rglob("*.md")):
        if "assets" in note.parts:
            continue
        rel = note.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            assets += copy_assets(note, target, args.dry_run)
            continue

        text = normalize_front(note.read_text(encoding="utf-8"))
        if args.dry_run:
            print(f"[dry] {rel}")
        else:
            target.write_text(text, encoding="utf-8", newline="\n")
        new_notes += 1
        assets += copy_assets(note, target, args.dry_run)

    print(f"新增笔记 {new_notes} 篇，搬运图片 {assets} 张")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
