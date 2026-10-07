#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export() 必须带上 WAL 里已提交的行。不启动爬虫，不读真实库。"""
from __future__ import annotations

import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run_until_done


def ok_run(args, cwd=None, env=None, **kwargs):
    return subprocess.CompletedProcess(args, 0)


def fail_run(args, cwd=None, env=None, **kwargs):
    return subprocess.CompletedProcess(args, 1)


class ExportBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {
            k: getattr(run_until_done, k) for k in ("DATA", "DB", "OUT", "CKPT", "LOG")
        }
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.data = root / "data"
        self.out = root / "out"
        self.data.mkdir()
        self.out.mkdir()
        self.db = self.data / "comments.sqlite"
        run_until_done.DATA = self.data
        run_until_done.DB = self.db
        run_until_done.OUT = self.out
        run_until_done.CKPT = self.data / "checkpoint.json"
        run_until_done.LOG = self.data / "runner.log"
        self.src = sqlite3.connect(self.db)
        self.src.execute("PRAGMA journal_mode=WAL")
        self.src.execute("PRAGMA wal_autocheckpoint=0")
        self.src.execute("CREATE TABLE comments(id INTEGER PRIMARY KEY, message TEXT)")
        self.src.commit()
        self.src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.src.executemany(
            "INSERT INTO comments(message) VALUES (?)",
            [("row-a",), ("row-b",)],
        )
        self.src.commit()

    def tearDown(self) -> None:
        self.src.close()
        for k, v in self._saved.items():
            setattr(run_until_done, k, v)

    def _messages(self, path: Path) -> list[str]:
        conn = sqlite3.connect(path)
        try:
            return [r[0] for r in conn.execute("SELECT message FROM comments ORDER BY id")]
        finally:
            conn.close()

    def test_backup_includes_committed_wal_rows(self) -> None:
        with patch("run_until_done.subprocess.run", ok_run):
            run_until_done.export()
        dest = self.out / "comments.sqlite"
        self.assertEqual(self._messages(dest), ["row-a", "row-b"])
        self.assertEqual(
            [r[0] for r in self.src.execute("SELECT message FROM comments ORDER BY id")],
            ["row-a", "row-b"],
        )
        self.assertEqual(list(self.out.glob(".comments-*")), [])

    def test_backup_failure_keeps_previous_file(self) -> None:
        good = self.out / "comments.sqlite"
        conn = sqlite3.connect(good)
        conn.execute("CREATE TABLE comments(id INTEGER PRIMARY KEY, message TEXT)")
        conn.execute("INSERT INTO comments(message) VALUES ('keep')")
        conn.commit()
        conn.close()
        blob = good.read_bytes()
        real_connect = sqlite3.connect

        class BoomSource:
            def __init__(self, inner: sqlite3.Connection) -> None:
                self._inner = inner

            def backup(self, *args, **kwargs):
                raise OSError("injected")

            def close(self) -> None:
                self._inner.close()

        def connect(path, *args, **kwargs):
            conn = real_connect(path, *args, **kwargs)
            if str(path) == str(self.db) or "mode=ro" in str(path):
                return BoomSource(conn)
            return conn

        raised = None
        with patch("run_until_done.subprocess.run", ok_run):
            with patch("run_until_done.sqlite3.connect", connect):
                try:
                    run_until_done.export()
                except OSError as exc:
                    raised = exc
        self.assertIsInstance(raised, OSError)
        self.assertEqual(good.read_bytes(), blob)
        self.assertEqual(self._messages(good), ["keep"])
        self.assertEqual(list(self.out.glob(".comments-*")), [])
        self.assertEqual(
            [r[0] for r in self.src.execute("SELECT message FROM comments ORDER BY id")],
            ["row-a", "row-b"],
        )

    def test_export_subprocess_failure_does_not_copy(self) -> None:
        good = self.out / "comments.sqlite"
        conn = sqlite3.connect(good)
        conn.execute("CREATE TABLE comments(id INTEGER PRIMARY KEY, message TEXT)")
        conn.execute("INSERT INTO comments(message) VALUES ('keep')")
        conn.commit()
        conn.close()
        blob = good.read_bytes()
        with patch("run_until_done.subprocess.run", fail_run):
            with self.assertRaises(RuntimeError):
                run_until_done.export()
        self.assertEqual(good.read_bytes(), blob)
        self.assertEqual(list(self.out.glob(".comments-*")), [])
        self.assertEqual(
            [r[0] for r in self.src.execute("SELECT message FROM comments ORDER BY id")],
            ["row-a", "row-b"],
        )


if __name__ == "__main__":
    unittest.main()
