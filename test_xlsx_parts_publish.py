#!/usr/bin/env python3
"""build_xlsx_parts 发布前失败不得破坏旧结果。只写临时目录。"""
from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import xlsxwriter

import export_rank


def users_csv(path: Path, rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["排名", "用户名", "UID"])
        w.writerows(rows)


def one_user(rank: int, name: str = "甲", uid: str = "10001") -> list:
    return [
        rank, name, uid, 6, "x", 3, 1.0, 0,
        "2021-07-25 16:00:00", "2021-07-26 16:00:00",
        1, 1, "16", "样例",
    ]


def hours_csv(path: Path, rows: list[list]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["小时", "评论数"])
        w.writerows(rows)


class XlsxPartsPublishTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            k: getattr(export_rank, k) for k in ("XLSX_DIR", "CSV_USERS", "CSV_HOURS", "PART_SIZE")
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "xlsx"
        self.out.mkdir()
        self.users = self.root / "users.csv"
        self.hours = self.root / "hours.csv"
        export_rank.XLSX_DIR = self.out
        export_rank.CSV_USERS = self.users
        export_rank.CSV_HOURS = self.hours
        self.old = {
            "rank-01.xlsx": b"OLD-RANK-01",
            "monthly.xlsx": b"OLD-MONTH-X",
            "monthly.csv": b"OLD-MONTH-C",
            "files.json": b'{"old":1}',
            "keep.txt": b"keep-me",
        }
        for name, data in self.old.items():
            (self.out / name).write_bytes(data)

    def tearDown(self) -> None:
        for k, v in self._saved.items():
            setattr(export_rank, k, v)

    def assert_old_intact(self) -> None:
        for name, data in self.old.items():
            self.assertEqual((self.out / name).read_bytes(), data, name)
        self.assertEqual(list(self.out.glob(".xlsx-*")), [])

    def test_missing_users_keeps_old(self) -> None:
        hours_csv(self.hours, [["2021-07-25 16:00", 2]])
        with self.assertRaises(FileNotFoundError):
            export_rank.build_xlsx_parts()
        self.assert_old_intact()

    def test_missing_hours_keeps_old(self) -> None:
        users_csv(self.users, [one_user(1)])
        with self.assertRaises(FileNotFoundError):
            export_rank.build_xlsx_parts()
        self.assert_old_intact()

    def test_bad_month_count_keeps_old(self) -> None:
        users_csv(self.users, [one_user(1)])
        hours_csv(self.hours, [["2021-07-25 16:00", "bad"]])
        with self.assertRaises(ValueError):
            export_rank.build_xlsx_parts()
        self.assert_old_intact()

    def test_stage_write_and_close_failures_keep_old(self) -> None:
        users_csv(self.users, [one_user(1, name="=1+1", uid="10001")])
        hours_csv(self.hours, [["2021-07-25 16:00", 2]])
        real_write = Path.write_text

        def fail_manifest(self_path, *args, **kwargs):
            if self_path.name == "files.json":
                raise OSError("manifest")
            return real_write(self_path, *args, **kwargs)

        with patch.object(Path, "write_text", fail_manifest):
            with self.assertRaises(OSError):
                export_rank.build_xlsx_parts()
        self.assert_old_intact()

        real_close = xlsxwriter.Workbook.close

        def fail_close(self_wb):
            real_close(self_wb)
            raise OSError("close")

        with patch.object(xlsxwriter.Workbook, "close", fail_close):
            with self.assertRaises(OSError):
                export_rank.build_xlsx_parts()
        self.assert_old_intact()

    def test_success_replaces_then_drops_extra(self) -> None:
        (self.out / "rank-04.xlsx").write_bytes(b"OLD-EXTRA")
        (self.out / "rank-04.csv").write_bytes(b"OLD-EXTRA-CSV")
        export_rank.PART_SIZE = 2
        users_csv(self.users, [one_user(i, name="=甲" if i == 1 else "乙", uid=str(10000 + i)) for i in range(1, 6)])
        hours_csv(self.hours, [["2021-07-25 16:00", 2], ["2021-08-01 01:00", 1]])
        out = export_rank.build_xlsx_parts()
        self.assertEqual(out, self.out)
        self.assertEqual(list(self.out.glob(".xlsx-*")), [])
        self.assertEqual((self.out / "keep.txt").read_bytes(), b"keep-me")
        self.assertFalse((self.out / "rank-04.xlsx").exists())
        self.assertFalse((self.out / "rank-04.csv").exists())
        manifest = json.loads((self.out / "files.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["monthly"], "monthly.csv")
        self.assertEqual(manifest["cdn"], "https://cdn.jsdelivr.net/gh/hualeide/dossoles-fengshen@main/docs/xlsx/")
        self.assertEqual(manifest["xlsx_parts"], ["rank-01.xlsx", "rank-02.xlsx", "rank-03.xlsx"])
        self.assertEqual([p["file"] for p in manifest["parts"]], ["rank-01.csv", "rank-02.csv", "rank-03.csv"])
        self.assertEqual([(p["from"], p["to"]) for p in manifest["parts"]], [(1, 2), (3, 4), (5, 5)])
        for item in manifest["parts"]:
            path = self.out / item["file"]
            self.assertEqual(item["size"], path.stat().st_size)
            with path.open(encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
            self.assertEqual(len(rows) - 1, item["to"] - item["from"] + 1)
        with (self.out / "rank-01.csv").open(encoding="utf-8-sig", newline="") as f:
            first = list(csv.reader(f))[1]
        self.assertEqual(first[1], "'=甲")
        self.assertEqual(first[2], '="10001"')
        for name in manifest["xlsx_parts"]:
            self.assertTrue(zipfile.is_zipfile(self.out / name))
        with (self.out / "monthly.csv").open(encoding="utf-8-sig", newline="") as f:
            months = list(csv.reader(f))
        self.assertEqual(months, [["月份", "评论数"], ["2021-07", "2"], ["2021-08", "1"]])
        self.assertTrue(zipfile.is_zipfile(self.out / "monthly.xlsx"))

    def test_empty_board_clears_rank_keeps_monthly(self) -> None:
        (self.out / "rank-02.csv").write_bytes(b"OLD-RANK-02")
        users_csv(self.users, [])
        hours_csv(self.hours, [["2021-07-25 16:00", 4]])
        export_rank.build_xlsx_parts()
        self.assertEqual(list(self.out.glob("rank-*")), [])
        self.assertEqual((self.out / "keep.txt").read_bytes(), b"keep-me")
        manifest = json.loads((self.out / "files.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["parts"], [])
        self.assertEqual(manifest["xlsx_parts"], [])
        self.assertEqual(manifest["monthly"], "monthly.csv")
        with (self.out / "monthly.csv").open(encoding="utf-8-sig", newline="") as f:
            self.assertEqual(list(csv.reader(f)), [["月份", "评论数"], ["2021-07", "4"]])
        self.assertTrue(zipfile.is_zipfile(self.out / "monthly.xlsx"))
        self.assertEqual(list(self.out.glob(".xlsx-*")), [])


if __name__ == "__main__":
    unittest.main()
