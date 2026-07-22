#!/usr/bin/env python3
"""Refresh free KIS intraday context for KR regime-lens candidates.

This is read-only market data collection.  It never places orders.

Inputs:
  - reports/regime_lens_candidates_kr.json

Outputs:
  - reports/lens_intraday_context_kr.csv
  - reports/intraday_orderbook_snapshot.csv

The AI paper trader reads lens_intraday_context_kr.csv to size/suppress
paper-only bear-rebound tests with live KIS quote/order-book/investor-flow
confirmation when available.
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
LENS_JSON = REPORTS / "regime_lens_candidates_kr.json"
LENS_CONTEXT_CSV = REPORTS / "lens_intraday_context_kr.csv"
ORDERBOOK_CSV = REPORTS / "intraday_orderbook_snapshot.csv"
RATE_LIMIT_SLEEP_SEC = 0.18

sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

KST = timezone(timedelta(hours=9))

FIELDS = [
    "updatedAt", "asOfDate", "symbol", "name", "setup", "regime",
    "quoteStatus", "currentPrice", "prevClose", "changePct", "priceTime",
    "orderbookStatus", "bidRatio", "totalBidQty", "totalAskQty",
    "flowStatus", "flowSignal", "flowScore", "foreign5d", "institution5d",
    "foreign20d", "institution20d",
    "entry", "stop", "target", "rrRatio", "calibrationGate",
]

ORDERBOOK_FIELDS = [
    "updatedAt", "market", "symbol", "name",
    "orderbook_fetch_status", "orderbook_source_label",
    "bidRatio", "totalBidQty", "totalAskQty",
    "bid1", "bid1Qty", "ask1", "ask1Qty",
]


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _num(value: Any) -> float:
    try:
        text = str(value or "").replace(",", "").strip()
        return float(text) if text else 0.0
    except Exception:
        return 0.0


def _read_lens_candidates() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not LENS_JSON.exists():
        return {}, []
    try:
        payload = json.loads(LENS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}, []
    candidates = payload.get("candidates") if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        candidates = []
    return payload, [row for row in candidates if isinstance(row, dict)]


def _append_or_replace_latest(path: Path, rows: list[dict[str, Any]], fields: list[str], key_fields: tuple[str, ...]) -> None:
    existing: list[dict[str, Any]] = []
    if path.exists():
        try:
            existing = list(csv.DictReader(path.open(encoding="utf-8-sig", newline="")))
        except Exception:
            existing = []
    keyed = {
        tuple(str(row.get(field) or "") for field in key_fields): row
        for row in existing
    }
    for row in rows:
        keyed[tuple(str(row.get(field) or "") for field in key_fields)] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in keyed.values():
            writer.writerow({field: row.get(field, "") for field in fields})


def main() -> int:
    from app.services import quotes

    report, candidates = _read_lens_candidates()
    if not candidates:
        print("regime_lens_candidates_kr.json has no candidates; run scripts/screen_regime_lens_kr.py first")
        return 0
    if not quotes._kis_enabled():
        print("KIS_APP_KEY/KIS_APP_SECRET missing; skipped KIS intraday context collection")
        return 0

    as_of = str(report.get("asOfDate") or "")
    regime = str(report.get("marketRegime") or "")
    now = _now()
    symbols = [str(row.get("symbol") or "").strip().zfill(6) for row in candidates if str(row.get("symbol") or "").strip()]
    quote_map: dict[str, dict[str, Any]] = {}
    for quote in quotes.fetch_quotes_bulk("kr", symbols):
        quote_map[str(quote.get("symbol") or "").strip().zfill(6)] = quote

    rows: list[dict[str, Any]] = []
    orderbook_rows: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = str(candidate.get("symbol") or "").strip().zfill(6)
        if not symbol:
            continue
        name = str(candidate.get("name") or symbol)
        quote = quote_map.get(symbol, {})
        orderbook = quotes.fetch_orderbook_kr(symbol)
        flow = quotes.fetch_investor_flow_kr(symbol)
        flow_score = quotes.investor_flow_supply_score(flow.get("history") or []) if flow.get("ok") else {"ok": False}

        bid1 = (orderbook.get("bids") or [{}])[0] if orderbook.get("bids") else {}
        ask1 = (orderbook.get("asks") or [{}])[0] if orderbook.get("asks") else {}
        row = {
            "updatedAt": now,
            "asOfDate": as_of,
            "symbol": symbol,
            "name": name,
            "setup": candidate.get("setup", ""),
            "regime": regime,
            "quoteStatus": "OK" if quote.get("ok") else "ERROR",
            "currentPrice": quote.get("currentPrice", ""),
            "prevClose": quote.get("prevClose", ""),
            "changePct": quote.get("changePct", ""),
            "priceTime": quote.get("priceTime", ""),
            "orderbookStatus": "OK" if orderbook.get("ok") else "ERROR",
            "bidRatio": orderbook.get("bidRatio", ""),
            "totalBidQty": orderbook.get("totalBidQty", ""),
            "totalAskQty": orderbook.get("totalAskQty", ""),
            "flowStatus": "OK" if flow.get("ok") else "ERROR",
            "flowSignal": flow.get("signal", ""),
            "flowScore": flow_score.get("score", "") if flow_score.get("ok") else "",
            "foreign5d": flow_score.get("foreign_5d", "") if flow_score.get("ok") else "",
            "institution5d": flow_score.get("institution_5d", "") if flow_score.get("ok") else "",
            "foreign20d": flow_score.get("foreign_20d", "") if flow_score.get("ok") else "",
            "institution20d": flow_score.get("institution_20d", "") if flow_score.get("ok") else "",
            "entry": candidate.get("entryRef", ""),
            "stop": candidate.get("stop", ""),
            "target": candidate.get("target", ""),
            "rrRatio": candidate.get("rrRatio", ""),
            "calibrationGate": candidate.get("calibrationGate", ""),
        }
        rows.append(row)
        orderbook_rows.append({
            "updatedAt": now,
            "market": "kr",
            "symbol": symbol,
            "name": name,
            "orderbook_fetch_status": row["orderbookStatus"],
            "orderbook_source_label": "KIS orderbook snapshot",
            "bidRatio": row["bidRatio"],
            "totalBidQty": row["totalBidQty"],
            "totalAskQty": row["totalAskQty"],
            "bid1": bid1.get("price", ""),
            "bid1Qty": bid1.get("qty", ""),
            "ask1": ask1.get("price", ""),
            "ask1Qty": ask1.get("qty", ""),
        })
        time.sleep(RATE_LIMIT_SLEEP_SEC)

    _append_or_replace_latest(LENS_CONTEXT_CSV, rows, FIELDS, ("asOfDate", "symbol", "setup"))
    _append_or_replace_latest(ORDERBOOK_CSV, orderbook_rows, ORDERBOOK_FIELDS, ("updatedAt", "symbol"))
    ok_quotes = sum(1 for row in rows if row.get("quoteStatus") == "OK")
    ok_orderbooks = sum(1 for row in rows if row.get("orderbookStatus") == "OK")
    ok_flows = sum(1 for row in rows if row.get("flowStatus") == "OK")
    print(
        f"KIS lens context: candidates={len(rows)} quote={ok_quotes} "
        f"orderbook={ok_orderbooks} flow={ok_flows} -> {LENS_CONTEXT_CSV.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
