from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", APP_DIR.parent)).resolve()
REPORT_DIR = REPO_ROOT / "reports"
DATA_DIR = REPO_ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"

load_dotenv(REPO_ROOT / ".env")
load_dotenv(APP_DIR / "backend" / ".env")

DEFAULT_VERSION_PRIORITY = ("v92", "v93", "v91", "v85")
FALLBACK_POLICY = ("v93", "v92", "v91", "v85")

REQUIRED_FILES = [
    "reports/v92_symbol_snapshot_kr.csv",
    "reports/v92_symbol_snapshot_us.csv",
    "reports/v92_position_cards_kr.csv",
    "reports/v92_position_cards_us.csv",
    "reports/v92_action_cards_kr.csv",
    "reports/v92_action_cards_us.csv",
    "reports/v92_pullback_cards_kr.csv",
    "reports/v92_pullback_cards_us.csv",
    "reports/v92_flow_cards_kr.csv",
    "reports/v92_flow_cards_us.csv",
    "reports/v92_risk_cards_kr.csv",
    "reports/v92_risk_cards_us.csv",
    "reports/v92_news_summary_kr.csv",
    "reports/v92_news_summary_us.csv",
    "reports/v92_company_integrated_kr.csv",
    "reports/v92_company_integrated_us.csv",
    "predictions.csv",
    "data/history/prediction_history.csv",
    "data/history/outcome_history.csv",
    "watchlist_kr_growth.csv",
    "watchlist_us_growth.csv",
    "watchlist_kr.csv",
    "watchlist_us.csv",
    "candidate_universe_kr.csv",
    "candidate_universe_us.csv",
    "data/holdings_kr.csv",
    "data/holdings_us.csv",
    "daily_watch_selection.json",
]

ENV_KEYS = [
    "GNEWS_API_KEY",
    "FINNHUB_API_KEY",
    "DART_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "KIS_ACCOUNT_NO",
    "KIS_ACCOUNT",
    "KIS_CANO",
    "KIS_ACNT_PRDT_CD",
    "SEC_USER_AGENT",
]


def _safe_str(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text.lower() in {"nan", "none", "nat", "null"}:
        return fallback
    return text or fallback


def _safe_float(value: Any) -> float | None:
    try:
        text = _safe_str(value).replace(",", "").replace("%", "").replace("$", "").strip()
        if not text or text == "-":
            return None
        out = float(text)
        if np.isnan(out) or np.isinf(out):
            return None
        return out
    except Exception:
        return None


def _market_label(market: str) -> str:
    return "한국주식" if market == "kr" else "미국주식"


def _market_candidates(market: str) -> set[str]:
    if market == "kr":
        return {"kr", "KR", "한국주식", "국장", "KOSPI", "KOSDAQ"}
    return {"us", "US", "미국주식", "미장", "USA", "NASDAQ", "NYSE"}


def normalize_symbol(symbol: Any, market: str = "") -> str:
    text = _safe_str(symbol).upper()
    text = text.replace(".KS", "").replace(".KQ", "")
    if market == "kr" and text.isdigit() and len(text) < 6:
        return text.zfill(6)
    return text


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=encoding, low_memory=False).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            data = json.loads(path.read_text(encoding=encoding))
            return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}


def rows_for(path: Path) -> int:
    if path.suffix.lower() == ".csv":
        return int(len(read_csv(path)))
    if path.suffix.lower() == ".json":
        data = read_json(path)
        return int(len(data)) if data else 0
    return 0


def file_mtime(path: Path) -> str:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def first_value(row: dict[str, Any] | pd.Series, names: list[str], fallback: str = "") -> str:
    for name in names:
        if name in row:
            text = _safe_str(row.get(name), "")
            if text and text != "-":
                return text
    return fallback


def first_number(row: dict[str, Any] | pd.Series, names: list[str]) -> float | None:
    for name in names:
        if name in row:
            num = _safe_float(row.get(name))
            if num is not None:
                return num
    return None


def report_path(kind: str, market: str, versions: tuple[str, ...] = DEFAULT_VERSION_PRIORITY) -> Path | None:
    for version in versions:
        path = REPORT_DIR / f"{version}_{kind}_{market}.csv"
        if path.exists() and path.stat().st_size > 0 and rows_for(path) > 0:
            return path
    return None


def read_report(kind: str, market: str, versions: tuple[str, ...] = DEFAULT_VERSION_PRIORITY) -> tuple[pd.DataFrame, str]:
    path = report_path(kind, market, versions)
    if path is None:
        return pd.DataFrame(), ""
    return read_csv(path), path.relative_to(REPO_ROOT).as_posix()


def dataframe_records(df: pd.DataFrame, limit: int | None = None) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    work = df.head(limit).copy() if limit else df.copy()
    return work.replace({np.nan: ""}).to_dict(orient="records")


def normalize_security_row(row: dict[str, Any] | pd.Series, market: str) -> dict[str, Any]:
    symbol = normalize_symbol(first_value(row, ["symbol", "ticker", "code", "종목코드", "종목", "stock_code"]), market)
    name = first_value(row, ["name", "종목명", "stock_name", "종목", "회사명"], symbol or "이름 없음")
    current_price = first_number(row, ["current_price", "last_price", "현재가", "실시간현재가", "quote_fallback_price", "기준가"])
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "marketLabel": _market_label(market),
        "currentPrice": current_price,
        "currentPriceText": format_price(current_price, market) if current_price else "기준가 없음",
        "priceTime": first_value(row, ["가격기준시각", "last_time", "updated_at", "created_at"], "기준시각 없음"),
        "priceSource": first_value(row, ["가격출처", "quote_source_label", "quote_source", "current_price_source", "price_source"], "가격출처 없음"),
        "dataStatus": first_value(row, ["data_status", "price_data_status", "데이터상태"], "상태 없음"),
        "entry": first_number(row, ["기준가", "preferred_entry", "entry", "조건부 진입가", "매수가"]),
        "stop": first_number(row, ["손절가", "stop_loss", "stop"]),
        "target": first_number(row, ["목표가", "take_profit1", "tp1", "1차 목표가"]),
        "raw": dict(row),
    }


def format_price(value: float | None, market: str) -> str:
    if value is None:
        return "기준가 없음"
    if market == "us":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def status_files() -> dict[str, Any]:
    items = []
    for rel in REQUIRED_FILES:
        path = REPO_ROOT / rel
        items.append({
            "path": rel,
            "exists": path.exists(),
            "status": "OK" if path.exists() and path.stat().st_size > 0 else "MISSING",
            "bytes": path.stat().st_size if path.exists() else 0,
            "rows": rows_for(path) if path.exists() else 0,
            "updatedAt": file_mtime(path) if path.exists() else "",
        })
    return {
        "repoRoot": str(REPO_ROOT),
        "fallbackPolicy": list(FALLBACK_POLICY),
        "defaultVersionPriority": list(DEFAULT_VERSION_PRIORITY),
        "items": items,
    }


def status_env() -> dict[str, Any]:
    items = []
    for key in ENV_KEYS:
        value = os.environ.get(key, "")
        items.append({"key": key, "status": "OK" if value else "MISSING"})
    return {"items": items}


def market_summary(market: str) -> dict[str, Any]:
    summary, source = read_report("today_summary", market)
    data_status, data_source = read_report("data_status", market)
    dashboard, dash_source = read_report("operational_dashboard", market)
    status_path = REPORT_DIR / "v93_github_actions_status.json"
    status = read_json(status_path)
    sources = [source, data_source, dash_source]
    return {
        "market": market,
        "marketLabel": _market_label(market),
        "cards": dataframe_records(summary),
        "dataStatus": dataframe_records(data_status),
        "dashboard": dataframe_records(dashboard),
        "automation": status,
        "sources": [s for s in sources if s],
        "updatedAt": latest_updated_at(),
    }


def latest_updated_at() -> str:
    candidates = [
        REPORT_DIR / "v92_symbol_snapshot_kr.csv",
        REPORT_DIR / "v92_symbol_snapshot_us.csv",
        REPORT_DIR / "v92_news_summary_kr.csv",
        REPORT_DIR / "v93_github_actions_status.json",
    ]
    times = [file_mtime(path) for path in candidates if path.exists()]
    return max(times) if times else "기준시각 없음"


def symbols(market: str) -> dict[str, Any]:
    df, source = read_report("symbol_snapshot", market)
    if df.empty:
        df = read_csv(REPO_ROOT / f"watchlist_{market}_growth.csv")
        source = f"watchlist_{market}_growth.csv" if not df.empty else ""
    rows = [normalize_security_row(row, market) for row in dataframe_records(df)]
    return {"market": market, "count": len(rows), "source": source, "items": rows}


def symbol_detail(symbol: str, market: str) -> dict[str, Any]:
    target = normalize_symbol(symbol, market)
    all_symbols = symbols(market)
    item = next((row for row in all_symbols["items"] if normalize_symbol(row["symbol"], market) == target), None)
    candidates = {}
    for kind in ("action", "pullback", "flow", "risk"):
        cand = candidate_rows(market, kind)
        candidates[kind] = [row for row in cand["items"] if normalize_symbol(row["symbol"], market) == target]
    company_df, company_source = read_report("company_integrated", market)
    company = []
    if not company_df.empty:
        for row in dataframe_records(company_df):
            if normalize_symbol(first_value(row, ["symbol", "ticker", "code", "종목코드"]), market) == target:
                company.append(row)
    news = [row for row in news_rows(market)["items"] if normalize_symbol(row.get("symbol"), market) == target]
    return {
        "market": market,
        "symbol": target,
        "item": item,
        "candidates": candidates,
        "company": company,
        "companySource": company_source,
        "news": news,
    }


def candidate_rows(market: str, kind: str) -> dict[str, Any]:
    allowed = {"action", "pullback", "flow", "risk"}
    if kind not in allowed:
        kind = "action"
    df, source = read_report(f"{kind}_cards", market)
    rows = []
    for row in dataframe_records(df):
        normalized = normalize_security_row(row, market)
        normalized.update({
            "category": first_value(row, ["분류", "category"], kind),
            "confidence": first_number(row, ["신뢰도점수", "confidence_score", "score"]),
            "reason": first_value(row, ["핵심근거", "근거1", "설명"], "근거 없음"),
            "warning": first_value(row, ["주의점", "주의", "risk_warning_flags"], "주의사항 없음"),
            "nextAction": first_value(row, ["다음행동", "suggested_action", "final_judgment"], "다음 행동 없음"),
        })
        rows.append(normalized)
    return {"market": market, "type": kind, "count": len(rows), "source": source, "items": rows}


def positions(market: str) -> dict[str, Any]:
    df, source = read_report("position_cards", market)
    if df.empty:
        fallback = DATA_DIR / f"holdings_{market}.csv"
        df = read_csv(fallback)
        source = fallback.relative_to(REPO_ROOT).as_posix() if not df.empty else ""
    rows = []
    for row in dataframe_records(df):
        normalized = normalize_security_row(row, market)
        normalized.update({
            "quantity": first_number(row, ["quantity", "보유수량", "shares"]),
            "avgPrice": first_number(row, ["avg_price", "평균단가", "평단가"]),
            "returnPct": first_value(row, ["수익률", "unrealized_return_pct"], "수익률 없음"),
            "pnl": first_value(row, ["평가손익", "unrealized_pnl"], "평가손익 없음"),
            "nextAction": first_value(row, ["다음행동", "조치", "memo"], "다음 행동 없음"),
        })
        rows.append(normalized)
    return {"market": market, "count": len(rows), "source": source, "items": rows}


def news_rows(market: str) -> dict[str, Any]:
    df, source = read_report("news_summary", market)
    rows = []
    for row in dataframe_records(df):
        rows.append({
            "market": market,
            "title": first_value(row, ["제목", "title", "headline"], "뉴스 없음"),
            "summary": first_value(row, ["3줄요약", "summary", "핵심요약"], "요약 없음"),
            "sourceName": first_value(row, ["출처", "source"], "출처 없음"),
            "url": first_value(row, ["URL", "url"], ""),
            "publishedAt": first_value(row, ["게시시간", "published_at", "time"], "게시시간 없음"),
            "symbol": normalize_symbol(first_value(row, ["종목코드", "symbol", "ticker"], ""), market),
            "name": first_value(row, ["종목명", "name"], ""),
            "nextAction": first_value(row, ["다음행동"], "다음 행동 없음"),
            "raw": row,
        })
    return {"market": market, "count": len(rows), "source": source, "items": rows}


def predictions(market: str) -> dict[str, Any]:
    df, source = read_report("future_probability", market)
    rows = []
    for row in dataframe_records(df):
        normalized = normalize_security_row(row, market)
        normalized.update({
            "prob1d": first_value(row, ["1일상승확률", "prob_up_1d"], "확률 없음"),
            "prob3d": first_value(row, ["3일상승확률", "prob_up_3d"], "확률 없음"),
            "prob5d": first_value(row, ["5일상승확률", "prob_up_5d"], "확률 없음"),
            "confidence": first_value(row, ["신뢰도점수", "confidence_score"], "신뢰도 없음"),
            "nextAction": first_value(row, ["다음행동"], "다음 행동 없음"),
        })
        rows.append(normalized)
    return {"market": market, "count": len(rows), "source": source, "items": rows}


def prediction_history() -> dict[str, Any]:
    path = HISTORY_DIR / "prediction_history.csv"
    df = read_csv(path)
    return {
        "count": int(len(df)),
        "source": path.relative_to(REPO_ROOT).as_posix(),
        "items": dataframe_records(df, 250),
    }


def outcome_history() -> dict[str, Any]:
    path = HISTORY_DIR / "outcome_history.csv"
    df = read_csv(path)
    return {
        "count": int(len(df)),
        "source": path.relative_to(REPO_ROOT).as_posix(),
        "items": dataframe_records(df, 250),
    }
