from pathlib import Path
from datetime import datetime
import json
import os
import shutil
import traceback
import pandas as pd
import numpy as np

ROOT = Path(".").resolve()
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
BACKUP_DIR = ROOT / "backups" / f"mone_quote_bind_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")

TARGET_FILES = [
    "holdings_us.csv",
    "data/holdings_us.csv",
    "data/holdings_kr.csv",
    "watchlist_us_growth.csv",
    "watchlist_kr_growth.csv",
    "watchlist_us.csv",
    "watchlist_kr.csv",
    "candidate_universe_us.csv",
    "candidate_universe_kr.csv",
]

REPORT_PATTERNS = [
    "v92_*.csv",
    "v91_*.csv",
    "operational_*.csv",
    "swing_candidates_*.csv",
]

SYMBOL_COLS = [
    "symbol", "ticker", "code", "종목코드", "종목", "stock_code",
    "Symbol", "Ticker", "Code"
]

NAME_COLS = [
    "name", "stock_name", "종목명", "company", "종목"
]

PRICE_COLS_TO_WRITE = [
    "current_price",
    "last_price",
    "현재가",
    "quote_fallback_price",
    "실시간현재가",
]

SOURCE_COLS_TO_WRITE = [
    "quote_source",
    "quote_source_label",
    "data_status",
    "price_data_status",
    "current_price_source",
]


def backup_file(path: Path):
    if path.exists() and path.is_file():
        dst = BACKUP_DIR / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


def write_csv_safe(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def clean_kr_symbol(value) -> str:
    s = str(value or "").strip()
    if not s or s.lower() in {"nan", "none", "null", "-"}:
        return ""
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    return ""


def clean_us_symbol(value) -> str:
    s = str(value or "").strip().upper()
    if not s or s.lower() in {"nan", "none", "null", "-"}:
        return ""
    s = "".join(ch for ch in s if ch.isalnum() or ch in {".", "-"})
    return s


def infer_market_from_file(path: Path) -> str:
    text = str(path).lower()
    if "_us" in text or "holdings_us" in text:
        return "us"
    if "_kr" in text or "holdings_kr" in text:
        return "kr"
    return ""


def row_symbol(row, market_hint: str = "") -> tuple[str, str]:
    vals = []
    for c in SYMBOL_COLS:
        if c in row.index:
            vals.append(row.get(c, ""))

    market_text = ""
    for c in ["market", "시장"]:
        if c in row.index:
            market_text += " " + str(row.get(c, ""))

    market = market_hint
    if not market:
        if "미국" in market_text or "US" in market_text.upper():
            market = "us"
        elif "한국" in market_text or "KR" in market_text.upper():
            market = "kr"

    for v in vals:
        if market == "kr":
            s = clean_kr_symbol(v)
            if s:
                return market, s
        elif market == "us":
            s = clean_us_symbol(v)
            if s and not s.isdigit():
                return market, s
        else:
            kr = clean_kr_symbol(v)
            us = clean_us_symbol(v)
            if kr:
                return "kr", kr
            if us and not us.isdigit():
                return "us", us

    return market or "", ""


def collect_symbols():
    kr = set()
    us = set()

    # daily_watch_selection 우선
    sel = ROOT / "daily_watch_selection.json"
    if sel.exists():
        try:
            data = json.loads(sel.read_text(encoding="utf-8-sig"))
            for s in data.get("KR", {}).get("symbols", []):
                c = clean_kr_symbol(s)
                if c:
                    kr.add(c)
            for s in data.get("US", {}).get("symbols", []):
                c = clean_us_symbol(s)
                if c:
                    us.add(c)
        except Exception:
            pass

    # 주요 CSV에서 종목 수집
    paths = [ROOT / f for f in TARGET_FILES]
    for pat in REPORT_PATTERNS:
        paths.extend(REPORT_DIR.glob(pat))

    for path in paths:
        if not path.exists() or path.suffix.lower() != ".csv":
            continue

        df = read_csv_safe(path)
        if df.empty:
            continue

        hint = infer_market_from_file(path)

        for _, row in df.iterrows():
            m, s = row_symbol(row, hint)
            if m == "kr" and s:
                kr.add(s)
            elif m == "us" and s:
                us.add(s)

    return sorted(kr), sorted(us)


def fmt_price(price: float, market: str) -> str:
    try:
        p = float(price)
    except Exception:
        return ""
    if np.isnan(p) or p <= 0:
        return ""
    if market == "kr":
        return f"{int(round(p)):,}원"
    return f"${p:,.2f}"


def fetch_quotes(kr_symbols, us_symbols):
    print("=== IMPORT APP ===")
    import app
    print("app import OK")

    rows = []

    print("\n=== FETCH KR QUOTES ===")
    for sym in kr_symbols:
        try:
            r = app.fetch_kis_domestic_price_v9960(sym)
            ok = bool(r.get("ok"))
            price = r.get("last_price")
            print("KR", sym, "OK" if ok else "FAIL", price, r.get("error", ""))

            if ok and price:
                rows.append({
                    "market": "kr",
                    "symbol": sym,
                    "ticker": sym,
                    "current_price": price,
                    "last_price": price,
                    "현재가": fmt_price(price, "kr"),
                    "quote_source": r.get("source", "KIS Open API"),
                    "quote_source_label": "KIS 현재가",
                    "data_status": "API 현재가 수신",
                    "price_data_status": "success",
                    "last_time": r.get("last_time", NOW),
                    "updated_at": NOW,
                })
        except Exception as e:
            print("KR", sym, "ERROR", type(e).__name__, str(e)[:120])

    print("\n=== FETCH US QUOTES ===")
    finnhub_key = os.environ.get("FINNHUB_API_KEY", "")

    for sym in us_symbols:
        done = False

        try:
            if hasattr(app, "fetch_kis_overseas_price_v9962"):
                r = app.fetch_kis_overseas_price_v9962(sym)
                ok = bool(r.get("ok"))
                price = r.get("last_price")
                print("US-KIS", sym, "OK" if ok else "FAIL", price, r.get("error", ""))

                if ok and price:
                    rows.append({
                        "market": "us",
                        "symbol": sym,
                        "ticker": sym,
                        "current_price": price,
                        "last_price": price,
                        "현재가": fmt_price(price, "us"),
                        "quote_source": r.get("source", "KIS Overseas Open API"),
                        "quote_source_label": "KIS 해외 현재가",
                        "data_status": "API 현재가 수신",
                        "price_data_status": "success",
                        "last_time": r.get("last_time", NOW),
                        "updated_at": NOW,
                    })
                    done = True
        except Exception as e:
            print("US-KIS", sym, "ERROR", type(e).__name__, str(e)[:120])

        if done:
            continue

        try:
            if hasattr(app, "fetch_finnhub_quote_snapshot") and finnhub_key:
                r = app.fetch_finnhub_quote_snapshot(sym, finnhub_key)
                price = r.get("last_price")
                print("US-FINNHUB", sym, "OK" if price else "FAIL", price, r.get("error", ""))

                if price:
                    rows.append({
                        "market": "us",
                        "symbol": sym,
                        "ticker": sym,
                        "current_price": price,
                        "last_price": price,
                        "현재가": fmt_price(price, "us"),
                        "quote_source": "Finnhub",
                        "quote_source_label": "Finnhub 보조 수신",
                        "data_status": "API 현재가 수신",
                        "price_data_status": "success",
                        "last_time": NOW,
                        "updated_at": NOW,
                    })
        except Exception as e:
            print("US-FINNHUB", sym, "ERROR", type(e).__name__, str(e)[:120])

    return pd.DataFrame(rows)


def build_price_lookup(qdf: pd.DataFrame):
    lookup = {}
    if qdf.empty:
        return lookup

    for _, r in qdf.iterrows():
        market = str(r.get("market", "")).strip()
        symbol = str(r.get("symbol", "")).strip()
        if market and symbol:
            lookup[(market, symbol)] = r.to_dict()
    return lookup


def update_csv_with_quotes(path: Path, lookup: dict):
    df = read_csv_safe(path)
    if df.empty:
        return 0

    hint = infer_market_from_file(path)
    changed = 0

    for col in PRICE_COLS_TO_WRITE + SOURCE_COLS_TO_WRITE:
        if col not in df.columns:
            df[col] = ""

    for idx, row in df.iterrows():
        m, s = row_symbol(row, hint)
        if not m or not s:
            continue

        hit = lookup.get((m, s))
        if not hit:
            continue

        price = hit.get("current_price", "")
        price_text = hit.get("현재가", "")

        df.at[idx, "current_price"] = price
        df.at[idx, "last_price"] = price
        df.at[idx, "quote_fallback_price"] = price
        df.at[idx, "실시간현재가"] = price_text or price
        df.at[idx, "현재가"] = price_text or price

        df.at[idx, "quote_source"] = hit.get("quote_source", "")
        df.at[idx, "quote_source_label"] = hit.get("quote_source_label", "")
        df.at[idx, "current_price_source"] = hit.get("quote_source_label", "")
        df.at[idx, "data_status"] = hit.get("data_status", "")
        df.at[idx, "price_data_status"] = hit.get("price_data_status", "")

        changed += 1

    if changed:
        backup_file(path)
        write_csv_safe(df, path)

    return changed


def alias_news_files():
    # 뉴스 파일명 fallback 확장
    for m in ["kr", "us"]:
        src = REPORT_DIR / f"v92_news_summary_{m}.csv"
        if not src.exists():
            continue

        aliases = [
            REPORT_DIR / f"v92_news_cards_{m}.csv",
            REPORT_DIR / f"v91_news_summary_{m}.csv",
            REPORT_DIR / f"v91_news_cards_{m}.csv",
            REPORT_DIR / f"operational_news_narrative_{m}.csv",
            REPORT_DIR / f"news_summary_{m}.csv",
            REPORT_DIR / f"news_cards_{m}.csv",
        ]

        for dst in aliases:
            backup_file(dst)
            shutil.copy2(src, dst)


def main():
    print("=== COLLECT SYMBOLS ===")
    kr, us = collect_symbols()
    print("KR count:", len(kr), kr[:20])
    print("US count:", len(us), us[:20])

    qdf = fetch_quotes(kr, us)

    quote_cache = DATA_DIR / "mone_live_quote_cache.csv"
    intraday_cache = DATA_DIR / "intraday_realtime_snapshot.csv"
    report_cache = REPORT_DIR / "v92_intraday_realtime_snapshot.csv"

    write_csv_safe(qdf, quote_cache)
    write_csv_safe(qdf, intraday_cache)
    write_csv_safe(qdf, report_cache)

    lookup = build_price_lookup(qdf)

    changed_files = {}

    paths = [ROOT / f for f in TARGET_FILES]
    for pat in REPORT_PATTERNS:
        paths.extend(REPORT_DIR.glob(pat))

    for path in sorted(set(paths)):
        if not path.exists() or path.suffix.lower() != ".csv":
            continue
        changed = update_csv_with_quotes(path, lookup)
        if changed:
            changed_files[str(path.relative_to(ROOT))] = changed

    alias_news_files()

    result = {
        "status": "OK",
        "updated_at": NOW,
        "backup_dir": str(BACKUP_DIR),
        "kr_symbols": len(kr),
        "us_symbols": len(us),
        "quote_rows": len(qdf),
        "quote_cache": str(quote_cache),
        "changed_files": changed_files,
        "news_alias_refreshed": True,
    }

    out = ROOT / "MONE_REFRESH_QUOTES_AND_BIND_RESULT.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8-sig")

    print("\n=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\nDONE")


if __name__ == "__main__":
    main()
