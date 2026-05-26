from __future__ import annotations

from pathlib import Path
from datetime import datetime
import json
import shutil
import re

import pandas as pd

ROOT = Path.cwd()
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
BACKUP_DIR = ROOT / "backups" / f"mone_final_live_data_fix_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

PRICE_COLS = [
    "current_price", "현재가", "last_price", "실시간현재가", "current_price_at_prediction",
    "close", "Close", "price", "가격", "직전가"
]
SYMBOL_COLS = ["symbol", "ticker", "code", "종목코드", "종목", "Symbol", "Ticker"]
NAME_COLS = ["name", "stock_name", "종목명", "company", "종목"]

CORE_BACKUP_FILES = [
    "app.py",
    "daily_watch_selection.json",
    "holdings_us.csv",
    "data/holdings_us.csv",
    "data/holdings_kr.csv",
    "reports/v92_symbol_snapshot_kr.csv",
    "reports/v92_symbol_snapshot_us.csv",
    "reports/v92_news_summary_kr.csv",
    "reports/v92_news_summary_us.csv",
    "reports/v91_news_summary_kr.csv",
    "reports/v91_news_summary_us.csv",
    "reports/operational_news_narrative_kr.csv",
    "reports/operational_news_narrative_us.csv",
]


def backup_file(rel: str) -> None:
    src = ROOT / rel
    if src.exists() and src.is_file():
        dst = BACKUP_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            return df.fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def clean_conflict_markers() -> int:
    cleaned = 0
    targets = list(ROOT.rglob("*.csv")) + list(ROOT.rglob("*.json"))
    for path in targets:
        if any(part in {".git", "__pycache__"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
        if "<<<<<<<" not in text and "=======" not in text and ">>>>>>>" not in text:
            continue
        rel = path.relative_to(ROOT)
        backup_file(str(rel))
        lines = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("<<<<<<<") or stripped.startswith("=======") or stripped.startswith(">>>>>>>"):
                continue
            lines.append(line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        cleaned += 1
    return cleaned


def normalize_symbol(x: object) -> str:
    s = str(x or "").strip().upper()
    if not s or s in {"NAN", "NONE", "-"}:
        return ""
    s = re.sub(r"\.KS$|\.KQ$", "", s)
    # 한국 종목코드는 6자리 유지
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


def first_col(df: pd.DataFrame, cols: list[str]) -> str | None:
    for c in cols:
        if c in df.columns:
            return c
    return None


def get_price_map(market: str) -> dict[str, dict[str, str]]:
    """로컬 파일에서 현재가 fallback map을 만든다."""
    files: list[Path] = []
    if market == "kr":
        files += [DATA_DIR / "holdings_kr.csv"]
        files += [REPORT_DIR / "v92_symbol_snapshot_kr.csv", REPORT_DIR / "v91_symbol_snapshot_kr.csv"]
        files += [ROOT / "candidate_universe_kr.csv", ROOT / "watchlist_kr_growth.csv", ROOT / "watchlist_kr.csv"]
    else:
        files += [ROOT / "holdings_us.csv", DATA_DIR / "holdings_us.csv"]
        files += [REPORT_DIR / "v92_symbol_snapshot_us.csv", REPORT_DIR / "v91_symbol_snapshot_us.csv"]
        files += [ROOT / "candidate_universe_us.csv", ROOT / "watchlist_us_growth.csv", ROOT / "watchlist_us.csv"]

    # reports cards도 가격 후보로 사용
    suffix = "kr" if market == "kr" else "us"
    for prefix in ["action_cards", "pullback_cards", "flow_cards", "risk_cards", "company_integrated", "company_cards", "kpi_cards"]:
        files.append(REPORT_DIR / f"v92_{prefix}_{suffix}.csv")
        files.append(REPORT_DIR / f"v91_{prefix}_{suffix}.csv")

    out: dict[str, dict[str, str]] = {}
    for path in files:
        df = read_csv(path)
        if df.empty:
            continue
        sym_col = first_col(df, SYMBOL_COLS)
        if not sym_col:
            continue
        price_col = first_col(df, PRICE_COLS)
        name_col = first_col(df, NAME_COLS)
        for _, row in df.iterrows():
            sym = normalize_symbol(row.get(sym_col, ""))
            if not sym:
                continue
            price = ""
            if price_col:
                price = str(row.get(price_col, "") or "").strip()
            if not price or price in {"-", "확인 필요", "현재가 미수신", "nan", "NaN"}:
                # 다른 가격 컬럼도 뒤져본다.
                for c in PRICE_COLS:
                    if c in df.columns:
                        v = str(row.get(c, "") or "").strip()
                        if v and v not in {"-", "확인 필요", "현재가 미수신", "nan", "NaN"}:
                            price = v
                            break
            name = str(row.get(name_col, "") or "").strip() if name_col else ""
            if sym not in out:
                out[sym] = {"price": "", "name": name, "source": path.name}
            if name and not out[sym].get("name"):
                out[sym]["name"] = name
            if price and not out[sym].get("price"):
                out[sym]["price"] = price
                out[sym]["source"] = path.name
    return out


def fill_symbol_snapshot_prices(market: str) -> int:
    suffix = "kr" if market == "kr" else "us"
    price_map = get_price_map(market)
    changed = 0
    for version in ["v92", "v91"]:
        path = REPORT_DIR / f"{version}_symbol_snapshot_{suffix}.csv"
        df = read_csv(path)
        if df.empty:
            continue
        backup_file(str(path.relative_to(ROOT)))
        sym_col = first_col(df, ["종목코드", "symbol", "ticker", "code"])
        if not sym_col:
            continue
        for col in ["현재가", "current_price", "last_price", "가격출처"]:
            if col not in df.columns:
                df[col] = ""
        for i, row in df.iterrows():
            sym = normalize_symbol(row.get(sym_col, ""))
            if not sym or sym not in price_map:
                continue
            price = price_map[sym].get("price", "")
            if price and str(df.at[i, "현재가"]).strip() in {"", "-", "확인 필요", "현재가 미수신", "nan", "NaN"}:
                df.at[i, "현재가"] = price
                df.at[i, "current_price"] = price
                df.at[i, "last_price"] = price
                df.at[i, "가격출처"] = f"local fallback: {price_map[sym].get('source','')}"
                changed += 1
        write_csv(df, path)
    return changed


def rebuild_news_summary(market: str) -> int:
    suffix = "kr" if market == "kr" else "us"
    market_name = "한국주식" if market == "kr" else "미국주식"
    src_candidates = [
        REPORT_DIR / f"v92_news_cards_{suffix}.csv",
        REPORT_DIR / f"v91_news_summary_{suffix}.csv",
        REPORT_DIR / f"operational_news_narrative_{suffix}.csv",
    ]
    rows = []
    for path in src_candidates:
        df = read_csv(path)
        if df.empty:
            continue
        # 충돌/빈 제목 제거
        title_col = first_col(df, ["제목", "title", "headline"])
        summary_col = first_col(df, ["요약", "3줄요약", "summary", "간략 번역"])
        source_col = first_col(df, ["출처", "source", "publisher"])
        url_col = first_col(df, ["URL", "url", "link"])
        time_col = first_col(df, ["게시시간", "time", "published", "date"])
        if not title_col:
            continue
        for _, r in df.iterrows():
            title = str(r.get(title_col, "") or "").strip()
            if not title or title.startswith("<<<<<<<") or title.startswith(">>>>>>>") or title == "=":
                continue
            rows.append({
                "시장": market_name,
                "제목": title,
                "3줄요약": str(r.get(summary_col, title) or title).strip() if summary_col else title,
                "출처": str(r.get(source_col, "") or "").strip() if source_col else "",
                "URL": str(r.get(url_col, "") or "").strip() if url_col else "",
                "게시시간": str(r.get(time_col, "") or "").strip() if time_col else "",
                "다음행동": "뉴스만으로 매수하지 말고 가격·수급·재무를 함께 확인",
                "종목코드": "",
                "종목명": "종목",
            })
    # 중복 제거, 최신/상위 20개
    seen = set()
    unique = []
    for r in rows:
        key = r["제목"][:120]
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    if not unique:
        return 0
    out = pd.DataFrame(unique[:20])
    for dest in [
        REPORT_DIR / f"v92_news_summary_{suffix}.csv",
        REPORT_DIR / f"v91_news_summary_{suffix}.csv",
        REPORT_DIR / f"operational_news_narrative_{suffix}.csv",
    ]:
        backup_file(str(dest.relative_to(ROOT)))
        write_csv(out, dest)
    return len(out)


def choose_daily_watch_from_holdings() -> dict:
    """선택 종목을 보유종목 우선으로 저장한다. 부족분은 watchlist로 채운다."""
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def symbols_from_file(path: Path, market: str) -> list[str]:
        df = read_csv(path)
        if df.empty:
            return []
        sym_col = first_col(df, ["symbol", "ticker", "code", "종목코드"])
        if not sym_col:
            return []
        syms = []
        for v in df[sym_col].tolist():
            s = normalize_symbol(v)
            if s and s not in syms:
                syms.append(s)
        return syms

    kr = symbols_from_file(DATA_DIR / "holdings_kr.csv", "kr")
    us = symbols_from_file(DATA_DIR / "holdings_us.csv", "us") or symbols_from_file(ROOT / "holdings_us.csv", "us")
    kr += [x for x in symbols_from_file(ROOT / "watchlist_kr_growth.csv", "kr") if x not in kr]
    us += [x for x in symbols_from_file(ROOT / "watchlist_us_growth.csv", "us") if x not in us]

    data = {
        "KR": {"date": today, "symbols": kr[:5], "updated_at": now + " KST", "source": "MONE_FINAL_LIVE_DATA_FIX"},
        "US": {"date": today, "symbols": us[:5], "updated_at": now + " KST", "source": "MONE_FINAL_LIVE_DATA_FIX"},
    }
    backup_file("daily_watch_selection.json")
    (ROOT / "daily_watch_selection.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def patch_app_py() -> bool:
    app = ROOT / "app.py"
    if not app.exists():
        return False
    s = app.read_text(encoding="utf-8")
    backup_file("app.py")

    start_marker = "# =========================\n# MONE LIVE PRICE NEWS SELECTION FINAL PATCH"
    end_marker = "# =========================\n# MONE FINAL ENTRYPOINT AFTER ALL OVERRIDES"

    if start_marker in s and end_marker in s:
        before = s.split(start_marker)[0].rstrip()
        after = end_marker + s.split(end_marker, 1)[1]
        s = before + "\n\n" + after

    if end_marker not in s:
        # final entrypoint marker가 없으면 맨 아래에 붙인다.
        end_marker = "if __name__ == \"__main__\":"
        if end_marker not in s:
            raise SystemExit("app.py entrypoint marker not found")

    patch = r'''
# =========================
# MONE LIVE PRICE NEWS SELECTION FINAL PATCH
# =========================
def _mone_live_norm_symbol(x: Any) -> str:
    s = str(x or "").strip().upper()
    if not s or s in {"NAN", "NONE", "-"}:
        return ""
    s = re.sub(r"\.KS$|\.KQ$", "", s)
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


def _mone_live_parse_price(v: Any) -> float:
    try:
        text = str(v or "").strip()
        if not text or text in {"-", "확인 필요", "현재가 미수신", "nan", "NaN", "None"}:
            return np.nan
        text = text.replace("$", "").replace("원", "").replace(",", "").replace("%", "").strip()
        return float(text)
    except Exception:
        return np.nan


def _mone_live_read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return pd.DataFrame()
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
            except Exception:
                continue
    except Exception:
        pass
    return pd.DataFrame()


def _mone_live_local_price_lookup(symbol: str, market: str = "") -> dict[str, Any]:
    sym = _mone_live_norm_symbol(symbol)
    m = "us" if str(market).lower() in {"us", "usa"} or "미국" in str(market) or "미장" in str(market) else "kr"
    suffix = "us" if m == "us" else "kr"
    files = []
    if m == "us":
        files += [Path("data/holdings_us.csv"), Path("holdings_us.csv")]
    else:
        files += [Path("data/holdings_kr.csv")]
    files += [
        REPORT_DIR / f"v92_symbol_snapshot_{suffix}.csv",
        REPORT_DIR / f"v91_symbol_snapshot_{suffix}.csv",
        REPORT_DIR / f"v92_action_cards_{suffix}.csv",
        REPORT_DIR / f"v92_pullback_cards_{suffix}.csv",
        REPORT_DIR / f"v92_flow_cards_{suffix}.csv",
        REPORT_DIR / f"v92_risk_cards_{suffix}.csv",
        REPORT_DIR / f"v92_company_integrated_{suffix}.csv",
        Path(f"candidate_universe_{suffix}.csv"),
        Path(f"watchlist_{suffix}_growth.csv"),
        Path(f"watchlist_{suffix}.csv"),
    ]
    sym_cols = ["symbol", "ticker", "code", "종목코드", "종목"]
    price_cols = ["current_price", "현재가", "last_price", "실시간현재가", "current_price_at_prediction", "close", "Close", "price", "가격"]
    name_cols = ["name", "stock_name", "종목명", "company", "종목"]
    for path in files:
        df = _mone_live_read_csv(path)
        if df.empty:
            continue
        sc = next((c for c in sym_cols if c in df.columns), None)
        if not sc:
            continue
        for _, row in df.iterrows():
            if _mone_live_norm_symbol(row.get(sc, "")) != sym:
                continue
            price = np.nan
            raw_price = ""
            for pc in price_cols:
                if pc in df.columns:
                    raw_price = str(row.get(pc, "") or "").strip()
                    price = _mone_live_parse_price(raw_price)
                    if not np.isnan(price) and price > 0:
                        break
            name = ""
            for nc in name_cols:
                if nc in df.columns:
                    name = str(row.get(nc, "") or "").strip()
                    if name:
                        break
            if not np.isnan(price) and price > 0:
                return {
                    "symbol": sym,
                    "last_price": price,
                    "current_price": price,
                    "prev_close": np.nan,
                    "change_pct": np.nan,
                    "last_time": "저장값",
                    "source": f"local:{path.name}",
                    "quote_source_label": f"저장값:{path.name}",
                    "data_status": "저장된 현재가 사용",
                    "ok": True,
                    "name": name,
                    "raw_price": raw_price,
                }
    return {"symbol": sym, "last_price": np.nan, "change_pct": np.nan, "ok": False, "source": "local_missing"}


try:
    _MONE_ORIG_fetch_watch_snapshot = fetch_watch_snapshot
except Exception:
    _MONE_ORIG_fetch_watch_snapshot = None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_watch_snapshot(symbol: str, market: str) -> dict[str, Any]:  # type: ignore[override]
    if _MONE_ORIG_fetch_watch_snapshot is not None:
        try:
            snap = _MONE_ORIG_fetch_watch_snapshot(symbol, market) or {}
            lp = _mone_live_parse_price(snap.get("last_price", snap.get("current_price", "")))
            if not np.isnan(lp) and lp > 0:
                snap["last_price"] = lp
                snap["current_price"] = lp
                snap["ok"] = True
                return snap
        except Exception:
            pass
    return _mone_live_local_price_lookup(symbol, market)


try:
    _MONE_ORIG_fetch_extended_snapshot = fetch_extended_snapshot
except Exception:
    _MONE_ORIG_fetch_extended_snapshot = None


@st.cache_data(ttl=60, show_spinner=False)
def fetch_extended_snapshot(ticker: str) -> dict[str, Any]:  # type: ignore[override]
    if _MONE_ORIG_fetch_extended_snapshot is not None:
        try:
            snap = _MONE_ORIG_fetch_extended_snapshot(ticker) or {}
            lp = _mone_live_parse_price(snap.get("last_price", snap.get("current_price", "")))
            if not np.isnan(lp) and lp > 0:
                snap["last_price"] = lp
                snap["current_price"] = lp
                snap["ok"] = True
                return snap
        except Exception:
            pass
    return _mone_live_local_price_lookup(ticker, "미국주식")


# 뉴스 summary 로더가 다른 파일명을 보더라도 v92 뉴스 요약으로 fallback
try:
    _MONE_ORIG_v92_candidates_for_news = _mone_abs_candidates if "_mone_abs_candidates" in globals() else None
except Exception:
    _MONE_ORIG_v92_candidates_for_news = None


def _mone_live_news_df(slug: str) -> pd.DataFrame:
    m = "us" if "us" in str(slug).lower() or "미국" in str(slug) or "미장" in str(slug) else "kr"
    for name in [f"v92_news_summary_{m}.csv", f"v92_news_cards_{m}.csv", f"v91_news_summary_{m}.csv", f"operational_news_narrative_{m}.csv"]:
        df = _mone_live_read_csv(REPORT_DIR / name)
        if not df.empty:
            # 충돌 행 제거
            title_col = next((c for c in ["제목", "title", "headline"] if c in df.columns), None)
            if title_col:
                df = df[~df[title_col].astype(str).str.startswith(("<<<<<<<", ">>>>>>>", "======="), na=False)].copy()
            if not df.empty:
                df["_source_file"] = name
                return df
    return pd.DataFrame()
'''

    s = s.replace(end_marker, patch.rstrip() + "\n\n" + end_marker)
    app.write_text(s, encoding="utf-8")
    return True


def diagnostic() -> pd.DataFrame:
    files = [
        "daily_watch_selection.json",
        "holdings_us.csv", "data/holdings_us.csv", "data/holdings_kr.csv",
        "reports/v92_symbol_snapshot_kr.csv", "reports/v92_symbol_snapshot_us.csv",
        "reports/v92_news_summary_kr.csv", "reports/v92_news_summary_us.csv",
        "reports/v91_news_summary_kr.csv", "reports/v91_news_summary_us.csv",
        "reports/operational_news_narrative_kr.csv", "reports/operational_news_narrative_us.csv",
    ]
    rows = []
    for rel in files:
        path = ROOT / rel
        info = {"file": rel, "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0, "rows": ""}
        if path.exists() and path.suffix.lower() == ".csv":
            df = read_csv(path)
            info["rows"] = len(df)
            info["cols"] = len(df.columns)
        rows.append(info)
    return pd.DataFrame(rows)


def main() -> None:
    for rel in CORE_BACKUP_FILES:
        backup_file(rel)

    cleaned = clean_conflict_markers()
    kr_prices = fill_symbol_snapshot_prices("kr")
    us_prices = fill_symbol_snapshot_prices("us")
    kr_news = rebuild_news_summary("kr")
    us_news = rebuild_news_summary("us")
    selection = choose_daily_watch_from_holdings()
    app_patched = patch_app_py()

    diag = diagnostic()
    diag_path = ROOT / "MONE_FINAL_LIVE_DATA_FIX_DIAGNOSTIC.csv"
    write_csv(diag, diag_path)

    result = {
        "status": "OK",
        "backup_dir": str(BACKUP_DIR),
        "conflict_marker_files_cleaned": cleaned,
        "filled_symbol_snapshot_prices": {"kr": kr_prices, "us": us_prices},
        "rebuilt_news_summary_rows": {"kr": kr_news, "us": us_news},
        "daily_watch_selection": selection,
        "app_patched": app_patched,
        "diagnostic_csv": str(diag_path),
    }
    (ROOT / "MONE_FINAL_LIVE_DATA_FIX_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== MONE FINAL LIVE DATA FIX ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n=== DIAGNOSTIC ===")
    print(diag.to_string(index=False))


if __name__ == "__main__":
    main()
