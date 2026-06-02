from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
STOCKAPP = REPO / "data" / "stockapp"
REPORTS = REPO / "reports"

FIELDS = ["market", "symbol", "name", "reason", "updatedAt"]
AUDIT_FIELDS = [
    "market",
    "symbol",
    "name",
    "inHoldings",
    "inWatchlist",
    "inTargets",
    "inRecommendations",
    "inCurrentPriceFile",
    "dataStatus",
    "missingReason",
    "source",
]


def now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def text(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip():
            return str(row[key]).strip()
        low = key.lower()
        if low in lower and lower[low] is not None and str(lower[low]).strip():
            return str(lower[low]).strip()
    return default


def norm_symbol(value: Any, market: str) -> str:
    raw = str(value or "").strip().upper()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = re.sub(r"\.(KS|KQ|KR)$", "", raw)
    raw = re.sub(r"[^0-9A-Z.\-]", "", raw)
    if market == "kr":
        digits = re.sub(r"\D", "", raw)
        return digits.zfill(6)[-6:] if digits else ""
    return raw


def infer_market(symbol: str, explicit: Any = "") -> str:
    raw = str(explicit or "").strip().lower()
    if raw in {"kr", "kospi", "kosdaq", "konex", "한국주식", "국장", "korea"}:
        return "kr"
    if raw in {"us", "usa", "nasdaq", "nyse", "amex", "미국주식", "미장"}:
        return "us"
    return "kr" if re.fullmatch(r"\d{6}", str(symbol or "")) else "us"


def row_symbol(row: dict[str, Any], fallback_market: str = "") -> tuple[str, str]:
    raw = text(row, ["symbol", "ticker", "code", "stock_code", "stockCode", "종목코드", "종목", "Symbol", "Ticker"])
    if not raw and row:
        raw = str(row.get(next(iter(row.keys())), "")).strip()
    market = infer_market(raw, text(row, ["market", "시장", "exchange", "marketType"], fallback_market))
    return norm_symbol(raw, market), market


def row_name(row: dict[str, Any], symbol: str) -> str:
    name = text(row, ["name", "companyName", "company_name", "stock_name", "corp_name", "종목명", "기업명", "Name"])
    return name if name and name.upper() != symbol.upper() else symbol


def add_symbol(
    bucket: dict[tuple[str, str], dict[str, Any]],
    row: dict[str, Any],
    fallback_market: str,
    flag: str,
    source: str,
) -> None:
    symbol, market = row_symbol(row, fallback_market)
    if not symbol or market not in {"kr", "us"}:
        return
    key = (market, symbol)
    current = bucket.setdefault(
        key,
        {
            "market": market,
            "symbol": symbol,
            "name": row_name(row, symbol),
            "flags": set(),
            "sources": set(),
        },
    )
    if current["name"] == symbol:
        current["name"] = row_name(row, symbol)
    current["flags"].add(flag)
    current["sources"].add(source)


def load_bucket() -> dict[tuple[str, str], dict[str, Any]]:
    bucket: dict[tuple[str, str], dict[str, Any]] = {}
    source_sets = [
        ("holdings", "kr", [REPO / "holdings_kr.csv", REPO / "data" / "holdings_kr.csv"]),
        ("holdings", "us", [REPO / "holdings_us.csv", REPO / "data" / "holdings_us.csv"]),
        ("watchlist", "kr", [REPO / "watchlist_kr.csv", REPO / "watchlist_kr_growth.csv", REPO / "data" / "watchlist_kr.csv", REPO / "data" / "watchlist_kr_growth.csv"]),
        ("watchlist", "us", [REPO / "watchlist_us.csv", REPO / "watchlist_us_growth.csv", REPO / "data" / "watchlist_us.csv", REPO / "data" / "watchlist_us_growth.csv"]),
        ("targets", "kr", [STOCKAPP / "kis_collection_targets_kr.csv"]),
        ("targets", "us", [STOCKAPP / "kis_collection_targets_us.csv"]),
        ("recommendations", "kr", list(REPORTS.glob("mone_v36_final_recommendations_kr_*.csv")) + [REPO / "candidate_universe_kr.csv", REPO / "data" / "candidate_universe_kr.csv"]),
        ("recommendations", "us", list(REPORTS.glob("mone_v36_final_recommendations_us_*.csv")) + [REPO / "candidate_universe_us.csv", REPO / "data" / "candidate_universe_us.csv"]),
    ]
    for flag, market, paths in source_sets:
        for path in paths:
            for row in read_csv(path):
                add_symbol(bucket, row, market, flag, path.name)
    return bucket


def price_symbols(market: str) -> set[str]:
    paths = [
        STOCKAPP / f"kis_current_price_{market}.csv",
        STOCKAPP / f"intraday_quote_snapshot_{market}.csv",
        STOCKAPP / f"intraday_realtime_snapshot_{market}.csv",
        REPORTS / f"kis_current_price_{market}.csv",
        REPORTS / f"intraday_quote_snapshot_{market}.csv",
        REPORTS / f"intraday_realtime_snapshot_{market}.csv",
    ]
    out: set[str] = set()
    for path in paths:
        for row in read_csv(path):
            symbol, mk = row_symbol(row, market)
            if symbol and mk == market:
                out.add(symbol)
    return out


def main() -> None:
    bucket = load_bucket()
    price = {"kr": price_symbols("kr"), "us": price_symbols("us")}
    updated = now_text()

    universe: dict[str, list[dict[str, Any]]] = {"kr": [], "us": []}
    audit: list[dict[str, Any]] = []
    for (market, symbol), item in sorted(bucket.items()):
        flags = item["flags"]
        reason = "|".join(sorted(flags))
        universe[market].append({
            "market": market,
            "symbol": symbol,
            "name": item["name"],
            "reason": reason,
            "updatedAt": updated,
        })
        has_price = symbol in price[market]
        audit.append({
            "market": market,
            "symbol": symbol,
            "name": item["name"],
            "inHoldings": "true" if "holdings" in flags else "false",
            "inWatchlist": "true" if "watchlist" in flags else "false",
            "inTargets": "true" if "targets" in flags else "false",
            "inRecommendations": "true" if "recommendations" in flags else "false",
            "inCurrentPriceFile": "true" if has_price else "false",
            "dataStatus": "NORMAL" if has_price else "PRICE_PENDING",
            "missingReason": "" if has_price else "current_price_not_collected",
            "source": "|".join(sorted(item["sources"])),
        })

    for market in ("kr", "us"):
        write_csv(STOCKAPP / f"price_collection_universe_{market}.csv", FIELDS, universe[market])

    write_csv(REPORTS / "price_collection_coverage_audit.csv", AUDIT_FIELDS, audit)

    summary = {
        "updatedAt": updated,
        "markets": {},
        "collector": {
            "githubWorkflow": ".github/workflows/mone-auto-accumulator.yml",
            "backendFunction": "app.services.quotes.refresh_quotes",
            "localUniverseFiles": [
                "data/stockapp/price_collection_universe_kr.csv",
                "data/stockapp/price_collection_universe_us.csv",
            ],
        },
    }
    for market in ("kr", "us"):
        market_rows = [row for row in audit if row["market"] == market]
        price_count = sum(1 for row in market_rows if row["inCurrentPriceFile"] == "true")
        missing = len(market_rows) - price_count
        summary["markets"][market] = {
            "targetCount": len(market_rows),
            "currentPriceCount": price_count,
            "missingTargetCount": missing,
            "currentPriceCoveragePct": round(price_count / len(market_rows) * 100, 2) if market_rows else 0.0,
        }

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "kis_collection_coverage_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
