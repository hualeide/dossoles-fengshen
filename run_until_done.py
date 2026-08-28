#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Keep scraping until complete, export, then shutdown."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "comments.sqlite"
CKPT = DATA / "checkpoint.json"
OUT = ROOT / "out"
LOG = DATA / "runner.log"
PIDFILE = DATA / "runner.pid"
PYTHON = sys.executable


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def ckpt() -> dict:
    if not CKPT.exists():
        return {}
    return json.loads(CKPT.read_text(encoding="utf-8"))


def stats() -> tuple[int, int, int, int]:
    if not DB.exists():
        return 0, 0, 0, 0
    conn = sqlite3.connect(DB, timeout=60)
    stored = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    users = conn.execute("SELECT COUNT(DISTINCT mid) FROM comments").fetchone()[0]
    roots = conn.execute("SELECT COUNT(*) FROM comments WHERE root=0").fetchone()[0]
    official_row = conn.execute("SELECT v FROM meta WHERE k='official_count'").fetchone()
    official = int(official_row[0]) if official_row else 0
    conn.close()
    return stored, users, roots, official


def run_scrape() -> int:
    log("start scrape_comments.py")
    env = os.environ.copy()
    env["SHARDS"] = "1"
    env.pop("MAX_PAGES", None)
    # Clash Verge mixed-port；不走本机山东 IP（-352）
    env["HTTP_PROXY"] = "http://127.0.0.1:7897"
    env["HTTPS_PROXY"] = "http://127.0.0.1:7897"
    env["http_proxy"] = env["HTTP_PROXY"]
    env["https_proxy"] = env["HTTPS_PROXY"]
    env.pop("NO_PROXY", None)
    env.pop("no_proxy", None)
    p = subprocess.run(
        [PYTHON, "-u", str(ROOT / "scrape_comments.py")],
        cwd=str(ROOT),
        env=env,
    )
    log(f"scrape exit={p.returncode}")
    return p.returncode


def export() -> None:
    log("export ranks")
    p = subprocess.run([PYTHON, "-u", str(ROOT / "export_rank.py")], cwd=str(ROOT))
    if p.returncode != 0:
        raise RuntimeError(f"export failed {p.returncode}")
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DB, OUT / "comments.sqlite")
    if CKPT.exists():
        shutil.copy2(CKPT, OUT / "checkpoint.json")


def write_report() -> Path:
    stored, users, roots, official = stats()
    replies = stored - roots
    cover = stored * 100 / official if official else 0
    c = ckpt()
    report = OUT / "完成报告.txt"
    lines = [
        f"完成时间: {datetime.now():%Y-%m-%d %H:%M:%S}",
        "视频: BV1fy4y1L7Rq 《明日方舟》夏日嘉年华限时活动宣传PV",
        f"B站显示评论数: {official}",
        f"入库评论数: {stored}",
        f"主评: {roots}",
        f"回复: {replies}",
        f"用户数: {users}",
        f"覆盖率: {cover:.2f}%",
        f"main_done: {flags(c)[0]}",
        f"replies_done: {flags(c)[1]}",
        f"pages: {c.get('pages')}",
        f"xlsx: {OUT / '明日方舟_多索雷斯假日_评论用户统计.xlsx'}",
        f"sqlite: {OUT / 'comments.sqlite'}",
        f"封神榜csv: {OUT / '封神榜.csv'}",
        f"评论明细csv: {OUT / '评论明细.csv'}",
        "",
        "比对说明: 以 B 站公开评论接口返回为准。主评翻完即结束，按用户要求未再爬楼中楼。",
        "若覆盖率不足 100%，通常是 B 站截断极旧楼层或接口不可见，不是本地漏存。",
    ]
    report.write_text("\n".join(lines), encoding="utf-8")
    log("\n".join(lines))
    return report


def flags(c: dict) -> tuple[bool, bool]:
    main = bool(c.get("main_done") or c.get("main_done"))
    replies = bool(c.get("replies_done") or c.get("replies_done"))
    return main, replies


def complete() -> bool:
    c = ckpt()
    stored, users, roots, official = stats()
    cover = stored / official if official else 0
    main, replies = flags(c)
    done = bool(main and replies)
    log(
        f"compare stored={stored} official={official} cover={cover:.4f} "
        f"roots={roots} replies={stored - roots} users={users} "
        f"main_done={main} replies_done={replies}"
    )
    return done


def shutdown() -> None:
    log("skip shutdown as requested")


def write_pid() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()), encoding="utf-8")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    write_pid()
    log("runner start")
    crashes = 0
    while not complete():
        code = run_scrape()
        if complete():
            break
        crashes += 1
        wait = min(120, 15 * crashes)
        log(f"not complete yet, scrape_exit={code}, wait {wait}s then retry")
        time.sleep(wait)
        if crashes >= 80:
            log("too many scrape restarts, export anyway")
            break
    export()
    write_report()
    (DATA / "finished.flag").write_text(
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8"
    )
    shutdown()


if __name__ == "__main__":
    main()
