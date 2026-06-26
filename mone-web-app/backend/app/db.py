"""
사용자별 보유종목/관심종목 영구 저장소.
DATABASE_URL 환경변수 있으면 → PostgreSQL (Supabase)
없으면                       → SQLite (로컬 개발/폴백)
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# ── 동시성 보호 ───────────────────────────────────────────────────────
# save_holdings는 해당 user의 보유종목을 DELETE 후 INSERT로 통째로 교체한다.
# 같은 uid에 대해 KIS 동기화와 일반 CRUD가 동시에 들어오면 한쪽이 사라질 수 있어
# user_id 단위로 직렬화한다 (payload가 kr/us를 섞어 보낼 수 있어 market은 키에서 제외).
_HOLDINGS_LOCKS: dict[str, threading.Lock] = {}
_HOLDINGS_LOCKS_GUARD = threading.Lock()


def holdings_lock(user_id: str) -> threading.Lock:
    with _HOLDINGS_LOCKS_GUARD:
        lock = _HOLDINGS_LOCKS.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _HOLDINGS_LOCKS[user_id] = lock
        return lock


# ── 백엔드 감지 ───────────────────────────────────────────────────────

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    # Render provides postgres:// but psycopg2 requires postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _resolve_ipv4_dsn(url: str) -> str:
    """Replace hostname with IPv4 address to avoid IPv6-only hosts on Render."""
    import socket, urllib.parse
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host or host.replace(".", "").isdigit():
            return url  # already IP or empty
        infos = socket.getaddrinfo(host, parsed.port or 5432, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            ipv4 = infos[0][4][0]
            # rebuild URL replacing hostname with ipv4
            netloc = parsed.netloc.replace(host, ipv4)
            return urllib.parse.urlunparse(parsed._replace(netloc=netloc))
    except Exception:
        pass
    return url

def _use_postgres() -> bool:
    return bool(_database_url())


# ══════════════════════════════════════════════════════════════════════
# PostgreSQL 백엔드 (psycopg2)
# ══════════════════════════════════════════════════════════════════════

_pg_pool: Any = None

def _pg_pool_get():
    global _pg_pool
    if _pg_pool is None:
        import psycopg2.pool
        url = _resolve_ipv4_dsn(_database_url())
        _pg_pool = psycopg2.pool.ThreadedConnectionPool(1, 10, dsn=url)
        _pg_init_schema()
    return _pg_pool

def _pg_conn():
    return _pg_pool_get().getconn()

def _pg_release(conn):
    try:
        _pg_pool_get().putconn(conn)
    except Exception:
        pass

def _pg_init_schema():
    conn = _pg_pool_get().getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS user_holdings (
                user_id      TEXT NOT NULL,
                market       TEXT NOT NULL CHECK(market IN ('kr','us')),
                symbol       TEXT NOT NULL,
                name         TEXT NOT NULL DEFAULT '',
                quantity     DOUBLE PRECISION NOT NULL DEFAULT 0,
                avg_price    DOUBLE PRECISION NOT NULL DEFAULT 0,
                stop_price   DOUBLE PRECISION,
                target_price DOUBLE PRECISION,
                broker       TEXT DEFAULT 'manual',
                current_price DOUBLE PRECISION,
                eval_amount  DOUBLE PRECISION,
                profit_loss  DOUBLE PRECISION,
                profit_loss_rate DOUBLE PRECISION,
                synced_at    BIGINT,
                updated_at   BIGINT NOT NULL,
                PRIMARY KEY (user_id, market, symbol)
            );
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS broker TEXT DEFAULT 'manual';
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS current_price DOUBLE PRECISION;
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS eval_amount DOUBLE PRECISION;
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS profit_loss DOUBLE PRECISION;
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS profit_loss_rate DOUBLE PRECISION;
            ALTER TABLE user_holdings ADD COLUMN IF NOT EXISTS synced_at BIGINT;
            CREATE TABLE IF NOT EXISTS user_watchlist (
                user_id    TEXT NOT NULL,
                market     TEXT NOT NULL CHECK(market IN ('kr','us')),
                symbol     TEXT NOT NULL,
                name       TEXT NOT NULL DEFAULT '',
                memo       TEXT DEFAULT '',
                updated_at BIGINT NOT NULL,
                PRIMARY KEY (user_id, market, symbol)
            );
            CREATE TABLE IF NOT EXISTS broker_connections (
                user_id        TEXT NOT NULL,
                broker         TEXT NOT NULL,
                connected      INTEGER NOT NULL DEFAULT 1,
                connection_mode TEXT DEFAULT 'local_bridge',
                sync_status    TEXT DEFAULT 'OK',
                last_sync      DOUBLE PRECISION,
                connected_at   DOUBLE PRECISION,
                account_no_hint TEXT DEFAULT '',
                item_count     INTEGER DEFAULT 0,
                source         TEXT DEFAULT 'local_bridge',
                updated_at     BIGINT NOT NULL,
                PRIMARY KEY (user_id, broker)
            );
            """)
            conn.commit()
    finally:
        _pg_pool_get().putconn(conn)

def _pg_get_holdings(uid: str, market: str) -> list[dict]:
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            if market == "all":
                cur.execute(
                    "SELECT market,symbol,name,quantity,avg_price,stop_price,target_price,broker,current_price,eval_amount,profit_loss,profit_loss_rate,synced_at "
                    "FROM user_holdings WHERE user_id=%s ORDER BY market,symbol",
                    (uid,)
                )
            else:
                cur.execute(
                    "SELECT market,symbol,name,quantity,avg_price,stop_price,target_price,broker,current_price,eval_amount,profit_loss,profit_loss_rate,synced_at "
                    "FROM user_holdings WHERE user_id=%s AND market=%s ORDER BY symbol",
                    (uid, market)
                )
            return [_pg_holding_row(r) for r in cur.fetchall()]
    finally:
        _pg_release(conn)

def _pg_save_holdings(uid: str, items: list[dict]) -> int:
    conn = _pg_conn()
    try:
        now = int(time.time())
        markets: set[str] = {("us" if str(i.get("market","kr")).lower()=="us" else "kr") for i in items}
        with conn.cursor() as cur:
            for mk in markets:
                cur.execute("DELETE FROM user_holdings WHERE user_id=%s AND market=%s", (uid, mk))
            saved = 0
            for item in items:
                mk = "us" if str(item.get("market","kr")).lower()=="us" else "kr"
                sym = str(item.get("symbol","")).strip()
                if not sym:
                    continue
                cur.execute("""
                    INSERT INTO user_holdings
                    (user_id,market,symbol,name,quantity,avg_price,stop_price,target_price,broker,current_price,eval_amount,profit_loss,profit_loss_rate,synced_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (user_id,market,symbol) DO UPDATE SET
                        name=EXCLUDED.name, quantity=EXCLUDED.quantity,
                        avg_price=EXCLUDED.avg_price, stop_price=EXCLUDED.stop_price,
                        target_price=EXCLUDED.target_price, broker=EXCLUDED.broker,
                        current_price=EXCLUDED.current_price, eval_amount=EXCLUDED.eval_amount,
                        profit_loss=EXCLUDED.profit_loss, profit_loss_rate=EXCLUDED.profit_loss_rate,
                        synced_at=EXCLUDED.synced_at, updated_at=EXCLUDED.updated_at
                """, (
                    uid, mk, sym,
                    str(item.get("name", sym)).strip(),
                    _to_float(item.get("quantity", 0)),
                    _to_float(item.get("avgPrice", 0)),
                    _opt_float(item.get("stopPrice")),
                    _opt_float(item.get("targetPrice")),
                    str(item.get("broker") or item.get("source") or "manual").strip() or "manual",
                    _to_float(item.get("currentPrice")),
                    _to_float(item.get("evalAmount") or item.get("valuation")),
                    _to_float(item.get("profitLoss")),
                    _to_float(item.get("profitLossRate")),
                    int(_to_float(item.get("syncedAt") or now) or now),
                    now,
                ))
                saved += 1
        conn.commit()
        return saved
    finally:
        _pg_release(conn)

def _pg_get_watchlist(uid: str, market: str) -> list[dict]:
    conn = _pg_conn()
    try:
        with conn.cursor() as cur:
            if market == "all":
                cur.execute(
                    "SELECT market,symbol,name,memo FROM user_watchlist "
                    "WHERE user_id=%s ORDER BY market,symbol", (uid,)
                )
            else:
                cur.execute(
                    "SELECT market,symbol,name,memo FROM user_watchlist "
                    "WHERE user_id=%s AND market=%s ORDER BY symbol", (uid, market)
                )
            return [_pg_watch_row(r) for r in cur.fetchall()]
    finally:
        _pg_release(conn)

def _pg_save_watchlist(uid: str, items: list[dict]) -> int:
    conn = _pg_conn()
    try:
        now = int(time.time())
        markets: set[str] = {("us" if str(i.get("market","kr")).lower()=="us" else "kr") for i in items}
        with conn.cursor() as cur:
            for mk in markets:
                cur.execute("DELETE FROM user_watchlist WHERE user_id=%s AND market=%s", (uid, mk))
            saved = 0
            for item in items:
                mk = "us" if str(item.get("market","kr")).lower()=="us" else "kr"
                sym = str(item.get("symbol","")).strip()
                if not sym:
                    continue
                cur.execute("""
                    INSERT INTO user_watchlist (user_id,market,symbol,name,memo,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (user_id,market,symbol) DO UPDATE SET
                        name=EXCLUDED.name, memo=EXCLUDED.memo, updated_at=EXCLUDED.updated_at
                """, (
                    uid, mk, sym,
                    str(item.get("name", sym)).strip(),
                    str(item.get("memo", item.get("group",""))).strip(),
                    now,
                ))
                saved += 1
        conn.commit()
        return saved
    finally:
        _pg_release(conn)

def _pg_holding_row(r) -> dict:
    return {
        "market": r[0], "symbol": r[1], "name": r[2],
        "quantity": str(r[3]), "avgPrice": str(r[4]),
        "stopPrice": str(r[5]) if r[5] is not None else "",
        "targetPrice": str(r[6]) if r[6] is not None else "",
        "broker": r[7] or "manual",
        "source": r[7] or "manual",
        "currentPrice": r[8],
        "evalAmount": r[9],
        "valuation": r[9],
        "profitLoss": r[10],
        "profitLossRate": r[11],
        "syncedAt": r[12],
    }

def _pg_watch_row(r) -> dict:
    return {"market": r[0], "symbol": r[1], "name": r[2], "memo": r[3] or "", "group": r[3] or ""}


# ══════════════════════════════════════════════════════════════════════
# SQLite 백엔드 (폴백 / 로컬)
# ══════════════════════════════════════════════════════════════════════

_sqlite_conn: sqlite3.Connection | None = None

def _sqlite_db_path() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "data").exists():
            return parent / "data" / "mone_users.db"
    return here.parent / "mone_users.db"

def _sqlite_get_conn() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        path = _sqlite_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _sqlite_conn = sqlite3.connect(str(path), check_same_thread=False, timeout=10)
        _sqlite_conn.row_factory = sqlite3.Row
        _sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _sqlite_conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_holdings (
            user_id TEXT NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '', quantity REAL NOT NULL DEFAULT 0,
            avg_price REAL NOT NULL DEFAULT 0, stop_price REAL, target_price REAL,
            broker TEXT DEFAULT 'manual', current_price REAL, eval_amount REAL,
            profit_loss REAL, profit_loss_rate REAL, synced_at INTEGER,
            updated_at INTEGER NOT NULL, PRIMARY KEY (user_id, market, symbol)
        );
        CREATE TABLE IF NOT EXISTS user_watchlist (
            user_id TEXT NOT NULL, market TEXT NOT NULL, symbol TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '', memo TEXT DEFAULT '', updated_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, market, symbol)
        );
        CREATE TABLE IF NOT EXISTS broker_connections (
            user_id TEXT NOT NULL, broker TEXT NOT NULL,
            connected INTEGER NOT NULL DEFAULT 1,
            connection_mode TEXT DEFAULT 'local_bridge',
            sync_status TEXT DEFAULT 'OK',
            last_sync REAL, connected_at REAL,
            account_no_hint TEXT DEFAULT '', item_count INTEGER DEFAULT 0,
            source TEXT DEFAULT 'local_bridge',
            updated_at INTEGER NOT NULL,
            PRIMARY KEY (user_id, broker)
        );
        """)
        cols = {row["name"] for row in _sqlite_conn.execute("PRAGMA table_info(user_holdings)").fetchall()}
        migrations = {
            "broker": "ALTER TABLE user_holdings ADD COLUMN broker TEXT DEFAULT 'manual'",
            "current_price": "ALTER TABLE user_holdings ADD COLUMN current_price REAL",
            "eval_amount": "ALTER TABLE user_holdings ADD COLUMN eval_amount REAL",
            "profit_loss": "ALTER TABLE user_holdings ADD COLUMN profit_loss REAL",
            "profit_loss_rate": "ALTER TABLE user_holdings ADD COLUMN profit_loss_rate REAL",
            "synced_at": "ALTER TABLE user_holdings ADD COLUMN synced_at INTEGER",
        }
        for col, sql in migrations.items():
            if col not in cols:
                _sqlite_conn.execute(sql)
        _sqlite_conn.commit()
    return _sqlite_conn

def _sqlite_get_holdings(uid: str, market: str) -> list[dict]:
    conn = _sqlite_get_conn()
    if market == "all":
        rows = conn.execute(
            "SELECT * FROM user_holdings WHERE user_id=? ORDER BY market,symbol", (uid,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_holdings WHERE user_id=? AND market=? ORDER BY symbol", (uid, market)
        ).fetchall()
    return [{
        "market": r["market"], "symbol": r["symbol"], "name": r["name"],
        "quantity": str(r["quantity"]), "avgPrice": str(r["avg_price"]),
        "stopPrice": str(r["stop_price"]) if r["stop_price"] is not None else "",
        "targetPrice": str(r["target_price"]) if r["target_price"] is not None else "",
        "broker": r["broker"] or "manual",
        "source": r["broker"] or "manual",
        "currentPrice": r["current_price"],
        "evalAmount": r["eval_amount"],
        "valuation": r["eval_amount"],
        "profitLoss": r["profit_loss"],
        "profitLossRate": r["profit_loss_rate"],
        "syncedAt": r["synced_at"],
    } for r in rows]

def _sqlite_save_holdings(uid: str, items: list[dict]) -> int:
    conn = _sqlite_get_conn()
    now = int(time.time())
    markets: set[str] = {("us" if str(i.get("market","kr")).lower()=="us" else "kr") for i in items}
    for mk in markets:
        conn.execute("DELETE FROM user_holdings WHERE user_id=? AND market=?", (uid, mk))
    saved = 0
    for item in items:
        mk = "us" if str(item.get("market","kr")).lower()=="us" else "kr"
        sym = str(item.get("symbol","")).strip()
        if not sym:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO user_holdings
            (user_id,market,symbol,name,quantity,avg_price,stop_price,target_price,broker,current_price,eval_amount,profit_loss,profit_loss_rate,synced_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (uid, mk, sym, str(item.get("name",sym)).strip(),
              _to_float(item.get("quantity",0)), _to_float(item.get("avgPrice",0)),
              _opt_float(item.get("stopPrice")), _opt_float(item.get("targetPrice")),
              str(item.get("broker") or item.get("source") or "manual").strip() or "manual",
              _to_float(item.get("currentPrice")),
              _to_float(item.get("evalAmount") or item.get("valuation")),
              _to_float(item.get("profitLoss")),
              _to_float(item.get("profitLossRate")),
              int(_to_float(item.get("syncedAt") or now) or now),
              now))
        saved += 1
    conn.commit()
    return saved

def _sqlite_get_watchlist(uid: str, market: str) -> list[dict]:
    conn = _sqlite_get_conn()
    if market == "all":
        rows = conn.execute(
            "SELECT * FROM user_watchlist WHERE user_id=? ORDER BY market,symbol", (uid,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM user_watchlist WHERE user_id=? AND market=? ORDER BY symbol", (uid, market)
        ).fetchall()
    return [{"market": r["market"], "symbol": r["symbol"], "name": r["name"],
             "memo": r["memo"] or "", "group": r["memo"] or ""} for r in rows]

def _sqlite_save_watchlist(uid: str, items: list[dict]) -> int:
    conn = _sqlite_get_conn()
    now = int(time.time())
    markets: set[str] = {("us" if str(i.get("market","kr")).lower()=="us" else "kr") for i in items}
    for mk in markets:
        conn.execute("DELETE FROM user_watchlist WHERE user_id=? AND market=?", (uid, mk))
    saved = 0
    for item in items:
        mk = "us" if str(item.get("market","kr")).lower()=="us" else "kr"
        sym = str(item.get("symbol","")).strip()
        if not sym:
            continue
        conn.execute("""
            INSERT OR REPLACE INTO user_watchlist (user_id,market,symbol,name,memo,updated_at)
            VALUES (?,?,?,?,?,?)
        """, (uid, mk, sym, str(item.get("name",sym)).strip(),
              str(item.get("memo", item.get("group",""))).strip(), now))
        saved += 1
    conn.commit()
    return saved


# ══════════════════════════════════════════════════════════════════════
# 공개 API (main.py에서 사용)
# ══════════════════════════════════════════════════════════════════════

def sanitize_uid(raw: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))[:64]

def get_holdings(user_id: str, market: str = "all") -> list[dict]:
    uid = sanitize_uid(user_id)
    if not uid:
        return []
    try:
        if _use_postgres():
            return _pg_get_holdings(uid, market)
        return _sqlite_get_holdings(uid, market)
    except Exception as e:
        print(f"[db] get_holdings error: {e}")
        return []

def save_holdings(user_id: str, items: list[dict]) -> int:
    uid = sanitize_uid(user_id)
    if not uid:
        return 0
    try:
        if _use_postgres():
            return _pg_save_holdings(uid, items)
        return _sqlite_save_holdings(uid, items)
    except Exception as e:
        print(f"[db] save_holdings error: {e}")
        return 0

def get_watchlist(user_id: str, market: str = "all") -> list[dict]:
    uid = sanitize_uid(user_id)
    if not uid:
        return []
    try:
        if _use_postgres():
            return _pg_get_watchlist(uid, market)
        return _sqlite_get_watchlist(uid, market)
    except Exception as e:
        print(f"[db] get_watchlist error: {e}")
        return []

def save_watchlist(user_id: str, items: list[dict]) -> int:
    uid = sanitize_uid(user_id)
    if not uid:
        return 0
    try:
        if _use_postgres():
            return _pg_save_watchlist(uid, items)
        return _sqlite_save_watchlist(uid, items)
    except Exception as e:
        print(f"[db] save_watchlist error: {e}")
        return 0

def save_broker_connection(user_id: str, broker: str, record: dict) -> None:
    uid = sanitize_uid(user_id)
    if not uid:
        return
    now = int(time.time())
    try:
        if _use_postgres():
            conn = _pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO broker_connections
                        (user_id,broker,connected,connection_mode,sync_status,last_sync,
                         connected_at,account_no_hint,item_count,source,updated_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT (user_id,broker) DO UPDATE SET
                            connected=EXCLUDED.connected,
                            connection_mode=EXCLUDED.connection_mode,
                            sync_status=EXCLUDED.sync_status,
                            last_sync=EXCLUDED.last_sync,
                            connected_at=EXCLUDED.connected_at,
                            account_no_hint=EXCLUDED.account_no_hint,
                            item_count=EXCLUDED.item_count,
                            source=EXCLUDED.source,
                            updated_at=EXCLUDED.updated_at
                    """, (
                        uid, broker.lower().strip(),
                        1 if record.get("connected", True) else 0,
                        record.get("connection_mode", "local_bridge"),
                        record.get("sync_status", "OK"),
                        record.get("last_sync"), record.get("connected_at"),
                        record.get("account_no_hint", ""),
                        int(record.get("item_count", 0)),
                        record.get("source", "local_bridge"),
                        now,
                    ))
                conn.commit()
            finally:
                _pg_release(conn)
        else:
            conn = _sqlite_get_conn()
            conn.execute("""
                INSERT OR REPLACE INTO broker_connections
                (user_id,broker,connected,connection_mode,sync_status,last_sync,
                 connected_at,account_no_hint,item_count,source,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                uid, broker.lower().strip(),
                1 if record.get("connected", True) else 0,
                record.get("connection_mode", "local_bridge"),
                record.get("sync_status", "OK"),
                record.get("last_sync"), record.get("connected_at"),
                record.get("account_no_hint", ""),
                int(record.get("item_count", 0)),
                record.get("source", "local_bridge"),
                now,
            ))
            conn.commit()
    except Exception as e:
        print(f"[db] save_broker_connection error: {e}")


def get_broker_connection(user_id: str, broker: str) -> dict | None:
    uid = sanitize_uid(user_id)
    if not uid:
        return None
    bk = broker.lower().strip()
    try:
        if _use_postgres():
            conn = _pg_conn()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT connected,connection_mode,sync_status,last_sync,connected_at,"
                        "account_no_hint,item_count,source FROM broker_connections "
                        "WHERE user_id=%s AND broker=%s", (uid, bk)
                    )
                    row = cur.fetchone()
            finally:
                _pg_release(conn)
        else:
            conn = _sqlite_get_conn()
            row = conn.execute(
                "SELECT connected,connection_mode,sync_status,last_sync,connected_at,"
                "account_no_hint,item_count,source FROM broker_connections "
                "WHERE user_id=? AND broker=?", (uid, bk)
            ).fetchone()
        if not row:
            return None
        return {
            "broker": bk,
            "connected": bool(row[0]),
            "connectionMode": row[1] or "local_bridge",
            "status": row[2] or "OK",
            "lastSync": row[3],
            "connectedAt": row[4],
            "accountNoHint": row[5] or "",
            "itemCount": row[6] or 0,
            "source": row[7] or "local_bridge",
        }
    except Exception as e:
        print(f"[db] get_broker_connection error: {e}")
        return None


def backend_info() -> dict:
    return {
        "backend": "postgresql" if _use_postgres() else "sqlite",
        "configured": _use_postgres(),
    }


# ── 유틸 ─────────────────────────────────────────────────────────────

def _to_float(value: Any) -> float:
    try:
        return float(str(value).replace(",", "") or 0)
    except Exception:
        return 0.0

def _opt_float(value: Any) -> float | None:
    if value is None or str(value).strip() in ("", "0", "0.0"):
        return None
    try:
        v = float(str(value).replace(",", ""))
        return v if v > 0 else None
    except Exception:
        return None
