"""本地 Web 面板：轻量、只读为主，长任务放后台线程跑。

启动：fav2note web --port 7788
"""

from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from ..config import Config
from ..pipeline.link import relink
from ..store.state import StateStore

STATIC = Path(__file__).with_name("static")


def _update_env(path: Path, updates: dict[str, str]) -> None:
    """就地更新 .env：有则替换，无则追加。"""
    lines: list[str] = []
    if path.is_file():
        lines = path.read_text(encoding="utf-8").splitlines()

    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in updates:
            result.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            result.append(line)
    for key, value in updates.items():
        if key not in seen:
            result.append(f"{key}={value}")
    path.write_text("\n".join(result) + "\n", encoding="utf-8")


class JobRunner:
    """同一时刻只跑一个后台任务，前端轮询进度。"""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.running = False
        self.name = ""
        self.started_at = 0.0
        self._lock = threading.Lock()

    def start(self, name: str, func) -> bool:
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.name = name
            self.log = []
            self.started_at = time.time()

        def wrapper():
            try:
                func(self.log.append)
            except Exception as error:  # noqa: BLE001
                self.log.append(f"出错：{error}")
            finally:
                with self._lock:
                    self.running = False
                    self.log.append("任务结束")

        threading.Thread(target=wrapper, daemon=True).start()
        return True

    def snapshot(self) -> dict:
        return {
            "running": self.running,
            "name": self.name,
            "log": self.log[-200:],
            "elapsed": round(time.time() - self.started_at, 1) if self.started_at else 0,
        }


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="fav2note", docs_url=None, redoc_url=None)
    runner = JobRunner()

    def state() -> StateStore:
        return StateStore(config.data / "state.db")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    @app.get("/api/summary")
    def summary() -> dict:
        counts = state().counts()
        notes = [p for p in config.vault.rglob("*.md") if "assets" not in p.parts]
        by_platform: dict[str, int] = {}
        for note in notes:
            head = note.read_text(encoding="utf-8")[:300]
            match = re.search(r"^platform:\s*(\S+)", head, re.M)
            name = match.group(1) if match else "未标注"
            by_platform[name] = by_platform.get(name, 0) + 1
        return {
            "counts": counts,
            "notes": len(notes),
            "by_platform": by_platform,
            "job": runner.snapshot(),
        }

    @app.get("/api/items")
    def items(status: str = "all", limit: int = 200) -> dict:
        rows: list[dict] = []
        if (config.data / "items.json").is_file():
            import json

            rows = json.loads((config.data / "items.json").read_text(encoding="utf-8"))
        store = state()
        for row in rows:
            key = f"{row['platform']}:{row['item_id']}"
            row["status"] = store.status(key) or "pending"
        if status != "all":
            rows = [r for r in rows if r["status"] == status]
        return {"items": rows[:limit], "total": len(rows)}

    @app.get("/api/notes")
    def notes(limit: int = 100) -> dict:
        found = []
        for path in sorted(config.vault.rglob("*.md"), reverse=True):
            if "assets" in path.parts:
                continue
            head = path.read_text(encoding="utf-8")[:400]
            platform = re.search(r"^platform:\s*(\S+)", head, re.M)
            category = re.search(r"^category:\s*(\S+)", head, re.M)
            found.append({
                "title": path.stem,
                "platform": platform.group(1) if platform else "",
                "category": category.group(1) if category else path.parent.name,
                "path": str(path),
            })
            if len(found) >= limit:
                break
        return {"notes": found, "total": len(found)}

    @app.post("/api/collect")
    def collect(source: str = "both", limit: int = 100) -> JSONResponse:
        from ..sources.douyin import DouyinSource
        from ..sources.xiaohongshu import XiaohongshuSource

        def job(log):
            from ..store.accounts import Accounts

            accounts = Accounts(config.data / "accounts.json")
            targets = ["xhs", "douyin"] if source == "both" else [source]
            found = []
            for name in targets:
                if name == "douyin":
                    try:
                        items = DouyinSource(config.cache / "douyin_profile").collect(limit=limit)
                        accounts.set("douyin", True, f"{len(items)} 条")
                        found += items
                        log(f"抖音：{len(items)} 条")
                    except Exception as error:  # noqa: BLE001
                        accounts.set("douyin", False, str(error)[:120])
                        log(f"抖音失败：{error}")
                else:
                    export = config.inbox / "fav_all.json"
                    if not export.is_file():
                        log(f"小红书：没找到 {export}，先用油猴脚本导出")
                        continue
                    items = XiaohongshuSource(export).collect()
                    found += items
                    log(f"小红书：{len(items)} 条")

            import json
            import sqlite3

            # 与既有清单合并，保留处理状态
            existing_path = config.data / "items.json"
            merged: dict[str, dict] = {}
            if existing_path.is_file():
                for row in json.loads(existing_path.read_text(encoding="utf-8")):
                    merged[f"{row['platform']}:{row['item_id']}"] = row
            for item in found:
                merged.setdefault(f"{item.platform}:{item.item_id}", item.__dict__)
            existing_path.write_text(
                json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"采集完成：新增 {len(found)} 条，清单共 {len(merged)} 条")

        ok = runner.start("collect", job)
        return JSONResponse({"started": ok})

    @app.post("/api/link")
    def link() -> JSONResponse:
        def job(log):
            count = relink(config.vault)
            log(f"关联更新：{count} 篇")

        return JSONResponse({"started": runner.start("link", job)})

    @app.get("/api/job")
    def job() -> dict:
        return runner.snapshot()

    @app.get("/api/config")
    def get_config() -> dict:
        return {
            "has_key": bool(config.api_key),
            "base_url": config.base_url,
            "model": config.model,
            "frames_min": config.frames_min,
            "frames_max": config.frames_max,
        }

    @app.get("/api/status")
    def accounts_status() -> dict:
        from ..store.accounts import Accounts

        store = Accounts(config.data / "accounts.json")
        douyin = store.get("douyin")
        return {
            "douyin": douyin,
            "xhs_export": (config.inbox / "fav_all.json").is_file(),
        }

    @app.post("/api/config")
    def set_config(payload: dict) -> dict:
        frames_min = int(payload.get("frames_min") or 3)
        frames_max = int(payload.get("frames_max") or 10)
        if frames_min > frames_max:
            frames_min, frames_max = frames_max, frames_min
        updates = {
            "FAV2NOTE_BASE_URL": str(payload.get("base_url", "")).strip(),
            "FAV2NOTE_MODEL": str(payload.get("model", "")).strip(),
            "FAV2NOTE_FRAMES_MIN": str(max(1, min(20, frames_min))),
            "FAV2NOTE_FRAMES_MAX": str(max(1, min(20, frames_max))),
        }
        key = str(payload.get("api_key", "")).strip()
        if key:
            updates["FAV2NOTE_API_KEY"] = key
        _update_env(config.home / ".env", {k: v for k, v in updates.items() if v})
        return {"saved": True}

    @app.post("/api/run")
    def run_pipeline(limit: int = 20, payload: dict | None = None) -> JSONResponse:
        keys = list((payload or {}).get("keys") or [])

        def job(log):
            import subprocess
            import sys

            cmd = [sys.executable, "-m", "fav2note.cli", "--home", str(config.home), "run"]
            if keys:
                selection = config.data / "selection.txt"
                selection.write_text("\n".join(keys), encoding="utf-8")
                cmd += ["--select", str(selection)]
                log(f"处理选中的 {len(keys)} 条")
            else:
                cmd += ["--limit", str(limit)]
                log(f"处理队列前 {limit} 条")
            log("$ " + " ".join(cmd[2:]))
            proc = subprocess.Popen(
                cmd, cwd=str(config.home), stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore",
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                log(line.rstrip())
            proc.wait()
            log(f"退出码 {proc.returncode}")

        return JSONResponse({"started": runner.start("run", job)})

    return app


def serve(config: Config, host: str = "127.0.0.1", port: int = 7788) -> None:
    import uvicorn

    config.ensure_dirs()
    uvicorn.run(create_app(config), host=host, port=port, log_level="warning")
