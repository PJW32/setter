"""SQLite 저장소: 수집한 시군구·동·실거래·통근.

한 번 모은 지역은 다시 모으지 않는다. 연결은 작업마다 새로 열고(스레드 안전), 쓰기는 잠금으로 묶는다.
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from config import ROOT

DB_PATH = ROOT / "data" / "store.sqlite"
_write_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sgg (
  code TEXT PRIMARY KEY, sido TEXT, name TEXT, status TEXT,
  dong_count INTEGER, deal_count INTEGER, collected_at TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS dong (code TEXT PRIMARY KEY, sgg_code TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS dong_sgg ON dong(sgg_code);
CREATE TABLE IF NOT EXISTS deal (
  dong_code TEXT, sgg_code TEXT, house_type TEXT, area_m2 REAL, area_kind TEXT,
  deposit REAL, monthly_rent REAL, deal_ym TEXT, contract_kind TEXT
);
CREATE INDEX IF NOT EXISTS deal_dong ON deal(dong_code);
CREATE TABLE IF NOT EXISTS commute (dong_code TEXT, dest_key TEXT, data TEXT, PRIMARY KEY (dong_code, dest_key));
"""


@contextmanager
def connect(path: Path | None = None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init(path: Path | None = None) -> None:
    (path or DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _write_lock, connect(path) as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript(SCHEMA)


# ------------------------------------------------------------------ 시군구
def sgg_status(code: str) -> dict | None:
    with connect() as c:
        row = c.execute("SELECT * FROM sgg WHERE code=?", (code,)).fetchone()
    return dict(row) if row else None


def list_sggs() -> list[dict]:
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sgg ORDER BY code")]


def save_sgg(code: str, sido: str, name: str, dongs: list[dict], deals: list[dict]) -> None:
    with _write_lock, connect() as c:
        c.execute("DELETE FROM dong WHERE sgg_code=?", (code,))
        c.execute("DELETE FROM deal WHERE sgg_code=?", (code,))
        c.executemany("INSERT INTO dong VALUES (?,?,?)",
                      [(d["dong_code"], code, json.dumps(d, ensure_ascii=False)) for d in dongs])
        c.executemany(
            "INSERT INTO deal VALUES (?,?,?,?,?,?,?,?,?)",
            [(r["dong_code"], code, r["house_type"], r["area_m2"], r["area_kind"], r["deposit"],
              r["monthly_rent"], r["deal_ym"], r["contract_kind"]) for r in deals if r["dong_code"]],
        )
        c.execute("INSERT OR REPLACE INTO sgg VALUES (?,?,?,?,?,?,?,?)",
                  (code, sido, name, "done", len(dongs), len(deals), datetime.now().isoformat(timespec="seconds"), None))


def mark_sgg_error(code: str, sido: str, name: str, error: str) -> None:
    with _write_lock, connect() as c:
        c.execute("INSERT OR REPLACE INTO sgg VALUES (?,?,?,?,?,?,?,?)",
                  (code, sido, name, "error", 0, 0, datetime.now().isoformat(timespec="seconds"), error[:500]))


# ------------------------------------------------------------------ 동·실거래
def dongs_in(sgg_codes: list[str]) -> list[dict]:
    if not sgg_codes:
        return []
    q = f"SELECT data FROM dong WHERE sgg_code IN ({','.join('?' * len(sgg_codes))})"
    with connect() as c:
        return [json.loads(r["data"]) for r in c.execute(q, sgg_codes)]


def deals_for(dong_codes: list[str]) -> list[sqlite3.Row]:
    if not dong_codes:
        return []
    out = []
    with connect() as c:
        for i in range(0, len(dong_codes), 500):
            chunk = dong_codes[i:i + 500]
            out += c.execute(f"SELECT * FROM deal WHERE dong_code IN ({','.join('?' * len(chunk))})", chunk).fetchall()
    return out


# ------------------------------------------------------------------ 통근
def commutes(dest_key: str, dong_codes: list[str]) -> dict[str, dict]:
    if not dong_codes:
        return {}
    out = {}
    with connect() as c:
        for i in range(0, len(dong_codes), 500):
            chunk = dong_codes[i:i + 500]
            q = f"SELECT dong_code, data FROM commute WHERE dest_key=? AND dong_code IN ({','.join('?' * len(chunk))})"
            for r in c.execute(q, [dest_key, *chunk]):
                out[r["dong_code"]] = json.loads(r["data"])
    return out


def save_commutes(dest_key: str, rows: dict[str, dict]) -> None:
    with _write_lock, connect() as c:
        c.executemany("INSERT OR REPLACE INTO commute VALUES (?,?,?)",
                      [(code, dest_key, json.dumps(v, ensure_ascii=False)) for code, v in rows.items()])


def stats() -> dict:
    with connect() as c:
        return {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("sgg", "dong", "deal", "commute")}
