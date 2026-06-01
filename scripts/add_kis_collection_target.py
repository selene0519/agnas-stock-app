# scripts/add_kis_collection_target.py
# Add a symbol to the local KIS collection target list.
# This does not fetch prices by itself; it creates/updates the target CSV used by follow-up collection logic.

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def norm_symbol(symbol: str, market: str) -> str:
    raw = str(symbol or "").strip()
    if market == "kr":
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits.zfill(6)[-6:] if digits else ""
    return raw.upper()


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", choices=["kr", "us"], required=True)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--reason", default="user_added")
    args = parser.parse_args()

    market = args.market
    symbol = norm_symbol(args.symbol, market)
    if not symbol:
        raise SystemExit("symbol is empty after normalization")

    path = REPO / "data" / "stockapp" / f"kis_collection_targets_{market}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)

    rows = read_rows(path)
    keyed = {}
    for row in rows:
        sym = norm_symbol(row.get("symbol") or row.get("ticker") or row.get("code") or "", market)
        if not sym:
            continue
        keyed[sym] = {
            "market": market,
            "symbol": sym,
            "name": str(row.get("name") or row.get("companyName") or sym).strip(),
            "reason": str(row.get("reason") or "existing").strip(),
            "updatedAt": str(row.get("updatedAt") or "").strip(),
        }

    keyed[symbol] = {
        "market": market,
        "symbol": symbol,
        "name": args.name.strip() or symbol,
        "reason": args.reason,
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
    }

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["market", "symbol", "name", "reason", "updatedAt"])
        writer.writeheader()
        writer.writerows(sorted(keyed.values(), key=lambda r: r["symbol"]))

    print(f"[OK] wrote {path}")
    print(f"[OK] target {market}:{symbol} {keyed[symbol]['name']}")


if __name__ == "__main__":
    main()
