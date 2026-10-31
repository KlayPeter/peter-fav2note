"""PyInstaller 入口：打包后由 Electron 直接拉起。"""

from __future__ import annotations

import argparse
from pathlib import Path

from fav2note.config import Config
from fav2note.web.app import serve


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", default=".")
    parser.add_argument("--port", type=int, default=7788)
    args = parser.parse_args()

    config = Config.load(Path(args.home))
    config.ensure_dirs()
    serve(config, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
