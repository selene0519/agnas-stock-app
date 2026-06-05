"""
SQLite 기반 사용자별 보유종목/관심종목 영구 저장소.
서버 재시작 후에도 data/mone_users.db 파일이 남아있으면 데이터가 유지된다.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH: Path | None = None


def _db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        here = Path(__file__).resolve()
        for parent in here.parents:
            if (parent / "data").exists():
                _DB_PATH = parent / "data" / "mone_users.db"
                break
        else:
            _DB_PATH = here.parent / "mone_users.db"
    return _DB_PATH


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS user_holdings (
        user_id     TEXT NOT NULL,
        market      TEXT NOT NULL CHECK(market IN ('kr','us')),
        symbol      TEXT NOT NULL,
        name        TEXT NOT NULL DEFAULT '',
        quantity    REAL NOT NULL DEFAULT 0,
        avg_price   REAL NOT NULL DEFAULT 0,
        stop_price  REAL,
        target_price REAL,
        updated_at  INTEGER NOT NULL,
        PRIMARY KEY (user_id, market, symbol)
    );
    CREATE TABLE IF NOT EXISTS user_watchlist (
        user_id    TEXT NOT NULL,
        market     TEXT NOT NULL CHECK(market IN ('kr','us')),
        symbol     TEXT NOT NULL,
        name       TEXT NOT NULL DEFAULT '',
        memo       TEXT DEFAULT '',
        updated_at INTEGER NOT NULL,
        PRIMARY KEY (user_id, market, symbol)
    );
    CREATE INDEX IF NOT EXISTS idx_holdings_user ON user_holdings(user_id);
    CREATE INDEX IF NOT EXISTS idx_watchlist_user ON user_watchlist(user_id);
    """)
    conn.commit()


# 단일 글로벌 연결 + 초기화
_global_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _global_conn
    if _global_conn is None:
        _global_conn = _conn()
        _init_schema(_global_conn)
    return _global_conn


def sanitize_uid(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))[:64]


# ── Holdings CRUD ─────────────────────────────────────────────────────

def get_holdings(user_id: str, market: str = "all") -> list[dict]:
    uid = sanitize_uid(user_id)
    if not uid:
        return []
    conn = get_conn()
    if market == "all":
        rows = conn.execute(
            "SELECT * FROM user_holdings WHERE user_id=? ORDER BY market, symbol",
            (uid,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_holdings WHERE user_id=? AND market=? ORDER BY symbol",
            (uid, market)
        ).fetchall()
    return [_holding_to_dict(r) for r in rows]


def save_holdings(user_id: str, items: list[dict]) -> int:
    uid = sanitize_uid(user_id)
    if not uid:
        return 0
    conn = get_conn()
    now = int(time.time())
    markets_in_items: set[str] = set()
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        markets_in_items.add(mk)

    # 기존 데이터 삭제 후 재삽입 (market 단위)
    for mk in markets_in_items:
        conn.execute("DELETE FROM user_holdings WHERE user_id=? AND market=?", (uid, mk))

    saved = 0
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        sym = str(item.get("symbol", "")).strip()
        if not sym:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO user_holdings
            (user_id, market, symbol, name, quantity, avg_price, stop_price, target_price, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (
            uid, mk, sym,
            str(item.get("name", sym)).strip(),
            float(str(item.get("quantity", 0)).replace(",", "") or 0),
            float(str(item.get("avgPrice", 0)).replace(",", "") or 0),
            _opt_float(item.get("stopPrice")),
            _opt_float(item.get("targetPrice")),
            now,
        ))
        saved += 1
    conn.commit()
    return saved


def _holding_to_dict(row: sqlite3.Row) -> dict:
    return {
        "market": row["market"],
        "symbol": row["symbol"],
        "name": row["name"],
        "quantity": str(row["quantity"]),
        "avgPrice": str(row["avg_price"]),
        "stopPrice": str(row["stop_price"]) if row["stop_price"] is not None else "",
        "targetPrice": str(row["target_price"]) if row["target_price"] is not None else "",
    }


# ── Watchlist CRUD ────────────────────────────────────────────────────

def get_watchlist(user_id: str, market: str = "all") -> list[dict]:
    uid = sanitize_uid(user_id)
    if not uid:
        return []
    conn = get_conn()
    if market == "all":
        rows = conn.execute(
            "SELECT * FROM user_watchlist WHERE user_id=? ORDER BY market, symbol",
            (uid,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_watchlist WHERE user_id=? AND market=? ORDER BY symbol",
            (uid, market)
        ).fetchall()
    return [_watch_to_dict(r) for r in rows]


def save_watchlist(user_id: str, items: list[dict]) -> int:
    uid = sanitize_uid(user_id)
    if not uid:
        return 0
    conn = get_conn()
    now = int(time.time())
    markets_in_items: set[str] = set()
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        markets_in_items.add(mk)

    for mk in markets_in_items:
        conn.execute("DELETE FROM user_watchlist WHERE user_id=? AND market=?", (uid, mk))

    saved = 0
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        sym = str(item.get("symbol", "")).strip()
        if not sym:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO user_watchlist
            (user_id, market, symbol, name, memo, updated_at)
            VALUES (?,?,?,?,?,?)
        """, (
            uid, mk, sym,
            str(item.get("name", sym)).strip(),
            str(item.get("memo", item.get("group", ""))).strip(),
            now,
        ))
        saved += 1
    conn.commit()
    return saved


def _watch_to_dict(row: sqlite3.Row) -> dict:
    return {
        "market": row["market"],
        "symbol": row["symbol"],
        "name": row["name"],
        "memo": row["memo"] or "",
        "group": row["memo"] or "",
    }


def _opt_float(value: Any) -> float | None:
    if value is None or str(value).strip() in ("", "0", "0.0"):
        return None
    try:
        v = float(str(value).replace(",", ""))
        return v if v > 0 else None
    except Exception:
        return None
