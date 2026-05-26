from pathlib import Path
from datetime import datetime
import json
import shutil
import pandas as pd
import numpy as np

ROOT = Path(".").resolve()
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
BACKUP_DIR = ROOT / "backups" / f"mone_fix_kr_watchlist_mapping_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

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


def clean_kr_code(v):
    s = str(v or "").strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 6:
        return digits[:6]
    return ""


def norm_name(v):
    s = str(v or "").strip()
    for x in [" ", "\t", "\n", "\r", "(주)", "㈜"]:
        s = s.replace(x, "")
    return s.lower()


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


def fmt_kr_price(v):
    n = parse_price(v)
    if np.isnan(n) or n <= 0:
        return "현재가 없음"
    return f"₩{n:,.0f}"


def pick_first(row, cols, default=""):
    for c in cols:
        if c in row.index:
            v = str(row.get(c, "") or "").strip()
            if v and v.lower() not in ["nan", "none", "null", "-"]:
                return v
    return default


def find_any_kr_code_in_row(row):
    # 행 전체 컬럼에서 6자리 코드 탐색
    for c in row.index:
        code = clean_kr_code(row.get(c, ""))
        if code:
            return code
    return ""


def build_name_code_map():
    mapping = {}

    sources = [
        ROOT / "candidate_universe_kr.csv",
        ROOT / "watchlist_kr.csv",
        ROOT / "watchlist_kr_growth.csv",
        ROOT / "data" / "holdings_kr.csv",
        REPORT_DIR / "v92_symbol_snapshot_kr.csv",
        REPORT_DIR / "v91_symbol_snapshot_kr.csv",
        REPORT_DIR / "v92_company_integrated_kr.csv",
        REPORT_DIR / "v92_action_cards_kr.csv",
        REPORT_DIR / "v92_pullback_cards_kr.csv",
        REPORT_DIR / "v92_flow_cards_kr.csv",
        REPORT_DIR / "v92_risk_cards_kr.csv",
    ]

    name_cols = ["종목명", "name", "stock_name", "company", "종목"]
    code_cols = ["종목코드", "symbol", "ticker", "code", "stock_code"]

    for path in sources:
        df = read_csv(path)
        if df.empty:
            continue

        for _, r in df.iterrows():
            code = ""
            for c in code_cols:
                if c in df.columns:
                    code = clean_kr_code(r.get(c, ""))
                    if code:
                        break

            if not code:
                code = find_any_kr_code_in_row(r)

            if not code:
                continue

            for nc in name_cols:
                if nc in df.columns:
                    name = norm_name(r.get(nc, ""))
                    if name:
                        mapping[name] = code

    return mapping


def row_name(row):
    for c in ["종목명", "name", "stock_name", "company", "종목"]:
        if c in row.index:
            v = str(row.get(c, "") or "").strip()
            if v and v.lower() not in ["nan", "none", "null", "-"]:
                return v

    # 이름 컬럼이 애매하면 한글이 들어간 첫 컬럼값 사용
    for c in row.index:
        v = str(row.get(c, "") or "").strip()
        if any("가" <= ch <= "힣" for ch in v):
            return v

    return ""


def build_quote_lookup():
    lookup = {}

    files = [
        DATA_DIR / "mone_live_quote_cache.csv",
        DATA_DIR / "intraday_realtime_snapshot.csv",
        REPORT_DIR / "v92_intraday_realtime_snapshot.csv",
        REPORT_DIR / "v92_symbol_snapshot_kr.csv",
        ROOT / "data" / "holdings_kr.csv",
    ]

    for path in files:
        df = read_csv(path)
        if df.empty:
            continue

        for _, r in df.iterrows():
            code = ""
            for c in ["symbol", "ticker", "code", "종목코드", "종목"]:
                if c in df.columns:
                    code = clean_kr_code(r.get(c, ""))
                    if code:
                        break

            if not code:
                code = find_any_kr_code_in_row(r)

            if not code:
                continue

            price = ""
            for c in ["current_price", "last_price", "현재가", "quote_fallback_price", "실시간현재가"]:
                if c in df.columns:
                    n = parse_price(r.get(c, ""))
                    if not np.isnan(n) and n > 0:
                        price = n
                        break

            if price == "":
                continue

            last_time = pick_first(r, ["last_time", "quote_time", "price_time", "updated_at", "갱신시각", "가격기준시각"], "")
            source = pick_first(r, ["quote_source_label", "quote_source", "current_price_source", "source", "가격출처"], "")

            lookup[code] = {
                "price": price,
                "price_text": fmt_kr_price(price),
                "last_time": last_time or NOW,
                "source": source or "저장/API 현재가",
            }

    return lookup


def rebuild_kr_snapshot_full():
    wl = read_csv(ROOT / "watchlist_kr_growth.csv")
    name_code = build_name_code_map()
    quote = build_quote_lookup()

    rows = []
    seen = set()
    unresolved = []

    for _, r in wl.iterrows():
        code = find_any_kr_code_in_row(r)
        name = row_name(r)

        if not code and name:
            code = name_code.get(norm_name(name), "")

        if not code:
            unresolved.append(name or str(dict(r)))
            continue

        if code in seen:
            continue

        seen.add(code)

        if not name:
            name = code

        hit = quote.get(code, {})
        price = hit.get("price", "")
        price_text = hit.get("price_text", "현재가 없음")
        last_time = hit.get("last_time", "")
        source = hit.get("source", "현재가 미수신")

        rows.append({
            "symbol": code,
            "ticker": code,
            "code": code,
            "종목코드": code,
            "name": name,
            "종목명": name,
            "market": "한국주식",
            "시장": "한국주식",
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

    out = pd.DataFrame(rows)

    write_csv(out, REPORT_DIR / "v92_symbol_snapshot_kr.csv")
    write_csv(out, REPORT_DIR / "v91_symbol_snapshot_kr.csv")

    # daily_watch_selection도 KR만 갱신하고 US는 유지
    sel_path = ROOT / "daily_watch_selection.json"
    try:
        sel = json.loads(sel_path.read_text(encoding="utf-8-sig"))
    except Exception:
        sel = {}

    sel["KR"] = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "count": int(len(out)),
        "symbols": out["symbol"].astype(str).tolist() if "symbol" in out.columns else [],
        "updated_at": NOW,
        "source": "watchlist_kr_growth.csv 전체 + candidate_universe_kr 종목명 매핑",
    }

    sel_path.write_text(json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8-sig")

    unresolved_path = ROOT / "MONE_KR_WATCHLIST_UNRESOLVED.txt"
    unresolved_path.write_text("\n".join(unresolved), encoding="utf-8-sig")

    result = {
        "status": "OK",
        "updated_at": NOW,
        "kr_watchlist_rows": int(len(wl)),
        "kr_snapshot_rows": int(len(out)),
        "kr_with_price": int((out["current_price"].astype(str).str.len() > 0).sum()) if not out.empty else 0,
        "unresolved_count": len(unresolved),
        "backup_dir": str(BACKUP_DIR),
        "written": [
            "reports/v92_symbol_snapshot_kr.csv",
            "reports/v91_symbol_snapshot_kr.csv",
            "daily_watch_selection.json",
            "MONE_KR_WATCHLIST_UNRESOLVED.txt",
        ],
    }

    (ROOT / "MONE_FIX_KR_WATCHLIST_MAPPING_RESULT.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8-sig"
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    rebuild_kr_snapshot_full()
