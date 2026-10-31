"""本地 Web 面板：轻量、只读为主，长任务放后台线程跑。

启动：fav2note web --port 7788
"""

from __future__ import annotations

import json
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


class Scheduler:
    """应用内定时：按间隔触发「采集 + 处理增量」。

    只处理未完成的条目，所以天然是增量，不会重复花钱。
    """

    def __init__(self, config: Config, runner: JobRunner) -> None:
        self.config = config
        self.runner = runner
        self.path = config.data / "schedule.json"
        self._thread: threading.Thread | None = None

    def read(self) -> dict:
        if self.path.is_file():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except ValueError:
                pass
        return {"enabled": False, "every_minutes": 1440, "last_run": ""}

    def write(self, data: dict) -> dict:
        current = self.read()
        current.update(data)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True, name="fav2note-scheduler")
        self._thread.start()

    def _loop(self) -> None:
        while True:
            try:
                self._tick()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(30)

    def _tick(self) -> None:
        state = self.read()
        if not state.get("enabled") or self.runner.running:
            return
        # 没做过全量就先不做定时，避免只吃到增量
        if not (self.config.data / "full_run.json").is_file():
            return
        every = max(30, int(state.get("every_minutes", 1440)))
        last = state.get("last_run") or ""
        if last:
            try:
                elapsed = (time.time() - time.mktime(time.strptime(last, "%Y-%m-%d %H:%M"))) / 60
            except ValueError:
                elapsed = every + 1
            if elapsed < every:
                return
        self.write({"last_run": time.strftime("%Y-%m-%d %H:%M")})
        self.runner.start("auto", self._job)

    def _job(self, log) -> None:
        import subprocess
        import sys

        log("定时任务：开始采集")
        for source in ("xhs", "douyin"):
            try:
                if source == "douyin":
                    from ..sources.douyin import DouyinSource

                    items = DouyinSource(self.config.cache / "douyin_profile").collect(limit=100)
                else:
                    export = self.config.inbox / "fav_all.json"
                    if not export.is_file():
                        log("小红书：缺少导出文件，跳过")
                        continue
                    from ..sources.xiaohongshu import XiaohongshuSource

                    items = XiaohongshuSource(export).collect()
                log(f"{source}：{len(items)} 条")
            except Exception as error:  # noqa: BLE001
                log(f"{source} 采集失败：{error}")

        cmd = [sys.executable, "-m", "fav2note.cli", "--home", str(self.config.home),
               "run", "--limit", "20"]
        proc = subprocess.Popen(cmd, cwd=str(self.config.home), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="ignore")
        assert proc.stdout is not None
        for line in proc.stdout:
            log(line.rstrip())
        proc.wait()


def create_app(config: Config) -> FastAPI:
    app = FastAPI(title="fav2note", docs_url=None, redoc_url=None)
    runner = JobRunner()
    scheduler = Scheduler(config, runner)
    scheduler.start()

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
    def collect(source: str = "both", limit: int = 100, payload: dict | None = None) -> JSONResponse:
        limit = 100000 if limit <= 0 else limit  # 0 表示全量
        from ..sources.douyin import DouyinSource
        from ..sources.xiaohongshu import XiaohongshuSource

        def job(log):
            from ..store.accounts import Accounts

            accounts = Accounts(config.data / "accounts.json")

            # 弹窗传来的排除设置：先落盘，采集时立即生效
            if payload and ("tags" in payload or "prompt" in payload):
                from ..pipeline.filters import Filters

                saved = Filters(config.data / "filters.json").save(
                    list(payload.get("tags") or []), str(payload.get("prompt", ""))
                )
                log(f"排除设置：{len(saved['tags'])} 个标签" + (f"，提示词 {len(saved['prompt'])} 字" if saved["prompt"] else ""))
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
                    xhs = XiaohongshuSource(config.inbox / "fav_all.json", config.cache / "xhs_profile")
                    try:
                        items = xhs.collect(limit=limit)
                        accounts.set("xhs", True, f"{len(items)} 条")
                    except Exception as error:  # noqa: BLE001
                        accounts.set("xhs", False, str(error)[:120])
                        log(f"小红书浏览器采集失败：{error}")
                        items = xhs.collect_from_file()
                        if not items:
                            log("小红书：没有导出文件可用，先在浏览器导出 fav_all.json")
                            continue
                    found += items
                    log(f"小红书：{len(items)} 条")

            import json

            # 采集时就按排除标签标记，避免后面处理时白跑
            from ..pipeline.filters import Filters

            store = Filters(config.data / "filters.json")
            dropped = 0
            for item in found:
                tag = store.excluded(item.title)
                if tag:
                    item.extra["verdict"] = "drop"
                    item.extra["excluded_by"] = tag
                    dropped += 1
            if dropped:
                log(f"按排除标签标记 {dropped} 条（不会进入处理队列）")

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

    @app.post("/api/add")
    def add_link(payload: dict) -> dict:
        from ..sources.douyin import DouyinSource
        from ..sources.xiaohongshu import XiaohongshuSource

        url = str(payload.get("url", "")).strip()
        if not url:
            return {"ok": False, "message": "链接为空"}
        try:
            if "xiaohongshu.com" in url or "xhslink" in url:
                item = XiaohongshuSource.from_url(url)
            elif "douyin.com" in url:
                item = DouyinSource.from_url(url)
            else:
                return {"ok": False, "message": "只认得小红书、抖音的链接"}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "message": f"解析失败：{error}"}

        path = config.data / "items.json"
        items = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        merged = {f"{i['platform']}:{i['item_id']}": i for i in items}
        merged[item.key] = item.__dict__
        path.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "key": item.key, "title": item.title, "platform": item.platform}

    @app.get("/api/vault")
    def get_vault() -> dict:
        count = len([p for p in config.vault.rglob("*.md") if "assets" not in p.parts]) if config.vault.is_dir() else 0
        return {"path": str(config.vault), "notes": count, "exists": config.vault.is_dir()}

    @app.post("/api/vault")
    def set_vault(payload: dict) -> dict:
        raw = str(payload.get("path", "")).strip()
        if not raw:
            return {"ok": False, "message": "路径为空"}
        target = Path(raw).expanduser()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            return {"ok": False, "message": f"无法创建目录：{error}"}

        config.vault_path = str(target.resolve())
        _update_env(config.home / ".env", {"FAV2NOTE_VAULT": config.vault_path})
        return {"ok": True, "path": config.vault_path}

    @app.post("/api/open")
    def open_target(payload: dict) -> dict:
        """在资源管理器或 Obsidian 中打开知识库。"""
        import subprocess

        target = str(payload.get("target", "folder"))
        vault = config.vault
        vault.mkdir(parents=True, exist_ok=True)
        try:
            if target == "folder":
                subprocess.Popen(["explorer", str(vault)])
            else:
                # obsidian://open?vault=<库名>，库名即目录名
                subprocess.Popen(["cmd", "/c", "start", "", f"obsidian://open?vault={vault.name}"])
            return {"ok": True}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "message": str(error)}

    @app.post("/api/vault/init")
    def init_vault() -> dict:
        """仅在配置缺失时补齐，绝不覆盖用户已有的 Obsidian 设置。"""
        import json as _json

        vault = config.vault
        obsidian = vault / ".obsidian"
        (obsidian / "plugins").mkdir(parents=True, exist_ok=True)
        created = []

        app_file = obsidian / "app.json"
        if not app_file.is_file():
            app_file.write_text(
                _json.dumps(
                    {
                        "attachmentFolderPath": "_attachments",
                        "newLinkFormat": "relative",
                        "useMarkdownLinks": True,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            created.append("app.json")

        return {"ok": True, "path": str(obsidian), "created": created}

    @app.post("/api/link")
    def link() -> JSONResponse:
        def job(log):
            count = relink(config.vault)
            log(f"关联更新：{count} 篇")

        return JSONResponse({"started": runner.start("link", job)})

    @app.get("/api/schedule")
    def get_schedule() -> dict:
        return scheduler.read()

    @app.post("/api/schedule")
    def set_schedule(payload: dict) -> dict:
        data = {
            "enabled": bool(payload.get("enabled")),
            "every_minutes": max(15, int(payload.get("every_minutes") or 180)),
        }
        return scheduler.write(data)

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
        export = config.inbox / "fav_all.json"
        return {
            "douyin": store.get("douyin"),
            "xhs": store.get("xhs"),
            "xhs_export": export.is_file(),
            "xhs_export_at": (
                __import__("datetime").datetime.fromtimestamp(export.stat().st_mtime).strftime("%m-%d %H:%M")
                if export.is_file()
                else ""
            ),
        }

    @app.post("/api/login")
    def login(source: str = "douyin") -> JSONResponse:
        from ..sources.douyin import DouyinSource
        from ..sources.xiaohongshu import XiaohongshuSource
        from ..store.accounts import Accounts

        def job(log):
            accounts = Accounts(config.data / "accounts.json")
            try:
                if source == "douyin":
                    DouyinSource(config.cache / "douyin_profile").login()
                else:
                    XiaohongshuSource(profile_dir=config.cache / "xhs_profile").login()
                accounts.set(source, True, "面板内登录")
                log(f"{source} 登录完成")
            except Exception as error:  # noqa: BLE001
                accounts.set(source, False, str(error)[:120])
                log(f"{source} 登录失败：{error}")

        return JSONResponse({"started": runner.start("login", job)})

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

        # 内存里同步更新，保存后立即生效，不用重启
        if key:
            config.api_key = key
        if updates["FAV2NOTE_BASE_URL"]:
            config.base_url = updates["FAV2NOTE_BASE_URL"]
        if updates["FAV2NOTE_MODEL"]:
            config.model = updates["FAV2NOTE_MODEL"]
        config.frames_min = int(updates["FAV2NOTE_FRAMES_MIN"])
        config.frames_max = int(updates["FAV2NOTE_FRAMES_MAX"])
        return {"saved": True}

    @app.get("/api/stats")
    def stats() -> dict:
        """清单按平台统计：总数与待处理数。"""
        path = config.data / "items.json"
        rows = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
        store = state()
        result: dict[str, dict] = {}
        for row in rows:
            name = row.get("platform", "未知")
            key = f"{name}:{row.get('item_id')}"
            bucket = result.setdefault(name, {"total": 0, "pending": 0})
            bucket["total"] += 1
            if store.status(key) != "done":
                bucket["pending"] += 1
        return {"platforms": result}

    @app.get("/api/filters")
    def get_filters() -> dict:
        from ..pipeline.filters import DEFAULT_TAGS, TAG_RULES, Filters

        store = Filters(config.data / "filters.json")
        return {
            "tags": store.data.get("tags", DEFAULT_TAGS),
            "prompt": store.data.get("prompt", ""),
            "all_tags": list(TAG_RULES),
        }

    @app.post("/api/filters")
    def set_filters(payload: dict) -> dict:
        from ..pipeline.filters import Filters

        store = Filters(config.data / "filters.json")
        return store.save(list(payload.get("tags") or []), str(payload.get("prompt", "")))

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
