import shutil
from pathlib import Path
v = Path("vault")
moved = 0
for platform in ("小红书", "抖音", "B站"):
    pdir = v / platform
    if not pdir.is_dir(): continue
    for cat in pdir.iterdir():
        if not cat.is_dir(): continue
        src_assets = cat / "assets"
        if not src_assets.is_dir(): continue
        dst_assets = v / cat.name / "assets"
        dst_assets.mkdir(parents=True, exist_ok=True)
        for sub in list(src_assets.iterdir()):
            target = dst_assets / sub.name
            if target.exists():
                shutil.rmtree(target)
            shutil.move(str(sub), str(target))
            moved += 1
        src_assets.rmdir()
    # 清空平台目录
    leftovers = [p for p in pdir.rglob("*") if p.is_file()]
    if not leftovers:
        shutil.rmtree(pdir)
        print("已删除空平台目录", platform)
print("合并图片目录", moved, "个")
