"""按分类结果清理知识库：verdict=drop 的笔记移到 _vault_dropped。

不删除，随时可以捞回来。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"
DROPPED = ROOT / "_vault_dropped"


def main() -> int:
    items_path = ROOT / "data" / "items.json"
    if not items_path.is_file():
        print("没有 items.json")
        return 1
    items = json.loads(items_path.read_text(encoding="utf-8"))
    drop_ids = {str(i["item_id"]) for i in items if i.get("extra", {}).get("verdict") == "drop"}
    print(f"分类为 drop 的条目：{len(drop_ids)}")

    moved = 0
    for note in list(VAULT.rglob("*.md")):
        if "assets" in note.parts:
            continue
        head = note.read_text(encoding="utf-8")[:400]
        match = re.search(r"^source_id:\s*(\S+)", head, re.M)
        if not match or match.group(1) not in drop_ids:
            continue

        rel = note.relative_to(VAULT)
        target = DROPPED / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        assets = note.parent / "assets" / note.stem
        if assets.is_dir():
            dst = DROPPED / rel.parent / "assets" / note.stem
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                shutil.rmtree(dst)
            shutil.move(str(assets), str(dst))
        shutil.move(str(note), str(target))
        moved += 1

    left = [p for p in VAULT.rglob("*.md") if "assets" not in p.parts]
    print(f"移出 {moved} 篇，剩余 {len(left)} 篇")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
