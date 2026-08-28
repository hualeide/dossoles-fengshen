#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crawl all Bilibili comments + replies for BV1fy4y1L7Rq. Resume-safe."""
from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
import uuid
from datetime import datetime
from multiprocessing import Process
from pathlib import Path
from urllib.parse import urlencode

import requests

OID = 804313673
BVID = "BV1fy4y1L7Rq"
TYPE = 1
ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DB = DATA / "comments.sqlite"
CKPT = DATA / "checkpoint.json"
LOG = DATA / "scrape.log"
COOLDOWN = DATA / "cooldown.json"
MAX_PAGES = int(os.environ.get("MAX_PAGES") or 0)
SHARDS = max(1, int(os.environ.get("SHARDS") or 1))

NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
MAIN_URL = "https://api.bilibili.com/x/v2/reply/main"
REPLY_URL = "https://api.bilibili.com/x/v2/reply/reply"
COUNT_URL = "https://api.bilibili.com/x/v2/reply/count"
MIXIN = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
    61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
    36, 20, 34, 44, 52,
]


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_ckpt() -> dict:
    if CKPT.exists():
        return json.loads(CKPT.read_text(encoding="utf-8"))
    return {
        "next": 0,
        "offset": "",
        "main_done": False,
        "main_done": False,
        "reply_cursor": 0,
        "replies_done": False,
        "replies_done": False,
        "pages": 0,
        "inserted": 0,
        "done": False,
    }


def save_ckpt(ckpt: dict) -> None:
    CKPT.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")


def load_login_cookies() -> dict[str, str]:
    want = ("SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5")
    out: dict[str, str] = {}
    env_path = DATA / "bili_cookie.env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            if k in want and v:
                out[k] = v
    sess = os.environ.get("BILI_SESSDATA") or ""
    if sess:
        out["SESSDATA"] = sess
    return out


def wait_cd() -> None:
    try:
        until = float(json.loads(COOLDOWN.read_text(encoding="utf-8")).get("until") or 0)
    except Exception:
        return
    wait = until - time.time()
    if wait > 0:
        time.sleep(wait)


def bump_cd(seconds: float) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    until = time.time() + seconds
    try:
        old = float(json.loads(COOLDOWN.read_text(encoding="utf-8")).get("until") or 0)
        until = max(until, old)
    except Exception:
        pass
    COOLDOWN.write_text(json.dumps({"until": until}), encoding="utf-8")


def connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB, timeout=120)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS comments (
            rpid INTEGER PRIMARY KEY,
            parent INTEGER,
            root INTEGER,
            mid INTEGER,
            uname TEXT,
            sex TEXT,
            level INTEGER,
            ctime INTEGER,
            message TEXT,
            like_count INTEGER,
            rcount INTEGER
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_mid ON comments(mid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ctime ON comments(ctime)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_root ON comments(root)")
    conn.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
    return conn


class Client:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.img_key = ""
        self.sub_key = ""
        self.key_ts = 0.0
        # 不要带 buvid：这个超大楼带 cookie 会直接 is_end
        self.login_cookies = load_login_cookies()
        self._headers()
        self.apply_login()
        self.pace = 0.85

    def _headers(self) -> None:
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                ),
                "Referer": f"https://www.bilibili.com/video/{BVID}",
                "Origin": "https://www.bilibili.com",
            }
        )

    def apply_login(self) -> None:
        for k, v in self.login_cookies.items():
            self.session.cookies.set(k, v, domain=".bilibili.com")
        if self.login_cookies.get("SESSDATA"):
            log("using SESSDATA login cookie")

    def recreate_session(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass
        self.session = requests.Session()
        self._headers()
        self.apply_login()
        self.key_ts = 0.0
        self.img_key = ""
        self.sub_key = ""

    def refresh_wbi(self) -> None:
        r = self.session.get(NAV_URL, timeout=20)
        r.raise_for_status()
        wbi = ((r.json().get("data") or {}).get("wbi_img") or {})
        img = str(wbi.get("img_url") or "")
        sub = str(wbi.get("sub_url") or "")
        self.img_key = img.rsplit("/", 1)[-1].split(".")[0]
        self.sub_key = sub.rsplit("/", 1)[-1].split(".")[0]
        self.key_ts = time.time()
        if not self.img_key or not self.sub_key:
            raise RuntimeError("wbi keys empty")

    def sign(self, params: dict) -> dict:
        if time.time() - self.key_ts > 1800 or not self.img_key:
            self.refresh_wbi()
        mixin = "".join((self.img_key + self.sub_key)[i] for i in MIXIN)[:32]
        signed = dict(params)
        signed["wts"] = int(time.time())
        clean = {
            k: "".join(ch for ch in str(v) if ch not in "!'()*")
            for k, v in signed.items()
        }
        query = urlencode(sorted(clean.items()))
        signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
        return signed

    def rotate_buvid(self) -> None:
        self.session.cookies.clear()
        self.apply_login()

    def get(self, url: str, params: dict, signed: bool = False) -> dict:
        delay = 8.0
        attempt = 0
        use_sign = signed
        while True:
            attempt += 1
            try:
                wait_cd()
                q = self.sign(params) if use_sign else params
                r = self.session.get(url, params=q, timeout=25)
                if r.status_code in (412, 429) or r.status_code >= 500:
                    raise RuntimeError(f"http {r.status_code}")
                data = r.json()
                code = data.get("code")
                if code in (-352, -412, -401, -509, 86090):
                    self.key_ts = 0
                    # 这栋超大楼 WBI 会空页截断；-352 保持未签名，换会话
                    if code == -352:
                        use_sign = False
                        self.recreate_session()
                    else:
                        use_sign = True
                    raise RuntimeError(f"api code {code} {data.get('message')}")
                if code != 0:
                    raise RuntimeError(f"api code {code} {data.get('message')}")
                time.sleep(self.pace + random.uniform(0, 0.15))
                self.pace = max(0.4, self.pace * 0.98)
                return data
            except Exception as e:
                self.pace = min(3.0, self.pace * 1.2)
                err = str(e)
                if "412" in err or "429" in err:
                    self.rotate_buvid()
                    sleep_s = min(240.0, 70 + attempt * 10 + random.uniform(0, 15))
                    bump_cd(sleep_s)
                elif "-352" in err:
                    # 10–15 分钟一戳会把风控钉死，改成 45–90 分钟
                    sleep_s = min(5400.0, 2700 + attempt * 120 + random.uniform(0, 180))
                    bump_cd(sleep_s)
                    self.pace = max(self.pace, 1.6)
                else:
                    sleep_s = min(180.0, delay + random.uniform(0, 2))
                log(f"retry {attempt} {e}; sleep {sleep_s:.1f}s pace={self.pace:.2f}")
                time.sleep(sleep_s)
                delay = min(delay * 1.4, 180)


def extract(item: dict) -> dict:
    member = item.get("member") or {}
    content = item.get("content") or {}
    level_info = member.get("level_info") or {}
    return {
        "rpid": int(item["rpid"]),
        "parent": int(item.get("parent") or 0),
        "root": int(item.get("root") or 0),
        "mid": int(member.get("mid") or item.get("mid") or 0),
        "uname": member.get("uname") or "",
        "sex": member.get("sex") or "",
        "level": int(level_info.get("current_level") or 0),
        "ctime": int(item.get("ctime") or 0),
        "message": content.get("message") or "",
        "like_count": int(item.get("like") or 0),
        "rcount": int(item.get("rcount") or 0),
    }


def walk_tree(item: dict) -> list[dict]:
    rows = [extract(item)]
    for child in item.get("replies") or []:
        rows.extend(walk_tree(child))
    return rows


def insert_rows(conn: sqlite3.Connection, rows: list[dict]) -> int:
    if not rows:
        return 0
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO comments
        (rpid, parent, root, mid, uname, sex, level, ctime, message, like_count, rcount)
        VALUES (:rpid, :parent, :root, :mid, :uname, :sex, :level, :ctime, :message, :like_count, :rcount)
        """,
        rows,
    )
    conn.commit()
    return conn.total_changes - before


def official_count(client: Client) -> int:
    data = client.get(COUNT_URL, {"type": TYPE, "oid": OID}, signed=False)
    return int((data.get("data") or {}).get("count") or 0)


def fmt_ts(ts: int | None) -> str:
    if not ts:
        return "-"
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def crawl_range(start_next: int, stop_next: int, ckpt_path: Path, tag: str) -> None:
    ckpt = {"next": start_next, "pages": 0, "inserted": 0, "done": False}
    if ckpt_path.exists():
        ckpt.update(json.loads(ckpt_path.read_text(encoding="utf-8")))
    if ckpt.get("done"):
        log(f"{tag} already done")
        return
    nxt = int(ckpt.get("next") or start_next)
    if start_next and nxt > start_next:
        nxt = start_next
    pages = int(ckpt.get("pages") or 0)
    conn = connect()
    client = Client()
    time.sleep(random.uniform(0, 1.2))
    empty_streak = 0
    while True:
        prev = nxt
        data = client.get(
            MAIN_URL,
            {"oid": OID, "type": TYPE, "mode": 2, "ps": 20, "next": nxt, "plat": 1},
        )
        payload = data.get("data") or {}
        cursor = payload.get("cursor") or {}
        replies = payload.get("replies") or []
        rows: list[dict] = []
        for item in replies:
            rows.extend(walk_tree(item))
        n = insert_rows(conn, rows)
        pages += 1
        nxt = int(cursor.get("next") or 0)
        ckpt["pages"] = pages
        ckpt["inserted"] = int(ckpt.get("inserted") or 0) + n
        ckpt["next"] = nxt
        ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
        stored = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
        if pages % 20 == 0 or cursor.get("is_end") or not replies:
            log(
                f"{tag} page={pages} next={prev}->{nxt} +{n}/{len(rows)} "
                f"stored={stored} is_end={cursor.get('is_end')}"
            )
        if not replies:
            empty_streak += 1
            time.sleep(2 + empty_streak)
        else:
            empty_streak = 0
        reached_floor = stop_next > 0 and nxt <= stop_next
        reached_oldest = cursor.get("is_end") and nxt == 0 and prev <= 20
        if reached_floor or reached_oldest:
            ckpt["done"] = True
            ckpt_path.write_text(json.dumps(ckpt, ensure_ascii=False, indent=2), encoding="utf-8")
            log(f"{tag} done next={nxt} stored={stored}")
            conn.close()
            return
        if nxt == prev and not cursor.get("is_end"):
            nxt = max(stop_next, nxt - 20)
            ckpt["next"] = nxt


def crawl_main(client: Client, conn: sqlite3.Connection, ckpt: dict) -> None:
    # 兼容单进程：整段 0
    crawl_range(int(ckpt.get("next") or 0), 0, CKPT, "main")
    ckpt.update(json.loads(CKPT.read_text(encoding="utf-8")))


def crawl_subreplies(client: Client, conn: sqlite3.Connection, ckpt: dict) -> None:
    roots = conn.execute(
        """
        SELECT rpid, rcount FROM comments
        WHERE root = 0 AND rcount > 0
        ORDER BY rpid
        """
    ).fetchall()
    start = int(ckpt.get("reply_cursor") or 0)
    log(f"subreply roots with rcount>0: {len(roots)}, resume={start}")
    for i, (rpid, rcount) in enumerate(roots):
        if i < start:
            continue
        have = conn.execute(
            "SELECT COUNT(*) FROM comments WHERE root = ? OR parent = ?",
            (rpid, rpid),
        ).fetchone()[0]
        if have - 1 >= rcount:
            ckpt["reply_cursor"] = i + 1
            if (i + 1) % 200 == 0:
                save_ckpt(ckpt)
            continue
        pn = 1
        while True:
            data = client.get(
                REPLY_URL,
                {"oid": OID, "type": TYPE, "root": rpid, "ps": 20, "pn": pn},
            )
            payload = data.get("data") or {}
            replies = payload.get("replies") or []
            rows: list[dict] = []
            for item in replies:
                rows.extend(walk_tree(item))
            insert_rows(conn, rows)
            page = payload.get("page") or {}
            count = int(page.get("count") or 0)
            size = int(page.get("size") or 20) or 20
            if not replies or pn * size >= count:
                break
            pn += 1
        ckpt["reply_cursor"] = i + 1
        if (i + 1) % 20 == 0:
            save_ckpt(ckpt)
            stored = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
            log(f"subreply {i + 1}/{len(roots)} stored={stored}")
    ckpt["replies_done"] = True
    ckpt["replies_done"] = True
    save_ckpt(ckpt)
    log("subreply pass done")


def run_shard(start_next: int, stop_next: int, shard_id: int) -> None:
    crawl_range(start_next, stop_next, DATA / f"ckpt_shard{shard_id}.json", f"shard{shard_id}")


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    conn = connect()
    ckpt = load_ckpt()
    client = Client()
    total = official_count(client)
    conn.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", ("official_count", str(total)))
    conn.commit()
    conn.close()
    resume = int(ckpt.get("next") or 6770200)
    if resume <= 0:
        resume = 6770200
    log(f"official count={total} shards={SHARDS} resume={resume}")
    if MAX_PAGES or SHARDS <= 1:
        crawl_range(resume, 0, CKPT, "main")
    else:
        cuts = [resume]
        for i in range(1, SHARDS):
            cuts.append(resume * (SHARDS - i) // SHARDS)
        cuts.append(0)
        procs: list[Process] = []
        for i in range(SHARDS):
            start, stop = cuts[i], cuts[i + 1]
            p = Process(target=run_shard, args=(start, stop, i))
            p.start()
            procs.append(p)
            log(f"shard{i} {start} -> {stop}")
        for p in procs:
            p.join()
        if not all(p.exitcode == 0 for p in procs):
            raise SystemExit("shard failed")
    ckpt = load_ckpt()
    ckpt["main_done"] = True
    ckpt["done"] = True
    ckpt["replies_done"] = True
    save_ckpt(ckpt)
    log("skip subreplies as requested")
    conn = connect()
    stored = conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    users = conn.execute("SELECT COUNT(DISTINCT mid) FROM comments").fetchone()[0]
    roots = conn.execute("SELECT COUNT(*) FROM comments WHERE root=0").fetchone()[0]
    log(f"DONE stored={stored} roots={roots} replies={stored - roots} users={users} official={total}")
    conn.close()


if __name__ == "__main__":
    from multiprocessing import freeze_support

    freeze_support()
    main()
