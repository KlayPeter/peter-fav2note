"""把知识库同步到 WebDAV（坚果云等）。

用法：
    python scripts/sync_webdav.py            # 同步
    python scripts/sync_webdav.py --dry-run  # 只看要传哪些

需要在 .env 里配置（坚果云「安全选项 → 添加应用密码」）：
    FAV2NOTE_WEBDAV_URL=https://dav.jianguoyun.com/dav/
    FAV2NOTE_WEBDAV_USER=你的邮箱
    FAV2NOTE_WEBDAV_PASS=应用密码
    FAV2NOTE_WEBDAV_DIR=知识库      # 可选，远端子目录

单线程 + 失败退避，避免坚果云 503。
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from urllib.parse import quote

import urllib.request

ROOT = Path(__file__).resolve().parent.parent
VAULT = ROOT / "vault"


def load_env() -> dict:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def request(url: str, method: str = "GET", data: bytes | None = None, auth: tuple[str, str] | None = None):
    req = urllib.request.Request(url, data=data, method=method)
    if auth:
        import base64

        token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
        req.add_header("Authorization", f"Basic {token}")
    req.add_header("User-Agent", "fav2note-sync/1.0")
    return urllib.request.urlopen(req, timeout=60)


def remote_url(base: str, remote_dir: str, rel: Path) -> str:
    parts = [p for p in (remote_dir.split("/") if remote_dir else []) if p]
    parts += [str(p) for p in rel.parts]
    return base.rstrip("/") + "/" + "/".join(quote(p) for p in parts)


def ensure_dir(base: str, remote_dir: str, rel: Path, auth: tuple[str, str]) -> None:
    current = base.rstrip("/")
    for part in [p for p in (remote_dir.split("/") if remote_dir else []) if p] + list(rel.parts):
        current = current + "/" + quote(part) + "/"
        try:
            request(current, "MKCOL", auth=auth)
        except Exception:  # noqa: BLE001 已存在会报 405
            pass


def upload(url: str, payload: bytes, auth: tuple[str, str], retries: int = 5) -> None:
    for attempt in range(retries):
        try:
            request(url, "PUT", data=payload, auth=auth)
            return
        except Exception as error:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            wait = min(60, 5 * (attempt + 1))
            print(f"    重试 {attempt + 2}/{retries}（{error}），等 {wait}s")
            time.sleep(wait)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--vault", default=str(VAULT))
    args = parser.parse_args()

    env = load_env()
    base = env.get("FAV2NOTE_WEBDAV_URL", "")
    user = env.get("FAV2NOTE_WEBDAV_USER", "")
    password = env.get("FAV2NOTE_WEBDAV_PASS", "")
    remote_dir = env.get("FAV2NOTE_WEBDAV_DIR", "")
    if not (base and user and password):
        print("缺少 FAV2NOTE_WEBDAV_URL / USER / PASS，见脚本开头说明")
        return 1

    vault = Path(args.vault)
    files = [p for p in vault.rglob("*") if p.is_file() and ".obsidian" not in p.parts]
    total = sum(p.stat().st_size for p in files)
    print(f"待同步 {len(files)} 个文件，{total / 1024 / 1024:.1f} MB")
    if args.dry_run:
        for p in files[:20]:
            print("  ", p.relative_to(vault))
        return 0

    auth = (user, password)
    done = 0
    started = time.time()
    for path in files:
        rel = path.relative_to(vault)
        ensure_dir(base, remote_dir, rel.parent, auth)
        upload(remote_url(base, remote_dir, rel), path.read_bytes(), auth)
        done += 1
        if done % 20 == 0 or done == len(files):
            rate = done / max(1e-6, time.time() - started)
            print(f"  {done}/{len(files)}  {rate:.1f} 个/秒")

    print("同步完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
