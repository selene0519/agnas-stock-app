from __future__ import annotations

import json
import os
import re
import requests
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
CACHE_DIR = APP_DIR / "backend" / "cache"
QUOTE_CACHE_FILE = CACHE_DIR / "quotes_cache.json"

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

MISSING_TOKENS = {"", "-", "nan", "none", "nat", "null", "n/a", "na", "없음"}

SYMBOL_ALIASES = ["symbol", "ticker", "code", "종목코드", "종목", "stock_code"]
NAME_ALIASES = ["name", "종목명", "stock_name", "종목", "회사명"]
CURRENT_PRICE_ALIASES = ["current_price", "last_price", "현재가", "실시간현재가", "quote_fallback_price"]
PRICE_TIME_ALIASES = ["가격기준시각", "updated_at", "last_time", "quote_time", "price_time", "갱신시각"]
PRICE_SOURCE_ALIASES = ["가격출처", "quote_source_label", "quote_source", "current_price_source", "source"]
ENTRY_ALIASES = ["기준가", "관찰 기준가", "active_scenario_pullback_price", "조건부 진입가", "매수가", "entry", "entry_price", "buy_price"]
STOP_ALIASES = ["손절가", "stop", "stop_loss"]
TARGET_ALIASES = ["목표가", "1차 목표가", "tp1", "target_price", "2차 목표가", "tp2"]
TARGET2_ALIASES = ["2차 목표가", "tp2", "take_profit2"]
EXPECTED_PRICE_ALIASES = {
    "1d": ["1일예상가", "1일 예상가", "예상가_1일", "expected_price_1d", "pred_price_1d", "predicted_price_1d", "price_1d", "target_price_1d"],
    "3d": ["3일예상가", "3일 예상가", "예상가_3일", "expected_price_3d", "pred_price_3d", "predicted_price_3d", "price_3d", "target_price_3d"],
    "5d": ["5일예상가", "5일 예상가", "예상가_5일", "expected_price_5d", "pred_price_5d", "predicted_price_5d", "price_5d", "target_price_5d"],
    "20d": ["20일예상가", "20일 예상가", "예상가_20일", "expected_price_20d", "pred_price_20d", "predicted_price_20d", "price_20d", "target_price_20d", "midterm_expected_price"],
}
SUPPLY_SCORE_ALIASES = ["수급점수", "수급 점수", "supply_score", "flow_score"]
EARNINGS_SCORE_ALIASES = ["실적점수", "실적 점수", "earnings_score"]
VALUATION_SCORE_ALIASES = ["밸류에이션점수", "밸류에이션 점수", "벨류에이션점수", "valuation_score"]
CHART_SCORE_ALIASES = ["차트점수", "차트 점수", "chart_score"]
DATA_STATUS_ALIASES = ["data_status", "price_data_status", "earnings_data_status", "valuation_data_status", "flow_data_status"]

MERGE_ALIAS_GROUPS = [
    SYMBOL_ALIASES,
    NAME_ALIASES,
    CURRENT_PRICE_ALIASES,
    PRICE_TIME_ALIASES,
    PRICE_SOURCE_ALIASES,
    ENTRY_ALIASES,
    STOP_ALIASES,
    TARGET_ALIASES,
    SUPPLY_SCORE_ALIASES,
    EARNINGS_SCORE_ALIASES,
    VALUATION_SCORE_ALIASES,
    CHART_SCORE_ALIASES,
    DATA_STATUS_ALIASES,
    ["다음행동", "nextAction", "suggested_action", "final_judgment"],
    ["예상시초가", "pred_open_mid", "pred_open", "expected_open", "premarket_price"],
    ["예상종가", "pred_close_mid", "pred_close", "expected_close"],
    ["손익비", "rr", "rr1", "risk_reward", "risk_reward_ratio"],
]


def _safe_str(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if text.lower() in MISSING_TOKENS:
        return fallback
    return text or fallback


def _is_missing(value: Any) -> bool:
    return _safe_str(value, "") == ""


def _safe_float(value: Any) -> float | None:
    try:
        text = _safe_str(value)
        if not text:
            return None
        text = text.replace(",", "").replace("%", "")
        text = re.sub(r"[^0-9.+-]", "", text)
        if not text or text in {".", "+", "-"}:
            return None
        out = float(text)
        if np.isnan(out) or np.isinf(out):
            return None
        return out
    except Exception:
        return None


def _market_label(market: str) -> str:
    return "한국주식" if market == "kr" else "미국주식"


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


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
            if text:
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


def quote_cache() -> dict[str, Any]:
    data = read_json(QUOTE_CACHE_FILE)
    if not data:
        return {"updatedAt": "", "markets": {"kr": {}, "us": {}}}
    data.setdefault("markets", {})
    data["markets"].setdefault("kr", {})
    data["markets"].setdefault("us", {})
    return data


def save_quote_cache(cache: dict[str, Any]) -> None:
    write_json(QUOTE_CACHE_FILE, cache)


def cached_quote_for(symbol: str, market: str) -> dict[str, Any]:
    cache = quote_cache()
    return dict((cache.get("markets", {}).get(market, {}) or {}).get(normalize_symbol(symbol, market), {}) or {})


def apply_quote_cache(row: dict[str, Any], market: str) -> dict[str, Any]:
    symbol = _row_symbol(row, market)
    cached = cached_quote_for(symbol, market) if symbol else {}
    if not cached or not cached.get("ok"):
        return row
    price = cached.get("currentPrice")
    if _safe_float(price) is None:
        return row
    merged = dict(row)
    merged["current_price"] = str(price)
    merged["last_price"] = str(price)
    merged["quote_fallback_price"] = str(price)
    merged["가격기준시각"] = cached.get("priceTime", "") or "현재가 기준시각 없음"
    merged["가격출처"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["quote_source_label"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["quote_source"] = cached.get("source", "") or cached.get("priceSource", "") or "가격출처 없음"
    merged["current_price_source"] = cached.get("priceSource", "") or "가격출처 없음"
    merged["data_status"] = "현재가 캐시 반영"
    merged["price_data_status"] = "cache_success"
    return merged


def _row_symbol(row: dict[str, Any] | pd.Series, market: str) -> str:
    return normalize_symbol(first_value(row, SYMBOL_ALIASES), market)


def _records_by_symbol(df: pd.DataFrame, market: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in dataframe_records(df):
        symbol = _row_symbol(row, market)
        if symbol and symbol not in out:
            out[symbol] = row
    return out


def _group_has_value(row: dict[str, Any], aliases: list[str]) -> bool:
    return any((name in row and not _is_missing(row.get(name))) for name in aliases)


def _merge_alias_values(base: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for aliases in MERGE_ALIAS_GROUPS:
        if _group_has_value(merged, aliases):
            continue
        for name in aliases:
            if name in fallback and not _is_missing(fallback.get(name)):
                merged[name] = fallback.get(name)
                break
    return merged


def enrich_records_with_version_fallback(kind: str, market: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows

    fallback_maps: list[dict[str, dict[str, Any]]] = []
    for version in FALLBACK_POLICY:
        path = REPORT_DIR / f"{version}_{kind}_{market}.csv"
        if path.exists() and path.stat().st_size > 0:
            fallback_maps.append(_records_by_symbol(read_csv(path), market))

    enriched: list[dict[str, Any]] = []
    for row in rows:
        symbol = _row_symbol(row, market)
        merged = dict(row)
        if symbol:
            for fallback_map in fallback_maps:
                fallback = fallback_map.get(symbol)
                if fallback:
                    merged = _merge_alias_values(merged, fallback)
        enriched.append(merged)
    return enriched


def enrich_records_from_file(rows: list[dict[str, Any]], path: Path, market: str) -> list[dict[str, Any]]:
    fallback_map = _records_by_symbol(read_csv(path), market)
    if not fallback_map:
        return rows
    enriched = []
    for row in rows:
        symbol = _row_symbol(row, market)
        enriched.append(_merge_alias_values(row, fallback_map.get(symbol, {})) if symbol else row)
    return enriched


def format_price(value: float | None, market: str) -> str:
    if value is None:
        return "현재가 없음"
    if market == "us":
        return f"${value:,.2f}"
    return f"{value:,.0f}원"


def format_signed_money(value: float | None, market: str, missing: str = "평가손익 없음") -> str:
    if value is None:
        return missing
    sign = "+" if value > 0 else ""
    if market == "us":
        return f"{sign}${value:,.2f}"
    return f"{sign}{value:,.0f}원"


def format_percent(value: float | None, missing: str = "수익률 없음") -> str:
    if value is None:
        return missing
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"



def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _format_probability(value: float | None) -> str:
    if value is None:
        return "확률 산출 필요"
    return f"{_clamp(value, 1, 99):.1f}%"


def _extract_percent(value: Any) -> float | None:
    num = _safe_float(value)
    if num is None:
        return None
    if 0 <= num <= 1:
        return num * 100
    return num


def _ohlcv_column(df: pd.DataFrame, aliases: list[str]) -> str | None:
    lower = {str(c).strip().lower(): c for c in df.columns}
    for alias in aliases:
        key = alias.lower()
        if key in lower:
            return lower[key]
    return None


def _find_ohlcv_candidates(symbol: str, market: str) -> list[Path]:
    symbol = normalize_symbol(symbol, market)
    names = [
        f"{market}_{symbol}_daily.csv",
        f"{market}_{symbol}_ohlcv.csv",
        f"{symbol}_daily.csv",
        f"{symbol}_ohlcv.csv",
        f"ohlcv_{market}_{symbol}.csv",
        f"chart_{market}_{symbol}.csv",
    ]
    roots = [DATA_DIR / "market", DATA_DIR / "chart", DATA_DIR / "ohlcv", DATA_DIR, REPORT_DIR]
    found: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for name in names:
            p = base / name
            if p.exists() and p.is_file() and p.stat().st_size > 0:
                found.append(p)
        for p in base.rglob("*.csv"):
            low = p.name.lower()
            if symbol.lower() in low and any(token in low for token in ("daily", "ohlcv", "chart")):
                found.append(p)
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = p.resolve().as_posix()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def _normalize_ohlcv_dataframe(df: pd.DataFrame, symbol: str, market: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    symbol_col = _ohlcv_column(work, ["symbol", "ticker", "code", "종목코드"])
    if symbol_col:
        norm = work[symbol_col].map(lambda v: normalize_symbol(v, market))
        target = normalize_symbol(symbol, market)
        filtered = work[norm == target]
        if not filtered.empty:
            work = filtered
    date_col = _ohlcv_column(work, ["date", "날짜", "일자", "datetime", "time"])
    open_col = _ohlcv_column(work, ["open", "시가"])
    high_col = _ohlcv_column(work, ["high", "고가"])
    low_col = _ohlcv_column(work, ["low", "저가"])
    close_col = _ohlcv_column(work, ["close", "종가", "adj_close", "adj close"])
    volume_col = _ohlcv_column(work, ["volume", "거래량"])
    if not close_col:
        return pd.DataFrame()
    out = pd.DataFrame()
    out["date"] = work[date_col].astype(str) if date_col else [str(i + 1) for i in range(len(work))]
    out["open"] = work[open_col].map(_safe_float) if open_col else work[close_col].map(_safe_float)
    out["high"] = work[high_col].map(_safe_float) if high_col else work[close_col].map(_safe_float)
    out["low"] = work[low_col].map(_safe_float) if low_col else work[close_col].map(_safe_float)
    out["close"] = work[close_col].map(_safe_float)
    out["volume"] = work[volume_col].map(_safe_float) if volume_col else 0
    out = out.dropna(subset=["close"]).copy()
    if out.empty:
        return out
    out["date_sort"] = pd.to_datetime(out["date"], errors="coerce")
    if out["date_sort"].notna().any():
        out = out.sort_values("date_sort")
    return out.drop(columns=["date_sort"], errors="ignore").tail(240).reset_index(drop=True)


def _load_ohlcv(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    for path in _find_ohlcv_candidates(symbol, market):
        df = _normalize_ohlcv_dataframe(read_csv(path), symbol, market)
        if not df.empty and len(df) >= 5:
            return df, path.relative_to(REPO_ROOT).as_posix()
    return pd.DataFrame(), ""


def _ohlcv_stats(symbol: str, market: str) -> dict[str, float | str | int]:
    df, source = _load_ohlcv(symbol, market)
    if df.empty:
        return {"source": source, "rows": 0, "avgReturn": 0.001, "volatility": 0.022, "gapAvg": 0.0, "lastClose": 0.0}
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 2:
        return {"source": source, "rows": len(df), "avgReturn": 0.001, "volatility": 0.022, "gapAvg": 0.0, "lastClose": float(close.iloc[-1]) if len(close) else 0.0}
    returns = close.pct_change().dropna()
    avg_return = float(returns.tail(20).mean()) if len(returns) else 0.001
    volatility = float(returns.tail(60).std()) if len(returns) > 3 else 0.022
    if not np.isfinite(volatility) or volatility <= 0:
        volatility = 0.022
    gap_avg = 0.0
    if "open" in df and len(df) >= 2:
        prev_close = close.shift(1)
        open_values = pd.to_numeric(df["open"], errors="coerce")
        gaps = ((open_values - prev_close) / prev_close).replace([np.inf, -np.inf], np.nan).dropna()
        if len(gaps):
            gap_avg = float(gaps.tail(20).mean())
    return {
        "source": source,
        "rows": len(df),
        "avgReturn": avg_return if np.isfinite(avg_return) else 0.001,
        "volatility": _clamp(volatility, 0.004, 0.08),
        "gapAvg": _clamp(gap_avg, -0.04, 0.04),
        "lastClose": float(close.iloc[-1]),
    }


def _confidence_value(row: dict[str, Any] | pd.Series) -> float:
    raw = first_number(row, ["신뢰도점수", "confidence_score", "confidence", "score", "risk_confidence_score"])
    if raw is None:
        return 55.0
    return _clamp(raw, 0, 100)


def _derive_price_levels(row: dict[str, Any] | pd.Series, market: str, current: float | None, entry: float | None, stop: float | None, target: float | None, symbol: str) -> tuple[float | None, float | None, float | None]:
    if current is None or current <= 0:
        return entry, stop, target
    stats = _ohlcv_stats(symbol, market) if symbol else {"volatility": 0.022}
    daily_vol = float(stats.get("volatility", 0.022) or 0.022)
    risk_pct = _clamp(daily_vol * 2.8, 0.045, 0.095)
    reward_pct = _clamp(risk_pct * 1.75, 0.075, 0.18)
    if entry is None:
        entry = current * (0.992 if market == "kr" else 0.995)
    if stop is None and entry:
        stop = entry * (1 - risk_pct)
    if target is None and entry:
        target = entry * (1 + reward_pct)
    return entry, stop, target


def _derived_probability_and_price(row: dict[str, Any] | pd.Series, market: str, symbol: str, current: float | None, entry: float | None) -> dict[str, Any]:
    if current is None or current <= 0:
        return {}
    stats = _ohlcv_stats(symbol, market) if symbol else {"avgReturn": 0.001, "volatility": 0.022, "rows": 0, "source": ""}
    avg_ret = float(stats.get("avgReturn", 0.001) or 0.001)
    vol = float(stats.get("volatility", 0.022) or 0.022)
    confidence = _confidence_value(row)
    confidence_edge = (confidence - 50) / 1000
    gap_penalty = 0.0
    if entry:
        gap = (current - entry) / entry
        gap_penalty = -max(0.0, gap - 0.02) * 0.10
    out: dict[str, Any] = {}
    for key, days in (("1d", 1), ("3d", 3), ("5d", 5), ("20d", 20)):
        existing_prob = first_value(row, [f"{days}일상승확률", f"prob_up_{days}d", f"prob{days}d", f"{days}d_probability", f"probability_{days}d"], "")
        existing_price = first_number(row, EXPECTED_PRICE_ALIASES.get(key, []))
        horizon_edge = avg_ret * days + confidence_edge * np.sqrt(days) + gap_penalty
        horizon_edge = _clamp(float(horizon_edge), -0.12, 0.28 if days >= 20 else 0.16)
        sigma = max(0.01, vol * np.sqrt(days))
        prob = _clamp(50 + (horizon_edge / sigma) * 10, 38, 74)
        expected = existing_price if existing_price is not None else current * (1 + horizon_edge)
        out[f"prob_{key}"] = existing_prob or _format_probability(prob)
        out[f"expected_{key}"] = expected
        out[f"expected_{key}_text"] = format_price(expected, market)
    out["predictionModelNote"] = "OHLCV·신뢰도·기준가거리 기반 추정" if stats.get("rows", 0) else "현재가·신뢰도 기반 임시 추정"
    return out


def _derive_open_close(row: dict[str, Any] | pd.Series, market: str, symbol: str, current: float | None) -> tuple[float | None, float | None]:
    explicit_open = first_number(row, ["예상시초가", "pred_open_mid", "pred_open", "expected_open", "premarket_price"])
    explicit_close = first_number(row, ["예상종가", "pred_close_mid", "pred_close", "expected_close"])
    if current is None or current <= 0:
        return explicit_open, explicit_close
    stats = _ohlcv_stats(symbol, market) if symbol else {"avgReturn": 0.001, "gapAvg": 0.0, "volatility": 0.022}
    gap_avg = float(stats.get("gapAvg", 0.0) or 0.0)
    avg_ret = float(stats.get("avgReturn", 0.001) or 0.001)
    confidence_edge = (_confidence_value(row) - 50) / 1800
    expected_open = explicit_open if explicit_open is not None else current * (1 + _clamp(gap_avg + confidence_edge, -0.04, 0.04))
    intraday_edge = _clamp(avg_ret * 0.75 + confidence_edge, -0.05, 0.06)
    expected_close = explicit_close if explicit_close is not None else expected_open * (1 + intraday_edge)
    return expected_open, expected_close




TRADE_MODE_SETTINGS: dict[str, dict[str, Any]] = {
    "conservative": {
        "label": "보수",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "기준가 이하 또는 기준가 근처에서만 체결",
        "entry_tolerance_pct": 0.0,
        "hold_days": 5,
        "target_first": False,
        "slippage_pct": 0.003,
    },
    "balanced": {
        "label": "균형",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "기준가 ±1% 이내면 체결",
        "entry_tolerance_pct": 0.01,
        "hold_days": 5,
        "target_first": False,
        "slippage_pct": 0.002,
    },
    "aggressive": {
        "label": "공격",
        "capital_kr": 1_000_000,
        "capital_us": 1_000,
        "buy_rule": "현재가 또는 예상 시초가 기준 체결",
        "entry_tolerance_pct": 0.025,
        "hold_days": 1,
        "target_first": True,
        "slippage_pct": 0.001,
    },
}


def _risk_reward_values(entry: float | None, stop: float | None, target: float | None) -> tuple[float | None, float | None, float | None]:
    if entry is None or stop is None or target is None or entry <= 0:
        return None, None, None
    risk = abs(entry - stop)
    reward = abs(target - entry)
    if risk <= 0 or reward <= 0:
        return None, None, None
    return risk, reward, reward / risk


def _swing_grade(row: dict[str, Any] | pd.Series, current: float | None, entry: float | None, stop: float | None, target: float | None) -> str:
    risk, reward, rr = _risk_reward_values(entry, stop, target)
    if entry is None or current is None or rr is None:
        return "C"
    confidence = _confidence_value(row)
    gap = abs((current - entry) / entry) if entry else 1.0
    risk_pct = (risk / entry) if risk else 1.0
    if rr >= 1.55 and gap <= 0.035 and risk_pct <= 0.09 and confidence >= 54:
        return "A"
    if rr >= 1.20 and gap <= 0.08 and risk_pct <= 0.13 and confidence >= 48:
        return "B"
    return "C"


def _recommendation_modes(grade: str, current: float | None, entry: float | None, stop: float | None, target: float | None) -> list[str]:
    risk, reward, rr = _risk_reward_values(entry, stop, target)
    if entry is None or current is None or stop is None or target is None or rr is None:
        return []
    gap = (current - entry) / entry if entry else 0
    risk_pct = (risk / entry) if risk else 1.0
    modes: list[str] = []
    if grade == "A" and gap <= 0.035 and risk_pct <= 0.09 and rr >= 1.45:
        modes.append("conservative")
    if grade in {"A", "B"} and gap <= 0.08 and risk_pct <= 0.13 and rr >= 1.15:
        modes.append("balanced")
    if grade in {"A", "B", "C"} and gap <= 0.14 and risk_pct <= 0.18:
        modes.append("aggressive")
    return modes


def _trade_plan_for_mode(market: str, mode: str, current: float | None, entry: float | None, stop: float | None, target: float | None, expected_open: float | None = None) -> dict[str, Any]:
    settings = TRADE_MODE_SETTINGS.get(mode, TRADE_MODE_SETTINGS["balanced"])
    capital = float(settings["capital_us"] if market == "us" else settings["capital_kr"])
    if mode == "aggressive" and current:
        planned_entry = current
    else:
        planned_entry = entry or current
    if mode == "aggressive" and expected_open:
        planned_entry = min(planned_entry or expected_open, expected_open)
    if planned_entry is None or planned_entry <= 0 or stop is None or target is None:
        return {
            "mode": mode,
            "modeLabel": settings["label"],
            "status": "PRICE_LEVEL_SHORT",
            "summary": "기준가·손절가·목표가 산출 필요",
            "buyRule": settings["buy_rule"],
            "holdDays": settings["hold_days"],
        }
    shares = int(capital // planned_entry)
    if shares < 1:
        shares = 1
    invested = planned_entry * shares
    cash = max(0.0, capital - invested)
    loss_per_share = stop - planned_entry
    profit_per_share = target - planned_entry
    loss_total = loss_per_share * shares
    profit_total = profit_per_share * shares
    loss_pct = (loss_per_share / planned_entry) * 100
    profit_pct = (profit_per_share / planned_entry) * 100
    account_loss_pct = (loss_total / capital) * 100 if capital else 0
    account_profit_pct = (profit_total / capital) * 100 if capital else 0
    return {
        "mode": mode,
        "modeLabel": settings["label"],
        "status": "OK",
        "capital": capital,
        "capitalText": format_price(capital, market),
        "entry": planned_entry,
        "entryText": format_price(planned_entry, market),
        "shares": shares,
        "sharesText": f"{shares:,}주",
        "invested": invested,
        "investedText": format_price(invested, market),
        "cash": cash,
        "cashText": format_price(cash, market),
        "lossPct": loss_pct,
        "lossPctText": format_percent(loss_pct),
        "profitPct": profit_pct,
        "profitPctText": format_percent(profit_pct),
        "lossTotal": loss_total,
        "lossTotalText": format_signed_money(loss_total, market, "손실 산출 필요"),
        "profitTotal": profit_total,
        "profitTotalText": format_signed_money(profit_total, market, "이익 산출 필요"),
        "accountLossPct": account_loss_pct,
        "accountLossPctText": format_percent(account_loss_pct),
        "accountProfitPct": account_profit_pct,
        "accountProfitPctText": format_percent(account_profit_pct),
        "buyRule": settings["buy_rule"],
        "holdDays": settings["hold_days"],
        "slippagePct": settings["slippage_pct"],
        "sellRule": "목표가·손절가·보유기간 종료 중 먼저 발생한 조건으로 청산",
        "summary": f"{settings['label']} {format_price(capital, market)} 기준 {shares:,}주 · 손실 {format_signed_money(loss_total, market)} · 이익 {format_signed_money(profit_total, market)}",
    }


def _virtual_trade_plans(market: str, current: float | None, entry: float | None, stop: float | None, target: float | None, expected_open: float | None = None) -> dict[str, dict[str, Any]]:
    return {mode: _trade_plan_for_mode(market, mode, current, entry, stop, target, expected_open) for mode in ("conservative", "balanced", "aggressive")}

def _market_matches(row: dict[str, Any], market: str) -> bool:
    value = first_value(row, ["market", "시장"], "")
    lowered = value.lower()
    if value:
        if market == "kr":
            return lowered in {"kr", "korea", "한국주식", "국장", "kospi", "kosdaq"} or "한국" in value
        return lowered in {"us", "usa", "미국주식", "미장", "nas", "nys", "amex"} or "미국" in value

    symbol = first_value(row, SYMBOL_ALIASES + ["ticker", "종목코드"], "")
    symbol = str(symbol).strip().replace(".0", "")
    symbol = re.sub(r"[^A-Za-z0-9._-]", "", symbol)
    if re.fullmatch(r"\d{1,6}", symbol):
        return market == "kr"
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]{0,12}", symbol):
        return market == "us"
    return False


def read_predictions_csv(market: str | None = None) -> list[dict[str, Any]]:
    df = read_csv(REPO_ROOT / "predictions.csv")
    rows = dataframe_records(df)
    if market is None:
        return rows
    return [row for row in rows if _market_matches(row, market)]


def _latest_records_by_symbol(rows: list[dict[str, Any]], market: str) -> dict[str, dict[str, Any]]:
    def sort_key(row: dict[str, Any]) -> str:
        return first_value(row, ["created_at", "target_date", "data_date", "updated_at"], "")

    out: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=sort_key, reverse=True):
        symbol = _row_symbol(row, market)
        if symbol and symbol not in out:
            out[symbol] = row
    return out


def _combine_symbol_maps(market: str) -> dict[str, dict[str, Any]]:
    maps: list[dict[str, dict[str, Any]]] = []
    for kind in ("symbol_snapshot", "position_cards", "action_cards", "pullback_cards", "risk_cards", "future_probability"):
        df, _ = read_report(kind, market)
        maps.append(_records_by_symbol(df, market))
    combined: dict[str, dict[str, Any]] = {}
    for symbol_map in maps:
        for symbol, row in symbol_map.items():
            combined[symbol] = _merge_alias_values(combined.get(symbol, {}), row) if symbol in combined else dict(row)
    return combined


def _format_optional_price(row: dict[str, Any], aliases: list[str], market: str, missing: str) -> str:
    value = first_number(row, aliases)
    return format_price(value, market) if value is not None else missing


def _display_value(row: dict[str, Any], aliases: list[str], missing: str) -> str:
    return first_value(row, aliases, missing)


def _direction_label(value: Any) -> str:
    text = _safe_str(value, "")
    if not text:
        return "검증 데이터 부족"
    if text.lower() in {"1", "true", "hit", "success", "성공"}:
        return "적중"
    if text.lower() in {"0", "false", "miss", "fail", "failure", "실패"}:
        return "불일치"
    return text


def _rate(rows: list[dict[str, Any]], aliases: list[str]) -> str:
    total = 0
    hits = 0
    for row in rows:
        value = first_value(row, aliases, "")
        if not value:
            continue
        normalized = value.lower()
        if normalized in {"대기", "pending"}:
            continue
        total += 1
        if normalized in {"1", "true", "hit", "success", "성공", "yes"}:
            hits += 1
    if not total:
        return "검증 데이터 부족"
    return f"{hits / total * 100:.1f}%"


def _report_group(path: Path) -> str:
    name = path.name.lower()
    if "latest" in name:
        return "latest"
    if name.startswith("v93"):
        return "v93"
    if name.startswith("v92"):
        return "v92"
    if name.startswith("v91"):
        return "v91"
    if "operational" in name:
        return "operational"
    if "portfolio" in name or "position" in name:
        return "portfolio"
    if "backtest" in name:
        return "backtest"
    return "other"


def _fallback_status_for_file(path: Path) -> str:
    match = re.match(r"v\d+_(.+)_(kr|us)\.csv$", path.name)
    if not match:
        return "fallback 대상 아님"
    suffix = f"{match.group(1)}_{match.group(2)}.csv"
    for version in ("v93", "v92", "v91"):
        candidate = REPORT_DIR / f"{version}_{suffix}"
        if candidate.exists() and candidate.stat().st_size > 0 and rows_for(candidate) > 0:
            return f"{version} 사용 가능" if candidate == path else f"{version} fallback 가능"
    return "fallback 없음"


def normalize_security_row(row: dict[str, Any] | pd.Series, market: str) -> dict[str, Any]:
    row_dict = dict(row)
    symbol = normalize_symbol(first_value(row_dict, SYMBOL_ALIASES), market)
    name = first_value(row_dict, NAME_ALIASES, symbol or "이름 없음")
    current_price = first_number(row_dict, CURRENT_PRICE_ALIASES)
    entry = first_number(row_dict, ENTRY_ALIASES)
    stop = first_number(row_dict, STOP_ALIASES)
    target = first_number(row_dict, TARGET_ALIASES)
    entry, stop, target = _derive_price_levels(row_dict, market, current_price, entry, stop, target, symbol)
    prediction_fields = _derived_probability_and_price(row_dict, market, symbol, current_price, entry)
    expected_open, expected_close = _derive_open_close(row_dict, market, symbol, current_price)
    swing_grade = _swing_grade(row_dict, current_price, entry, stop, target)
    recommendation_modes = _recommendation_modes(swing_grade, current_price, entry, stop, target)
    virtual_plans = _virtual_trade_plans(market, current_price, entry, stop, target, expected_open)
    scores = {
        "supply": first_value(row_dict, SUPPLY_SCORE_ALIASES, "수급 데이터 없음"),
        "earnings": first_value(row_dict, EARNINGS_SCORE_ALIASES, "재무 데이터 없음"),
        "valuation": first_value(row_dict, VALUATION_SCORE_ALIASES, "재무 데이터 없음"),
        "chart": first_value(row_dict, CHART_SCORE_ALIASES, "차트 데이터 부족"),
    }
    statuses = {
        "data": first_value(row_dict, ["data_status"], "상태 없음"),
        "price": first_value(row_dict, ["price_data_status"], "현재가 상태 없음"),
        "earnings": first_value(row_dict, ["earnings_data_status", "실적상태"], "재무 데이터 없음"),
        "valuation": first_value(row_dict, ["valuation_data_status", "밸류상태"], "재무 데이터 없음"),
        "flow": first_value(row_dict, ["flow_data_status", "수급상태"], "수급 데이터 없음"),
    }
    return {
        "symbol": symbol,
        "name": name,
        "market": market,
        "marketLabel": _market_label(market),
        "currentPrice": current_price,
        "currentPriceText": format_price(current_price, market) if current_price is not None else "현재가 없음",
        "priceTime": first_value(row_dict, PRICE_TIME_ALIASES, "현재가 기준시각 없음"),
        "priceSource": first_value(row_dict, PRICE_SOURCE_ALIASES, "가격출처 없음"),
        "dataStatus": first_value(row_dict, DATA_STATUS_ALIASES, "상태 없음"),
        "entry": entry,
        "entryText": format_price(entry, market) if entry is not None else "기준가 산출 필요",
        "stop": stop,
        "stopText": format_price(stop, market) if stop is not None else "손절가 산출 필요",
        "target": target,
        "targetText": format_price(target, market) if target is not None else "목표가 산출 필요",
        "prob1d": prediction_fields.get("prob_1d", "확률 산출 필요"),
        "prob3d": prediction_fields.get("prob_3d", "확률 산출 필요"),
        "prob5d": prediction_fields.get("prob_5d", "확률 산출 필요"),
        "prob20d": prediction_fields.get("prob_20d", "확률 산출 필요"),
        "probShort": prediction_fields.get("prob_1d", "확률 산출 필요"),
        "probSwing": prediction_fields.get("prob_5d", "확률 산출 필요"),
        "probMid": prediction_fields.get("prob_20d", "확률 산출 필요"),
        "expectedPrice1dText": prediction_fields.get("expected_1d_text", "예상가 산출 필요"),
        "expectedPrice3dText": prediction_fields.get("expected_3d_text", "예상가 산출 필요"),
        "expectedPrice5dText": prediction_fields.get("expected_5d_text", "예상가 산출 필요"),
        "expectedPrice20dText": prediction_fields.get("expected_20d_text", "예상가 산출 필요"),
        "expectedPriceShortText": prediction_fields.get("expected_1d_text", "예상가 산출 필요"),
        "expectedPriceSwingText": prediction_fields.get("expected_5d_text", "예상가 산출 필요"),
        "expectedPriceMidText": prediction_fields.get("expected_20d_text", "예상가 산출 필요"),
        "expectedOpenText": format_price(expected_open, market) if expected_open is not None else "예상 시초가 산출 필요",
        "expectedCloseText": format_price(expected_close, market) if expected_close is not None else "예상 종가 산출 필요",
        "swingGrade": f"스윙 {swing_grade}군",
        "swingGradeCode": swing_grade,
        "recommendationModes": recommendation_modes,
        "recommendationModeText": " / ".join(TRADE_MODE_SETTINGS[m]["label"] for m in recommendation_modes) if recommendation_modes else "추천 모드 산출 필요",
        "virtualPlans": virtual_plans,
        "predictionModelNote": prediction_fields.get("predictionModelNote", "예측 산출 대기"),
        "scores": scores,
        "statuses": statuses,
        "raw": row_dict,
    }


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
    cache_updated = quote_cache().get("updatedAt", "")
    if cache_updated:
        times.append(str(cache_updated))
    return max(times) if times else "기준시각 없음"


def symbols(market: str) -> dict[str, Any]:
    df, source = read_report("symbol_snapshot", market)
    rows = dataframe_records(df)
    if rows:
        rows = enrich_records_with_version_fallback("symbol_snapshot", market, rows)
    else:
        df = read_csv(REPO_ROOT / f"watchlist_{market}_growth.csv")
        source = f"watchlist_{market}_growth.csv" if not df.empty else ""
        rows = dataframe_records(df)
    normalized = [normalize_security_row(apply_quote_cache(row, market), market) for row in rows]
    return {"market": market, "count": len(normalized), "source": source, "items": normalized}


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
            if normalize_symbol(first_value(row, SYMBOL_ALIASES), market) == target:
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
    rows = enrich_records_with_version_fallback(f"{kind}_cards", market, dataframe_records(df))
    normalized_rows = []
    for row in rows:
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        normalized.update({
            "category": first_value(row, ["분류", "category"], kind),
            "confidence": first_number(row, ["신뢰도점수", "confidence_score", "score"]),
            "reason": first_value(row, ["핵심근거", "근거1", "설명"], "근거 없음"),
            "warning": first_value(row, ["주의점", "주의", "risk_warning_flags"], "주의사항 없음"),
            "nextAction": first_value(row, ["다음행동", "suggested_action", "final_judgment"], "다음 행동 없음"),
        })
        normalized_rows.append(normalized)
    return {"market": market, "type": kind, "count": len(normalized_rows), "source": source, "items": normalized_rows}


def positions(market: str) -> dict[str, Any]:
    df, source = read_report("position_cards", market)
    rows = dataframe_records(df)
    if rows:
        rows = enrich_records_with_version_fallback("position_cards", market, rows)
        rows = enrich_records_from_file(rows, DATA_DIR / f"holdings_{market}.csv", market)
    else:
        fallback = DATA_DIR / f"holdings_{market}.csv"
        df = read_csv(fallback)
        source = fallback.relative_to(REPO_ROOT).as_posix() if not df.empty else ""
        rows = dataframe_records(df)

    # Include direct holdings rows that may not yet have a generated position_card report.
    direct_holdings = dataframe_records(read_csv(DATA_DIR / f"holdings_{market}.csv"))
    existing_symbols = {_row_symbol(row, market) for row in rows}
    for holding_row in direct_holdings:
        symbol = _row_symbol(holding_row, market)
        if symbol and symbol not in existing_symbols:
            rows.append(holding_row)
            existing_symbols.add(symbol)

    normalized_rows = []
    for row in rows:
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        quantity = first_number(row, ["quantity", "보유수량", "shares"])
        avg_price = first_number(row, ["avg_price", "평균단가", "평단가"])
        current_price = normalized.get("currentPrice")
        pnl_value = None
        return_pct_value = None
        market_value = None
        cost_basis = None
        if quantity is not None and avg_price is not None and current_price is not None and avg_price:
            market_value = current_price * quantity
            cost_basis = avg_price * quantity
            pnl_value = market_value - cost_basis
            return_pct_value = ((current_price - avg_price) / avg_price) * 100

        normalized.update({
            "quantity": quantity,
            "quantityText": f"{quantity:,.0f}주" if quantity is not None else "보유수량 없음",
            "avgPrice": avg_price,
            "avgPriceText": format_price(avg_price, market) if avg_price is not None else "평균단가 없음",
            "marketValue": market_value,
            "marketValueText": format_price(market_value, market) if market_value is not None else "평가금액 없음",
            "costBasis": cost_basis,
            "costBasisText": format_price(cost_basis, market) if cost_basis is not None else "매입금액 없음",
            "returnPct": return_pct_value,
            "returnPctText": format_percent(return_pct_value),
            "pnl": pnl_value,
            "pnlText": format_signed_money(pnl_value, market),
            "nextAction": first_value(row, ["다음행동", "조치", "memo"], "다음 행동 없음"),
        })
        normalized_rows.append(normalized)
    return {"market": market, "count": len(normalized_rows), "source": source, "items": normalized_rows}


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
            "symbol": normalize_symbol(first_value(row, SYMBOL_ALIASES, ""), market),
            "name": first_value(row, NAME_ALIASES, ""),
            "nextAction": first_value(row, ["다음행동"], "다음 행동 없음"),
            "raw": row,
        })
    return {"market": market, "count": len(rows), "source": source, "items": rows}


def predictions(market: str) -> dict[str, Any]:
    df, source = read_report("future_probability", market)
    rows = enrich_records_with_version_fallback("future_probability", market, dataframe_records(df))
    if not rows:
        rows = [dict(item.get("raw", item)) for item in symbols(market)["items"][:30]]
        source = source or "symbols fallback + derived prediction"
    normalized_rows = []
    for row in rows:
        row = dict(row.get("raw", row)) if isinstance(row, dict) else dict(row)
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        normalized.update({
            "confidence": first_value(row, ["신뢰도점수", "confidence_score", "confidence", "score"], str(_confidence_value(row))),
            "nextAction": first_value(row, ["다음행동", "suggested_action", "final_judgment"], "확률과 예상가를 보조지표로 확인"),
        })
        normalized_rows.append(normalized)
    return {"market": market, "count": len(normalized_rows), "source": source, "items": normalized_rows}


def premarket_report(market: str) -> dict[str, Any]:
    summary_df, summary_source = read_report("today_summary", market)
    source_rows: list[tuple[str, str, dict[str, Any]]] = []
    sources = [summary_source]
    for kind, label in (("action_cards", "오늘 확인"), ("pullback_cards", "눌림목"), ("risk_cards", "주의"), ("future_probability", "확률")):
        df, source = read_report(kind, market)
        if source:
            sources.append(source)
        for row in enrich_records_with_version_fallback(kind, market, dataframe_records(df)):
            source_rows.append((kind, label, row))

    prediction_map = _latest_records_by_symbol(read_predictions_csv(market), market)
    base_map = _combine_symbol_maps(market)
    items = []
    seen: set[str] = set()
    for kind, label, row in source_rows:
        symbol = _row_symbol(row, market)
        if not symbol:
            continue
        merged = _merge_alias_values(base_map.get(symbol, {}), row)
        prediction = prediction_map.get(symbol, {})
        merged = _merge_alias_values(merged, prediction)
        merged = apply_quote_cache(merged, market)
        normalized = normalize_security_row(merged, market)
        key = f"{label}:{symbol}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            **normalized,
            "sourceGroup": label,
            "expectedOpen": normalized.get("expectedOpenText", _format_optional_price(merged, ["예상시초가", "pred_open_mid", "pred_open", "premarket_price"], market, "예상 시초가 산출 필요")),
            "expectedClose": normalized.get("expectedCloseText", _format_optional_price(merged, ["예상종가", "pred_close_mid", "pred_close"], market, "예상 종가 산출 필요")),
            "target2Text": _format_optional_price(merged, TARGET2_ALIASES, market, "2차 목표가 없음"),
            "riskReward": _display_value(merged, ["손익비", "rr", "rr1", "risk_reward", "risk_reward_ratio"], "손익비 없음"),
            "nextAction": first_value(merged, ["다음행동", "primary_action", "suggested_action", "final_judgment", "memo"], "다음 행동 없음"),
            "riskStatus": first_value(merged, ["주의점", "no_buy_flags", "risk_warning_flags", "risk_final_decision", "분류"], "리스크 상태 없음"),
            "dataStatus": first_value(merged, DATA_STATUS_ALIASES + ["prediction_quality_grade"], "데이터 상태 없음"),
        })

    return {
        "market": market,
        "count": len(items),
        "sources": [source for source in sources if source],
        "summary": dataframe_records(summary_df),
        "items": items,
    }


def intraday_report(market: str) -> dict[str, Any]:
    symbol_map = _combine_symbol_maps(market)
    position_items = positions(market)["items"]
    risk_items = candidate_rows(market, "risk")["items"]
    news = news_rows(market)["items"]
    news_count_by_symbol: dict[str, int] = {}
    for row in news:
        symbol = normalize_symbol(row.get("symbol"), market)
        if symbol:
            news_count_by_symbol[symbol] = news_count_by_symbol.get(symbol, 0) + 1

    symbols_order = []
    for collection in (position_items, risk_items, symbols(market)["items"][:30]):
        for item in collection:
            symbol = normalize_symbol(item.get("symbol"), market)
            if symbol and symbol not in symbols_order:
                symbols_order.append(symbol)

    risk_map = {normalize_symbol(item.get("symbol"), market): item for item in risk_items}
    position_map = {normalize_symbol(item.get("symbol"), market): item for item in position_items}
    items = []
    for symbol in symbols_order:
        merged = symbol_map.get(symbol, {})
        position = position_map.get(symbol)
        if position:
            merged = _merge_alias_values(merged, position.get("raw", {}))
        if risk_map.get(symbol):
            merged = _merge_alias_values(merged, risk_map[symbol].get("raw", {}))
        merged = apply_quote_cache(merged, market)
        normalized = normalize_security_row(merged, market)
        current = normalized.get("currentPrice")
        entry = normalized.get("entry")
        stop = normalized.get("stop")
        target = normalized.get("target")
        divergence = ((current - entry) / entry * 100) if current is not None and entry else None
        stop_break = bool(current is not None and stop is not None and current <= stop)
        target_hit = bool(current is not None and target is not None and current >= target)
        if stop_break:
            decision = "손절 주의"
        elif target_hit:
            decision = "익절 검토"
        elif divergence is not None and -2.0 <= divergence <= 1.0:
            decision = "진입 가능"
        elif entry is None:
            decision = "관망"
        else:
            decision = "대기"

        items.append({
            **normalized,
            "divergencePct": divergence,
            "divergenceText": format_percent(divergence, "기준가 없음"),
            "stopBreak": stop_break,
            "stopBreakText": "손절가 이탈" if stop_break else ("손절가 이상" if stop is not None else "손절가 없음"),
            "targetHit": target_hit,
            "targetHitText": "목표가 도달" if target_hit else ("목표가 미도달" if target is not None else "목표가 없음"),
            "holdingRisk": position.get("returnPctText", "보유종목 아님") if position else "보유종목 아님",
            "newsRiskStatus": f"뉴스 {news_count_by_symbol.get(symbol, 0)}건 / {risk_map[symbol].get('warning', '리스크 상태 있음')}" if symbol in risk_map else f"뉴스 {news_count_by_symbol.get(symbol, 0)}건",
            "intradayDecision": decision,
        })

    return {
        "market": market,
        "count": len(items),
        "sources": [
            f"reports/v92_symbol_snapshot_{market}.csv",
            f"reports/v92_position_cards_{market}.csv",
            f"reports/v92_risk_cards_{market}.csv",
            f"reports/v92_news_summary_{market}.csv",
        ],
        "items": items,
    }


def closing_report(market: str) -> dict[str, Any]:
    prediction_rows = read_predictions_csv(market)
    prediction_history_rows = prediction_history(market)["items"]
    outcome_rows = outcome_history(market)["items"]
    recent_predictions = sorted(prediction_rows, key=lambda row: first_value(row, ["created_at", "target_date"], ""), reverse=True)[:120]
    recent_history = sorted(prediction_history_rows, key=lambda row: first_value(row, ["created_at", "target_date"], ""), reverse=True)[:80]

    items = []
    for row in recent_predictions[:80]:
        symbol = _row_symbol(row, market)
        name = first_value(row, NAME_ALIASES + ["stock_name"], symbol or "이름 없음")
        direction = _direction_label(first_value(row, ["direction_hit", "decision_success", "prediction_result"], ""))
        open_range = _direction_label(first_value(row, ["open_in_range"], ""))
        close_range = _direction_label(first_value(row, ["close_in_range"], ""))
        entry_touched = _direction_label(first_value(row, ["entry_touched", "virtual_entry_filled"], ""))
        stop_touched = _direction_label(first_value(row, ["stop_touched"], ""))
        tp_touched = _direction_label(first_value(row, ["tp1_touched", "tp2_touched"], ""))
        failed = direction == "불일치" or open_range == "불일치" or close_range == "불일치"
        items.append({
            "symbol": symbol or "코드 없음",
            "name": name,
            "predictionBaseDate": first_value(row, ["created_at", "data_date", "target_date"], "예측 기준일 없음"),
            "actualResultDate": first_value(row, ["actual_date", "target_date"], "실제 결과일 없음"),
            "directionHit": direction,
            "rangeHit": f"시초 {open_range} / 종가 {close_range}",
            "entryTouched": entry_touched,
            "stopTakeProfit": f"손절 {stop_touched} / 익절 {tp_touched}",
            "failedSymbol": name if failed else "해당 없음",
            "failureReason": first_value(row, ["prediction_error_reason", "failure_reason", "prediction_cause_summary"], "실패 사유 또는 데이터 부족 사유 없음"),
        })

    if not items:
        for row in recent_history[:80]:
            items.append({
                "symbol": normalize_symbol(first_value(row, SYMBOL_ALIASES + ["ticker"], ""), market) or "코드 없음",
                "name": first_value(row, NAME_ALIASES + ["stock_name"], "이름 없음"),
                "predictionBaseDate": first_value(row, ["created_at", "target_date"], "예측 기준일 없음"),
                "actualResultDate": first_value(row, ["target_date"], "실제 결과일 없음"),
                "directionHit": _direction_label(first_value(row, ["prediction_result"], "")),
                "rangeHit": "범위 검증 데이터 부족",
                "entryTouched": "주문 기준가 검증 데이터 부족",
                "stopTakeProfit": "손절/익절 검증 데이터 부족",
                "failedSymbol": "검증 대기",
                "failureReason": "predictions.csv 상세 검증 컬럼 없음",
            })

    return {
        "market": market,
        "count": len(items),
        "directionHitRate": _rate(prediction_rows, ["direction_hit", "decision_success"]),
        "rangeHitRate": _rate(prediction_rows, ["close_in_range", "open_in_range"]),
        "predictionHistoryCount": prediction_history(market)["count"],
        "outcomeHistoryCount": outcome_history(market)["count"],
        "sources": ["predictions.csv", "data/history/prediction_history.csv", "data/history/outcome_history.csv"],
        "items": items,
        "outcomes": outcome_rows[:80],
    }


def report_files() -> dict[str, Any]:
    keywords = ("latest", "v92", "v93", "operational", "portfolio", "backtest")
    items = []
    for path in sorted(REPORT_DIR.glob("*")):
        if not path.is_file() or not any(keyword in path.name.lower() for keyword in keywords):
            continue
        df = read_csv(path) if path.suffix.lower() == ".csv" else pd.DataFrame()
        rows = int(len(df)) if path.suffix.lower() == ".csv" else rows_for(path)
        column_count = int(len(df.columns)) if path.suffix.lower() == ".csv" and not df.empty else 0
        status = "EMPTY" if path.stat().st_size == 0 or rows == 0 else "OK"
        items.append({
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "fileName": path.name,
            "group": _report_group(path),
            "rows": rows,
            "columns": column_count,
            "updatedAt": file_mtime(path),
            "bytes": path.stat().st_size,
            "status": status,
            "fallbackStatus": _fallback_status_for_file(path),
            "preview": dataframe_records(df, 3) if path.suffix.lower() == ".csv" else [],
        })
    return {"count": len(items), "fallbackPolicy": list(FALLBACK_POLICY), "items": items}


def report_preview(path: str) -> dict[str, Any]:
    rel = Path(path.replace("\\", "/"))
    target = (REPO_ROOT / rel).resolve()
    try:
        target.relative_to(REPORT_DIR.resolve())
    except ValueError:
        return {"path": path, "status": "BLOCKED", "items": [], "message": "reports 폴더 안의 파일만 미리보기할 수 있습니다."}
    if not target.exists() or not target.is_file():
        return {"path": path, "status": "MISSING", "items": [], "message": "파일 없음"}
    if target.suffix.lower() != ".csv":
        return {"path": path, "status": "UNSUPPORTED", "items": [], "message": "CSV 미리보기만 지원합니다."}
    df = read_csv(target)
    return {
        "path": target.relative_to(REPO_ROOT).as_posix(),
        "status": "OK" if not df.empty else "EMPTY",
        "rows": int(len(df)),
        "columns": list(df.columns),
        "items": dataframe_records(df, 20),
    }


def prediction_history(market: str | None = None) -> dict[str, Any]:
    path = HISTORY_DIR / "prediction_history.csv"
    df = read_csv(path)
    rows = dataframe_records(df)
    if market:
        rows = [row for row in rows if _market_matches(row, market)]
    return {
        "count": int(len(rows)),
        "source": path.relative_to(REPO_ROOT).as_posix(),
        "items": rows[:250],
    }


def outcome_history(market: str | None = None) -> dict[str, Any]:
    path = HISTORY_DIR / "outcome_history.csv"
    df = read_csv(path)
    rows = dataframe_records(df)
    if market:
        rows = [row for row in rows if _market_matches(row, market)]
    return {
        "count": int(len(rows)),
        "source": path.relative_to(REPO_ROOT).as_posix(),
        "items": rows[:250],
    }


def _find_data_files(patterns: tuple[str, ...], exclude: tuple[str, ...] = ()) -> list[Path]:
    roots = [DATA_DIR, REPORT_DIR]
    found: list[Path] = []
    for base in roots:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            name = path.name.lower()
            full = path.as_posix().lower()
            if exclude and any(term in name or term in full for term in exclude):
                continue
            if any(re.search(pattern, name) or re.search(pattern, full) for pattern in patterns):
                found.append(path)
    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[Path] = []
    for path in sorted(found, key=lambda p: p.as_posix()):
        key = path.resolve().as_posix()
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique



def github_actions_status() -> dict[str, Any]:
    repo = os.environ.get("GITHUB_REPOSITORY") or os.environ.get("MONE_GITHUB_REPOSITORY") or "selene0519/agnas-stock-app"
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("MONE_GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    api_base = f"https://api.github.com/repos/{repo}"
    try:
        wf_res = requests.get(f"{api_base}/actions/workflows", headers=headers, timeout=8)
        runs_res = requests.get(f"{api_base}/actions/runs?per_page=8", headers=headers, timeout=8)
        if wf_res.status_code == 404 and not token:
            return {
                "status": "NEED_TOKEN",
                "repo": repo,
                "message": "private repo이거나 인증이 없어 GitHub Actions를 조회할 수 없습니다. GITHUB_TOKEN 또는 MONE_GITHUB_TOKEN을 .env에 넣으면 연결됩니다.",
                "workflows": [],
                "runs": [],
            }
        if wf_res.status_code >= 400:
            return {"status": "ERROR", "repo": repo, "message": f"workflow 조회 실패 HTTP {wf_res.status_code}", "workflows": [], "runs": []}
        workflows = []
        for wf in wf_res.json().get("workflows", []):
            workflows.append({
                "name": wf.get("name", ""),
                "path": wf.get("path", ""),
                "state": wf.get("state", ""),
                "id": wf.get("id", ""),
            })
        runs = []
        if runs_res.status_code < 400:
            for run in runs_res.json().get("workflow_runs", []):
                runs.append({
                    "name": run.get("name", ""),
                    "event": run.get("event", ""),
                    "status": run.get("status", ""),
                    "conclusion": run.get("conclusion", ""),
                    "created_at": run.get("created_at", ""),
                    "updated_at": run.get("updated_at", ""),
                    "head_branch": run.get("head_branch", ""),
                    "html_url": run.get("html_url", ""),
                })
        schedule_runs = [r for r in runs if r.get("event") == "schedule"]
        return {
            "status": "OK",
            "repo": repo,
            "message": "GitHub Actions API 연결됨" if token else "공개 API로 조회됨",
            "workflows": workflows,
            "runs": runs,
            "latestScheduled": schedule_runs[0] if schedule_runs else None,
        }
    except Exception as exc:
        return {"status": "ERROR", "repo": repo, "message": f"GitHub Actions 조회 실패: {exc}", "workflows": [], "runs": []}


def chart_data(symbol: str, market: str) -> dict[str, Any]:
    target = normalize_symbol(symbol, market)
    df, source = _load_ohlcv(target, market)
    if df.empty:
        return {"status": "NO_DATA", "symbol": target, "market": market, "source": "", "items": [], "message": "OHLCV CSV를 찾지 못했습니다."}
    work = df.copy()
    work["ma5"] = work["close"].rolling(5).mean()
    work["ma20"] = work["close"].rolling(20).mean()
    work["ma60"] = work["close"].rolling(60).mean()
    ma20 = work["close"].rolling(20).mean()
    std20 = work["close"].rolling(20).std()
    work["bbUpper"] = ma20 + std20 * 2
    work["bbLower"] = ma20 - std20 * 2
    delta = work["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    work["rsi"] = 100 - (100 / (1 + rs))
    ema12 = work["close"].ewm(span=12, adjust=False).mean()
    ema26 = work["close"].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    work["macd"] = macd
    work["macdSignal"] = macd.ewm(span=9, adjust=False).mean()
    cols = ["date", "open", "high", "low", "close", "volume", "ma5", "ma20", "ma60", "bbUpper", "bbLower", "rsi", "macd", "macdSignal"]
    items = []
    for row in work.tail(160)[cols].replace({np.nan: None}).to_dict(orient="records"):
        items.append({k: (round(v, 4) if isinstance(v, float) and np.isfinite(v) else v) for k, v in row.items()})
    latest = items[-1] if items else {}
    return {"status": "OK", "symbol": target, "market": market, "source": source, "count": len(items), "latest": latest, "items": items}



def disclosure_rows(market: str) -> dict[str, Any]:
    files = _find_data_files((r"disclosure", r"filing", r"공시"), ("sector", "dart_corp", "node_modules"))
    # DART/SEC 파일명은 너무 넓게 잡으면 기업코드/섹터 파일이 섞이므로, 명시적 공시성 파일만 우선 사용합니다.
    if not files:
        files = _find_data_files((r"dart", r"sec"), ("sector", "dart_corp", "corp_code", "company_code", "node_modules"))
    items: list[dict[str, Any]] = []
    used_sources: list[str] = []
    for path in files[:12]:
        if path.suffix.lower() != ".csv":
            continue
        df = read_csv(path)
        if df.empty:
            continue
        used_sources.append(path.relative_to(REPO_ROOT).as_posix())
        for row in dataframe_records(df):
            if not _market_matches(row, market):
                # market 값이 없는 공시 파일은 파일명으로 보조 판단합니다.
                low_name = path.name.lower()
                if market == "kr" and any(tok in low_name for tok in ("us", "sec")):
                    continue
                if market == "us" and any(tok in low_name for tok in ("kr", "dart", "kor")):
                    continue
            symbol = normalize_symbol(first_value(row, SYMBOL_ALIASES + ["종목코드", "ticker"], ""), market)
            name = first_value(row, NAME_ALIASES + ["corp_name", "company", "회사명"], symbol or "회사명 없음")
            title = first_value(row, ["title", "공시제목", "report_nm", "보고서명", "form", "filing"], "공시 제목 없음")
            date = first_value(row, ["date", "공시일", "rcept_dt", "filing_date", "accepted", "게시일"], "공시일 없음")
            source_name = first_value(row, ["source", "출처", "provider"], "DART" if market == "kr" else "SEC")
            url = first_value(row, ["url", "link", "공시링크", "html_url"], "")
            items.append({
                "symbol": symbol,
                "name": name,
                "title": title,
                "date": date,
                "sourceName": source_name,
                "url": url,
                "status": "OK",
                "raw": row,
            })
    return {"market": market, "count": len(items), "sources": used_sources, "items": items[:200]}


def company_analysis(market: str) -> dict[str, Any]:
    df, source = read_report("company_integrated", market)
    rows = dataframe_records(df)
    if not rows:
        rows = [dict(item) for item in symbols(market).get("items", [])[:80]]
        source = source or "symbols fallback"
    items: list[dict[str, Any]] = []
    for row in rows:
        normalized = normalize_security_row(apply_quote_cache(row, market), market)
        items.append({
            "symbol": normalized.get("symbol", ""),
            "name": normalized.get("name", ""),
            "currentPriceText": normalized.get("currentPriceText", "현재가 없음"),
            "supply": normalized.get("scores", {}).get("supply", "수급 데이터 없음"),
            "earnings": normalized.get("scores", {}).get("earnings", "재무 데이터 없음"),
            "valuation": normalized.get("scores", {}).get("valuation", "재무 데이터 없음"),
            "chart": normalized.get("scores", {}).get("chart", "차트 데이터 부족"),
            "flowStatus": normalized.get("statuses", {}).get("flow", "수급 데이터 없음"),
            "earningsStatus": normalized.get("statuses", {}).get("earnings", "재무 데이터 없음"),
            "valuationStatus": normalized.get("statuses", {}).get("valuation", "재무 데이터 없음"),
            "dataStatus": normalized.get("dataStatus", "상태 없음"),
            "raw": row,
        })
    return {"market": market, "count": len(items), "source": source, "items": items}



def _execution_status_for_plan(current: float | None, entry: float | None, mode: str) -> str:
    settings = TRADE_MODE_SETTINGS.get(mode, TRADE_MODE_SETTINGS["balanced"])
    if current is None or entry is None or entry <= 0:
        return "체결 판단 불가"
    gap = (current - entry) / entry
    tol = float(settings.get("entry_tolerance_pct", 0.01) or 0.0)
    if mode == "conservative":
        if current <= entry * (1 + 0.003):
            return "체결 가능"
        if current <= entry * 1.02:
            return "대기"
        return "추격 부담"
    if mode == "aggressive":
        if gap <= tol:
            return "체결 가능"
        if gap <= 0.08:
            return "공격 검토"
        return "추격 부담"
    if abs(gap) <= tol:
        return "체결 가능"
    if gap > tol:
        return "대기"
    return "기준가 아래"


def virtual_portfolio_summary(market: str, mode: str = "balanced") -> dict[str, Any]:
    if mode not in TRADE_MODE_SETTINGS:
        mode = "balanced"
    settings = TRADE_MODE_SETTINGS[mode]
    max_positions = {"conservative": 3, "balanced": 5, "aggressive": 8}.get(mode, 5)
    universe = candidate_rows(market, "action").get("items", []) + candidate_rows(market, "pullback").get("items", []) + candidate_rows(market, "flow").get("items", [])
    seen: set[str] = set()
    selected: list[dict[str, Any]] = []
    for item in universe:
        symbol = normalize_symbol(item.get("symbol"), market)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        modes = item.get("recommendationModes") or []
        if mode not in modes and mode != "aggressive":
            continue
        plan = (item.get("virtualPlans") or {}).get(mode) or {}
        if plan.get("status") != "OK":
            continue
        selected.append({"item": item, "plan": plan})
        if len(selected) >= max_positions:
            break

    capital_per_position = float(settings["capital_us"] if market == "us" else settings["capital_kr"])
    total_capital = capital_per_position * max_positions
    invested = sum(float(row["plan"].get("invested", 0) or 0) for row in selected)
    loss_total = sum(float(row["plan"].get("lossTotal", 0) or 0) for row in selected)
    profit_total = sum(float(row["plan"].get("profitTotal", 0) or 0) for row in selected)
    cash = max(0.0, total_capital - invested)
    loss_pct = (loss_total / total_capital * 100) if total_capital else 0
    profit_pct = (profit_total / total_capital * 100) if total_capital else 0

    cards = [
        {"label": "추천 모드", "value": settings["label"], "note": settings["buy_rule"]},
        {"label": "최대 보유", "value": f"{max_positions}종목", "note": f"종목당 {format_price(capital_per_position, market)} 기준"},
        {"label": "예상 최대 손실", "value": format_signed_money(loss_total, market), "note": format_percent(loss_pct)},
        {"label": "예상 목표 이익", "value": format_signed_money(profit_total, market), "note": format_percent(profit_pct)},
        {"label": "잔여 현금", "value": format_price(cash, market), "note": "정수 수량 계산 후 잔여"},
    ]
    items = []
    for row in selected:
        item = row["item"]
        plan = row["plan"]
        items.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", item.get("symbol", "")),
            "swingGrade": item.get("swingGrade", "스윙 C군"),
            "currentPrice": item.get("currentPriceText", "현재가 없음"),
            "entry": plan.get("entryText", "예상 매수가 산출 필요"),
            "shares": plan.get("sharesText", "수량 산출 필요"),
            "invested": plan.get("investedText", "투입금 산출 필요"),
            "loss": plan.get("lossTotalText", "손실 산출 필요"),
            "profit": plan.get("profitTotalText", "이익 산출 필요"),
            "accountLossPct": plan.get("accountLossPctText", "운용 손실률 산출 필요"),
            "accountProfitPct": plan.get("accountProfitPctText", "운용 수익률 산출 필요"),
            "executionStatus": _execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
            "buyRule": plan.get("buyRule", settings["buy_rule"]),
            "holdDays": plan.get("holdDays", settings["hold_days"]),
        })
    return {
        "market": market,
        "mode": mode,
        "modeLabel": settings["label"],
        "maxPositions": max_positions,
        "capitalPerPosition": format_price(capital_per_position, market),
        "totalCapital": format_price(total_capital, market),
        "invested": format_price(invested, market),
        "cash": format_price(cash, market),
        "lossTotal": format_signed_money(loss_total, market),
        "profitTotal": format_signed_money(profit_total, market),
        "lossPct": format_percent(loss_pct),
        "profitPct": format_percent(profit_pct),
        "cards": cards,
        "count": len(items),
        "items": items,
        "note": "가상 운용은 자동주문이 아니며, 기준가·손절가·목표가와 OHLCV 기반 검증을 위한 참고 계산입니다.",
    }

def virtual_operation_preview(market: str, mode: str = "balanced") -> dict[str, Any]:
    if mode not in TRADE_MODE_SETTINGS:
        mode = "balanced"
    rows = []
    universe = candidate_rows(market, "action").get("items", []) + candidate_rows(market, "pullback").get("items", []) + candidate_rows(market, "flow").get("items", [])
    seen: set[str] = set()
    for item in universe:
        symbol = normalize_symbol(item.get("symbol"), market)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        modes = item.get("recommendationModes") or []
        if mode not in modes and mode != "aggressive":
            continue
        plan = (item.get("virtualPlans") or {}).get(mode) or {}
        rows.append({
            "symbol": symbol,
            "name": item.get("name", symbol),
            "swingGrade": item.get("swingGrade", "스윙 C군"),
            "mode": mode,
            "modeLabel": TRADE_MODE_SETTINGS[mode]["label"],
            "currentPrice": item.get("currentPriceText", "현재가 없음"),
            "entry": plan.get("entryText", item.get("entryText", "기준가 산출 필요")),
            "shares": plan.get("sharesText", "수량 산출 필요"),
            "invested": plan.get("investedText", "투입금 산출 필요"),
            "loss": plan.get("lossTotalText", "손실 산출 필요"),
            "profit": plan.get("profitTotalText", "이익 산출 필요"),
            "accountLossPct": plan.get("accountLossPctText", "운용 손실률 산출 필요"),
            "accountProfitPct": plan.get("accountProfitPctText", "운용 수익률 산출 필요"),
            "buyRule": plan.get("buyRule", "매수 기준 없음"),
            "holdDays": plan.get("holdDays", "보유기간 없음"),
            "executionStatus": _execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
            "summary": plan.get("summary", "가상 운용 산출 필요"),
        })
    return {"market": market, "mode": mode, "modeLabel": TRADE_MODE_SETTINGS[mode]["label"], "count": len(rows), "items": rows[:80]}

def data_source_status() -> dict[str, Any]:
    groups = [
        {
            "key": "chart",
            "name": "차트/OHLCV",
            "patterns": (r"ohlcv", r"daily", r"chart"),
            "exclude": ("node_modules",),
            "target": "차트·기술분석 > 차트 보기",
        },
        {
            "key": "flow",
            "name": "수급/거래대금",
            "patterns": (r"flow", r"supply", r"수급", r"investor", r"volume"),
            "exclude": ("node_modules",),
            "target": "장중 체크 / 오늘 매수 검토 / 기업분석",
        },
        {
            "key": "orderbook",
            "name": "호가/체결",
            "patterns": (r"orderbook", r"quote", r"quotes", r"bid", r"ask", r"호가", r"체결"),
            "exclude": ("node_modules", "quotes_cache"),
            "target": "장중 체크 / 오늘 매수 검토",
        },
        {
            "key": "disclosure",
            "name": "공시",
            "patterns": (r"disclosure", r"filing", r"dart", r"sec", r"공시"),
            "exclude": ("sector", "dart_corp"),
            "target": "뉴스·기업분석 > 공시",
        },
    ]
    items = []
    for group in groups:
        files = _find_data_files(group["patterns"], group["exclude"])
        csv_files = [path for path in files if path.suffix.lower() == ".csv"]
        latest = max((file_mtime(path) for path in files if path.exists()), default="")
        row_count = sum(rows_for(path) for path in csv_files[:20])
        items.append({
            "key": group["key"],
            "name": group["name"],
            "status": "OK" if files else "MISSING",
            "files": len(files),
            "csvFiles": len(csv_files),
            "rows": int(row_count),
            "latestUpdatedAt": latest,
            "target": group["target"],
            "examples": [path.relative_to(REPO_ROOT).as_posix() for path in files[:5]],
            "message": "파일 감지됨" if files else "API 키/워크플로가 있어도 저장된 CSV가 없으면 앱에 표시할 데이터가 없습니다.",
        })
    return {"items": items}
