"""把 vault 从「平台/分类」改成「分类」，平台只留在 frontmatter。

旧：vault/小红书/技术AI/标题.md
新：vault/技术AI/标题.md

用法：
    python scripts/flatten_vault.py --dry-run
    python scripts/flatten_vault.py
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
PLATFORMS = {"小红书", "抖音", "B站"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    moved = 0
    for platform_dir in VAULT.iterdir():
        if not platform_dir.is_dir() or platform_dir.name not in PLATFORMS:
            continue
        for note in sorted(platform_dir.rglob("*.md")):
            if "assets" in note.parts:
                continue
            rel = note.relative_to(platform_dir)
            target = VAULT / rel
            if target.exists():
                continue
            if args.dry_run:
                print(f"[dry] {note.relative_to(VAULT)} -> {rel}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(note), str(target))

            source_assets = note.parent / "assets" / note.stem
            if source_assets.is_dir():
                dest_assets = target.parent / "assets" / target.stem
                if args.dry_run:
                    print(f"[dry] {source_assets.relative_to(VAULT)} -> {dest_assets.relative_to(VAULT)}")
                else:
                    dest_assets.parent.mkdir(parents=True, exist_ok=True)
                    if dest_assets.exists():
                        shutil.rmtree(dest_assets)
                    shutil.move(str(source_assets), str(dest_assets))
            moved += 1

    if not args.dry_run:
        # 清掉空的平台目录
        for platform_dir in list(VAULT.iterdir()):
            if platform_dir.is_dir() and platform_dir.name in PLATFORMS:
                remaining = list(platform_dir.rglob("*"))
                if not remaining:
                    platform_dir.rmdir()
        print(f"迁移 {moved} 篇")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
