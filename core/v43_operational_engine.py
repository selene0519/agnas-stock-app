"""v43 operational fixes for ARCFLOW/NEXORA.

This module is intentionally conservative: it never places orders. It only reads
local CSV/JSON files, optionally fetches public/news/price data when API keys are
available, and writes reports used by the Streamlit UI.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
REPORT_DIR = ROOT / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
(DATA_DIR / "news").mkdir(parents=True, exist_ok=True)

KR_NAME_FALLBACK = {
    "403870": "HPSP",
    "131970": "두산테스나",
    "222800": "심텍",
    "058470": "리노공업",
    "095340": "ISC",
    "017670": "SK텔레콤",
    "375500": "DL이앤씨",
    "000990": "DB하이텍",
    "006260": "LS",
    "012450": "한화에어로스페이스",
    "329180": "HD현대중공업",
    "032640": "LG유플러스",
    "005930": "삼성전자",
    "000660": "SK하이닉스",
}

US_NAME_FALLBACK = {
    "NVDA": "NVIDIA",
    "GOOGL": "Alphabet",
    "TSLA": "Tesla",
    "PLTR": "Palantir",
    "INTC": "Intel",
    "LITE": "Lumentum",
    "SNDK": "SanDisk",
    "CAT": "Caterpillar",
    "CRCL": "Circle",
    "NBIS": "Nebius",
    "SMCI": "Super Micro Computer",
    "COST": "Costco",
    "AMZN": "Amazon",
    "TSM": "TSMC",
    "NET": "Cloudflare",
    "RIOT": "Riot Platforms",
    "IWM": "Russell 2000 ETF",
    "XLE": "Energy ETF",
}


def market_slug(market: str) -> str:
    return "kr" if str(market) == "한국주식" else "us"


def market_label(market: str) -> str:
    return "한국주식" if market_slug(market) == "kr" else "미국주식"


def read_csv_safe(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        return pd.read_csv(path)
    except Exception:
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return pd.DataFrame()


def read_json_safe(path: Path) -> dict[str, Any]:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def load_dotenv_values() -> dict[str, str]:
    out: dict[str, str] = {}
    for p in [ROOT / ".env", ROOT / ".env.local"]:
        if not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip('"').strip("'")
        except Exception:
            continue
    return out


def get_secret(name: str) -> str:
    return str(os.environ.get(name) or load_dotenv_values().get(name) or "").strip()


def to_num(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if not s or s in {"-", "nan", "NaN", "None"}:
            return default
        s = re.sub(r"[^0-9.\-]", "", s)
        return float(s) if s not in {"", "-", "."} else default
    except Exception:
        return default


def money(value: Any, market: str) -> str:
    v = to_num(value)
    if math.isnan(v) or v <= 0:
        return "-"
    if market_slug(market) == "kr":
        return f"{v:,.0f}원"
    return f"${v:,.2f}"


def qty_text(value: Any, market: str) -> str:
    v = to_num(value, 0.0)
    if market_slug(market) == "us":
        return f"{v:,.4g}주" if abs(v - int(v)) > 1e-8 else f"{int(v):,}주"
    return f"{int(math.floor(v)):,}주"


def first(row: Any, cols: Iterable[str], default: Any = "-") -> Any:
    for c in cols:
        try:
            if c in row.index:
                val = row.get(c)
                if pd.notna(val) and str(val).strip() not in {"", "-", "nan", "None"}:
                    return val
        except Exception:
            continue
    return default


def discover_symbol_names(market: str) -> dict[str, str]:
    slug = market_slug(market)
    fallback = KR_NAME_FALLBACK if slug == "kr" else US_NAME_FALLBACK
    mapping: dict[str, str] = {k.upper(): v for k, v in fallback.items()}
    patterns = [
        "*.csv", "portfolio/*.csv", "market/*.csv", "news/*.csv",
    ]
    for base in [REPORT_DIR, DATA_DIR, ROOT]:
        if not base.exists():
            continue
        for pat in patterns:
            for p in base.glob(pat):
                df = read_csv_safe(p)
                if df.empty:
                    continue
                # market filter where possible
                if "market" in df.columns:
                    maybe = df[df["market"].astype(str).isin([market_label(market), "국장" if slug == "kr" else "미장", slug])]
                    if not maybe.empty:
                        df = maybe
                sym_col = next((c for c in ["symbol", "ticker", "종목코드", "티커", "종목", "code"] if c in df.columns), None)
                name_col = next((c for c in ["name", "종목명", "company", "회사명", "corp_name", "stock_name"] if c in df.columns), None)
                if not sym_col:
                    continue
                for _, r in df.head(800).iterrows():
                    sym = str(r.get(sym_col, "")).strip().upper()
                    if not sym or sym in {"-", "NAN", "NONE"}:
                        continue
                    if slug == "kr":
                        # Keep pure six-digit code where possible.
                        m = re.search(r"(\d{6})", sym)
                        if m:
                            sym = m.group(1)
                    name = str(r.get(name_col, "")).strip() if name_col else ""
                    if name and name not in {"-", "nan", "None"}:
                        mapping.setdefault(sym, name)
    return mapping


def label_for_symbol(symbol: str, market: str, names: dict[str, str] | None = None) -> str:
    names = names or discover_symbol_names(market)
    sym = str(symbol).strip().upper()
    if market_slug(market) == "kr":
        m = re.search(r"(\d{6})", sym)
        if m:
            sym = m.group(1)
    name = names.get(sym, "")
    return f"{name} ({sym})" if name else sym


def parse_symbol_label(label: str) -> str:
    s = str(label or "").strip()
    m = re.search(r"\(([A-Za-z0-9.\-]{1,12})\)", s)
    if m:
        return m.group(1).upper()
    m = re.search(r"\b(\d{6})\b", s)
    if m:
        return m.group(1)
    return s.split()[0].upper() if s else ""


def symbol_options_with_names(market: str, limit: int = 250) -> list[str]:
    names = discover_symbol_names(market)
    syms = list(names.keys())
    # candidates/holdings symbols first
    priority: list[str] = []
    for p in [REPORT_DIR / f"swing_candidates_{market_slug(market)}_A_top3.csv", REPORT_DIR / f"swing_candidates_{market_slug(market)}_B_watch.csv", DATA_DIR / f"holdings_{market_slug(market)}.csv", ROOT / f"holdings_{market_slug(market)}.csv"]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        c = next((x for x in ["symbol", "ticker", "종목코드", "티커", "종목"] if x in df.columns), None)
        if c:
            for x in df[c].dropna().astype(str).tolist():
                sym = parse_symbol_label(x)
                if sym and sym not in priority:
                    priority.append(sym)
    ordered = priority + [x for x in syms if x not in priority]
    return [label_for_symbol(x, market, names) for x in ordered[:limit]]


def _quote_lookup(market: str) -> dict[str, float]:
    slug = market_slug(market)
    out: dict[str, float] = {}
    for p in [REPORT_DIR / f"intraday_realtime_snapshot_{slug}.csv", REPORT_DIR / "intraday_realtime_snapshot.csv", DATA_DIR / "portfolio" / "position_daily_snapshot.csv"]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        sym_col = next((c for c in ["symbol", "ticker", "종목코드", "티커", "종목"] if c in df.columns), None)
        price_col = next((c for c in ["current_price", "현재가", "price", "last", "close", "Close"] if c in df.columns), None)
        if not sym_col or not price_col:
            continue
        for _, r in df.iterrows():
            sym = parse_symbol_label(str(r.get(sym_col, "")))
            if not sym:
                continue
            price = to_num(r.get(price_col))
            if not math.isnan(price) and price > 0:
                out[sym.upper()] = price
    return out


def fetch_yfinance_price(symbol: str, market: str) -> float:
    try:
        import yfinance as yf  # type: ignore
        candidates = [symbol]
        if market_slug(market) == "kr" and re.fullmatch(r"\d{6}", symbol):
            candidates = [f"{symbol}.KS", f"{symbol}.KQ"]
        for t in candidates:
            hist = yf.Ticker(t).history(period="5d")
            if hist is not None and not hist.empty and "Close" in hist.columns:
                val = float(hist["Close"].dropna().iloc[-1])
                if val > 0:
                    return val
    except Exception:
        return math.nan
    return math.nan


def build_sell_budget_table_v43(market: str, limit: int = 80) -> pd.DataFrame:
    try:
        from core.operational_plus_engine import build_sell_budget_table, load_holdings
        base = build_sell_budget_table(market, limit=limit)
        holdings = load_holdings(market)
    except Exception:
        base = pd.DataFrame()
        holdings = pd.DataFrame()
    if (base is None or base.empty) and (holdings is None or holdings.empty):
        return pd.DataFrame()
    if base is None or base.empty:
        base = pd.DataFrame()
        source = holdings.copy()
        rows = []
        for _, r in source.head(limit).iterrows():
            rows.append({
                "종목코드": parse_symbol_label(first(r, ["symbol", "ticker", "종목코드", "티커", "종목"], "-")),
                "종목명": first(r, ["name", "종목명", "company", "회사명"], "-"),
                "시장": market_label(market),
                "보유수량": qty_text(first(r, ["quantity", "shares", "보유수량", "수량"], 0), market),
                "평단가": money(first(r, ["avg_price", "average_price", "평단가", "매입가"], math.nan), market),
                "현재가": "-",
                "수익률": "-",
                "판단": "보유 점검",
                "권장매도수량": "0주",
                "예상회수금액": "-",
                "사유": "현재가·손절/익절 조건이 들어오면 자동 계산됩니다.",
            })
        base = pd.DataFrame(rows)
    quotes = _quote_lookup(market)
    rows2: list[dict[str, Any]] = []
    for _, r in base.head(limit).iterrows():
        row = dict(r)
        sym = parse_symbol_label(str(row.get("종목코드") or row.get("symbol") or row.get("ticker") or ""))
        cur = to_num(row.get("현재가"))
        if (math.isnan(cur) or cur <= 0) and sym:
            cur = quotes.get(sym.upper(), math.nan)
        if (math.isnan(cur) or cur <= 0) and sym:
            # Only fetch a small number to avoid slowing the UI too much.
            cur = fetch_yfinance_price(sym, market)
        avg = to_num(row.get("평단가"))
        qty = to_num(row.get("보유수량"), 0.0)
        sell_qty = to_num(row.get("권장매도수량"), 0.0)
        if not math.isnan(cur) and cur > 0:
            row["현재가"] = money(cur, market)
            if not math.isnan(avg) and avg > 0:
                row["수익률"] = f"{(cur / avg - 1) * 100:+.2f}%"
            if sell_qty > 0:
                row["예상회수금액"] = money(sell_qty * cur, market)
            elif qty > 0 and str(row.get("판단", "")).find("보유") >= 0:
                row["예상회수금액"] = "-"
        if str(row.get("종목명", "")).strip() in {"", "-", "nan"}:
            row["종목명"] = discover_symbol_names(market).get(sym, "-")
        rows2.append(row)
    return pd.DataFrame(rows2)


def _gnews_queries(market: str) -> list[str]:
    if market_slug(market) == "kr":
        return ["한국 주식 반도체 로봇 전력기기 조선 방산", "코스피 코스닥 시장 주도주 실적"]
    return ["US stock market AI semiconductor earnings", "Nasdaq technology stocks market movers"]


def _gnews_sentiment(title: str, desc: str) -> str:
    text = f"{title} {desc}".lower()
    neg = ["falls", "slumps", "lawsuit", "miss", "risk", "warning", "cuts", "probe", "하락", "급락", "부진", "소송", "리스크", "경고"]
    pos = ["rises", "surges", "beats", "growth", "strong", "upgrade", "record", "상승", "급등", "호실적", "성장", "수주", "강세"]
    if any(x in text for x in neg):
        return "부정/주의"
    if any(x in text for x in pos):
        return "긍정"
    return "중립"


def fetch_gnews(market: str, max_items: int = 20) -> pd.DataFrame:
    key = get_secret("GNEWS_API_KEY") or get_secret("NEWS_API_KEY")
    rows: list[dict[str, Any]] = []
    if not key:
        return pd.DataFrame()
    try:
        import requests  # type: ignore
        for q in _gnews_queries(market):
            params = {
                "q": q,
                "max": min(10, max_items),
                "apikey": key,
                "lang": "ko" if market_slug(market) == "kr" else "en",
                "country": "kr" if market_slug(market) == "kr" else "us",
            }
            resp = requests.get("https://gnews.io/api/v4/search", params=params, timeout=15)
            if resp.status_code >= 400:
                rows.append({"status": "ERROR", "query": q, "error": f"HTTP {resp.status_code}: {resp.text[:160]}"})
                continue
            data = resp.json()
            for a in data.get("articles", []) or []:
                title = str(a.get("title") or "").strip()
                desc = str(a.get("description") or "").strip()
                if not title:
                    continue
                rows.append({
                    "market": market_label(market),
                    "query": q,
                    "title": title,
                    "description": desc,
                    "url": a.get("url") or "",
                    "source": (a.get("source") or {}).get("name") if isinstance(a.get("source"), dict) else a.get("source"),
                    "publishedAt": a.get("publishedAt") or "",
                    "sentiment": _gnews_sentiment(title, desc),
                    "summary_ko": _simple_news_korean(title, desc),
                    "status": "OK",
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                })
    except Exception as exc:
        rows.append({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "market": market_label(market)})
    df = pd.DataFrame(rows)
    if not df.empty and "title" in df.columns:
        df = df.drop_duplicates(subset=["title"], keep="first").head(max_items)
    return df


def _simple_news_korean(title: str, desc: str) -> str:
    desc = re.sub(r"\s+", " ", str(desc or "")).strip()
    if desc:
        return f"{title} — {desc[:180]}"
    return title


def save_gnews_reports() -> dict[str, Any]:
    status: dict[str, Any] = {"updated_at": datetime.now().isoformat(timespec="seconds"), "markets": {}}
    combined: list[pd.DataFrame] = []
    for market in ["한국주식", "미국주식"]:
        slug = market_slug(market)
        df = fetch_gnews(market, max_items=20)
        out_path = REPORT_DIR / f"gnews_latest_{slug}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        ok_rows = int((df.get("status", pd.Series(dtype=str)).astype(str).eq("OK")).sum()) if not df.empty and "status" in df.columns else 0
        status["markets"][slug] = {
            "rows": int(len(df)),
            "ok_rows": ok_rows,
            "api_key_present": bool(get_secret("GNEWS_API_KEY") or get_secret("NEWS_API_KEY")),
            "path": str(out_path.relative_to(ROOT)),
        }
        if ok_rows:
            combined.append(df[df["status"].astype(str).eq("OK")].copy())
    if combined:
        all_news = pd.concat(combined, ignore_index=True, sort=False)
    else:
        all_news = pd.DataFrame()
    all_news.to_csv(DATA_DIR / "news" / "gnews_cache.csv", index=False, encoding="utf-8-sig")
    write_json(REPORT_DIR / "gnews_summary.json", status)
    return status


def build_news_narrative_table_v43(market: str, limit: int = 60) -> pd.DataFrame:
    slug = market_slug(market)
    frames: list[pd.DataFrame] = []
    for p in [REPORT_DIR / f"gnews_latest_{slug}.csv", DATA_DIR / "news" / "gnews_cache.csv", REPORT_DIR / f"operational_news_narrative_{slug}.csv"]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        if "market" in df.columns:
            maybe = df[df["market"].astype(str).eq(market_label(market))]
            if not maybe.empty:
                df = maybe
        df = df.copy()
        df["_source_file"] = str(p.relative_to(ROOT))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True, sort=False)
    rows: list[dict[str, Any]] = []
    for _, r in raw.head(300).iterrows():
        title = str(first(r, ["title", "제목/종목", "headline", "news_title"], "-")).strip()
        desc = str(first(r, ["summary_ko", "description", "한글 요약", "summary", "요약"], "")).strip()
        if title in {"", "-"} and not desc:
            continue
        rows.append({
            "분류": "외부 뉴스" if "gnews" in str(r.get("_source_file", "")) else "후보/내러티브",
            "제목": title if title != "-" else desc[:80],
            "초보자 요약": desc[:260] if desc else title[:260],
            "감성": str(first(r, ["sentiment", "감성", "tone"], _gnews_sentiment(title, desc))),
            "출처": str(first(r, ["source", "출처", "_source_file"], "-")),
            "링크": str(first(r, ["url", "link", "링크"], "-")),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates(subset=["제목"], keep="first").head(limit)


def build_flow_cards_v43(summary_df: pd.DataFrame | None) -> list[dict[str, str]]:
    if summary_df is None or summary_df.empty:
        return [{"title": "데이터 없음", "status": "확인 필요", "summary": "수급·호가·현재가 리포트가 아직 없습니다.", "action": "장중 갱신 또는 API 설정을 확인하세요."}]
    cards: list[dict[str, str]] = []
    for _, r in summary_df.iterrows():
        title = str(r.get("구분", "항목"))
        status = str(r.get("상태", "-"))
        summary = str(r.get("핵심 요약", "-"))
        beginner = str(r.get("초보자 해석", ""))
        action = str(r.get("다음 행동", ""))
        cards.append({"title": title, "status": status, "summary": summary, "beginner": beginner, "action": action})
    return cards


def _yf_history(symbol: str, market: str, period: str = "1y") -> pd.DataFrame:
    try:
        import yfinance as yf  # type: ignore
        tickers = [symbol]
        if market_slug(market) == "kr" and re.fullmatch(r"\d{6}", symbol):
            tickers = [f"{symbol}.KS", f"{symbol}.KQ"]
        for t in tickers:
            hist = yf.Ticker(t).history(period=period)
            if hist is not None and not hist.empty and "Close" in hist.columns:
                hist = hist.reset_index()
                return hist
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


def _simulate_ma_strategy(hist: pd.DataFrame) -> dict[str, Any]:
    if hist is None or hist.empty or len(hist) < 80:
        return {"status": "가격 데이터 부족"}
    df = hist.copy()
    df["Close"] = pd.to_numeric(df["Close"], errors="coerce")
    df = df.dropna(subset=["Close"]).reset_index(drop=True)
    df["MA10"] = df["Close"].rolling(10).mean()
    df["MA20"] = df["Close"].rolling(20).mean()
    df["signal"] = (df["MA10"] > df["MA20"]) & (df["MA10"].shift(1) <= df["MA20"].shift(1))
    trades: list[float] = []
    max_hold = 20
    stop = -0.05
    target = 0.10
    for i in df.index[df["signal"].fillna(False)].tolist():
        if i + 2 >= len(df):
            continue
        entry = float(df.loc[i + 1, "Close"])
        if entry <= 0:
            continue
        exit_ret = None
        for j in range(i + 2, min(len(df), i + 2 + max_hold)):
            ret = float(df.loc[j, "Close"]) / entry - 1
            if ret <= stop or ret >= target:
                exit_ret = ret
                break
        if exit_ret is None:
            j = min(len(df) - 1, i + 1 + max_hold)
            exit_ret = float(df.loc[j, "Close"]) / entry - 1
        trades.append(exit_ret)
    if not trades:
        return {"status": "신호 없음"}
    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x <= 0]
    return {
        "status": "OK",
        "trades": len(trades),
        "win_rate": len(wins) / len(trades) * 100,
        "avg_return": sum(trades) / len(trades) * 100,
        "avg_win": (sum(wins) / len(wins) * 100) if wins else 0.0,
        "avg_loss": (sum(losses) / len(losses) * 100) if losses else 0.0,
    }


def save_v43_strategy_backtest(limit_symbols: int = 30) -> dict[str, Any]:
    result: dict[str, Any] = {"updated_at": datetime.now().isoformat(timespec="seconds"), "status": "OK", "rows": 0}
    rows: list[dict[str, Any]] = []
    for market in ["한국주식", "미국주식"]:
        names = discover_symbol_names(market)
        symbols = list(names.keys())[:limit_symbols]
        for sym in symbols:
            hist = _yf_history(sym, market, period="1y")
            sim = _simulate_ma_strategy(hist)
            rows.append({
                "시장": market_label(market),
                "종목코드": sym,
                "종목명": names.get(sym, "-"),
                "전략": "MA10 상향돌파 후 20거래일/손절-5%/목표+10%",
                "상태": sim.get("status", "-"),
                "거래수": sim.get("trades", 0),
                "승률": f"{sim.get('win_rate', 0):.1f}%" if sim.get("status") == "OK" else "-",
                "평균수익률": f"{sim.get('avg_return', 0):+.2f}%" if sim.get("status") == "OK" else "-",
                "평균이익": f"{sim.get('avg_win', 0):+.2f}%" if sim.get("status") == "OK" else "-",
                "평균손실": f"{sim.get('avg_loss', 0):+.2f}%" if sim.get("status") == "OK" else "-",
                "초보자 해석": "검증 가능" if sim.get("status") == "OK" else "가격 데이터가 더 쌓이면 계산됩니다.",
            })
    df = pd.DataFrame(rows)
    out = REPORT_DIR / "v43_strategy_backtest_summary.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    result["rows"] = int(len(df))
    result["ok_rows"] = int(df["상태"].astype(str).eq("OK").sum()) if not df.empty and "상태" in df.columns else 0
    result["path"] = str(out.relative_to(ROOT))
    write_json(REPORT_DIR / "v43_strategy_backtest_summary.json", result)
    return result


def run_v43_update() -> dict[str, Any]:
    result = {"updated_at": datetime.now().isoformat(timespec="seconds"), "status": "OK"}
    try:
        result["gnews"] = save_gnews_reports()
    except Exception as exc:
        result["status"] = "ERROR"
        result["gnews_error"] = f"{type(exc).__name__}: {exc}"
    try:
        result["strategy_backtest"] = save_v43_strategy_backtest(limit_symbols=18)
    except Exception as exc:
        result["status"] = "ERROR"
        result["strategy_backtest_error"] = f"{type(exc).__name__}: {exc}"
    write_json(REPORT_DIR / "v43_update_status.json", result)
    return result
