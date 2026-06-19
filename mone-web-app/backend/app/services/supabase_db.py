"""Supabase REST (PostgREST) sync layer for holdings and watchlist.

Pattern: CSV is primary store; this module syncs changes to Supabase so the
data is accessible across devices. All writes go to CSV first, then here.
Falls back silently when SUPABASE_URL / SUPABASE_KEY are not set.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

import httpx

log = logging.getLogger(__name__)

_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_ANON_KEY") or ""
_DEFAULT_USER = "default"
_TIMEOUT = 8.0

# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _enabled() -> bool:
    return bool(_URL and _KEY)


def _headers() -> dict[str, str]:
    return {
        "apikey": _KEY,
        "Authorization": f"Bearer {_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rest(table: str) -> str:
    return f"{_URL}/rest/v1/{table}"


def _get(table: str, params: dict[str, str]) -> list[dict[str, Any]]:
    resp = httpx.get(_rest(table), headers=_headers(), params=params, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json() or []


def _upsert(table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    headers = {**_headers(), "Prefer": f"resolution=merge-duplicates,return=minimal"}
    resp = httpx.post(
        _rest(table),
        headers=headers,
        json=rows,
        params={"on_conflict": on_conflict},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()


def _delete(table: str, params: dict[str, str]) -> None:
    resp = httpx.delete(_rest(table), headers=_headers(), params=params, timeout=_TIMEOUT)
    resp.raise_for_status()


# --------------------------------------------------------------------------- #
# Holdings
# --------------------------------------------------------------------------- #

def upsert_holding(market: str, symbol: str, row: dict[str, Any], user_id: str = _DEFAULT_USER) -> None:
    """Upsert a single holding row to Supabase."""
    if not _enabled():
        return
    try:
        _upsert("holdings", [
            {
                "user_id": user_id,
                "market": market,
                "symbol": symbol,
                "name": str(row.get("name") or row.get("종목명") or ""),
                "avg_price": _num(row.get("avg_price") or row.get("평균단가") or row.get("평단가")),
                "quantity": _num(row.get("quantity") or row.get("보유수량")),
                "stop_price": _num(row.get("stopPrice") or row.get("stop_price")),
                "target_price": _num(row.get("targetPrice") or row.get("target_price")),
                "memo": str(row.get("memo") or row.get("메모") or ""),
                "updated_at": _now_iso(),
            }
        ], on_conflict="user_id,market,symbol")
    except Exception as exc:
        log.warning("supabase upsert_holding failed: %s", exc)


def delete_holding(market: str, symbol: str, user_id: str = _DEFAULT_USER) -> None:
    if not _enabled():
        return
    try:
        _delete("holdings", {
            "user_id": f"eq.{user_id}",
            "market": f"eq.{market}",
            "symbol": f"eq.{symbol}",
        })
    except Exception as exc:
        log.warning("supabase delete_holding failed: %s", exc)


def fetch_holdings(market: str, user_id: str = _DEFAULT_USER) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    try:
        return _get("holdings", {
            "user_id": f"eq.{user_id}",
            "market": f"eq.{market}",
            "select": "*",
        })
    except Exception as exc:
        log.warning("supabase fetch_holdings failed: %s", exc)
        return []


def replace_all_holdings(market: str, rows: list[dict[str, Any]], user_id: str = _DEFAULT_USER) -> None:
    """Replace entire holdings list for a market (used on full CSV sync)."""
    if not _enabled():
        return
    try:
        _delete("holdings", {"user_id": f"eq.{user_id}", "market": f"eq.{market}"})
        if rows:
            _upsert("holdings", [
                {
                    "user_id": user_id,
                    "market": market,
                    "symbol": str(r.get("symbol") or r.get("ticker") or ""),
                    "name": str(r.get("name") or r.get("종목명") or ""),
                    "avg_price": _num(r.get("avg_price") or r.get("평균단가") or r.get("평단가")),
                    "quantity": _num(r.get("quantity") or r.get("보유수량")),
                    "stop_price": _num(r.get("stopPrice") or r.get("stop_price")),
                    "target_price": _num(r.get("targetPrice") or r.get("target_price")),
                    "memo": str(r.get("memo") or r.get("메모") or ""),
                    "updated_at": _now_iso(),
                }
                for r in rows if r.get("symbol") or r.get("ticker")
            ], on_conflict="user_id,market,symbol")
    except Exception as exc:
        log.warning("supabase replace_all_holdings failed: %s", exc)


# --------------------------------------------------------------------------- #
# Watchlist
# --------------------------------------------------------------------------- #

def upsert_watch(market: str, symbol: str, row: dict[str, Any], user_id: str = _DEFAULT_USER) -> None:
    if not _enabled():
        return
    try:
        _upsert("watchlist", [
            {
                "user_id": user_id,
                "market": market,
                "symbol": symbol,
                "name": str(row.get("name") or row.get("종목명") or ""),
                "memo": str(row.get("memo") or row.get("메모") or ""),
                "updated_at": _now_iso(),
            }
        ], on_conflict="user_id,market,symbol")
    except Exception as exc:
        log.warning("supabase upsert_watch failed: %s", exc)


def delete_watch(market: str, symbol: str, user_id: str = _DEFAULT_USER) -> None:
    if not _enabled():
        return
    try:
        _delete("watchlist", {
            "user_id": f"eq.{user_id}",
            "market": f"eq.{market}",
            "symbol": f"eq.{symbol}",
        })
    except Exception as exc:
        log.warning("supabase delete_watch failed: %s", exc)


def fetch_watchlist(market: str, user_id: str = _DEFAULT_USER) -> list[dict[str, Any]]:
    if not _enabled():
        return []
    try:
        return _get("watchlist", {
            "user_id": f"eq.{user_id}",
            "market": f"eq.{market}",
            "select": "*",
        })
    except Exception as exc:
        log.warning("supabase fetch_watchlist failed: %s", exc)
        return []


# --------------------------------------------------------------------------- #
# Startup sync — pull Supabase → overwrite local CSV on server start
# --------------------------------------------------------------------------- #

def pull_to_csv(repo_root: "Path") -> dict[str, Any]:  # type: ignore[name-defined]
    """On Render startup, pull Supabase data into local CSVs so the app has
    fresh data even if the CSV files are stale (git-committed snapshot)."""
    if not _enabled():
        return {"status": "DISABLED"}

    import pandas as pd
    from pathlib import Path

    root = Path(repo_root)

    def _csv_path(name: str) -> Path:
        # data/ 하위 파일이 있으면 사용, 없으면 루트 (user_data.py write 경로)
        p = root / "data" / name
        if p.exists():
            return p
        return root / name

    results: dict[str, Any] = {}
    for market in ("kr", "us"):
        try:
            h_rows = fetch_holdings(market)
            if h_rows:
                df = pd.DataFrame(h_rows).drop(columns=["user_id"], errors="ignore")
                path = _csv_path(f"holdings_{market}.csv")
                df.to_csv(path, index=False, encoding="utf-8-sig")
                results[f"holdings_{market}"] = len(h_rows)

            w_rows = fetch_watchlist(market)
            if w_rows:
                df = pd.DataFrame(w_rows).drop(columns=["user_id"], errors="ignore")
                path = _csv_path(f"watchlist_{market}.csv")
                df.to_csv(path, index=False, encoding="utf-8-sig")
                results[f"watchlist_{market}"] = len(w_rows)
        except Exception as exc:
            results[f"{market}_error"] = str(exc)

    return {"status": "OK", "pulled": results}


# --------------------------------------------------------------------------- #
# Utility
# --------------------------------------------------------------------------- #

def _num(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "", "nan") else None
    except (TypeError, ValueError):
        return None
