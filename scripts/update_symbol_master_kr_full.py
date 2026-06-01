from __future__ import annotations

import csv
import re
from datetime import datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "symbol_master_kr_full.csv"
EXTRA = REPO / "data" / "symbol_master_kr_extra.csv"

FIELDNAMES = ["symbol", "name", "market", "source", "updatedAt"]
REQUIRED = {
    "005930": "삼성전자",
    "009150": "삼성전기",
    "006340": "대원전선",
}


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


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in FIELDNAMES})


def norm_symbol(value: Any) -> str:
    raw = str(value or "").strip().upper()
    raw = re.sub(r"\.(KS|KQ|KR)$", "", raw)
    digits = re.sub(r"\D", "", raw)
    return digits.zfill(6)[-6:] if digits else ""


def text(row: dict[str, Any], keys: list[str]) -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip():
            return str(row[key]).strip()
        lk = key.lower()
        if lk in lower and lower[lk] is not None and str(lower[lk]).strip():
            return str(lower[lk]).strip()
    return ""


def add_row(rows: dict[str, dict[str, str]], symbol: Any, name: Any, source: str) -> None:
    sym = norm_symbol(symbol)
    nm = str(name or "").strip()
    if not sym or not nm or nm.upper() == sym:
        return
    rows[sym] = {
        "symbol": sym,
        "name": nm,
        "market": "kr",
        "source": source,
        "updatedAt": now_text(),
    }


def merge_csv_rows(rows: dict[str, dict[str, str]], paths: list[Path], source: str) -> None:
    for path in paths:
        for row in read_csv(path):
            add_row(
                rows,
                text(row, ["symbol", "code", "ticker", "stock_code", "종목코드", "종목"]),
                text(row, ["name", "companyName", "company_name", "stock_name", "종목명", "기업명"]),
                source or path.name,
            )


def collect_finance_data_reader(rows: dict[str, dict[str, str]]) -> tuple[int, str]:
    try:
        import FinanceDataReader as fdr  # type: ignore

        frame = fdr.StockListing("KRX")
        count = 0
        for _, row in frame.iterrows():
            symbol = row.get("Code") or row.get("Symbol") or row.get("Ticker")
            name = row.get("Name") or row.get("MarketName")
            before = len(rows)
            add_row(rows, symbol, name, "FinanceDataReader_KRX")
            if len(rows) > before:
                count += 1
        return count, "OK"
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def collect_pykrx(rows: dict[str, dict[str, str]]) -> tuple[int, str]:
    try:
        from pykrx import stock  # type: ignore

        count = 0
        for market in ("KOSPI", "KOSDAQ", "KONEX"):
            try:
                tickers = stock.get_market_ticker_list(market=market)
            except Exception:
                tickers = []
            for ticker in tickers:
                try:
                    name = stock.get_market_ticker_name(ticker)
                except Exception:
                    name = ticker
                before = len(rows)
                add_row(rows, ticker, name, f"pykrx_{market.lower()}")
                if len(rows) > before:
                    count += 1
        return count, "OK"
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def ensure_extra_file() -> None:
    existing: dict[str, dict[str, str]] = {}
    for row in read_csv(EXTRA):
        sym = norm_symbol(text(row, ["symbol", "code", "ticker", "종목코드"]))
        name = text(row, ["name", "companyName", "company_name", "종목명"])
        if sym and name:
            existing[sym] = {
                "symbol": sym,
                "name": name,
                "market": "kr",
                "source": text(row, ["source"]) or "manual_extra",
                "updatedAt": text(row, ["updatedAt"]) or now_text(),
            }
    for symbol, name in REQUIRED.items():
        existing.setdefault(
            symbol,
            {
                "symbol": symbol,
                "name": name,
                "market": "kr",
                "source": "manual_required_seed",
                "updatedAt": now_text(),
            },
        )
    write_csv(EXTRA, sorted(existing.values(), key=lambda row: row["symbol"]))


def main() -> None:
    ensure_extra_file()
    rows: dict[str, dict[str, str]] = {}

    fdr_count, fdr_status = collect_finance_data_reader(rows)
    pykrx_count, pykrx_status = (0, "SKIPPED")
    if len(rows) < 500:
        pykrx_count, pykrx_status = collect_pykrx(rows)

    merge_csv_rows(
        rows,
        [
            REPO / "holdings_kr.csv",
            REPO / "watchlist_kr.csv",
            REPO / "watchlist_kr_growth.csv",
            REPO / "candidate_universe_kr.csv",
            REPO / "data" / "holdings_kr.csv",
            REPO / "data" / "watchlist_kr.csv",
            REPO / "data" / "watchlist_kr_growth.csv",
            REPO / "data" / "candidate_universe_kr.csv",
        ],
        "local_symbol_csv",
    )
    merge_csv_rows(rows, [EXTRA], "manual_extra")

    for symbol, name in REQUIRED.items():
        add_row(rows, symbol, name, "manual_required_seed")

    write_csv(OUT, sorted(rows.values(), key=lambda row: row["symbol"]))

    print(f"[OK] wrote {OUT}")
    print(f"[OK] count={len(rows)}")
    print(f"[INFO] FinanceDataReader={fdr_count} ({fdr_status})")
    print(f"[INFO] pykrx={pykrx_count} ({pykrx_status})")
    for symbol, expected in REQUIRED.items():
        actual = rows.get(symbol, {}).get("name", "")
        status = "OK" if actual == expected else "CHECK"
        print(f"[{status}] {symbol} {actual or 'MISSING'} expected={expected}")


if __name__ == "__main__":
    main()
