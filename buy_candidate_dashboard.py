"""Fast Toss-style buy candidate dashboard.

This module is intentionally display-only:
- reads already-generated CSV/JSON files
- does not call external APIs
- does not run prediction/trading/order logic
- keeps the first screen lightweight by showing TOP cards first
"""
from __future__ import annotations

import html
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import pandas as pd
import streamlit as st

REPORT_DIR = Path("reports")
DATA_DIR = Path("data")

EMPTY = {
    "", "-", "N/A", "NA", "None", "none", "nan", "NaN", "NULL", "null",
    "저장값 없음", "현재가 미수신", "가격 기준 미산출", "예측값 없음", "데이터 없음",
}

PRICE_COLS = {
    "현재가": ("현재가", "current_price", "last_price", "price", "close", "latest_price"),
    "관찰 기준가": ("관찰 기준가", "basis_price", "pullback_wait_price", "active_scenario_pullback_price"),
    "조건부 진입가": ("조건부 진입가", "매수가", "entry", "entry_price", "buy_price", "active_scenario_entry_price"),
    "손절가": ("손절가", "stop", "stop_loss", "active_scenario_stop_loss"),
    "1차 목표가": ("1차 목표가", "목표가", "tp1", "target1", "target_price", "active_scenario_take_profit_1"),
    "2차 목표가": ("2차 목표가", "tp2", "target2", "take_profit2", "active_scenario_take_profit_2"),
}

SCORE_COLS = {
    "종합점수": ("종합점수", "종합 점수", "total_score", "score", "실전등급점수"),
    "수급점수": ("수급점수", "수급 점수", "supply_score", "flow_score", "investor_flow_score"),
    "실적점수": ("실적점수", "실적 점수", "earnings_score", "performance_score"),
    "밸류에이션점수": ("밸류에이션점수", "밸류에이션 점수", "벨류에이션점수", "valuation_score", "value_score"),
    "차트점수": ("차트점수", "차트 점수", "chart_score", "technical_score"),
    "리스크감점": ("리스크감점", "risk_penalty", "risk_deduction", "risk_deduction_score"),
}

NAME_COLS = ("종목명", "name", "stock_name", "company_name", "display_name", "종목")
SYMBOL_COLS = ("종목코드", "symbol", "ticker", "code", "stock_code")
MARKET_COLS = ("시장", "market", "market_name", "market_type")


@st.cache_data(ttl=90, show_spinner=False)
def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, low_memory=False).fillna("")
        except Exception:
            pass
    return pd.DataFrame()


@st.cache_data(ttl=90, show_spinner=False)
def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            pass
    return {}


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    text = str(value).strip()
    return text in EMPTY or text.lower() in {x.lower() for x in EMPTY}


def _first(row: pd.Series | dict[str, Any], cols: Iterable[str], default: str = "") -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": ""
    try:
        lower_map = {str(c).strip().lower(): c for c in row.index}  # type: ignore[attr-defined]
    except Exception:
        lower_map = {}
    for col in cols:
        val = getter(col, "")
        if not _is_empty(val):
            return str(val).strip()
        hit = lower_map.get(str(col).strip().lower())
        if hit is not None:
            val = getter(hit, "")
            if not _is_empty(val):
                return str(val).strip()
    return default


def _to_num(value: Any) -> float | None:
    if _is_empty(value):
        return None
    text = str(value).strip()
    text = text.replace("원", "").replace("$", "").replace(",", "").replace("%", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", ".", "-", "-."}:
        return None
    try:
        num = float(text)
        if math.isfinite(num):
            return num
    except Exception:
        return None
    return None


def _market_from_value(value: Any, fallback: str = "") -> str:
    text = str(value or fallback or "").strip()
    low = text.lower()
    if "한국" in text or "국장" in text or low in {"kr", "krx", "kospi", "kosdaq"}:
        return "한국주식"
    if "미국" in text or "미장" in text or low in {"us", "usa", "nasdaq", "nyse", "amex"}:
        return "미국주식"
    if text in {"전체", "통합", "ALL", "all"}:
        return "전체"
    return text or fallback


def _infer_market_from_symbol(symbol: str, fallback: str = "") -> str:
    sym = str(symbol or "").strip().replace(".KS", "").replace(".KQ", "")
    if re.fullmatch(r"\d{1,6}", sym):
        return "한국주식"
    if sym and re.fullmatch(r"[A-Za-z][A-Za-z0-9.\-]*", sym):
        return "미국주식"
    return _market_from_value(fallback) or "한국주식"


def _row_market_strict(row: pd.Series, fallback: str = "전체") -> str:
    raw = _first(row, MARKET_COLS)
    norm = _market_from_value(raw, "")
    sym_raw = _first(row, SYMBOL_COLS)
    inferred = _infer_market_from_symbol(sym_raw, fallback)
    if norm in {"한국주식", "미국주식"}:
        if inferred == "한국주식" and norm == "미국주식":
            return "한국주식"
        return norm
    return inferred if inferred in {"한국주식", "미국주식"} else (_market_from_value(fallback) or "한국주식")


def _symbol(row: pd.Series, market: str) -> str:
    sym = _first(row, SYMBOL_COLS)
    if not sym:
        return ""
    sym = sym.strip().replace(".KS", "").replace(".KQ", "")
    if sym.endswith(".0"):
        sym = sym[:-2]
    if re.fullmatch(r"\d{1,6}", sym):
        return sym.zfill(6)
    return sym.upper() if market == "미국주식" else sym


def _name(row: pd.Series, symbol: str) -> str:
    nm = _first(row, NAME_COLS)
    return nm if nm else symbol


def _row_key(row: pd.Series, fallback_market: str = "전체") -> str:
    mkt = _row_market_strict(row, fallback_market)
    sym = _symbol(row, mkt)
    if sym:
        return f"{mkt}:{sym}"
    return f"{mkt}:{_name(row, sym)}"


def _format_price(value: Any, market: str) -> str:
    n = _to_num(value)
    if n is None:
        return "확인 필요" if _is_empty(value) else str(value)
    if market == "미국주식":
        return f"${n:,.2f}"
    return f"{round(n):,}원"


def _format_score(value: Any) -> str:
    if _is_empty(value):
        return "확인 필요"
    n = _to_num(value)
    if n is None:
        return str(value)
    if abs(n - round(n)) < 1e-9:
        return f"{int(round(n))}"
    return f"{n:.1f}"


def _concat_existing(paths: Iterable[Path], market: str | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    wanted_market = _market_from_value(market or "전체") or "전체"
    for p in paths:
        df = _read_csv(p)
        if df.empty:
            continue
        df = df.copy()
        df["_source_file"] = str(p)
        if wanted_market != "전체":
            mask = []
            for _, row in df.iterrows():
                mask.append(_row_market_strict(row, wanted_market) == wanted_market)
            df = df[pd.Series(mask, index=df.index)].copy()
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).fillna("")


def _dedupe_by_symbol(df: pd.DataFrame, market: str = "전체") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    keys = [_row_key(row, market) for _, row in work.iterrows()]
    work["_dedupe_key"] = keys
    work = work.loc[~work["_dedupe_key"].duplicated()].drop(columns=["_dedupe_key"], errors="ignore")
    return work.reset_index(drop=True)


def _unique_excluding(df: pd.DataFrame, market: str, used: set[str] | None = None, *, limit: int | None = None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    used = used if used is not None else set()
    rows = []
    local_seen: set[str] = set()
    for _, row in _dedupe_by_symbol(df, market).iterrows():
        key = _row_key(row, market)
        if key in used or key in local_seen:
            continue
        local_seen.add(key)
        rows.append(row)
        if limit is not None and len(rows) >= limit:
            break
    if not rows:
        return pd.DataFrame(columns=df.columns)
    used.update(local_seen)
    return pd.DataFrame(rows).reset_index(drop=True)


def _split_distinct_categories(categories: list[tuple[str, str, str, str, pd.DataFrame]], market: str) -> list[tuple[str, str, str, str, pd.DataFrame]]:
    used: set[str] = set()
    out: list[tuple[str, str, str, str, pd.DataFrame]] = []
    for icon, title, desc, key, df in categories:
        out.append((icon, title, desc, key, _unique_excluding(df, market, used)))
    return out


def _rank(df: pd.DataFrame, cols: Iterable[str], ascending: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    work = df.copy()
    score = pd.Series([0.0] * len(work), index=work.index)
    for col in cols:
        if col in work.columns:
            score = score + pd.to_numeric(
                work[col].astype(str).str.replace(",", "", regex=False).str.replace("원", "", regex=False).str.replace("$", "", regex=False),
                errors="coerce"
            ).fillna(0)
    work["_sort_score"] = score
    return work.sort_values("_sort_score", ascending=ascending).reset_index(drop=True)


def _preferred_columns(df: pd.DataFrame, market: str, limit: int = 30) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=["종목", "현재가", "진입가", "손절가", "1차 목표", "종합", "수급", "실적", "밸류", "차트", "상태"])
    rows: list[dict[str, Any]] = []
    for rank_no, (_, row) in enumerate(_dedupe_by_symbol(df, market).head(limit).iterrows(), start=1):
        mkt = _row_market_strict(row, market)
        sym = _symbol(row, mkt)
        nm = _name(row, sym)
        rows.append({
            "종목": f"{nm} {sym}" if sym and sym != nm else nm,
            "현재가": _format_price(_first(row, PRICE_COLS["현재가"]), mkt),
            "진입가": _format_price(_first(row, PRICE_COLS["조건부 진입가"]), mkt),
            "손절가": _format_price(_first(row, PRICE_COLS["손절가"]), mkt),
            "1차 목표": _format_price(_first(row, PRICE_COLS["1차 목표가"]), mkt),
            "종합": _format_score(_first(row, SCORE_COLS["종합점수"])),
            "수급": _format_score(_first(row, SCORE_COLS["수급점수"])),
            "실적": _format_score(_first(row, SCORE_COLS["실적점수"])),
            "밸류": _format_score(_first(row, SCORE_COLS["밸류에이션점수"])),
            "차트": _format_score(_first(row, SCORE_COLS["차트점수"])),
            "상태": _first(row, ("price_data_status", "데이터 상태", "final_judgment", "최종 판단"), "확인 필요"),
        })
    return pd.DataFrame(rows)


def _inject_css() -> None:
    st.markdown(
        """
        <style>
        .home-hero{padding:18px 20px;border-radius:24px;background:linear-gradient(135deg,#132033,#0b1220);border:1px solid rgba(148,163,184,.18);margin:8px 0 16px 0;}
        .home-hero h2{margin:0 0 8px 0;color:#f8fafc;font-size:1.45rem;}
        .home-hero p{margin:0;color:#a7b0c0;line-height:1.55;}
        .market-card-row{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:10px 0 18px 0;}
        .category-grid{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:10px;margin:10px 0 18px 0;padding-bottom:6px;}
        .market-card,.category-card{padding:14px;border-radius:20px;background:#111827;border:1px solid rgba(148,163,184,.18);box-shadow:0 10px 30px rgba(0,0,0,.22);}
        .market-label,.cat-desc{color:#94a3b8;font-size:.82rem;}
        .market-value,.cat-title{color:#f8fafc;font-size:1.02rem;font-weight:800;margin-top:4px;}
        .market-sub,.cat-meta{color:#cbd5e1;font-size:.80rem;margin-top:7px;line-height:1.38;}
        .cat-icon{width:34px;height:34px;border-radius:14px;background:#1f2937;display:flex;align-items:center;justify-content:center;margin-bottom:10px;font-size:1.2rem;}
        .section-title{font-size:1.25rem;font-weight:900;color:#f8fafc;margin:22px 0 8px;}
        .home-section-card{padding:16px;border-radius:22px;background:#0f172a;border:1px solid rgba(148,163,184,.22);margin:12px 0 18px 0;}
        .section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px;}
        .section-kicker{font-weight:900;color:#f8fafc;font-size:1.05rem;}
        .section-desc{color:#94a3b8;font-size:.86rem;margin-top:4px;line-height:1.45;}
        .section-count{color:#cbd5e1;background:#111827;border:1px solid rgba(148,163,184,.18);padding:6px 10px;border-radius:999px;font-size:.82rem;white-space:nowrap;}
        .candidate-list{display:grid;grid-template-columns:repeat(3,minmax(260px,1fr));gap:12px;overflow-x:auto;padding-bottom:4px;scroll-snap-type:x proximity;}
        .candidate-list::-webkit-scrollbar{height:8px;}
        .candidate-list::-webkit-scrollbar-thumb{background:rgba(148,163,184,.22);border-radius:999px;}
        .candidate-item{padding:14px;border-radius:18px;background:#111827;border:1px solid rgba(148,163,184,.14);min-height:116px;scroll-snap-align:start;}
        .candidate-main{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap;}
        .candidate-name{color:#f8fafc;font-weight:800;font-size:1rem;}
        .candidate-code{color:#94a3b8;font-size:.8rem;}
        .candidate-metrics{display:flex;gap:10px;flex-wrap:wrap;color:#cbd5e1;font-size:.84rem;margin-top:7px;}
        .candidate-badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;}
        .badge{font-size:.76rem;color:#dbeafe;background:rgba(59,130,246,.12);border:1px solid rgba(96,165,250,.20);padding:4px 8px;border-radius:999px;}
        .badge.muted{color:#cbd5e1;background:rgba(148,163,184,.10);border-color:rgba(148,163,184,.15);}
        .candidate-empty{color:#94a3b8;padding:10px 0;}
        .tool-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;margin:10px 0 20px;}
        .tool-card{min-height:170px;padding:18px;border-radius:24px;background:linear-gradient(145deg,#f8fafc,#eef2ff);color:#111827;border:1px solid rgba(148,163,184,.25);box-shadow:0 12px 30px rgba(15,23,42,.16);}
        .tool-card h4{margin:0 0 8px;font-size:1.05rem;color:#0f172a;}
        .tool-card p{margin:0;color:#334155;line-height:1.55;font-size:.92rem;}
        .tool-thumb{height:72px;margin-top:14px;border-radius:18px;background:rgba(15,23,42,.08);display:flex;align-items:center;justify-content:center;font-size:1.8rem;}
        .news-row{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start;padding:12px 0;border-bottom:1px solid rgba(148,163,184,.14);}
        .news-row:last-child{border-bottom:0}
        .news-title{color:#f8fafc;font-weight:800;line-height:1.45}.news-meta{color:#94a3b8;font-size:.82rem;margin-top:4px}.news-badge{color:#dbeafe;background:rgba(59,130,246,.14);border:1px solid rgba(96,165,250,.2);border-radius:999px;padding:4px 8px;font-size:.75rem;white-space:nowrap}
        @media(max-width:1200px){.category-grid{grid-template-columns:repeat(3,minmax(0,1fr));}.candidate-list{grid-template-columns:repeat(3,minmax(240px,1fr));}}@media(max-width:900px){.market-card-row{grid-template-columns:1fr}.category-grid{grid-template-columns:1fr}.candidate-list{grid-template-columns:repeat(3,minmax(230px,1fr));}.tool-grid{grid-template-columns:1fr}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _market_summary_cards(market: str) -> None:
    regime = _read_json(REPORT_DIR / "market_regime_summary.json")
    portfolio = _read_json(REPORT_DIR / "portfolio_risk_summary.json")
    realtime = _read_json(REPORT_DIR / "intraday_realtime_summary.json") or _read_json(REPORT_DIR / "intraday_realtime_status.json")
    flow = _read_json(REPORT_DIR / "intraday_flow_summary.json")
    cards = [
        ("선택 시장", market, f"{regime.get('market_regime', '시장 상태 확인 필요')} · 위험도 {regime.get('market_risk_score', '-')}"),
        ("데이터 상태", str(realtime.get("overall_status", realtime.get("status", "저장값 기준"))), f"현재가 수신률 {realtime.get('data_available_rate', realtime.get('quote_available_rate', '-'))}"),
        ("보유 리스크", str(portfolio.get("portfolio_risk_level", "확인 필요")), f"수급 상태 {flow.get('overall_status', flow.get('status', '-'))}"),
    ]
    html_parts = ['<div class="market-card-row">']
    for label, value, sub in cards:
        html_parts.append(
            f'<div class="market-card"><div class="market-label">{_e(label)}</div>'
            f'<div class="market-value">{_e(value)}</div><div class="market-sub">{_e(sub)}</div></div>'
        )
    html_parts.append('</div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)


def _category_cards_html(categories: list[tuple[str, str, str, str, pd.DataFrame]], market: str) -> None:
    html_parts = ['<div class="category-grid">']
    for icon, title, desc, key, df in categories:
        top = "-"
        if isinstance(df, pd.DataFrame) and not df.empty:
            row = df.iloc[0]
            mkt = _row_market_strict(row, market)
            sym = _symbol(row, mkt)
            top = _name(row, sym) or sym or "-"
        count = len(df) if isinstance(df, pd.DataFrame) else 0
        html_parts.append(
            f'<div class="category-card"><div class="cat-icon">{_e(icon)}</div>'
            f'<div class="cat-title">{_e(title)}</div><div class="cat-desc">{_e(desc)}</div>'
            f'<div class="cat-meta"><b>{count:,}</b>개 · TOP {_e(top)}</div></div>'
        )
    html_parts.append('</div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)


def _candidate_card_html(df: pd.DataFrame, market: str, limit: int = 3) -> str:
    if df is None or df.empty:
        return '<div class="candidate-empty">표시할 후보가 없습니다.</div>'
    items: list[str] = ['<div class="candidate-list">']
    for rank_no, (_, row) in enumerate(_dedupe_by_symbol(df, market).head(limit).iterrows(), start=1):
        mkt = _row_market_strict(row, market)
        sym = _symbol(row, mkt)
        name = _name(row, sym)
        current = _format_price(_first(row, PRICE_COLS["현재가"]), mkt)
        entry = _format_price(_first(row, PRICE_COLS["조건부 진입가"]), mkt)
        target = _format_price(_first(row, PRICE_COLS["1차 목표가"]), mkt)
        total = _format_score(_first(row, SCORE_COLS["종합점수"]))
        supply = _format_score(_first(row, SCORE_COLS["수급점수"]))
        state = _first(row, ("price_data_status", "데이터 상태", "risk_final_decision", "final_judgment", "판단"), "확인 필요")
        items.append(
            '<div class="candidate-item">'
            '<div class="candidate-main">'
            f'<span class="badge">TOP {rank_no}</span>'
            f'<div class="candidate-name">{_e(name)}</div>'
            f'<div class="candidate-code">{_e(sym)} · {_e(mkt)}</div>'
            '</div>'
            '<div class="candidate-metrics">'
            f'<span>현재 {_e(current)}</span>'
            f'<span>진입 {_e(entry)}</span>'
            f'<span>목표 {_e(target)}</span>'
            '</div>'
            '<div class="candidate-badges">'
            f'<span class="badge">종합 {_e(total)}</span>'
            f'<span class="badge">수급 {_e(supply)}</span>'
            f'<span class="badge muted">{_e(state)}</span>'
            '</div>'
            '</div>'
        )
    items.append('</div>')
    return ''.join(items)


def _render_candidate_section(
    title: str,
    desc: str,
    icon: str,
    df: pd.DataFrame,
    market: str,
    key: str,
    *,
    limit: int = 3,
    show_full_expander: bool = True,
) -> None:
    count = 0 if df is None or df.empty else len(_dedupe_by_symbol(df, market))
    st.markdown(
        f"""
        <div class="home-section-card">
            <div class="section-head">
                <div>
                    <div class="section-kicker">{_e(icon)} {_e(title)}</div>
                    <div class="section-desc">{_e(desc)}</div>
                </div>
                <div class="section-count">{count:,}개</div>
            </div>
            {_candidate_card_html(df, market, limit=limit)}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if show_full_expander:
        with st.expander(f"{icon} {title} 전체 보기", expanded=False):
            if df is None or df.empty:
                st.info("표시할 후보가 없습니다.")
            else:
                st.dataframe(_preferred_columns(_dedupe_by_symbol(df, market), market, limit=50), use_container_width=True, hide_index=True)



def _news_source_label_from_url(url: str, fallback: str = "") -> str:
    """Convert a stored news URL/source into a short user-facing source label."""
    src = str(fallback or "").strip()
    u = str(url or "").strip().lower()
    host = ""
    try:
        host = urlparse(u).netloc.lower().replace("www.", "")
    except Exception:
        host = ""
    text = f"{src} {host} {u}".lower()
    if "investing.com" in text:
        return "Investing.com"
    if "finance.yahoo" in text or "yahoo" in text:
        return "Yahoo Finance"
    if "marketwatch" in text:
        return "MarketWatch"
    if "cnbc" in text:
        return "CNBC"
    if "reuters" in text:
        return "Reuters"
    if "bloomberg" in text:
        return "Bloomberg"
    if "benzinga" in text:
        return "Benzinga"
    if "seekingalpha" in text:
        return "Seeking Alpha"
    if "google" in text and "news" in text:
        return "Google News"
    if "naver" in text:
        return "네이버금융"
    if "hankyung" in text:
        return "한국경제"
    if "yna" in text or "연합뉴스" in text:
        return "연합뉴스"
    if src:
        return src[:32]
    return host[:32] if host else "뉴스"


def _news_paths() -> list[Path]:
    """Known stored news files. No web/API call is made on the first screen."""
    roots = [DATA_DIR / "news", REPORT_DIR]
    candidates = [
        DATA_DIR / "news" / "today_news.csv",
        DATA_DIR / "news" / "market_summary.json",
        REPORT_DIR / "today_news.csv",
        REPORT_DIR / "market_news.csv",
        REPORT_DIR / "realtime_news.csv",
        REPORT_DIR / "news_items.csv",
        REPORT_DIR / "macro_news.csv",
        REPORT_DIR / "news_dedup_report.csv",
    ]
    out: list[Path] = []
    for path in candidates:
        if path.exists() and path not in out:
            out.append(path)
    for root in roots:
        try:
            if root.exists():
                for path in sorted(root.glob("*news*.csv")):
                    if path not in out:
                        out.append(path)
        except Exception:
            continue
    return out


NEWS_TITLE_COLS = ("title", "headline", "news_title", "제목", "뉴스제목", "기사제목")
NEWS_SUMMARY_COLS = ("summary", "description", "content", "요약", "본문", "reason", "해설", "trade_takeaway")
NEWS_SOURCE_COLS = ("source", "provider", "media", "publisher", "출처", "언론사")
NEWS_TIME_COLS = ("datetime", "time", "published", "published_at", "collected_at", "updated_at", "일시", "시간")
NEWS_URL_COLS = ("url", "link", "href", "기사URL", "뉴스URL")
NEWS_MARKET_COLS = ("market", "시장")
NEWS_TICKER_COLS = ("ticker", "symbol", "related_ticker", "종목코드", "관련종목", "tickers")



SAMPLE_NEWS_SOURCES = {"샘플뉴스", "샘플경제", "샘플마켓", "샘플리서치", "샘플글로벌", "sample"}


def _parse_news_date(value: Any) -> tuple[pd.Timestamp | None, str]:
    """Return parsed news timestamp and original text.

    Stored news rows can contain RFC dates, ISO dates, or Korean sample labels.
    The first screen should only show genuinely recent news, so rows that cannot
    be dated are filtered out instead of being shown as today's news.
    """
    text = str(value or "").strip()
    if not text:
        return None, ""
    # Fast path for YYYY-MM-DD embedded in arbitrary strings.
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", text)
    if m:
        try:
            ts = pd.Timestamp(year=int(m.group(1)), month=int(m.group(2)), day=int(m.group(3)))
            return ts, text
        except Exception:
            pass
    try:
        ts = pd.to_datetime(text, errors="coerce", utc=True)
        if pd.isna(ts):
            return None, text
        if isinstance(ts, pd.Timestamp):
            try:
                ts = ts.tz_convert(None)
            except Exception:
                try:
                    ts = ts.tz_localize(None)
                except Exception:
                    pass
            return ts, text
    except Exception:
        return None, text
    return None, text


def _news_datetime_from_row(row: pd.Series | dict[str, Any]) -> tuple[pd.Timestamp | None, str]:
    # Prefer published datetime over collected_at when both exist.
    priority_cols = (
        "datetime", "published", "published_at", "date", "날짜", "시간", "time", "created_at", "updated_at", "collected_at"
    )
    for col in priority_cols:
        val = _first(row, (col,))
        ts, raw = _parse_news_date(val)
        if ts is not None:
            return ts, raw
    return None, ""


def _is_sample_news_row(row: pd.Series | dict[str, Any]) -> bool:
    fields = [
        _first(row, NEWS_SOURCE_COLS),
        _first(row, NEWS_TIME_COLS),
        _first(row, ("collected_at",)),
        _first(row, NEWS_TITLE_COLS),
    ]
    text = " ".join(str(x or "") for x in fields).strip().lower()
    if not text:
        return False
    if "샘플" in text or "sample" in text:
        return True
    source = str(_first(row, NEWS_SOURCE_COLS)).strip().lower()
    return source in SAMPLE_NEWS_SOURCES


def _is_recent_news_ts(ts: pd.Timestamp, *, today: pd.Timestamp | None = None, days: int = 2) -> bool:
    if ts is None or pd.isna(ts):
        return False
    today = today or pd.Timestamp.now().normalize()
    try:
        news_date = pd.Timestamp(ts).normalize()
    except Exception:
        return False
    delta = (today - news_date).days
    # Allow a one-day future edge case caused by timezone conversion, but do not
    # allow old archived rows to appear as today's news.
    return -1 <= delta <= days


def _news_recency_bucket(ts: pd.Timestamp, today: pd.Timestamp | None = None) -> int:
    """Sort bucket: today's news first, then recent news."""
    today = today or pd.Timestamp.now().normalize()
    if ts is None or pd.isna(ts):
        return 99
    news_date = pd.Timestamp(ts).normalize()
    delta = (today - news_date).days
    if delta == 0:
        return 0
    if 0 < delta <= 2:
        return 1
    if delta < 0:
        return 2
    return 99


def _normalize_news_signature(title: str) -> str:
    """Loose duplicate key for similar news titles from different sources."""
    text = str(title or "").lower()
    text = re.sub(r"\[[^\]]+\]|\([^\)]*\)", " ", text)
    text = re.sub(r"\b(reuters|cnbc|marketwatch|yahoo|investing\.com|bloomberg|google news|exclusive|update\d*)\b", " ", text)
    text = re.sub(r"[^a-z0-9가-힣\s]", " ", text)
    text = re.sub(r"\b\d{1,2}:\d{2}\b|\b\d+(\.\d+)?%?\b", " ", text)
    stop = {
        "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "as", "by", "from",
        "news", "stock", "stocks", "market", "markets", "shares", "share", "corp", "inc", "co", "ltd",
        "뉴스", "관련", "증시", "시장", "주식", "종목", "오늘", "속보", "단독",
    }
    toks = [t for t in text.split() if len(t) >= 2 and t not in stop]
    # Keep order but cap so near-identical long titles collapse.
    return " ".join(toks[:10])


def _is_similar_news(sig: str, existing: set[str]) -> bool:
    if not sig:
        return True
    sig_tokens = set(sig.split())
    if not sig_tokens:
        return True
    for old in existing:
        old_tokens = set(old.split())
        if not old_tokens:
            continue
        inter = len(sig_tokens & old_tokens)
        union = len(sig_tokens | old_tokens)
        if sig == old or (union and inter / union >= 0.68) or inter >= 5:
            return True
    return False


def _simple_korean_news_summary(title: str, summary: str = "", market: str = "전체") -> str:
    """Short Korean explanation for stored English market/news headlines.
    This is rule-based and does not invent facts beyond the saved title/summary.
    """
    base = " ".join([str(title or ""), str(summary or "")]).strip()
    low = base.lower()
    if not base:
        return "저장된 뉴스 제목 기준으로 확인하세요."
    if any(k in low for k in ["earnings", "eps", "revenue", "sales", "guidance", "quarter", "q1", "q2", "q3", "q4"]):
        return "실적·매출·가이던스 관련 뉴스입니다. 예상치 대비 결과와 장중 반응을 함께 확인하세요."
    if any(k in low for k in ["fed", "fomc", "powell", "rate", "yield", "treasury", "inflation", "cpi", "ppi"]):
        return "금리·연준·물가 관련 뉴스입니다. 성장주와 기술주 변동성에 영향을 줄 수 있습니다."
    if any(k in low for k in ["nvidia", "nvda", "semiconductor", "chip", "ai", "data center", "gpu", "memory"]):
        return "AI·반도체 관련 뉴스입니다. 관련 기술주와 반도체 수급 흐름을 같이 확인하세요."
    if any(k in low for k in ["tariff", "trade", "china", "export", "sanction"]):
        return "관세·무역·중국 관련 뉴스입니다. 공급망과 수출 비중이 큰 종목에 영향을 줄 수 있습니다."
    if any(k in low for k in ["oil", "wti", "opec", "crude", "energy"]):
        return "유가·에너지 관련 뉴스입니다. 에너지주와 비용 민감 업종을 함께 확인하세요."
    if any(k in low for k in ["bitcoin", "crypto", "coinbase", "ethereum", "btc"]):
        return "가상자산 관련 뉴스입니다. 관련주와 위험자산 선호 변화를 함께 확인하세요."
    if market == "미국주식" or re.search(r"\b[A-Z]{2,5}\b", str(title or "")):
        return "미국 시장 관련 뉴스입니다. 관련 종목의 가격·거래량 반응을 확인하세요."
    # Korean original summary can be used if it is already concise.
    if summary and any("가" <= ch <= "힣" for ch in str(summary)):
        return str(summary)[:180]
    return "시장에 영향을 줄 수 있는 뉴스입니다. 관련 종목과 섹터 반응을 확인하세요."

def _news_matches_market(item: dict[str, str], market: str) -> bool:
    wanted = _market_from_value(market or "전체") or "전체"
    if wanted == "전체":
        return True
    raw_market = _market_from_value(item.get("market", ""), "")
    if raw_market in {"한국주식", "미국주식"}:
        return raw_market == wanted
    text = " ".join(str(item.get(k, "")) for k in ["title", "summary", "source", "ticker", "url"]).lower()
    if wanted == "한국주식":
        kr_terms = ["코스피", "코스닥", "국내", "한국", "원달러", "삼성전자", "하이닉스", "외국인", "기관", "순매수", "순매도"]
        us_terms = ["nasdaq", "s&p", "dow", "fomc", "fed", "nvidia", "tesla", "apple", "google", "microsoft"]
        if any(t in text for t in kr_terms):
            return True
        if any(t in text for t in us_terms):
            return False
    if wanted == "미국주식":
        us_terms = ["nasdaq", "s&p", "dow", "fomc", "fed", "nvidia", "tesla", "apple", "google", "microsoft", "earnings"]
        kr_terms = ["코스피", "코스닥", "국내증시", "원달러", "외국인", "기관"]
        if any(t in text for t in us_terms):
            return True
        if any(t in text for t in kr_terms):
            return False
    return True


@st.cache_data(ttl=120, show_spinner=False)
def _load_stored_news_items(market: str = "전체", limit: int = 5) -> list[dict[str, str]]:
    """Load only recent real stored news rows.

    Rules for the first screen:
    - do not show sample rows
    - do not show old archived rows as today's news
    - do not replace missing news with candidate rows
    - de-duplicate similar headlines and cap at 5
    """
    candidates: list[dict[str, Any]] = []
    today = pd.Timestamp.now().normalize()
    max_limit = max(1, min(5, int(limit or 5)))

    for path in _news_paths():
        if path.suffix.lower() == ".json":
            # JSON news summaries vary a lot. Use only obvious list formats.
            data = _read_json(path)
            raw_items = data.get("items") or data.get("news") or data.get("rows") or [] if isinstance(data, dict) else []
            if not isinstance(raw_items, list):
                continue
            iterable = raw_items[:300]
        else:
            df = _read_csv(path)
            if df.empty:
                continue
            iterable = [r for _, r in df.head(600).iterrows()]

        for r in iterable:
            title = _first(r, NEWS_TITLE_COLS)
            if _is_empty(title) or len(str(title).strip()) < 8:
                continue
            if _is_sample_news_row(r):
                continue

            published_ts, published_raw = _news_datetime_from_row(r)
            if published_ts is None or not _is_recent_news_ts(published_ts, today=today, days=2):
                continue

            title = " ".join(str(title).split())
            summary_raw = _first(r, NEWS_SUMMARY_COLS)
            summary_clean = " ".join(str(summary_raw).replace("\n", " ").split())
            if len(summary_clean) > 180:
                summary_clean = summary_clean[:177] + "..."

            url = _first(r, NEWS_URL_COLS)
            source = _news_source_label_from_url(url, _first(r, NEWS_SOURCE_COLS))
            item = {
                "title": title,
                "summary": _simple_korean_news_summary(title, summary_clean, market),
                "source": source,
                "time": published_raw or _first(r, NEWS_TIME_COLS, "-"),
                "url": url,
                "ticker": _first(r, NEWS_TICKER_COLS),
                "market": _first(r, NEWS_MARKET_COLS),
                "importance": _first(r, ("importance", "importance_score", "중요도"), "0"),
                "path": str(path),
                "_signature": _normalize_news_signature(title),
                "_published_ts": published_ts,
                "_bucket": _news_recency_bucket(published_ts, today),
            }
            if not _news_matches_market(item, market):
                continue
            candidates.append(item)

    if not candidates:
        return []

    # Today's news first, then recent news. Within the same bucket, sort by time
    # and importance so the visible maximum 5 are the most useful ones.
    def _sort_key(item: dict[str, Any]) -> tuple:
        ts = item.get("_published_ts")
        try:
            tsv = pd.Timestamp(ts).timestamp() if ts is not None else 0
        except Exception:
            tsv = 0
        importance = _to_num(item.get("importance")) or 0
        return (int(item.get("_bucket", 99)), -tsv, -importance)

    sorted_items = sorted(candidates, key=_sort_key)
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in sorted_items:
        key = str(item.get("_signature", ""))
        if _is_similar_news(key, seen):
            continue
        seen.add(key)
        cleaned = {k: str(v) for k, v in item.items() if not k.startswith("_")}
        out.append(cleaned)
        if len(out) >= max_limit:
            break
    return out


def _news_issue_summary(market: str = "전체") -> None:
    """First-screen issue block: show real stored market/news items, not candidate rows."""
    sector = _read_json(REPORT_DIR / "intraday_sector_flow_summary.json")
    regime = _read_json(REPORT_DIR / "market_regime_summary.json")
    st.markdown('<div class="section-title">오늘의 뉴스·이슈 요약</div>', unsafe_allow_html=True)
    sector_items: list[str] = []
    top = sector.get("top_intraday_sectors")
    if isinstance(top, list) and top:
        sector_items.append("강세/관심 섹터: " + ", ".join(map(str, top[:4])))
    weak = sector.get("weak_intraday_sectors")
    if isinstance(weak, list) and weak:
        sector_items.append("약세/주의 섹터: " + ", ".join(map(str, weak[:4])))
    if regime:
        sector_items.append(f"시장 국면: {regime.get('market_regime', '-')} · 위험도 {regime.get('market_risk_level', '-')}")
        hb = regime.get("hardblock_reasons")
        if isinstance(hb, list) and hb:
            sector_items.append("주의 사유: " + ", ".join(map(str, hb[:3])))
    rows = _load_stored_news_items(market, limit=5)
    html_parts = ['<div class="home-section-card">']
    if sector_items:
        html_parts.append('<div class="candidate-item"><b>시장 요약</b><br>' + _e(" · ".join(sector_items[:3])) + '</div>')
    if rows:
        for item in rows:
            url = item.get("url", "")
            title = item.get("title", "")
            source = item.get("source", "뉴스")
            tm = item.get("time", "-")
            ticker = item.get("ticker", "")
            summary = item.get("summary", "")
            title_html = f'<a href="{_e(url)}" target="_blank" style="color:#f8fafc;text-decoration:none">{_e(title)}</a>' if url else _e(title)
            meta = " · ".join([x for x in [source, tm, ticker] if x and x != "-"])
            html_parts.append(
                '<div class="news-row">'
                '<div>'
                f'<div class="news-title">{title_html}</div>'
                f'<div class="news-meta">{_e(meta)}</div>'
                f'<div class="news-meta">{_e(summary) if summary else "뉴스 원문 제목 기준으로 확인하세요."}</div>'
                '</div>'
                '<div class="news-badge">뉴스</div>'
                '</div>'
            )
    else:
        dedup_status = _read_json(REPORT_DIR / "news_dedup_summary.json")
        status_note = ""
        if dedup_status:
            collected = dedup_status.get("collected_news_count", "-")
            deduped = dedup_status.get("deduped_news_count", "-")
            api_available = dedup_status.get("api_available", "-")
            fallback_used = dedup_status.get("fallback_used", "-")
            status_note = f"<br><span style='color:#64748b'>수집 {collected}건 · 중복제거 후 {deduped}건 · API {api_available} · fallback {fallback_used}</span>"
        html_parts.append(
            '<div class="candidate-empty">오늘 수집된 최신 뉴스가 없습니다. 뉴스 수집 상태를 확인하세요.'
            + status_note +
            '</div>'
        )
    html_parts.append('</div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)


def _available_feature_cards(market: str = "전체") -> list[tuple[str, str, str, str]]:
    """Return only features that are already backed by saved files in this app."""
    cards: list[tuple[str, str, str, str]] = []
    if (REPORT_DIR / "fundamental_valuation_detail.csv").exists() or (REPORT_DIR / "fundamental_valuation_summary.json").exists():
        cards.append(("💎", "종목 가치평가", "PER/PBR/PSR 같은 가격 부담과 실적 점수를 함께 보며 저평가 여부를 점검합니다.", "밸류·실적"))
        cards.append(("📋", "재무·실적 점검", "매출·이익·성장률 기반으로 실적이 개선되는 후보를 빠르게 확인합니다.", "실적 데이터"))
    if any((REPORT_DIR / f).exists() for f in ["buy_priority_candidates.csv", "watchlist_buy_candidates.csv", "swing_candidates.csv"]):
        cards.append(("🔍", "종목 스크리너", "수급·실적·밸류·차트 조건을 조합해 오늘 볼 후보를 자동으로 나눕니다.", "후보 분류"))
    if (REPORT_DIR / "portfolio_risk_summary.json").exists() or (DATA_DIR / "holdings_kr.csv").exists() or (DATA_DIR / "holdings_us.csv").exists():
        cards.append(("🏯", "보유 리스크 분석", "보유종목의 손절·익절·비중축소 기준을 정리해 대응 우선순위를 보여줍니다.", "보유/매도"))
    if (REPORT_DIR / "catalyst_validation_summary.json").exists() or (REPORT_DIR / "intraday_sector_flow_summary.json").exists():
        cards.append(("🔔", "뉴스·수급 이슈", "뉴스·공시·수급 변화가 후보 판단에 어떻게 연결되는지 요약합니다.", "Catalyst"))
    return cards[:6]


def _feature_cards_section(market: str = "전체") -> None:
    cards = _available_feature_cards(market)
    if not cards:
        return
    st.markdown('<div class="section-title">분석 도구 한눈에 보기</div>', unsafe_allow_html=True)
    html_parts = ['<div class="tool-grid">']
    for icon, title, desc, tag in cards:
        html_parts.append(
            f'<div class="tool-card"><h4>{_e(icon)} {_e(title)}</h4>'
            f'<p>{_e(desc)}</p><div class="tool-thumb">{_e(tag)}</div></div>'
        )
    html_parts.append('</div>')
    st.markdown(''.join(html_parts), unsafe_allow_html=True)

def _watchlist_quick(market: str) -> None:
    df = _concat_existing((DATA_DIR / "holdings_kr.csv", DATA_DIR / "holdings_us.csv"), market=None)
    if df.empty:
        return
    if market != "전체":
        mask = []
        for _, row in df.iterrows():
            mask.append(_row_market_strict(row, market) == market)
        df = df[pd.Series(mask, index=df.index)].copy()
    if df.empty:
        return
    st.markdown('<div class="section-title">내 보유/관심 빠른 점검</div>', unsafe_allow_html=True)
    rows = []
    for _, row in _dedupe_by_symbol(df, market).head(8).iterrows():
        mkt = _row_market_strict(row, market)
        sym = _symbol(row, mkt)
        nm = _name(row, sym)
        avg = _first(row, ("avg_price", "평균단가", "average_price"), "")
        qty = _first(row, ("quantity", "qty", "보유수량"), "")
        rows.append({"종목": f"{nm} {sym}", "평균단가": _format_price(avg, mkt) if avg else "입력 필요", "수량": qty or "입력 필요"})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _load_candidate_groups(market: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    buy = _dedupe_by_symbol(_concat_existing((REPORT_DIR / "buy_priority_candidates.csv",), market), market)
    watch = _dedupe_by_symbol(_concat_existing((REPORT_DIR / "watchlist_buy_candidates.csv",), market), market)
    swing = _dedupe_by_symbol(_concat_existing((REPORT_DIR / "swing_candidates.csv", REPORT_DIR / "swing_candidates_kr.csv", REPORT_DIR / "swing_candidates_us.csv"), market), market)
    risk = _dedupe_by_symbol(_concat_existing((REPORT_DIR / "swing_candidates_kr_C_excluded.csv", REPORT_DIR / "swing_candidates_us_C_excluded.csv"), market), market)

    priority = _rank(buy, ("total_score", "score", "종합점수", "supply_score", "수급점수"))
    pullback = _rank(watch if not watch.empty else buy, ("chart_score", "차트점수", "total_score", "score"))
    flow = _rank(swing if not swing.empty else buy, ("supply_score", "수급점수", "flow_score"))
    value = _rank(watch if not watch.empty else buy, ("valuation_score", "밸류에이션점수", "earnings_score", "실적점수"))
    danger = _rank(risk, ("risk_penalty", "리스크감점", "total_score", "score"))
    return priority, pullback, flow, value, danger


def render_execution_plan_home(market: str = "한국주식") -> None:
    """Fast first page: all essential sections visible, full lists tucked under expanders."""
    _inject_css()
    market = _market_from_value(market) or "한국주식"
    st.markdown(
        """
        <div class="home-hero">
            <h2>오늘의 실행 플랜</h2>
            <p>오늘 먼저 볼 후보와 실제 뉴스 이슈만 빠르게 보여줍니다. 줄이거나 기다릴 종목은 매수금지·주의 카드에서 필요할 때 확인하세요.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _market_summary_cards(market)

    priority, pullback, flow, value, danger = _load_candidate_groups(market)
    categories_raw = [
        ("🎯", "오늘 우선 확인", "조건이 가장 가까운 후보", "priority", priority),
        ("🪜", "눌림목 대기", "추격보다 진입가 대기", "pullback", pullback),
        ("💚", "수급 급증", "수급 변화 우선 확인", "flow", flow),
        ("💎", "실적·저평가", "실적과 밸류를 같이 확인", "value", value),
        ("🚫", "축소·주의", "매수보다 리스크 점검", "danger", danger),
    ]
    # Cards show real category counts. Do not turn categories into 0 just because the
    # same ticker also appears in an earlier category.
    categories = categories_raw
    distinct_categories = _split_distinct_categories(categories_raw, market)
    st.markdown('<div class="section-title">매수 후보 골라보기</div>', unsafe_allow_html=True)
    _category_cards_html(categories, market)

    # Main top lists are intentionally disjoint, but if a category becomes empty after
    # de-duplication, fall back to the original category so users do not see false 0s.
    priority_d, pullback_d, flow_d, value_d, danger_d = [x[4] for x in distinct_categories]
    if priority_d.empty:
        priority_d = priority
    if pullback_d.empty:
        pullback_d = pullback
    if flow_d.empty:
        flow_d = flow
    if value_d.empty:
        value_d = value
    if danger_d.empty:
        danger_d = danger
    _render_candidate_section("오늘 먼저 볼 종목", "TOP 3만 먼저 보여줍니다.", "🔥", priority_d, market, "home_priority", limit=3)

    _news_issue_summary(market)

    with st.expander("나머지 후보 카테고리 TOP 3 보기", expanded=False):
        for icon, title, desc, key, df in categories[1:4]:
            _render_candidate_section(title, desc, icon, df, market, f"home_{key}", limit=3, show_full_expander=False)
    with st.expander("후보 전체표 보기", expanded=False):
        for icon, title, desc, key, df in categories:
            st.markdown(f"**{icon} {title}**")
            if df is None or df.empty:
                st.info("표시할 후보가 없습니다.")
            else:
                st.dataframe(_preferred_columns(_dedupe_by_symbol(df, market), market, limit=80), use_container_width=True, hide_index=True)



def render_risk_candidates_page(market: str = "한국주식") -> None:
    """Lightweight risk candidate page that avoids heavy nested expanders."""
    _inject_css()
    market = _market_from_value(market) or "한국주식"
    st.markdown(
        """
        <div class="home-hero">
            <h2>매수 위험 후보</h2>
            <p>추격매수·신규매수 주의·제외 후보를 저장된 후보 CSV 기준으로 빠르게 보여줍니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, pullback, flow, value, danger = _load_candidate_groups(market)
    if danger is None or danger.empty:
        # If C/excluded files are empty, show the riskiest pullback/flow names rather than an error.
        danger = _rank(pd.concat([x for x in [pullback, flow, value] if isinstance(x, pd.DataFrame) and not x.empty], ignore_index=True) if any(isinstance(x, pd.DataFrame) and not x.empty for x in [pullback, flow, value]) else pd.DataFrame(), ("risk_penalty", "리스크감점", "total_score", "score"))
    _render_candidate_section("축소·주의 TOP", "신규매수보다 제외·관망이 우선인 후보입니다.", "🚫", danger, market, "risk_danger", limit=10)
    with st.expander("매수 위험 후보 전체 보기", expanded=False):
        if danger is None or danger.empty:
            st.info("표시할 매수 위험 후보가 없습니다.")
        else:
            st.dataframe(_preferred_columns(_dedupe_by_symbol(danger, market), market, limit=120), use_container_width=True, hide_index=True)

def render_dashboard(market: str = "한국주식") -> None:
    """Candidate summary page: card-first, top5-first, no duplicate ranking table."""
    _inject_css()
    market = _market_from_value(market) or "한국주식"
    st.markdown(
        """
        <div class="home-hero">
            <h2>후보 요약</h2>
            <p>후보를 목적별로 묶어 TOP 3부터 보여줍니다. 같은 종목이 여러 항목에 반복되지 않도록 요약 화면에서는 중복을 줄였습니다.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    priority, pullback, flow, value, danger = _load_candidate_groups(market)
    categories = [
        ("🎯", "오늘 우선 확인", "점수와 가격 기준을 먼저 확인할 후보", "priority", priority),
        ("🪜", "눌림목 진입 후보", "추격보다 눌림·조건부 진입을 기다릴 후보", "pullback", pullback),
        ("💚", "수급 급증 후보", "외국인·기관·거래대금 흐름을 우선 보는 후보", "flow", flow),
        ("💎", "실적·저평가 후보", "실적과 밸류를 같이 확인할 후보", "value", value),
        ("🚫", "매수금지·주의", "신규매수보다 제외·관망이 우선인 후보", "danger", danger),
    ]

    _category_cards_html(categories, market)
    for icon, title, desc, key, df in categories:
        _render_candidate_section(title, desc, icon, df, market, f"dashboard_{key}", limit=3)

    with st.expander("관리자용 원본 파일 상태", expanded=False):
        rows = []
        source_groups = {
            "buy_priority": _concat_existing((REPORT_DIR / "buy_priority_candidates.csv",), market),
            "watchlist": _concat_existing((REPORT_DIR / "watchlist_buy_candidates.csv",), market),
            "swing": _concat_existing((REPORT_DIR / "swing_candidates.csv", REPORT_DIR / "swing_candidates_kr.csv", REPORT_DIR / "swing_candidates_us.csv"), market),
            "risk": _concat_existing((REPORT_DIR / "swing_candidates_kr_C_excluded.csv", REPORT_DIR / "swing_candidates_us_C_excluded.csv"), market),
        }
        for name, df in source_groups.items():
            rows.append({"파일그룹": name, "행수": len(df) if isinstance(df, pd.DataFrame) else 0})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
