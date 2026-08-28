#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export 封神榜 xlsx in the 异环 comment-user-stats format."""
from __future__ import annotations

import csv
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import xlsxwriter

BVID = "BV1fy4y1L7Rq"
TITLE = "《明日方舟》夏日嘉年华限时活动宣传PV"
AID = 804313673
PUBDATE = 1627215310
ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "comments.sqlite"
OUT = ROOT / "out"
XLSX = OUT / "明日方舟_多索雷斯假日_评论用户统计.xlsx"
CSV_USERS = OUT / "封神榜.csv"
CSV_COMMENTS = OUT / "评论明细.csv"
CSV_HOURS = OUT / "时段统计.csv"
EXCEL_ROWS = 1_048_000
CELL_LIMIT = 32000
EXCEL_JOIN = 400
ILLEGAL_XML = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")

USER_HEADERS = [
    "排名",
    "用户名",
    "UID",
    "等级",
    "性别",
    "评论数",
    "占比%",
    "点赞合计",
    "首次评论",
    "末次评论",
    "持续天数",
    "峰值小时条数",
    "峰值小时",
    "评论样例",
    "评论拼接",
]


def xml_cell(v: object, limit: int = 0) -> str:
    s = ILLEGAL_XML.sub("", "" if v is None else str(v))
    if limit and len(s) > limit:
        s = s[:limit]
    if s[:1] in ("=", "+", "-", "@"):
        s = "'" + s
    return s


def ts_fmt(ts: int | None) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")


def user_row(rank: int, u: dict, total: int, samples: dict, all_text: dict) -> list:
    peak_h, peak_n = ("", 0)
    if u["hours"]:
        peak_h, peak_n = max(u["hours"].items(), key=lambda kv: kv[1])
    days = 0
    if u["first"] and u["last"]:
        days = max(0, (u["last"] - u["first"]) // 86400)
    return [
        rank,
        u["uname"],
        u["mid"],
        u["level"],
        u["sex"],
        u["n"],
        round(u["n"] * 100 / total, 4),
        u["likes"],
        ts_fmt(u["first"]),
        ts_fmt(u["last"]),
        days,
        peak_n,
        peak_h,
        " | ".join(samples.get(u["mid"], [])),
        " | ".join(all_text.get(u["mid"], []))[:CELL_LIMIT],
    ]


def main() -> None:
    if not DB.exists():
        raise SystemExit("no db yet, run scrape_comments.py first")
    OUT.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=120)
    conn.row_factory = sqlite3.Row
    official = conn.execute("SELECT v FROM meta WHERE k='official_count'").fetchone()
    official_n = int(official["v"]) if official else 0
    stored = conn.execute("SELECT COUNT(*) n FROM comments").fetchone()["n"]
    user_n = conn.execute("SELECT COUNT(DISTINCT mid) n FROM comments").fetchone()["n"]
    tmin, tmax = conn.execute("SELECT MIN(ctime), MAX(ctime) FROM comments").fetchone()

    users: dict[int, dict] = {}
    hour_count: dict[str, int] = defaultdict(int)
    samples: dict[int, list[str]] = defaultdict(list)
    all_text: dict[int, list[str]] = defaultdict(list)

    with CSV_COMMENTS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["rpid", "时间", "UID", "用户名", "等级", "性别", "点赞", "类型", "root", "parent", "评论内容"]
        )
        cur = conn.execute(
            "SELECT rpid,parent,root,mid,uname,sex,level,ctime,message,like_count "
            "FROM comments ORDER BY ctime, rpid"
        )
        for row in cur:
            mid = int(row["mid"])
            uname = row["uname"] or ""
            msg = row["message"] or ""
            ctime = int(row["ctime"] or 0)
            like = int(row["like_count"] or 0)
            kind = "主评" if int(row["root"] or 0) == 0 else "回复"
            writer.writerow(
                [
                    row["rpid"],
                    ts_fmt(ctime),
                    mid,
                    uname,
                    row["level"],
                    row["sex"],
                    like,
                    kind,
                    row["root"],
                    row["parent"],
                    msg,
                ]
            )
            u = users.get(mid)
            if u is None:
                users[mid] = {
                    "mid": mid,
                    "uname": uname,
                    "level": row["level"],
                    "sex": row["sex"],
                    "n": 1,
                    "likes": like,
                    "first": ctime,
                    "last": ctime,
                    "hours": defaultdict(int),
                }
                u = users[mid]
            else:
                if uname:
                    u["uname"] = uname
                u["level"] = row["level"] or u["level"]
                u["sex"] = row["sex"] or u["sex"]
                if ctime and (not u["first"] or ctime < u["first"]):
                    u["first"] = ctime
                if ctime > u["last"]:
                    u["last"] = ctime
                u["n"] += 1
                u["likes"] += like
            hour = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:00") if ctime else ""
            if hour:
                u["hours"][hour] += 1
                hour_count[hour] += 1
            if len(samples[mid]) < 5 and msg:
                samples[mid].append(msg.replace("\n", " ")[:120])
            if msg and sum(len(x) for x in all_text[mid]) < CELL_LIMIT:
                all_text[mid].append(msg.replace("\n", " "))

    ranked = sorted(users.values(), key=lambda x: (-x["n"], x["first"], x["mid"]))
    total = stored or 1

    with CSV_USERS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(USER_HEADERS)
        for i, u in enumerate(ranked, 1):
            writer.writerow(user_row(i, u, total, samples, all_text))

    with CSV_HOURS.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["小时", "评论数"])
        for h in sorted(hour_count):
            writer.writerow([h, hour_count[h]])

    wb = xlsxwriter.Workbook(
        str(XLSX),
        {
            "strings_to_urls": False,
            "strings_to_formulas": False,
            "strings_to_numbers": False,
        },
    )
    header_fmt = wb.add_format(
        {"bold": True, "bg_color": "#1F4E79", "font_color": "white", "border": 1}
    )
    num_fmt = wb.add_format({"num_format": "0.0000"})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})

    top5 = ranked[:5]
    top5_sum = sum(u["n"] for u in top5)
    n1 = max(1, int(user_n * 0.01))
    top1p = sum(u["n"] for u in ranked[:n1])
    cover = stored * 100 / official_n if official_n else 0
    overview = [
        ("视频标题", TITLE),
        ("BV号", BVID),
        ("aid/oid", str(AID)),
        ("发布时间", ts_fmt(PUBDATE)),
        ("B站显示评论数", official_n),
        ("本次入库评论数", stored),
        ("覆盖率%", f"{cover:.2f}"),
        ("用户数", user_n),
        ("抓取时间窗", f"{ts_fmt(tmin)} ~ {ts_fmt(tmax)}"),
        ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("前1%用户贡献评论占比%", f"{top1p * 100 / total:.2f}"),
        ("前五名合计占比%", f"{top5_sum * 100 / total:.2f}"),
        ("前五名", "；".join(f"{u['uname']}({u['n']}条)" for u in top5)),
        (
            "格式说明",
            "对齐异环《评论用户统计》封神榜：按评论数排名，含UID、等级、样例与拼接文本。评论明细因超过Excel行上限，完整数据在CSV。",
        ),
        (
            "数据说明",
            "未完成稿：主评尚未翻完（当前最早约2021-07-29，视频发布2021-07-25，发布后高峰仍缺），未爬楼中楼。"
            "名次与条数之后还会变。仅统计公开评论接口；B站可能截断极旧楼层。",
        ),
    ]
    ws0 = wb.add_worksheet("概述")
    ws0.write_row(0, 0, ["字段", "值"], header_fmt)
    for i, (k, v) in enumerate(overview, 1):
        ws0.write(i, 0, k)
        ws0.write(i, 1, v)
    ws0.set_column(0, 0, 22)
    ws0.set_column(1, 1, 90)

    ws1 = wb.add_worksheet("封神榜")
    ws1.write_row(0, 0, USER_HEADERS, header_fmt)
    limit = min(len(ranked), EXCEL_ROWS - 1)
    for i, u in enumerate(ranked[:limit], 1):
        row = user_row(i, u, total, samples, all_text)
        row[1] = xml_cell(row[1])
        row[4] = xml_cell(row[4])
        row[13] = xml_cell(row[13], 2000)
        row[14] = xml_cell(row[14], EXCEL_JOIN)
        ws1.write_row(i, 0, row)
        ws1.write_number(i, 6, row[6], num_fmt)
    ws1.set_column(0, 0, 8)
    ws1.set_column(1, 1, 22)
    ws1.set_column(2, 2, 14)
    ws1.set_column(13, 14, 60, wrap)
    ws1.freeze_panes(1, 0)
    ws1.autofilter(0, 0, limit, 14)

    ws2 = wb.add_worksheet("时段统计")
    ws2.write_row(0, 0, ["小时", "评论数"], header_fmt)
    hours = sorted(hour_count)
    for i, h in enumerate(hours[: EXCEL_ROWS - 1], 1):
        ws2.write(i, 0, h)
        ws2.write(i, 1, hour_count[h])
    ws2.set_column(0, 0, 20)

    note = wb.add_worksheet("说明")
    note.write_row(0, 0, ["项", "路径"], header_fmt)
    note.write_row(1, 0, ["完整封神榜CSV", str(CSV_USERS)])
    note.write_row(2, 0, ["完整评论明细CSV", str(CSV_COMMENTS)])
    note.write_row(3, 0, ["SQLite原始库", str(DB)])
    note.write_row(4, 0, ["完成状态", "未完成，发布后头几天主评未齐，未爬楼中楼"])
    note.set_column(0, 0, 22)
    note.set_column(1, 1, 80)
    wb.close()

    print(f"xlsx={XLSX}")
    print(f"users={CSV_USERS}")
    print(f"comments={CSV_COMMENTS}")
    print(f"stored={stored} users={user_n} official={official_n}")


def build_xlsx_from_csv(dest: Path | None = None) -> Path:
    dest = dest or XLSX
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=60)
    official = conn.execute("SELECT v FROM meta WHERE k='official_count'").fetchone()
    official_n = int(official[0]) if official else 0
    stored, user_n, tmin, tmax = conn.execute(
        "SELECT COUNT(*), COUNT(DISTINCT mid), MIN(ctime), MAX(ctime) FROM comments"
    ).fetchone()
    conn.close()

    wb = xlsxwriter.Workbook(
        str(dest),
        {
            "strings_to_urls": False,
            "strings_to_formulas": False,
            "strings_to_numbers": False,
        },
    )
    header_fmt = wb.add_format(
        {"bold": True, "bg_color": "#1F4E79", "font_color": "white", "border": 1}
    )
    num_fmt = wb.add_format({"num_format": "0.0000"})
    wrap = wb.add_format({"text_wrap": True, "valign": "top"})

    hours: list[tuple[str, int]] = []
    with CSV_HOURS.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) >= 2:
                hours.append((row[0], int(row[1] or 0)))

    top5: list[tuple[str, str]] = []
    ws1 = wb.add_worksheet("封神榜")
    ws1.write_row(0, 0, USER_HEADERS, header_fmt)
    limit = 0
    with CSV_USERS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for i, row in enumerate(reader, 1):
            if i <= 5 and len(row) > 5:
                top5.append((row[1], row[5]))
            if i >= EXCEL_ROWS:
                break
            while len(row) < 15:
                row.append("")
            row[1] = xml_cell(row[1])
            row[4] = xml_cell(row[4])
            row[13] = xml_cell(row[13], 2000)
            row[14] = xml_cell(row[14], EXCEL_JOIN)
            ws1.write_row(i, 0, row)
            try:
                ws1.write_number(i, 6, float(row[6]), num_fmt)
            except Exception:
                pass
            limit = i
            if i % 50000 == 0:
                print(f"xlsx users {i}", flush=True)

    ws1.set_column(0, 0, 8)
    ws1.set_column(1, 1, 22)
    ws1.set_column(2, 2, 14)
    ws1.set_column(13, 14, 40, wrap)
    ws1.freeze_panes(1, 0)
    if limit:
        ws1.autofilter(0, 0, limit, 14)

    cover = stored * 100 / official_n if official_n else 0
    overview = [
        ("视频标题", TITLE),
        ("BV号", BVID),
        ("aid/oid", str(AID)),
        ("发布时间", ts_fmt(PUBDATE)),
        ("B站显示评论数", official_n),
        ("本次入库评论数", stored),
        ("覆盖率%", f"{cover:.2f}"),
        ("用户数", user_n),
        ("抓取时间窗", f"{ts_fmt(tmin)} ~ {ts_fmt(tmax)}"),
        ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("前五名", "；".join(f"{n}({c}条)" for n, c in top5)),
        ("格式说明", "Excel里评论拼接已截断。完整拼接和明细在CSV。"),
        (
            "数据说明",
            "未完成稿：主评尚未翻完（最早约2021-07-29），未爬楼中楼。名次之后还会变。",
        ),
    ]
    ws0 = wb.add_worksheet("概述")
    ws0.write_row(0, 0, ["字段", "值"], header_fmt)
    for i, (k, v) in enumerate(overview, 1):
        ws0.write(i, 0, k)
        ws0.write(i, 1, xml_cell(v))
    ws0.set_column(0, 0, 22)
    ws0.set_column(1, 1, 90)
    ws0.activate()

    ws2 = wb.add_worksheet("时段统计")
    ws2.write_row(0, 0, ["小时", "评论数"], header_fmt)
    for i, (h, n) in enumerate(hours[: EXCEL_ROWS - 1], 1):
        ws2.write(i, 0, h)
        ws2.write(i, 1, n)
    ws2.set_column(0, 0, 20)

    note = wb.add_worksheet("说明")
    note.write_row(0, 0, ["项", "路径"], header_fmt)
    note.write_row(1, 0, ["完整封神榜CSV", str(CSV_USERS)])
    note.write_row(2, 0, ["完整评论明细CSV", str(CSV_COMMENTS)])
    note.write_row(3, 0, ["SQLite原始库", str(DB)])
    note.write_row(4, 0, ["完成状态", "未完成，发布后头几天主评未齐，未爬楼中楼"])
    note.write_row(5, 0, ["Excel说明", "评论拼接在表里只留前400字，完整内容看封神榜.csv"])
    note.set_column(0, 0, 22)
    note.set_column(1, 1, 80)
    wb.close()
    print(f"xlsx={dest} size={dest.stat().st_size}", flush=True)
    return dest


LEAN_HEADERS = USER_HEADERS[:13]


def _overview_rows(stored: int, user_n: int, official_n: int, tmin: int, tmax: int, top5: list[tuple[str, str]]) -> list[tuple[str, object]]:
    cover = stored * 100 / official_n if official_n else 0
    return [
        ("视频标题", TITLE),
        ("BV号", BVID),
        ("aid/oid", str(AID)),
        ("发布时间", ts_fmt(PUBDATE)),
        ("B站显示评论数", official_n),
        ("本次入库评论数", stored),
        ("覆盖率%", f"{cover:.2f}"),
        ("用户数", user_n),
        ("抓取时间窗", f"{ts_fmt(tmin)} ~ {ts_fmt(tmax)}"),
        ("导出时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("前五名", "；".join(f"{n}({c}条)" for n, c in top5)),
        ("格式说明", "Excel不含评论拼接/样例，避免打不开。完整内容在封神榜.csv。"),
        ("数据说明", "未完成稿：主评尚未翻完（最早约2021-07-29），未爬楼中楼。名次之后还会变。"),
    ]


def build_xlsx_lean() -> Path:
    dest = OUT / "明日方舟_多索雷斯假日_封神榜.xlsx"
    dest_top = OUT / "明日方舟_多索雷斯假日_封神榜_前1万.xlsx"
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True, timeout=30)
    official = conn.execute("SELECT v FROM meta WHERE k='official_count'").fetchone()
    official_n = int(official[0]) if official else 0
    stored, tmin, tmax = conn.execute(
        "SELECT COUNT(*), MIN(ctime), MAX(ctime) FROM comments"
    ).fetchone()
    conn.close()

    def write_one(path: Path, max_rows: int) -> None:
        wb = xlsxwriter.Workbook(
            str(path),
            {
                "constant_memory": True,
                "strings_to_urls": False,
                "strings_to_formulas": False,
                "strings_to_numbers": False,
            },
        )
        header_fmt = wb.add_format(
            {"bold": True, "bg_color": "#1F4E79", "font_color": "white", "border": 1}
        )
        num_fmt = wb.add_format({"num_format": "0.0000"})
        top5: list[tuple[str, str]] = []
        n_users = 414217
        with CSV_USERS.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            for i, row in enumerate(reader, 1):
                if i <= 5 and len(row) > 5:
                    top5.append((row[1], row[5]))
                if i >= 5:
                    break

        ws0 = wb.add_worksheet("概述")
        ws0.write_row(0, 0, ["字段", "值"], header_fmt)
        for i, (k, v) in enumerate(
            _overview_rows(stored, n_users, official_n, tmin, tmax, top5),
            1,
        ):
            ws0.write(i, 0, k)
            ws0.write(i, 1, xml_cell(v))
        ws0.set_column(0, 0, 22)
        ws0.set_column(1, 1, 90)

        ws1 = wb.add_worksheet("封神榜")
        ws1.write_row(0, 0, LEAN_HEADERS, header_fmt)
        ws1.set_column(0, 0, 8)
        ws1.set_column(1, 1, 22)
        ws1.set_column(2, 2, 14)
        ws1.freeze_panes(1, 0)
        with CSV_USERS.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            next(reader, None)
            for i, row in enumerate(reader, 1):
                if i > max_rows:
                    break
                while len(row) < 13:
                    row.append("")
                lean = [xml_cell(x) for x in row[:13]]
                ws1.write_row(i, 0, lean)
                try:
                    ws1.write_number(i, 6, float(row[6]), num_fmt)
                except Exception:
                    pass
                if i % 50000 == 0:
                    print(f"{path.name} {i}", flush=True)

        ws2 = wb.add_worksheet("时段统计")
        ws2.write_row(0, 0, ["小时", "评论数"], header_fmt)
        ws2.set_column(0, 0, 20)
        with CSV_HOURS.open("r", encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            next(r, None)
            for i, row in enumerate(r, 1):
                if len(row) >= 2:
                    ws2.write(i, 0, row[0])
                    try:
                        ws2.write_number(i, 1, int(row[1]))
                    except Exception:
                        ws2.write(i, 1, row[1])

        note = wb.add_worksheet("说明")
        note.write_row(0, 0, ["项", "路径"], header_fmt)
        note.write_row(1, 0, ["完整封神榜CSV", str(CSV_USERS)])
        note.write_row(2, 0, ["本表不含", "评论样例、评论拼接（否则Excel打不开）"])
        note.write_row(3, 0, ["完成状态", "未完成，发布后头几天主评未齐，未爬楼中楼"])
        note.set_column(0, 0, 22)
        note.set_column(1, 1, 80)
        wb.close()
        print(f"xlsx={path} size={path.stat().st_size}", flush=True)

    write_one(dest_top, 10000)
    write_one(dest, EXCEL_ROWS)
    return dest


PART_HEADERS = [
    "排名",
    "用户名",
    "UID",
    "等级",
    "评论数",
    "点赞合计",
    "首次评论",
    "末次评论",
    "评论样例",
]
PART_SIZE = 50000
XLSX_DIR = ROOT / "docs" / "xlsx"


def build_xlsx_parts() -> Path:
    XLSX_DIR.mkdir(parents=True, exist_ok=True)
    for old in list(XLSX_DIR.glob("rank-*.xlsx")) + list(XLSX_DIR.glob("rank-*.csv")):
        old.unlink()
    header_opts = {
        "constant_memory": True,
        "strings_to_urls": False,
        "strings_to_formulas": False,
        "strings_to_numbers": False,
    }
    header_fmt_args = {"bold": True, "bg_color": "#1F4E79", "font_color": "white", "border": 1}

    files: list[dict] = []
    csv_files: list[dict] = []
    wb = None
    ws = None
    header_fmt = None
    uid_fmt = None
    date_fmt = None
    wrap_fmt = None
    int_fmt = None
    csv_buf: list[list] = []
    part = 0
    in_part = 0
    start_rank = 1
    n = 0

    def close_part() -> None:
        nonlocal wb, part, in_part, start_rank, csv_buf
        if wb is None:
            return
        ws.autofilter(0, 0, in_part, 8)
        wb.close()
        path = XLSX_DIR / f"rank-{part:02d}.xlsx"
        files.append(
            {
                "file": path.name,
                "from": start_rank,
                "to": start_rank + in_part - 1,
                "size": path.stat().st_size,
            }
        )
        csv_path = XLSX_DIR / f"rank-{part:02d}.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            w.writerow(PART_HEADERS)
            w.writerows(csv_buf)
        csv_files.append(
            {
                "file": csv_path.name,
                "from": start_rank,
                "to": start_rank + in_part - 1,
                "size": csv_path.stat().st_size,
            }
        )
        print(f"xlsx={path.name} csv={csv_path.name} rows={in_part}", flush=True)
        wb = None
        csv_buf = []

    def open_part() -> None:
        nonlocal wb, ws, header_fmt, uid_fmt, date_fmt, wrap_fmt, int_fmt
        nonlocal part, in_part, start_rank, csv_buf
        part += 1
        in_part = 0
        start_rank = n + 1
        csv_buf = []
        path = XLSX_DIR / f"rank-{part:02d}.xlsx"
        wb = xlsxwriter.Workbook(str(path), header_opts)
        header_fmt = wb.add_format({**header_fmt_args, "align": "center", "valign": "vcenter"})
        uid_fmt = wb.add_format({"align": "left", "num_format": "@"})
        date_fmt = wb.add_format({"align": "left", "num_format": "@"})
        wrap_fmt = wb.add_format({"text_wrap": True, "valign": "top"})
        int_fmt = wb.add_format({"num_format": "#,##0", "align": "right"})
        ws = wb.add_worksheet("封神榜")
        ws.write_row(0, 0, PART_HEADERS, header_fmt)
        ws.set_column(0, 0, 10)
        ws.set_column(1, 1, 24)
        ws.set_column(2, 2, 16)
        ws.set_column(3, 3, 8)
        ws.set_column(4, 5, 12)
        ws.set_column(6, 7, 22)
        ws.set_column(8, 8, 56)
        ws.set_row(0, 22)
        ws.freeze_panes(1, 0)

    with CSV_USERS.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            if wb is None:
                open_part()
            while len(row) < 14:
                row.append("")
            sample = xml_cell((row[13] or "").split(" | ")[0], 48)
            uid = str(row[2] or "").strip()
            first = (row[8] or "").strip()
            last = (row[9] or "").strip()
            r = in_part + 1
            try:
                ws.write_number(r, 0, int(row[0] or n + 1), int_fmt)
            except Exception:
                ws.write(r, 0, row[0])
            ws.write_string(r, 1, xml_cell(row[1]))
            ws.write_string(r, 2, uid, uid_fmt)
            try:
                ws.write_number(r, 3, int(row[3] or 0), int_fmt)
            except Exception:
                ws.write(r, 3, row[3])
            try:
                ws.write_number(r, 4, int(row[5] or 0), int_fmt)
            except Exception:
                ws.write(r, 4, row[5])
            try:
                ws.write_number(r, 5, int(row[7] or 0), int_fmt)
            except Exception:
                ws.write(r, 5, row[7])
            ws.write_string(r, 6, first, date_fmt)
            ws.write_string(r, 7, last, date_fmt)
            ws.write_string(r, 8, sample, wrap_fmt)
            # CSV：UID/日期当文本，避免科学计数和 ####
            csv_buf.append(
                [
                    row[0],
                    xml_cell(row[1]),
                    f'="{uid}"' if uid else "",
                    row[3],
                    row[5],
                    row[7],
                    f'="{first}"' if first else "",
                    f'="{last}"' if last else "",
                    sample,
                ]
            )
            in_part += 1
            n += 1
            if in_part >= PART_SIZE:
                close_part()
        close_part()

    mpath = XLSX_DIR / "monthly.xlsx"
    wb = xlsxwriter.Workbook(str(mpath), header_opts)
    header_fmt = wb.add_format({**header_fmt_args, "align": "center"})
    ws = wb.add_worksheet("月度")
    ws.write_row(0, 0, ["月份", "评论数"], header_fmt)
    month: dict[str, int] = {}
    with CSV_HOURS.open("r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        next(r, None)
        for row in r:
            if len(row) < 2:
                continue
            key = (row[0] or "")[:7]
            if len(key) == 7:
                month[key] = month.get(key, 0) + int(row[1] or 0)
    int_fmt = wb.add_format({"num_format": "#,##0"})
    for i, k in enumerate(sorted(month), 1):
        ws.write_string(i, 0, k)
        ws.write_number(i, 1, month[k], int_fmt)
    ws.set_column(0, 0, 12)
    ws.set_column(1, 1, 14)
    wb.close()
    csv_month = XLSX_DIR / "monthly.csv"
    with csv_month.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["月份", "评论数"])
        for k in sorted(month):
            w.writerow([k, month[k]])
    manifest = {
        "parts": csv_files,
        "monthly": "monthly.csv",
        "xlsx_parts": [p["file"] for p in files],
        "note": "国内下 CSV。UID 和日期已按文本导出，避免科学计数和显示成 ####。",
        "cdn": "https://cdn.jsdelivr.net/gh/hualeide/dossoles-fengshen@main/docs/xlsx/",
    }
    (XLSX_DIR / "files.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"parts={len(files)} users={n} monthly={mpath.stat().st_size}")
    return XLSX_DIR


if __name__ == "__main__":
    if "--parts" in sys.argv:
        build_xlsx_parts()
    elif "--lean" in sys.argv:
        build_xlsx_lean()
    elif "--from-csv" in sys.argv:
        out = XLSX
        if "--alt" in sys.argv:
            out = OUT / "明日方舟_多索雷斯假日_评论用户统计_可打开.xlsx"
        build_xlsx_from_csv(out)
    else:
        main()

