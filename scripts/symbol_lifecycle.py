"""Shared active-universe lifecycle registry for collectors and recommenders."""
from __future__ import annotations

import csv
from datetime import date
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REGISTRY = REPO / "data" / "market" / "inactive_symbols.csv"


def inactive_symbols(market: str, as_of: date | None = None) -> set[str]:
    cutoff = as_of or date.today()
    target_market = str(market or "").strip().lower()
    if not REGISTRY.is_file():
        return set()
    result: set[str] = set()
    with REGISTRY.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("market") or "").strip().lower() != target_market:
                continue
            symbol = str(row.get("symbol") or "").strip().upper()
            try:
                effective = date.fromisoformat(str(row.get("effectiveDate") or ""))
            except ValueError:
                continue
            if symbol and effective <= cutoff:
                result.add(symbol)
    return result


def is_inactive(market: str, symbol: str, as_of: date | None = None) -> bool:
    return str(symbol or "").strip().upper() in inactive_symbols(market, as_of)
