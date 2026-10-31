"""清理脚本：缓存、丢弃区、重复笔记。

用法：
    python scripts/clean.py --dry-run      # 先看会删什么
    python scripts/clean.py --cache        # 清下载缓存
    python scripts/clean.py --dropped      # 清丢弃区
    python scripts/clean.py --duplicates   # 按 source_id 去重
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def human(size: int) -> str:
    return f"{size / 1024 / 1024:.1f} MB"


def dir_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def clean_cache(dry: bool) -> None:
    cache = ROOT / "data" / "cache"
    if not cache.is_dir():
        print("缓存目录不存在")
        return
    size = dir_size(cache)
    if dry:
        print(f"[dry] 清空 data/cache（{human(size)}）")
        return
    shutil.rmtree(cache)
    cache.mkdir(parents=True)
    print(f"已清空 data/cache（{human(size)}）")


def clean_dropped(dry: bool) -> None:
    dropped = ROOT / "_vault_dropped"
    if not dropped.is_dir():
        print("没有丢弃区")
        return
    size = dir_size(dropped)
    count = len(list(dropped.rglob("*.md")))
    if dry:
        print(f"[dry] 清空 _vault_dropped（{count} 篇，{human(size)}）")
        return
    shutil.rmtree(dropped)
    print(f"已清空 _vault_dropped（{count} 篇，{human(size)}）")


def dedupe(dry: bool) -> None:
    """同一 source_id 只留一份，优先保留不带 (2)(3) 后缀的。"""
    vault = ROOT / "vault"
    if not vault.is_dir():
        print("知识库不存在")
        return
    seen: dict[str, Path] = {}
    removed = 0
    for note in sorted(vault.rglob("*.md")):
        if "assets" in note.parts:
            continue
        head = note.read_text(encoding="utf-8")[:400]
        match = re.search(r"^source_id:\s*(\S+)", head, re.M)
        if not match:
            continue
        key = match.group(1)
        keep = seen.get(key)
        if keep is None or ("(" in note.stem and "(" not in keep.stem):
            if keep is not None:
                if dry:
                    print(f"[dry] 删除副本 {keep.name}")
                else:
                    keep.unlink()
                    removed += 1
            seen[key] = note
        else:
            if dry:
                print(f"[dry] 删除副本 {note.name}")
            else:
                note.unlink()
                removed += 1
    print(f"去重完成，删除 {removed} 个副本" if not dry else "以上为将删除的副本")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", action="store_true")
    parser.add_argument("--dropped", action="store_true")
    parser.add_argument("--duplicates", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not any((args.cache, args.dropped, args.duplicates)):
        args.cache = args.dropped = args.duplicates = True

    if args.duplicates:
        dedupe(args.dry_run)
    if args.cache:
        clean_cache(args.dry_run)
    if args.dropped:
        clean_dropped(args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
