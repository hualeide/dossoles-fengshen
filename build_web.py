#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build compact chunked JSON for GitHub Pages 封神榜."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "comments.sqlite"
CSV_USERS = ROOT / "out" / "封神榜.csv"
CSV_HOURS = ROOT / "out" / "时段统计.csv"
OUT = ROOT / "docs" / "data"
CHUNK = 40000
SAMPLE_MAX = 36


def ts_fmt(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")


def sample_of(text: str) -> str:
    s = (text or "").split(" | ")[0].replace("\n", " ").replace("\r", " ")
    s = "".join(ch for ch in s if ch >= " ")
    return s[:SAMPLE_MAX]


def _stage(directory: Path, text: str) -> Path:
    fd, name = tempfile.mkstemp(prefix=".part-", suffix=".tmp", dir=directory)
    os.close(fd)
    tmp = Path(name)
    try:
        tmp.write_text(text, encoding="utf-8")
    except Exception:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[str, Path]] = []
    try:
        _build(staged)
    finally:
        for _, tmp in staged:
            tmp.unlink(missing_ok=True)


def _build(staged: list[tuple[str, Path]]) -> None:
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=60)
    official_row = conn.execute("SELECT v FROM meta WHERE k='official_count'").fetchone()
    official_n = int(official_row[0]) if official_row else 0
    stored, tmin, tmax = conn.execute(
        "SELECT COUNT(*), MIN(ctime), MAX(ctime) FROM comments"
    ).fetchone()
    conn.close()

    files: list[str] = []
    chunk: list[list] = []
    total = 0
    idx = 0

    def flush() -> None:
        nonlocal chunk, idx
        if not chunk:
            return
        name = f"rank-{idx:02d}.json"
        staged.append(
            (name, _stage(OUT, json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))))
        )
        files.append(name)
        print(f"write {name} n={len(chunk)}", flush=True)
        idx += 1
        chunk = []

    with CSV_USERS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            chunk.append(
                [
                    int(row["排名"] or i + 1),
                    row["用户名"] or "",
                    int(row["UID"] or 0),
                    int(row["评论数"] or 0),
                    int(row["点赞合计"] or 0),
                    sample_of(row.get("评论样例") or ""),
                ]
            )
            total += 1
            if len(chunk) >= CHUNK:
                flush()
        flush()

    daily: dict[str, int] = defaultdict(int)
    with CSV_HOURS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if len(row) < 2:
                continue
            day = (row[0] or "")[:10]
            if len(day) == 10:
                daily[day] += int(row[1] or 0)
    daily_list = [{"d": k, "c": v} for k, v in sorted(daily.items())]

    cover = stored * 100 / official_n if official_n else 0
    overview = {
        "title": "《明日方舟》夏日嘉年华限时活动宣传PV",
        "bvid": "BV1fy4y1L7Rq",
        "aid": 804313673,
        "pubdate": "2021-07-25 18:55:10",
        "official": official_n,
        "stored": stored,
        "cover": round(cover, 2),
        "users": total,
        "window": f"{ts_fmt(tmin)} ~ {ts_fmt(tmax)}",
        "exported": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rank_shown": total,
        "draft": True,
        "note": "未完成稿。主评翻到约2021-07-29，发布后高峰未齐，未爬楼中楼。2026-02 高峰是新宣传片出来后的刷评。名次还会变。",
        "video": "https://www.bilibili.com/video/BV1fy4y1L7Rq/",
        "files": files,
        "cols": ["r", "n", "id", "c", "lk", "s"],
    }
    overview_text = json.dumps(overview, ensure_ascii=False, indent=2)
    daily_text = json.dumps(daily_list, ensure_ascii=False, separators=(",", ":"))
    staged.append(("daily.json", _stage(OUT, daily_text)))
    staged.append(("overview.json", _stage(OUT, overview_text)))
    keep: set[str] = set()
    for name, tmp in staged:
        os.replace(tmp, OUT / name)
        if name.startswith("rank"):
            keep.add(name)
    staged.clear()
    for old in OUT.glob("rank*.json"):
        if old.name not in keep:
            old.unlink()
    sizes = sum((OUT / name).stat().st_size for name in files)
    print(f"ranks={total} files={len(files)} bytes={sizes} daily={len(daily_list)}")


if __name__ == "__main__":
    main()
