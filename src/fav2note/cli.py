"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .config import Config
from .models import Item
from .pipeline.extract import Extractor
from .pipeline.frames import frames_for_sections
from .pipeline.link import relink
from .pipeline.transcribe import Transcriber, timed_text
from .sources.douyin import DouyinSource
from .sources.xiaohongshu import XiaohongshuSource
from .store.state import StateStore
from .store.vault import Vault


def _items_file(config: Config) -> Path:
    return config.data / "items.json"


def _load_items(config: Config) -> list[Item]:
    path = _items_file(config)
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Item(**row) for row in raw]


def _save_items(config: Config, items: list[Item]) -> None:
    _items_file(config).write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------- 命令 ----------------
def _collect_items(config: Config, source: str, limit: int) -> list[Item]:
    """采集单平台；失败返回空列表而不是抛错。"""
    try:
        if source == "xhs":
            export = config.inbox / "fav_all.json"
            if not export.is_file():
                print(f"跳过小红书：{export} 不存在")
                return []
            return XiaohongshuSource(export).collect()
        return DouyinSource(config.cache / "douyin_profile").collect(limit=limit)
    except Exception as error:  # noqa: BLE001
        print(f"{source} 采集失败：{error}")
        return []


def _merge_items(config: Config, new_items: list[Item]) -> list[Item]:
    """与已有清单按 key 合并，保留旧条目的处理状态。"""
    existing = _load_items(config)
    merged = {item.key: item for item in existing}
    for item in new_items:
        merged.setdefault(item.key, item)
    result = list(merged.values())
    _save_items(config, result)
    return result


def cmd_collect(args, config: Config) -> int:
    config.ensure_dirs()
    sources = ["xhs", "douyin"] if args.source == "both" else [args.source]
    collected: list[Item] = []
    for source in sources:
        items = _collect_items(config, source, args.limit)
        print(f"{source}：{len(items)} 条")
        collected.extend(items)

    merged = _merge_items(config, collected)
    print(f"清单共 {len(merged)} 条（新增 {len(collected)}）→ {_items_file(config)}")
    return 0


def cmd_login(args, config: Config) -> int:
    if args.source == "douyin":
        DouyinSource(config.cache / "douyin_profile").login()
        print("登录态已保存")
        return 0
    print("小红书不需要单独登录：用浏览器登录后导出收藏 JSON 即可")
    return 0


def cmd_run(args, config: Config) -> int:
    config.ensure_dirs()
    items = _load_items(config)
    if not items:
        print("还没有采集结果，先跑 fav2note collect")
        return 1

    state = StateStore(config.data / "state.db")
    vault = Vault(config.vault)
    transcriber = Transcriber(config)
    extractor = Extractor(config)

    todo = [i for i in items if state.status(i.key) not in {"done", "skip", "image_only"}]
    if args.limit:
        todo = todo[: args.limit]
    print(f"待处理 {len(todo)} 条 / 共 {len(items)} 条")

    for index, item in enumerate(todo, start=1):
        started = time.perf_counter()
        head = f"[{index}/{len(todo)}] {item.platform}｜{item.title[:28]}"
        print(head)
        state.set(item.key, item.platform, item.title, "running")

        workdir = config.cache / item.platform / item.item_id
        workdir.mkdir(parents=True, exist_ok=True)

        try:
            source = (
                DouyinSource(config.cache / "douyin_profile")
                if item.platform == "抖音"
                else XiaohongshuSource(Path(""))
            )
            media = None
            last_error: Exception = RuntimeError("下载失败")
            for attempt, wait in enumerate((0, 15, 45), start=1):
                if wait:
                    print(f"    [重试 {attempt}] 等待 {wait}s")
                    time.sleep(wait)
                try:
                    media = source.fetch(item, workdir)
                    break
                except Exception as error:  # noqa: BLE001
                    last_error = error
            if media is None:
                raise last_error
        except Exception as error:  # noqa: BLE001
            state.set(item.key, item.platform, item.title, "failed", error=str(error))
            print(f"    下载失败：{error}")
            continue

        if not media.has_video:
            state.set(item.key, item.platform, item.title, "image_only")
            print("    纯图文，暂不处理")
            continue

        try:
            transcript = transcriber.run(media)
        except Exception as error:  # noqa: BLE001
            state.set(item.key, item.platform, item.title, "failed", error=str(error))
            print(f"    转写失败：{error}")
            continue

        if len(transcript.segments) < 3:
            state.set(item.key, item.platform, item.title, "skip", error="逐字稿过短")
            print("    跳过：几乎没有人声")
            continue

        item.extra["timed_text"] = timed_text(transcript.segments)
        try:
            draft = extractor.run(item, transcript)
        except Exception as error:  # noqa: BLE001
            state.set(item.key, item.platform, item.title, "failed", error=str(error))
            print(f"    提炼失败：{error}")
            continue

        frames = frames_for_sections(
            config, media.video, draft.sections,
            vault.assets_dir(item, draft.category), limit=config.frames_per_note,
        )
        path = vault.write(item, draft, frames, vault.root)
        cost = time.perf_counter() - started
        state.set(item.key, item.platform, item.title, "done", note_path=str(path), seconds=cost)
        print(f"    完成 {cost:.0f}s｜截图 {len(frames)}｜{draft.category}｜density={draft.density}")

    if not args.no_link:
        linked = relink(config.vault)
        print(f"关联更新：{linked} 篇")

    counts = StateStore(config.data / "state.db").counts()
    print("状态：", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


def cmd_link(args, config: Config) -> int:
    linked = relink(config.vault, top=args.top)
    print(f"已为 {linked} 篇写入相关笔记")
    return 0


def cmd_stats(args, config: Config) -> int:
    state = StateStore(config.data / "state.db")
    counts = state.counts()
    if not counts:
        print("还没有处理记录")
        return 0
    for status, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"{status:<12}{count}")
    notes = [p for p in config.vault.rglob("*.md") if "assets" not in p.parts]
    print(f"\n知识库笔记：{len(notes)} 篇")
    return 0


def cmd_web(args, config: Config) -> int:
    from .web import serve

    print(f"面板已启动：http://{args.host}:{args.port}")
    serve(config, host=args.host, port=args.port)
    return 0


def cmd_daemon(args, config: Config) -> int:
    """常驻：定时采集两个平台，再处理队列。"""
    config.ensure_dirs()
    round_no = 0
    while True:
        round_no += 1
        print(f"\n=== 第 {round_no} 轮 {time.strftime('%Y-%m-%d %H:%M:%S')} ===")
        collected: list[Item] = []
        for source in ("xhs", "douyin"):
            collected.extend(_collect_items(config, source, args.limit))
        if collected:
            merged = _merge_items(config, collected)
            print(f"清单共 {len(merged)} 条")

        run_args = argparse.Namespace(limit=args.batch, no_link=False)
        cmd_run(run_args, config)

        if args.once:
            return 0
        print(f"下一轮在 {args.interval // 60} 分钟后")
        time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fav2note", description="收藏转知识库")
    parser.add_argument("--home", default=".", help="工作目录（默认当前目录）")
    parser.add_argument("--version", action="version", version=f"fav2note {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)

    collect = subs.add_parser("collect", help="采集收藏列表")
    collect.add_argument("--source", choices=["xhs", "douyin", "both"], default="both")
    collect.add_argument("--file", help="兼容旧用法：指定小红书导出文件")
    collect.add_argument("--limit", type=int, default=200)
    collect.set_defaults(func=cmd_collect)

    login = subs.add_parser("login", help="保存登录态")
    login.add_argument("--source", choices=["xhs", "douyin"], required=True)
    login.set_defaults(func=cmd_login)

    run = subs.add_parser("run", help="下载 → 转写 → 提炼 → 入库")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--no-link", action="store_true")
    run.set_defaults(func=cmd_run)

    link = subs.add_parser("link", help="重建笔记关联")
    link.add_argument("--top", type=int, default=3)
    link.set_defaults(func=cmd_link)

    stats = subs.add_parser("stats", help="查看处理统计")
    stats.set_defaults(func=cmd_stats)

    web = subs.add_parser("web", help="启动本地面板")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=7788)
    web.set_defaults(func=cmd_web)

    daemon = subs.add_parser("daemon", help="常驻：定时采集并处理")
    daemon.add_argument("--interval", type=int, default=3600, help="间隔秒数，默认 1 小时")
    daemon.add_argument("--limit", type=int, default=200, help="每轮每平台最多采集多少条")
    daemon.add_argument("--batch", type=int, default=20, help="每轮最多处理多少条")
    daemon.add_argument("--once", action="store_true", help="只跑一轮，用于测试")
    daemon.set_defaults(func=cmd_daemon)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = Config.load(Path(args.home))
    try:
        return args.func(args, config)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
