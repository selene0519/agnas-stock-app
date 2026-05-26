from __future__ import annotations

import json
import os
import re
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


def _market_matches(row: dict[str, Any], market: str) -> bool:
    value = first_value(row, ["market", "시장"], "")
    if not value:
        return True
    lowered = value.lower()
    if market == "kr":
        return lowered in {"kr", "korea", "한국주식", "국장"} or "한국" in value
    return lowered in {"us", "usa", "미국주식", "미장"} or "미국" in value


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
        "entryText": format_price(entry, market) if entry is not None else "기준가 없음",
        "stop": stop,
        "stopText": format_price(stop, market) if stop is not None else "손절가 없음",
        "target": target,
        "targetText": format_price(target, market) if target is not None else "목표가 없음",
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
    normalized_rows = []
    for row in rows:
        row = apply_quote_cache(row, market)
        normalized = normalize_security_row(row, market)
        normalized.update({
            "prob1d": first_value(row, ["1일상승확률", "prob_up_1d"], "확률 없음"),
            "prob3d": first_value(row, ["3일상승확률", "prob_up_3d"], "확률 없음"),
            "prob5d": first_value(row, ["5일상승확률", "prob_up_5d"], "확률 없음"),
            "confidence": first_value(row, ["신뢰도점수", "confidence_score"], "신뢰도 없음"),
            "nextAction": first_value(row, ["다음행동"], "다음 행동 없음"),
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
            "expectedOpen": _format_optional_price(merged, ["예상시초가", "pred_open_mid", "pred_open", "premarket_price"], market, "예상 시초가 없음"),
            "expectedClose": _format_optional_price(merged, ["예상종가", "pred_close_mid", "pred_close"], market, "예상 종가 없음"),
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
    prediction_history_rows = [row for row in prediction_history()["items"] if _market_matches(row, market)]
    outcome_rows = [row for row in outcome_history()["items"] if _market_matches(row, market)]
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
        "predictionHistoryCount": prediction_history()["count"],
        "outcomeHistoryCount": outcome_history()["count"],
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
