"""本地 Web 面板：轻量、只读为主，长任务放后台线程跑。

启动：fav2note web --port 7788
"""

from __future__ import annotations

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
            platform = note.relative_to(config.vault).parts[0]
            by_platform[platform] = by_platform.get(platform, 0) + 1
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
            rel = path.relative_to(config.vault)
            found.append({
                "title": path.stem,
                "platform": rel.parts[0] if len(rel.parts) > 1 else "",
                "category": rel.parts[1] if len(rel.parts) > 2 else "",
                "path": str(path),
            })
            if len(found) >= limit:
                break
        return {"notes": found, "total": len(found)}

    @app.post("/api/collect")
    def collect(source: str = "douyin", limit: int = 100) -> JSONResponse:
        from ..sources.douyin import DouyinSource
        from ..sources.xiaohongshu import XiaohongshuSource

        def job(log):
            log(f"开始采集：{source}")
            if source == "douyin":
                found = DouyinSource(config.cache / "douyin_profile").collect(limit=limit)
            else:
                export = config.inbox / "fav_all.json"
                if not export.is_file():
                    log(f"没找到 {export}，先把导出的 JSON 放进来")
                    return
                found = XiaohongshuSource(export).collect()
            import json

            (config.data / "items.json").write_text(
                json.dumps([i.__dict__ for i in found], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(f"采集完成：{len(found)} 条")

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
            "frames": config.frames_per_note,
        }

    @app.post("/api/config")
    def set_config(payload: dict) -> dict:
        updates = {
            "FAV2NOTE_BASE_URL": str(payload.get("base_url", "")).strip(),
            "FAV2NOTE_MODEL": str(payload.get("model", "")).strip(),
            "FAV2NOTE_FRAMES": str(payload.get("frames", "")).strip(),
        }
        key = str(payload.get("api_key", "")).strip()
        if key:
            updates["FAV2NOTE_API_KEY"] = key
        _update_env(config.home / ".env", {k: v for k, v in updates.items() if v})
        return {"saved": True}

    @app.post("/api/run")
    def run_pipeline(limit: int = 20) -> JSONResponse:
        def job(log):
            import subprocess
            import sys

            cmd = [sys.executable, "-m", "fav2note.cli", "--home", str(config.home), "run", "--limit", str(limit)]
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
