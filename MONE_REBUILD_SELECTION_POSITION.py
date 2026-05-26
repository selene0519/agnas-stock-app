from pathlib import Path
from datetime import datetime
import json
import shutil
import pandas as pd
import numpy as np

ROOT = Path(".").resolve()
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups" / f"mone_rebuild_snapshot_position_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")


def backup(path: Path):
    if path.exists():
        dst = BACKUP_DIR / path.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dst)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    backup(path)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def clean_kr(v):
    s = str(v or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    return ""


def clean_us(v):
    s = str(v or "").strip().upper()
    s = "".join(ch for ch in s if ch.isalnum() or ch in [".", "-"])
    if s and not s.isdigit():
        return s
    return ""


def parse_price(v):
    try:
        s = str(v or "").strip()
        if not s or s.lower() in ["nan", "none", "null"]:
            return np.nan
        for token in ["₩", "원", "$", "USD", "KRW", ",", " "]:
            s = s.replace(token, "")
        if s in ["-", "확인필요", "확인 필요", "현재가미수신", "현재가 미수신"]:
            return np.nan
        return float(s)
    except Exception:
        return np.nan


def fmt_price(v, market):
    n = parse_price(v)
    if np.isnan(n) or n <= 0:
        return "현재가 없음"
    if market == "kr":
        return f"₩{n:,.0f}"
    return f"${n:,.2f}"


def pick_first(row, cols, default=""):
    for c in cols:
        if c in row.index:
            v = str(row.get(c, "") or "").strip()
            if v and v.lower() not in ["nan", "none", "null"]:
                return v
    return default


def detect_col(df, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return df.columns[0] if len(df.columns) else None


def load_watchlist(market):
    if market == "kr":
        path = ROOT / "watchlist_kr_growth.csv"
        df = read_csv(path)
        sym_col = detect_col(df, ["symbol", "code", "ticker", "종목코드", "stock_code", "종목"])
        name_col = detect_col(df, ["name", "stock_name", "종목명", "company", "종목"])
        rows = []
        seen = set()
        for _, r in df.iterrows():
            sym = clean_kr(r.get(sym_col, ""))
            if not sym or sym in seen:
                continue
            seen.add(sym)
            name = pick_first(r, [name_col, "종목명", "name", "stock_name", "company"], sym)
            rows.append({"symbol": sym, "ticker": sym, "code": sym, "종목코드": sym, "name": name, "종목명": name})
        return pd.DataFrame(rows)

    path = ROOT / "watchlist_us_growth.csv"
    df = read_csv(path)
    sym_col = detect_col(df, ["ticker", "symbol", "code", "종목코드", "stock_code", "종목"])
    name_col = detect_col(df, ["name", "stock_name", "종목명", "company", "종목"])
    rows = []
    seen = set()
    for _, r in df.iterrows():
        sym = clean_us(r.get(sym_col, ""))
        if not sym or sym in seen:
            continue
        seen.add(sym)
        name = pick_first(r, [name_col, "name", "stock_name", "종목명", "company"], sym)
        rows.append({"symbol": sym, "ticker": sym, "code": sym, "종목코드": sym, "name": name, "종목명": name})
    return pd.DataFrame(rows)


def load_holdings(market):
    if market == "kr":
        return read_csv(ROOT / "data" / "holdings_kr.csv")
    df = read_csv(ROOT / "data" / "holdings_us.csv")
    if df.empty:
        df = read_csv(ROOT / "holdings_us.csv")
    return df


def build_quote_lookup():
    lookup = {}

    quote_files = [
        DATA_DIR / "mone_live_quote_cache.csv",
        DATA_DIR / "intraday_realtime_snapshot.csv",
        REPORT_DIR / "v92_intraday_realtime_snapshot.csv",
        REPORT_DIR / "v92_symbol_snapshot_kr.csv",
        REPORT_DIR / "v92_symbol_snapshot_us.csv",
        ROOT / "data" / "holdings_kr.csv",
        ROOT / "data" / "holdings_us.csv",
        ROOT / "holdings_us.csv",
    ]

    for path in quote_files:
        df = read_csv(path)
        if df.empty:
            continue

        hint = ""
        ptxt = str(path).lower()
        if "_kr" in ptxt or "holdings_kr" in ptxt:
            hint = "kr"
        elif "_us" in ptxt or "holdings_us" in ptxt:
            hint = "us"

        for _, r in df.iterrows():
            market = hint
            market_text = " ".join(str(r.get(c, "")) for c in ["market", "시장"])
            if not market:
                if "미국" in market_text or "us" in market_text.lower():
                    market = "us"
                elif "한국" in market_text or "kr" in market_text.lower():
                    market = "kr"

            if market == "kr":
                sym = ""
                for c in ["symbol", "ticker", "code", "종목코드", "stock_code", "종목"]:
                    sym = clean_kr(r.get(c, ""))
                    if sym:
                        break
            else:
                sym = ""
                for c in ["symbol", "ticker", "code", "종목코드", "stock_code", "종목"]:
                    sym = clean_us(r.get(c, ""))
                    if sym:
                        break

            if not market or not sym:
                continue

            price = ""
            for c in ["current_price", "last_price", "현재가", "quote_fallback_price", "실시간현재가"]:
                if c in r.index:
                    n = parse_price(r.get(c, ""))
                    if not np.isnan(n) and n > 0:
                        price = n
                        break

            if price == "":
                continue

            last_time = pick_first(r, ["last_time", "quote_time", "price_time", "updated_at", "갱신시각", "가격기준시각"], "")
            source = pick_first(r, ["quote_source_label", "quote_source", "current_price_source", "source", "가격출처"], "")

            lookup[(market, sym)] = {
                "price": price,
                "price_text": fmt_price(price, market),
                "last_time": last_time or NOW,
                "source": source or "저장/API 현재가",
            }

    return lookup


def make_snapshot(market):
    wl = load_watchlist(market)
    holdings = load_holdings(market)
    q = build_quote_lookup()

    rows = []
    market_name = "한국주식" if market == "kr" else "미국주식"

    for _, r in wl.iterrows():
        sym = clean_kr(r.get("symbol", "")) if market == "kr" else clean_us(r.get("symbol", ""))
        if not sym:
            continue

        hit = q.get((market, sym), {})
        price = hit.get("price", "")
        price_text = hit.get("price_text", "현재가 없음")
        last_time = hit.get("last_time", "")
        source = hit.get("source", "현재가 미수신")

        name = pick_first(r, ["종목명", "name", "stock_name", "company"], sym)

        rows.append({
            "symbol": sym,
            "ticker": sym,
            "code": sym,
            "종목코드": sym,
            "name": name,
            "종목명": name,
            "market": market_name,
            "시장": market_name,
            "current_price": price,
            "last_price": price,
            "현재가": price_text,
            "가격기준시각": last_time or "시각 확인 필요",
            "가격출처": f"{source} · {last_time or '시각 확인 필요'}",
            "quote_source_label": source,
            "data_status": "현재가 반영" if price != "" else "현재가 미수신",
            "price_data_status": "success" if price != "" else "missing",
            "기준가": pick_first(r, ["관찰 기준가", "기준가", "entry_price", "매수가"], "-"),
            "손절가": pick_first(r, ["손절가", "stop_loss", "stop"], "-"),
            "목표가": pick_first(r, ["목표가", "target_price", "tp1", "1차 목표가"], "-"),
            "다음행동": "현재가·기준가·손절가 확인 후 판단",
            "updated_at": NOW,
        })

    return pd.DataFrame(rows)


def make_position(market):
    df = load_holdings(market)
    q = build_quote_lookup()
    rows = []
    market_name = "한국주식" if market == "kr" else "미국주식"

    if df.empty:
        return pd.DataFrame()

    for _, r in df.iterrows():
        if market == "kr":
            sym = ""
            for c in ["symbol", "ticker", "code", "종목코드", "종목"]:
                sym = clean_kr(r.get(c, ""))
                if sym:
                    break
        else:
            sym = ""
            for c in ["symbol", "ticker", "code", "종목코드", "종목"]:
                sym = clean_us(r.get(c, ""))
                if sym:
                    break

        if not sym:
            continue

        hit = q.get((market, sym), {})
        price = hit.get("price", "")
        price_text = hit.get("price_text", "현재가 없음")
        last_time = hit.get("last_time", "")
        source = hit.get("source", "현재가 미수신")

        name = pick_first(r, ["종목명", "name", "stock_name", "company", "종목"], sym)
        avg = pick_first(r, ["avg_price", "평균단가", "매수가", "entry_price"], "")
        qty = pick_first(r, ["quantity", "shares", "보유수량", "수량"], "")

        avg_n = parse_price(avg)
        cur_n = parse_price(price)
        qty_n = parse_price(qty)

        pnl = ""
        pnl_rate = ""
        if not np.isnan(avg_n) and avg_n > 0 and not np.isnan(cur_n) and cur_n > 0:
            pnl_rate_num = (cur_n / avg_n - 1) * 100
            pnl_rate = f"{pnl_rate_num:+.2f}%"
            if not np.isnan(qty_n) and qty_n > 0:
                pnl_val = (cur_n - avg_n) * qty_n
                pnl = fmt_price(abs(pnl_val), market)
                pnl = ("+" if pnl_val >= 0 else "-") + pnl

        rows.append({
            "symbol": sym,
            "ticker": sym,
            "code": sym,
            "종목코드": sym,
            "name": name,
            "종목명": name,
            "market": market_name,
            "시장": market_name,
            "avg_price": avg,
            "평균단가": fmt_price(avg, market) if avg else "",
            "quantity": qty,
            "보유수량": qty,
            "current_price": price,
            "last_price": price,
            "현재가": price_text,
            "가격기준시각": last_time or "시각 확인 필요",
            "가격출처": f"{source} · {last_time or '시각 확인 필요'}",
            "quote_source_label": source,
            "수익률": pnl_rate,
            "평가손익": pnl,
            "data_status": "현재가 반영" if price != "" else "현재가 미수신",
            "price_data_status": "success" if price != "" else "missing",
            "다음행동": "보유 유지/축소/익절 여부는 손절가와 목표가 기준으로 확인",
            "updated_at": NOW,
        })

    return pd.DataFrame(rows)


def save_aliases(df, names):
    for name in names:
        write_csv(df, REPORT_DIR / name)


def update_daily_selection_from_snapshot(kr_df, us_df):
    data = {
        "KR": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": int(len(kr_df)),
            "symbols": kr_df["symbol"].astype(str).tolist() if "symbol" in kr_df.columns else [],
            "updated_at": NOW,
            "source": "watchlist_kr_growth.csv 전체 → v92_symbol_snapshot_kr.csv",
        },
        "US": {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "count": int(len(us_df)),
            "symbols": us_df["symbol"].astype(str).tolist() if "symbol" in us_df.columns else [],
            "updated_at": NOW,
            "source": "watchlist_us_growth.csv 전체 → v92_symbol_snapshot_us.csv",
        }
    }
    (ROOT / "daily_watch_selection.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8-sig")


def main():
    kr_snapshot = make_snapshot("kr")
    us_snapshot = make_snapshot("us")
    kr_position = make_position("kr")
    us_position = make_position("us")

    save_aliases(kr_snapshot, ["v92_symbol_snapshot_kr.csv", "v91_symbol_snapshot_kr.csv"])
    save_aliases(us_snapshot, ["v92_symbol_snapshot_us.csv", "v91_symbol_snapshot_us.csv"])

    save_aliases(kr_position, ["v92_position_cards_kr.csv", "v91_position_cards_kr.csv"])
    save_aliases(us_position, ["v92_position_cards_us.csv", "v91_position_cards_us.csv"])

    update_daily_selection_from_snapshot(kr_snapshot, us_snapshot)

    result = {
        "status": "OK",
        "updated_at": NOW,
        "backup_dir": str(BACKUP_DIR),
        "snapshot": {
            "kr_rows": int(len(kr_snapshot)),
            "us_rows": int(len(us_snapshot)),
            "kr_with_price": int((kr_snapshot["current_price"].astype(str).str.len() > 0).sum()) if not kr_snapshot.empty else 0,
            "us_with_price": int((us_snapshot["current_price"].astype(str).str.len() > 0).sum()) if not us_snapshot.empty else 0,
        },
        "position": {
            "kr_rows": int(len(kr_position)),
            "us_rows": int(len(us_position)),
            "kr_with_price": int((kr_position["current_price"].astype(str).str.len() > 0).sum()) if not kr_position.empty else 0,
            "us_with_price": int((us_position["current_price"].astype(str).str.len() > 0).sum()) if not us_position.empty else 0,
        },
        "files_written": [
            "reports/v92_symbol_snapshot_kr.csv",
            "reports/v92_symbol_snapshot_us.csv",
            "reports/v92_position_cards_kr.csv",
            "reports/v92_position_cards_us.csv",
            "daily_watch_selection.json",
        ],
    }

    out = ROOT / "MONE_REBUILD_SELECTION_POSITION_RESULT.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8-sig")

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
