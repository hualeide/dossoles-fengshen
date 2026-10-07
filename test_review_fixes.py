#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""临时库调用 build_web.main / export_rank.main。不读真实 data、cookie、密钥。"""
from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import build_web
import export_rank

OLD = {
    "rank-00.json": b'[["keep-rank-0"]]',
    "rank-01.json": b'[["keep-rank-1"]]',
    "rank-07.json": b'[["keep-rank-7"]]',
    "overview.json": b'{"keep":"overview"}',
    "daily.json": b'[{"d":"keep"}]',
}

FORMULAS = ("=1+1", "@x", "+x", "-x")


def make_db(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta(k TEXT, v TEXT)")
    conn.execute("INSERT INTO meta VALUES ('official_count', '9')")
    conn.execute(
        "CREATE TABLE comments("
        "rpid INTEGER, parent INTEGER, root INTEGER, mid INTEGER, "
        "uname TEXT, sex TEXT, level INTEGER, ctime INTEGER, "
        "message TEXT, like_count INTEGER)"
    )
    for i, (uname, msg) in enumerate(rows, 1):
        conn.execute(
            "INSERT INTO comments VALUES (?,?,?,?,?,?,?,?,?,?)",
            (i, 0, 0, 1000 + i, uname, "x", 1, 1627215310 + i, msg, 0),
        )
    conn.commit()
    conn.close()


def write_users(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["排名", "用户名", "UID", "评论数", "点赞合计", "评论样例"])
        w.writerows(rows)


def write_hours(path: Path, rows: list[tuple]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["小时", "评论数"])
        w.writerows(rows)


class BuildWebPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            k: getattr(build_web, k) for k in ("DB", "CSV_USERS", "CSV_HOURS", "OUT", "CHUNK")
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "web"
        self.out.mkdir()
        for name, data in OLD.items():
            (self.out / name).write_bytes(data)
        build_web.OUT = self.out
        build_web.DB = self.root / "comments.sqlite"
        build_web.CSV_USERS = self.root / "users.csv"
        build_web.CSV_HOURS = self.root / "hours.csv"
        build_web.CHUNK = 40000

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            setattr(build_web, k, v)

    def assert_old_bytes(self) -> None:
        for name, data in OLD.items():
            path = self.out / name
            self.assertTrue(path.is_file(), name)
            self.assertEqual(path.read_bytes(), data, name)
        self.assertEqual(list(self.out.glob(".part-*")), [])

    def test_missing_db_keeps_old_bytes(self) -> None:
        write_users(build_web.CSV_USERS, [(1, "a", 1, 1, 0, "s")])
        write_hours(build_web.CSV_HOURS, [("2021-07-25 18:00", 1)])
        with self.assertRaises(sqlite3.OperationalError):
            build_web.main()
        self.assert_old_bytes()

    def test_missing_users_csv_keeps_old_bytes(self) -> None:
        make_db(build_web.DB, [("a", "s")])
        write_hours(build_web.CSV_HOURS, [("2021-07-25 18:00", 1)])
        with self.assertRaises(FileNotFoundError):
            build_web.main()
        self.assert_old_bytes()

    def test_missing_hours_csv_keeps_old_bytes(self) -> None:
        make_db(build_web.DB, [("a", "s")])
        write_users(build_web.CSV_USERS, [(1, "a", 1, 1, 0, "s")])
        with self.assertRaises(FileNotFoundError):
            build_web.main()
        self.assert_old_bytes()

    def _fail_write(self, needle: str) -> None:
        real = Path.write_text

        def wrapped(path, data, *args, **kwargs):
            if isinstance(data, str) and needle in data:
                raise OSError("injected stage write")
            return real(path, data, *args, **kwargs)

        Path.write_text = wrapped
        self.addCleanup(setattr, Path, "write_text", real)

    def _ready_one_row(self) -> None:
        make_db(build_web.DB, [("a", "s")])
        write_users(build_web.CSV_USERS, [(1, "a", 1, 1, 0, "s")])
        write_hours(build_web.CSV_HOURS, [("2021-07-25 18:00", 1)])

    def test_overview_stage_oserror_keeps_old_bytes(self) -> None:
        self._fail_write('"bvid"')
        self._ready_one_row()
        with self.assertRaises(OSError):
            build_web.main()
        self.assert_old_bytes()

    def test_daily_stage_oserror_keeps_old_bytes(self) -> None:
        self._fail_write('{"d":')
        self._ready_one_row()
        with self.assertRaises(OSError):
            build_web.main()
        self.assert_old_bytes()

    def test_bad_row_keeps_old_bytes(self) -> None:
        build_web.CHUNK = 1
        make_db(build_web.DB, [("a", "s"), ("b", "t")])
        write_users(
            build_web.CSV_USERS,
            [(1, "a", 1, 2, 0, "s"), (2, "b", 2, "nope", 0, "t")],
        )
        write_hours(build_web.CSV_HOURS, [("2021-07-25 18:00", 1)])
        with self.assertRaises(ValueError):
            build_web.main()
        self.assert_old_bytes()

    def test_multi_chunk_publishes_exact_json(self) -> None:
        build_web.CHUNK = 2
        make_db(build_web.DB, [("a", "s0"), ("b", "s1"), ("c", "s2")])
        write_users(
            build_web.CSV_USERS,
            [
                (1, "a", 11, 3, 4, "s0"),
                (2, "b", 12, 1, 0, "s1"),
                (3, "c", 13, 1, 0, "s2"),
            ],
        )
        write_hours(build_web.CSV_HOURS, [("2021-07-25 18:00", 2), ("2021-07-25 19:00", 1)])
        build_web.main()
        self.assertEqual(
            (self.out / "rank-00.json").read_text(encoding="utf-8"),
            '[[1,"a",11,3,4,"s0"],[2,"b",12,1,0,"s1"]]',
        )
        self.assertEqual(
            (self.out / "rank-01.json").read_text(encoding="utf-8"),
            '[[3,"c",13,1,0,"s2"]]',
        )
        self.assertFalse((self.out / "rank-07.json").exists())
        self.assertEqual(list(self.out.glob(".part-*")), [])
        overview = json.loads((self.out / "overview.json").read_text(encoding="utf-8"))
        self.assertEqual(overview["files"], ["rank-00.json", "rank-01.json"])
        self.assertEqual(overview["users"], 3)
        self.assertEqual(overview["stored"], 3)
        self.assertEqual(
            (self.out / "daily.json").read_text(encoding="utf-8"),
            '[{"d":"2021-07-25","c":3}]',
        )

    def test_zero_rows_clears_old_ranks(self) -> None:
        make_db(build_web.DB, [])
        write_users(build_web.CSV_USERS, [])
        write_hours(build_web.CSV_HOURS, [])
        build_web.main()
        self.assertEqual(list(self.out.glob("rank*.json")), [])
        self.assertEqual(list(self.out.glob(".part-*")), [])
        overview = json.loads((self.out / "overview.json").read_text(encoding="utf-8"))
        self.assertEqual(overview["users"], 0)
        self.assertEqual(overview["files"], [])
        self.assertEqual(overview["stored"], 0)
        self.assertEqual((self.out / "daily.json").read_text(encoding="utf-8"), "[]")


class ExportRankCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            k: getattr(export_rank, k)
            for k in ("DB", "OUT", "CSV_USERS", "CSV_COMMENTS", "CSV_HOURS", "XLSX")
        }
        self._web = {
            k: getattr(build_web, k) for k in ("DB", "CSV_USERS", "CSV_HOURS", "OUT", "CHUNK")
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        export_rank.OUT = root / "out"
        export_rank.DB = root / "comments.sqlite"
        export_rank.CSV_USERS = export_rank.OUT / "封神榜.csv"
        export_rank.CSV_COMMENTS = export_rank.OUT / "评论明细.csv"
        export_rank.CSV_HOURS = export_rank.OUT / "时段统计.csv"
        export_rank.XLSX = export_rank.OUT / "out.xlsx"

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            setattr(export_rank, k, v)
        for k, v in self._web.items():
            setattr(build_web, k, v)

    def test_formula_text_escaped_only_in_comment_csv(self) -> None:
        rows = [(text, text) for text in FORMULAS] + [("普通", "你好")]
        make_db(export_rank.DB, rows)
        export_rank.main()

        with export_rank.CSV_COMMENTS.open(encoding="utf-8-sig", newline="") as f:
            comments = list(csv.DictReader(f))
        self.assertEqual([r["用户名"] for r in comments], ["'=1+1", "'@x", "'+x", "'-x", "普通"])
        self.assertEqual(
            [r["评论内容"] for r in comments], ["'=1+1", "'@x", "'+x", "'-x", "你好"]
        )

        with export_rank.CSV_USERS.open(encoding="utf-8-sig", newline="") as f:
            users = list(csv.DictReader(f))
        self.assertEqual([r["用户名"] for r in users], [*FORMULAS, "普通"])
        self.assertEqual([r["评论样例"] for r in users], [*FORMULAS, "你好"])
        self.assertEqual([r["评论拼接"] for r in users], [*FORMULAS, "你好"])

        conn = sqlite3.connect(export_rank.DB)
        stored = [r[0] for r in conn.execute("SELECT message FROM comments ORDER BY rpid")]
        conn.close()
        self.assertEqual(stored, [*FORMULAS, "你好"])

        web = Path(self.tmp.name) / "web"
        build_web.DB = export_rank.DB
        build_web.CSV_USERS = export_rank.CSV_USERS
        build_web.CSV_HOURS = export_rank.CSV_HOURS
        build_web.OUT = web
        build_web.CHUNK = 40000
        build_web.main()
        rank = json.loads((web / "rank-00.json").read_text(encoding="utf-8"))
        self.assertEqual([row[1] for row in rank], [*FORMULAS, "普通"])
        self.assertEqual([row[5] for row in rank], [*FORMULAS, "你好"])


if __name__ == "__main__":
    unittest.main()
