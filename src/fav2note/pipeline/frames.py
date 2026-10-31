"""视频截帧：按分节时间点取样，挑细节最丰富的一帧。"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import Config


def duration(config: Config, video: Path) -> float:
    try:
        out = subprocess.run(
            [config.ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", str(video)],
            capture_output=True, text=True, timeout=60,
        )
        return float(out.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return 0.0


def grab_one(config: Config, video: Path, dest: Path, seconds: float) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [config.ffmpeg, "-v", "error", "-y", "-ss", f"{seconds:.1f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=720:-2", "-q:v", "3", str(dest)],
            capture_output=True, timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False
    return dest.is_file() and dest.stat().st_size > 1024


def frames_for_sections(
    config: Config,
    video: Path,
    sections: list[dict],
    dest: Path,
    limit: int = 5,
) -> list[tuple[int, Path]]:
    """每个分节在 +1/+3/+6 秒各取一帧，选文件最大（≈最清晰）的一张。"""
    total = duration(config, video)
    if total <= 0:
        return []
    dest.mkdir(parents=True, exist_ok=True)

    times: list[int] = []
    for section in sections:
        raw = str(section.get("time", ""))
        parts = raw.split(":")
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            times.append(int(parts[0]) * 60 + int(parts[1]))
    if not times:
        step = total / (limit + 1)
        times = [int(step * (i + 1)) for i in range(limit)]

    picked: list[tuple[int, Path]] = []
    for index, base in enumerate(times[:limit]):
        best: tuple[Path, int, float] | None = None
        for offset in (3, 6, 1):
            moment = min(base + offset, max(0.0, total - 1))
            candidate = dest / f"_c{index}_{offset}.jpg"
            if not grab_one(config, video, candidate, moment):
                continue
            if best is None or candidate.stat().st_size > best[2]:
                if best:
                    best[0].unlink(missing_ok=True)
                best = (candidate, base, float(candidate.stat().st_size))
            else:
                candidate.unlink(missing_ok=True)
        if best:
            final = dest / f"f{index + 1:02d}.jpg"
            final.unlink(missing_ok=True)
            best[0].replace(final)
            picked.append((index, final))
    return picked
