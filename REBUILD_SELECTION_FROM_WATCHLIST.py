from pathlib import Path
from datetime import datetime
import json
import pandas as pd

ROOT = Path(".")
TODAY = "2026-05-26"

KR_FILE = ROOT / "watchlist_kr_growth.csv"
US_FILE = ROOT / "watchlist_us_growth.csv"
OUT_FILE = ROOT / "daily_watch_selection.json"

def read_csv(path: Path) -> pd.DataFrame:
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str).fillna("")
        except Exception:
            pass
    return pd.DataFrame()

def pick_symbol_column(df: pd.DataFrame, market: str):
    if df.empty:
        return None

    if market == "kr":
        candidates = [
            "symbol", "code", "ticker", "종목코드", "종목 코드",
            "stock_code", "종목"
        ]
    else:
        candidates = [
            "ticker", "symbol", "code", "종목코드", "stock_code", "종목"
        ]

    for c in candidates:
        if c in df.columns:
            return c

    # 컬럼명이 애매하면 첫 번째 컬럼 사용
    return df.columns[0]

def clean_symbols(values, market: str):
    out = []
    seen = set()

    for v in values:
        s = str(v).strip()

        if not s or s.lower() in ["nan", "none", "null"]:
            continue

        # 괄호/공백 정리
        s = s.replace(".0", "").strip()

        if market == "kr":
            # 한국 종목코드는 숫자 6자리 중심
            digits = "".join(ch for ch in s if ch.isdigit())
            if len(digits) >= 6:
                s = digits[:6]
            else:
                continue
        else:
            # 미국 티커는 영문/점/하이픈 허용
            s = s.upper()
            s = "".join(ch for ch in s if ch.isalnum() or ch in [".", "-"])
            if not s:
                continue

        if s not in seen:
            seen.add(s)
            out.append(s)

    return out

def get_symbols(path: Path, market: str):
    df = read_csv(path)
    if df.empty:
        return []

    col = pick_symbol_column(df, market)
    if col is None:
        return []

    return clean_symbols(df[col].tolist(), market)

kr_symbols = get_symbols(KR_FILE, "kr")
us_symbols = get_symbols(US_FILE, "us")

data = {
    "KR": {
        "date": TODAY,
        "symbols": kr_symbols,
        "count": len(kr_symbols),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "source": "watchlist_kr_growth.csv 전체 반영"
    },
    "US": {
        "date": TODAY,
        "symbols": us_symbols,
        "count": len(us_symbols),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S KST"),
        "source": "watchlist_us_growth.csv 전체 반영"
    }
}

OUT_FILE.write_text(
    json.dumps(data, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("DONE: daily_watch_selection.json regenerated from full watchlists")
print("KR count:", len(kr_symbols))
print("US count:", len(us_symbols))
print("Output:", OUT_FILE.resolve())
