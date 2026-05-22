from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from core.finnhub_quote import fetch_finnhub_intraday_quote, is_finnhub_quote_symbol, load_finnhub_api_key
from core.market_session_engine import current_session_for_market, current_session_code, current_session_status
from core.intraday_quote_log import log_intraday_quote_event
from core.kis_us_quote import fetch_kis_us_quote_api
from core.intraday_signal_engine import INTRADAY_SIGNAL_COLUMNS, apply_intraday_signals_to_candidates
from core.kis_token_manager import get_kis_access_token, merged_env, _parse_bool, _safe_str
from core.swing_candidate_io import SWING_CANDIDATE_FILES, read_swing_candidate_csv, save_swing_candidate_csv


REPORT_DIR = Path("reports")
KST = ZoneInfo("Asia/Seoul")
US_ET = ZoneInfo("America/New_York")
SNAPSHOT_PATH = REPORT_DIR / "intraday_realtime_snapshot.csv"
SUMMARY_PATH = REPORT_DIR / "intraday_realtime_summary.json"
ORDERBOOK_SNAPSHOT_PATH = REPORT_DIR / "intraday_orderbook_snapshot.csv"
HOLDING_FILES = [
    Path("holdings_us.csv"),
    Path("holdings_kr.csv"),
    Path("data/holdings.csv"),
    Path("data/holdings_us.csv"),
    Path("data/holdings_kr.csv"),
]
WATCHLIST_CSV_PATHS = [
    Path("watchlist_us.csv"),
    Path("watchlist_kr.csv"),
    Path("watchlist_us_growth.csv"),
    Path("watchlist_kr_growth.csv"),
    Path("watchlist_us_symbols_only.csv"),
    Path("data/watchlist.csv"),
    Path("config/watchlist.csv"),
    Path("data/decision_system/watchlist_user_us.csv"),
    Path("data/decision_system/watchlist_user_kr.csv"),
]
DAILY_WATCH_SELECTION_PATH = Path("daily_watch_selection.json")
REQUIRED_US_INTRADAY_SYMBOLS = frozenset({"TSLA", "NVDA", "GOOGL", "PLTR", "INTC"})
DEFAULT_SWING_CANDIDATE_FILES = tuple(Path(p) for p in SWING_CANDIDATE_FILES)
DEFAULT_HOLDING_FILES = tuple(Path(p) for p in HOLDING_FILES)
QUOTE_PRICE_ENDPOINT = "inquire-price"
QUOTE_TR_ID = "FHKST01010100"
INTRADAY_SNAPSHOT_COLUMNS = [
    "symbol",
    "market",
    "last_price",
    "intraday_change_pct",
    "intraday_volume",
    "intraday_trading_value",
    "intraday_volume_ratio",
    "intraday_trading_value_ratio",
    "intraday_data_available",
    "intraday_data_source",
    "intraday_fetch_status",
    "intraday_failure_reason",
    "intraday_market_session",
    "market_session_status",
    "intraday_updated_at",
    "intraday_warning",
    "quote_available",
    "quote_partial_available",
    "quote_full_available",
    "quote_source",
    "quote_source_label",
    "kis_quote_attempted",
    "kis_quote_success",
    "kis_quote_error",
    "kis_exchange_code",
    "quote_failure_reason",
    "quote_retry_used",
    "quote_fallback_used",
    "quote_fallback_source",
    "quote_fallback_price",
    "quote_fallback_warning",
    "bid_total_volume",
    "ask_total_volume",
    "orderbook_imbalance",
    "execution_strength",
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any, default: float = math.nan) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "-"}:
        return default
    for token in ["$", "원", ",", "배", "%"]:
        text = text.replace(token, "")
    try:
        return float(text)
    except Exception:
        return default


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "yes", "y"}


def _is_kr_market(market: str) -> bool:
    text = str(market or "").strip().upper()
    return "한국" in str(market) or text in {"KR", "KRX", "KOSPI", "KOSDAQ"}


def _normalize_kr_symbol(symbol: str) -> tuple[str, bool]:
    raw = str(symbol or "").strip().upper()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if not digits:
        return raw, False
    if len(digits) > 6:
        return digits[-6:], False
    normalized = digits.zfill(6)
    return normalized, len(normalized) == 6 and normalized.isdigit()


def _normalize_us_symbol(symbol: str) -> tuple[str, bool]:
    raw = str(symbol or "").strip().upper()
    if not raw:
        return "", False
    cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in {".", "-"})
    return cleaned, bool(cleaned) and cleaned.replace(".", "").replace("-", "").isalnum()


def _is_us_market(market: str) -> bool:
    text = str(market or "").strip().upper()
    return "미국" in str(market) or text in {"US", "NASDAQ", "NYSE", "AMEX"}


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        if path.exists() and path.stat().st_size > 0:
            return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        pass
    return pd.DataFrame()


def _symbol_from_row(row: pd.Series) -> str:
    for col in ["symbol", "ticker", "종목코드", "종목"]:
        if col in row.index:
            value = str(row.get(col, "")).strip()
            if value:
                return value
    return ""


def _market_from_path_or_row(path: Path | None, row: pd.Series) -> str:
    if "market" in row.index and str(row.get("market", "")).strip():
        return str(row.get("market", "")).strip()
    name = (path.name if path else "").lower()
    if "_kr_" in name or "holdings_kr" in name or "watchlist_kr" in name:
        return "한국주식"
    if "_us_" in name or "holdings_us" in name or "watchlist_us" in name:
        return "미국주식"
    raw = str(row.get("symbol", row.get("ticker", "")) or "").strip()
    if raw.replace(".KS", "").replace(".KQ", "").isdigit():
        return "한국주식"
    if raw and raw.replace(".", "").replace("-", "").isalnum():
        return "미국주식"
    return ""


def _normalize_intraday_symbol(symbol: str, market: str) -> tuple[str, str, bool]:
    """Normalize symbol and infer market. Returns (symbol, market, valid)."""
    market_text = str(market or "").strip()
    if _is_kr_market(market_text):
        sym, valid = _normalize_kr_symbol(symbol)
        return sym, market_text or "한국주식", valid
    if _is_us_market(market_text):
        sym, valid = _normalize_us_symbol(symbol)
        return sym or str(symbol).strip().upper(), market_text or "미국주식", valid
    raw = str(symbol or "").strip()
    if raw.replace(".KS", "").replace(".KQ", "").isdigit():
        sym, valid = _normalize_kr_symbol(raw)
        return sym, "한국주식", valid
    sym, valid = _normalize_us_symbol(raw)
    return sym or raw.upper(), "미국주식", valid


def _append_source_tag(tags: str, tag: str) -> str:
    parts = [p.strip() for p in str(tags or "").split("|") if p.strip()]
    if tag and tag not in parts:
        parts.append(tag)
    return "|".join(parts)


def _merge_target_row(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    for key, val in incoming.items():
        if key in {"source_tags", "source_file"}:
            continue
        if key not in out or not str(out.get(key, "")).strip():
            out[key] = val
    out["source_tags"] = _append_source_tag(
        str(out.get("source_tags", "")),
        str(incoming.get("source_tags", incoming.get("target_type", ""))),
    )
    if incoming.get("source_file"):
        files = [p.strip() for p in str(out.get("source_file", "")).split("|") if p.strip()]
        sf = str(incoming.get("source_file", "")).strip()
        if sf and sf not in files:
            files.append(sf)
        out["source_file"] = "|".join(files)
    return out


def _coerce_kst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def _kr_market_session(now: datetime | None = None) -> str:
    return current_session_code("한국주식", now)


def _us_market_session(now: datetime | None = None) -> str:
    return current_session_code("미국주식", now)


def _market_session(market: str, now: datetime | None = None) -> str:
    return current_session_code(market, now)


def _market_session_status_label(market: str, now: datetime | None = None) -> str:
    return current_session_status(market, now)


def _target_rows_from_candidates(paths: list[str | Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        df = read_swing_candidate_csv(path)
        if df.empty:
            continue
        work = df.copy()
        if "score" in work.columns:
            work["_score_num"] = pd.to_numeric(work["score"].map(_num), errors="coerce").fillna(0)
        else:
            work["_score_num"] = 0
        lower_name = path.name.lower()
        if "c_excluded" in lower_name:
            strong = pd.Series(False, index=work.index)
            for col in ["strong_watch_candidate", "weak_market_leader_flag"]:
                if col in work.columns:
                    strong = strong | work[col].astype(str).str.lower().isin(["true", "1", "1.0"])
            if "forecast_label" in work.columns:
                strong = strong | work["forecast_label"].astype(str).str.contains("강한 관찰", na=False)
            selected = work.loc[strong].copy()
            if selected.empty:
                selected = work.sort_values("_score_num", ascending=False).head(10)
            else:
                selected = selected.sort_values("_score_num", ascending=False).head(20)
        else:
            selected = work
        for _, row in selected.iterrows():
            symbol = _symbol_from_row(row)
            if not symbol:
                continue
            market = _market_from_path_or_row(path, row)
            sym, market, valid = _normalize_intraday_symbol(symbol, market)
            if not sym or not valid:
                continue
            item = row.to_dict()
            item["symbol"] = sym
            item["market"] = market
            item["source_file"] = str(path)
            item["target_type"] = "c_excluded_limited" if "c_excluded" in lower_name else "candidate"
            item["source_tags"] = item["target_type"]
            rows.append(item)
    return rows


def _target_rows_from_holdings() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in HOLDING_FILES:
        df = _read_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            symbol = _symbol_from_row(row)
            if not symbol:
                continue
            market = _market_from_path_or_row(path, row)
            sym, market, valid = _normalize_intraday_symbol(symbol, market)
            if not sym or not valid:
                continue
            item = row.to_dict()
            item["symbol"] = sym
            item["market"] = market
            item["source_file"] = str(path)
            item["target_type"] = "holding"
            item["source_tags"] = "holding"
            rows.append(item)
    return rows


def _target_rows_from_watchlist_csvs() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in WATCHLIST_CSV_PATHS:
        df = _read_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            symbol = _symbol_from_row(row)
            if not symbol:
                continue
            market = _market_from_path_or_row(path, row)
            sym, market, valid = _normalize_intraday_symbol(symbol, market)
            if not sym or not valid:
                continue
            item = row.to_dict()
            item["symbol"] = sym
            item["market"] = market
            item["source_file"] = str(path)
            item["target_type"] = "watchlist"
            item["source_tags"] = "watchlist"
            rows.append(item)
    return rows


def _target_rows_from_daily_watch_selection() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        if not DAILY_WATCH_SELECTION_PATH.exists():
            return rows
        data = json.loads(DAILY_WATCH_SELECTION_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return rows
        for market_key, block in data.items():
            if not isinstance(block, dict):
                continue
            market = "미국주식" if str(market_key).upper() == "US" else "한국주식"
            for raw in block.get("symbols", []) or []:
                sym, market, valid = _normalize_intraday_symbol(str(raw), market)
                if not sym or not valid:
                    continue
                rows.append({
                    "symbol": sym,
                    "market": market,
                    "source_file": str(DAILY_WATCH_SELECTION_PATH),
                    "target_type": "daily_watch",
                    "source_tags": "daily_watch",
                })
    except Exception:
        return rows
    return rows


def _target_rows_required_us_symbols() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sym in sorted(REQUIRED_US_INTRADAY_SYMBOLS):
        normalized, market, valid = _normalize_intraday_symbol(sym, "미국주식")
        if not valid:
            continue
        rows.append({
            "symbol": normalized,
            "market": market,
            "source_file": "required_us_watchlist",
            "target_type": "required_us",
            "source_tags": "required_us",
        })
    return rows


def _kis_configured() -> bool:
    env = merged_env()
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    return bool(_parse_bool(env.get("KIS_ENABLED"), True) and app_key and app_secret)


def _kis_base_url(is_mock: bool) -> str:
    return (
        "https://openapivts.koreainvestment.com:29443"
        if is_mock
        else "https://openapi.koreainvestment.com:9443"
    )


def _kis_headers(tr_id: str, token: str, app_key: str, app_secret: str) -> dict[str, str]:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }


QUOTE_SOURCE_LABELS: dict[str, str] = {
    "kis_us_quote": "KIS 해외 현재가",
    "kis_kr_quote": "KIS 국내 현재가",
    "kis_inquire_price": "KIS 국내 현재가",
    "finnhub_quote": "Finnhub 보조 수신",
    "csv_fallback": "저장 가격 사용",
    "missing": "현재가 미수신",
}


def quote_source_label(quote_source: Any) -> str:
    text = str(quote_source or "").strip().lower()
    if text in QUOTE_SOURCE_LABELS:
        return QUOTE_SOURCE_LABELS[text]
    if text.startswith("fallback_candidate_") or text.startswith("fallback_"):
        return QUOTE_SOURCE_LABELS["csv_fallback"]
    return QUOTE_SOURCE_LABELS["missing"] if not text else text


def _kis_tracking_defaults() -> dict[str, Any]:
    return {
        "kis_quote_attempted": False,
        "kis_quote_success": False,
        "kis_quote_error": "",
        "kis_exchange_code": "",
    }


def _kis_tracking_from_result(api_result: dict[str, Any] | None) -> dict[str, Any]:
    row = api_result or {}
    return {
        "kis_quote_attempted": bool(row.get("kis_quote_attempted", False)),
        "kis_quote_success": bool(row.get("kis_quote_success", row.get("ok", False))),
        "kis_quote_error": str(row.get("kis_quote_error", "") or row.get("failure_reason", "") or "")[:500],
        "kis_exchange_code": str(row.get("kis_exchange_code", "") or row.get("kis_exchange", "") or ""),
    }


def _finalize_quote_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    source = str(out.get("quote_source", "") or "").strip().lower()
    if not source or source in {"api_unavailable_safe", "unknown"}:
        if out.get("quote_available") in {True, "True", "true", "1"} or _truthy(out.get("quote_available")):
            source = str(out.get("intraday_data_source", "") or "csv_fallback").strip().lower()
        else:
            source = "missing"
    out["quote_source"] = source
    out["quote_source_label"] = quote_source_label(source)
    return out


def _quote_meta_defaults() -> dict[str, Any]:
    return {
        "quote_available": False,
        "quote_partial_available": False,
        "quote_full_available": False,
        "quote_source": "missing",
        "quote_source_label": QUOTE_SOURCE_LABELS["missing"],
        "quote_failure_reason": "",
        "quote_retry_used": False,
        "quote_fallback_used": False,
        "quote_fallback_source": "",
        "quote_fallback_price": None,
        "quote_fallback_warning": "",
        **_kis_tracking_defaults(),
    }


def _parse_kis_quote_output(output: Any) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {"ok": False, "failure_reason": "api_response_empty", "parser_status": "empty_output"}
    last = _num(output.get("stck_prpr"))
    change_pct = _num(output.get("prdy_ctrt"), 0.0)
    volume = _num(output.get("acml_vol"), 0.0)
    trading_value = _num(output.get("acml_tr_pbmn"), 0.0)
    if math.isnan(last) or last <= 0:
        return {"ok": False, "failure_reason": "api_response_empty", "parser_status": "no_price_fields"}
    full = volume > 0 or trading_value > 0
    return {
        "ok": True,
        "failure_reason": "",
        "last_price": last,
        "intraday_change_pct": 0.0 if math.isnan(change_pct) else change_pct,
        "intraday_volume": 0.0 if math.isnan(volume) else volume,
        "intraday_trading_value": 0.0 if math.isnan(trading_value) else trading_value,
        "quote_full_available": full,
        "quote_partial_available": not full,
    }


def _fetch_kis_kr_quote_api(code: str) -> dict[str, Any]:
    if not _kis_configured():
        return {"ok": False, "failure_reason": "endpoint_not_configured", "parser_status": "skipped"}
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        return {"ok": False, "failure_reason": "auth_error", "parser_status": "auth_error"}
    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    params = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    url = f"{_kis_base_url(is_mock)}/uapi/domestic-stock/v1/quotations/{QUOTE_PRICE_ENDPOINT}?{params}"
    request = urllib.request.Request(
        url,
        headers=_kis_headers(QUOTE_TR_ID, token, app_key, app_secret),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return {"ok": False, "failure_reason": "rate_limited", "parser_status": "http_error"}
        return {"ok": False, "failure_reason": "auth_error" if exc.code in {401, 403} else "unknown", "parser_status": "http_error"}
    except Exception:
        return {"ok": False, "failure_reason": "unknown", "parser_status": "request_error"}

    if str(payload.get("rt_cd", "")).strip() not in {"", "0"}:
        return {"ok": False, "failure_reason": "api_response_empty", "parser_status": "api_error"}
    output = payload.get("output") or payload.get("output1") or {}
    parsed = _parse_kis_quote_output(output)
    parsed["quote_source"] = "kis_inquire_price"
    return parsed


def _price_from_candidate_row(row: dict[str, Any] | None) -> tuple[float, str]:
    if not row:
        return math.nan, ""
    for col in ["last_price", "current_price", "close", "price"]:
        value = _num(row.get(col))
        if not math.isnan(value) and value > 0:
            return value, f"candidate_{col}"
    return math.nan, ""


def _price_from_orderbook(orderbook: dict[str, Any] | None) -> tuple[float, str]:
    if not orderbook:
        return math.nan, ""
    bid = _num(orderbook.get("best_bid"))
    ask = _num(orderbook.get("best_ask"))
    if not math.isnan(bid) and not math.isnan(ask) and bid > 0 and ask > 0:
        return (bid + ask) / 2.0, "orderbook_mid"
    if not math.isnan(bid) and bid > 0:
        return bid, "orderbook_best_bid"
    if not math.isnan(ask) and ask > 0:
        return ask, "orderbook_best_ask"
    return math.nan, ""


def _apply_quote_fallback(
    symbol: str,
    market: str,
    session: str,
    failure_reason: str,
    *,
    target_row: dict[str, Any] | None = None,
    orderbook: dict[str, Any] | None = None,
    retry_used: bool = False,
    kis_tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _quote_meta_defaults()
    meta.update(_kis_tracking_from_result(kis_tracking))
    meta["quote_failure_reason"] = failure_reason or "fallback_unavailable"
    meta["quote_retry_used"] = bool(retry_used)
    price, source = _price_from_candidate_row(target_row)
    if math.isnan(price):
        price, source = _price_from_orderbook(orderbook)
    if math.isnan(price) or price <= 0:
        meta["quote_failure_reason"] = failure_reason or "fallback_unavailable"
        human_reason = {
            "api_response_empty": "미국주식 현재가 API 응답 없음" if _is_us_market(market) else "장중 quote API 미수신",
            "unsupported_quote_api": "미국주식 현재가 API 미지원 심볼",
        }.get(meta["quote_failure_reason"], "장중 quote API 미수신, fallback 가격 없음")
        meta["quote_source"] = "missing"
        meta["quote_source_label"] = quote_source_label("missing")
        return _finalize_quote_row({
            "symbol": symbol,
            "market": market,
            "intraday_data_available": False,
            "intraday_data_source": "missing",
            "intraday_fetch_status": "no_data",
            "intraday_failure_reason": human_reason,
            "intraday_market_session": session,
            "market_session_status": _market_session_status_label(market),
            "intraday_updated_at": _now(),
            "intraday_warning": human_reason + " (호가/수급은 별도 미지원 가능)",
            "last_price": None,
            "intraday_change_pct": 0.0,
            "intraday_volume": 0.0,
            "intraday_trading_value": 0.0,
            "intraday_volume_ratio": 0.0,
            "intraday_trading_value_ratio": 0.0,
            **meta,
        })
    change_pct = _num(target_row.get("intraday_change_pct", target_row.get("change_pct")), 0.0) if target_row else 0.0
    warning = "quote API 미수신, 가격 fallback 사용"
    meta.update({
        "quote_available": True,
        "quote_partial_available": True,
        "quote_full_available": False,
        "quote_source": "csv_fallback",
        "quote_source_label": quote_source_label("csv_fallback"),
        "quote_failure_reason": "fallback_used",
        "quote_fallback_used": True,
        "quote_fallback_source": source,
        "quote_fallback_price": price,
        "quote_fallback_warning": warning,
    })
    if meta.get("kis_quote_error"):
        warning = "; ".join([p for p in [f"KIS 실패: {meta['kis_quote_error']}", warning] if p])
    return _finalize_quote_row({
        "symbol": symbol,
        "market": market,
        "last_price": price,
        "intraday_change_pct": change_pct,
        "intraday_volume": 0.0,
        "intraday_trading_value": 0.0,
        "intraday_volume_ratio": 0.0,
        "intraday_trading_value_ratio": 0.0,
        "intraday_data_available": False,
        "intraday_data_source": "csv_fallback",
        "intraday_fetch_status": "fallback",
        "intraday_failure_reason": "fallback_used",
        "intraday_market_session": session,
        "market_session_status": _market_session_status_label(market),
        "intraday_updated_at": _now(),
        "intraday_warning": warning,
        **meta,
    })


def _us_quote_response_from_api(
    display_symbol: str,
    market_text: str,
    session: str,
    api_result: dict[str, Any],
    *,
    retry_used: bool = False,
    extra_warning: str = "",
    kis_tracking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    meta = _quote_meta_defaults()
    meta.update(_kis_tracking_from_result(kis_tracking or api_result))
    full = bool(api_result.get("quote_full_available"))
    partial = bool(api_result.get("quote_partial_available")) or not full
    source = str(api_result.get("quote_source", "")).strip().lower()
    current_price_ok = "last_price" in api_result and not math.isnan(_num(api_result.get("last_price"))) and _num(api_result.get("last_price")) > 0
    meta.update({
        "quote_available": True,
        "quote_partial_available": partial,
        "quote_full_available": full,
        "quote_source": source,
        "quote_source_label": quote_source_label(source),
        "quote_failure_reason": "",
        "quote_retry_used": bool(retry_used),
    })
    volume = float(api_result.get("intraday_volume", 0.0) or 0.0)
    trading_value = float(api_result.get("intraday_trading_value", 0.0) or 0.0)
    source = meta["quote_source"]
    if source == "kis_us_quote":
        warning = "" if full else "KIS 현재가 수신, 거래량/거래대금은 응답에 없거나 미수신"
    elif source == "finnhub_quote":
        warning = "KIS 실패 후 Finnhub 보조 수신" if extra_warning else (
            "" if full else "Finnhub 가격 수신, 거래량/거래대금은 API 미제공"
        )
    else:
        warning = "" if full else "quote API 가격만 수신, 거래량/거래대금 제한"
    if meta.get("kis_quote_error") and source == "finnhub_quote":
        kis_note = f"KIS 실패: {meta['kis_quote_error']}"
        warning = "; ".join([p for p in [kis_note, extra_warning, warning] if p])
    elif extra_warning and extra_warning not in warning:
        warning = "; ".join([p for p in [extra_warning, warning] if p])
    return _finalize_quote_row({
        "symbol": display_symbol,
        "market": market_text,
        "last_price": api_result["last_price"],
        "intraday_change_pct": api_result.get("intraday_change_pct", 0.0),
        "intraday_volume": volume,
        "intraday_trading_value": trading_value,
        "intraday_volume_ratio": 0.0,
        "intraday_trading_value_ratio": 0.0,
        "intraday_data_available": current_price_ok,
        "intraday_data_source": meta["quote_source"],
        "intraday_fetch_status": "success",
        "intraday_failure_reason": "",
        "intraday_market_session": session,
        "market_session_status": _market_session_status_label(market_text),
        "intraday_updated_at": _now(),
        "intraday_warning": warning,
        **meta,
    })


def summarize_us_quote_source_counts(df: pd.DataFrame) -> dict[str, int]:
    """미국주식 quote_source별 건수 (진단·요약 공용)."""
    if df is None or df.empty or "market" not in df.columns:
        return {
            "kis_us_quote_success_count": 0,
            "kis_us_quote_fail_count": 0,
            "finnhub_fallback_used_count": 0,
            "csv_fallback_used_count": 0,
            "quote_partial_fallback_count": 0,
            "quote_missing_count": 0,
        }
    us = df.loc[df["market"].astype(str).map(_is_us_market)].copy()
    if us.empty:
        return {
            "kis_us_quote_success_count": 0,
            "kis_us_quote_fail_count": 0,
            "finnhub_fallback_used_count": 0,
            "csv_fallback_used_count": 0,
            "quote_partial_fallback_count": 0,
            "quote_missing_count": 0,
        }
    sources = us.get("quote_source", pd.Series("", index=us.index)).astype(str).str.strip().str.lower()
    boolish = lambda col: us.get(col, pd.Series(False, index=us.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    kis_ok = int(sources.eq("kis_us_quote").sum())
    finnhub_ok = int(sources.eq("finnhub_quote").sum())
    csv_ok = int(sources.eq("csv_fallback").sum()) + int(sources.str.startswith("fallback_candidate_").sum())
    missing = int(sources.eq("missing").sum()) + int((~boolish("quote_available") & sources.eq("")).sum())
    partial = int((boolish("quote_partial_available") & ~boolish("quote_full_available")).sum())
    attempted = boolish("kis_quote_attempted")
    success = boolish("kis_quote_success")
    kis_fail = int((attempted & ~success).sum())
    return {
        "kis_us_quote_success_count": kis_ok,
        "kis_us_quote_fail_count": kis_fail,
        "finnhub_fallback_used_count": finnhub_ok,
        "csv_fallback_used_count": csv_ok,
        "quote_partial_fallback_count": partial,
        "quote_missing_count": missing,
    }


def _load_orderbook_map() -> dict[tuple[str, str], dict[str, Any]]:
    df = _read_csv(ORDERBOOK_SNAPSHOT_PATH)
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if df.empty or "symbol" not in df.columns:
        return out
    if "market" not in df.columns:
        df = df.copy()
        df["market"] = ""
    for _, row in df.iterrows():
        sym = str(row.get("symbol", "")).strip().upper()
        mkt = str(row.get("market", "")).strip()
        if sym:
            out[(sym, mkt)] = row.to_dict()
    return out


def load_intraday_targets() -> pd.DataFrame:
    """Swing candidates + holdings + watchlists + daily watch + required US symbols."""
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    default_source_scope = (
        tuple(Path(p) for p in SWING_CANDIDATE_FILES) == DEFAULT_SWING_CANDIDATE_FILES
        and tuple(Path(p) for p in HOLDING_FILES) == DEFAULT_HOLDING_FILES
    )

    def _upsert(item: dict[str, Any]) -> None:
        sym = str(item.get("symbol", "")).strip()
        mkt = str(item.get("market", "")).strip()
        if not sym:
            return
        sym, mkt, _ = _normalize_intraday_symbol(sym, mkt)
        if not sym:
            return
        item = dict(item)
        item["symbol"] = sym
        item["market"] = mkt
        key = (sym.upper(), mkt)
        if key not in merged:
            merged[key] = item
        else:
            merged[key] = _merge_target_row(merged[key], item)

    for row in _target_rows_from_candidates([Path(p) for p in SWING_CANDIDATE_FILES]):
        if not row.get("source_tags"):
            row["source_tags"] = str(row.get("target_type", "candidate"))
        _upsert(row)
    for row in _target_rows_from_holdings():
        _upsert(row)
    if default_source_scope:
        for row in _target_rows_from_watchlist_csvs():
            _upsert(row)
        for row in _target_rows_from_daily_watch_selection():
            _upsert(row)
        for row in _target_rows_required_us_symbols():
            _upsert(row)

    if not merged:
        return pd.DataFrame(columns=["symbol", "market", "source_file", "source_tags", "target_type"])
    return pd.DataFrame(list(merged.values())).reset_index(drop=True)


def fetch_intraday_quote(
    symbol: str,
    market: str,
    target_row: dict[str, Any] | None = None,
    orderbook: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market_text = str(market).strip()
    session = _market_session(market_text)

    if not _is_kr_market(market_text):
        symbol_text, valid = _normalize_us_symbol(symbol)
        display_symbol = symbol_text or str(symbol).strip().upper()
        if not valid:
            meta = _quote_meta_defaults()
            meta["quote_failure_reason"] = "invalid_symbol"
            return {
                "symbol": display_symbol,
                "market": market_text,
                "intraday_data_available": False,
                "intraday_data_source": "api_unavailable_safe",
                "intraday_fetch_status": "invalid_symbol",
                "intraday_failure_reason": "invalid_symbol",
                "intraday_market_session": session,
                "market_session_status": _market_session_status_label(market_text),
                "intraday_updated_at": _now(),
                "intraday_warning": "미국주식 심볼 형식 확인 필요",
                **meta,
            }
        kis_result = fetch_kis_us_quote_api(display_symbol, target_row=target_row)
        kis_tracking = _kis_tracking_from_result(kis_result)
        kis_retry = False
        if not kis_result.get("ok"):
            kis_retry = True
            kis_result = fetch_kis_us_quote_api(display_symbol, target_row=target_row)
            kis_tracking = _kis_tracking_from_result(kis_result)
            if kis_tracking.get("kis_quote_error"):
                log_intraday_quote_event(
                    "intraday_quote",
                    "warning",
                    ticker=display_symbol,
                    market=market_text,
                    message=f"KIS retry failed: {kis_tracking['kis_quote_error']}",
                    resolution="finnhub_quote or csv_fallback next",
                )
        if kis_result.get("ok"):
            return _us_quote_response_from_api(
                display_symbol,
                market_text,
                session,
                kis_result,
                retry_used=kis_retry,
                kis_tracking=kis_tracking,
            )

        finnhub_key = load_finnhub_api_key()
        if finnhub_key and is_finnhub_quote_symbol(display_symbol):
            fh = fetch_finnhub_intraday_quote(display_symbol, finnhub_key)
            if fh.get("ok"):
                fh["quote_source"] = "finnhub_quote"
                log_intraday_quote_event(
                    "intraday_quote",
                    "info",
                    ticker=display_symbol,
                    market=market_text,
                    message=f"Finnhub fallback after KIS fail: {kis_tracking.get('kis_quote_error', '')}",
                    resolution="quote_source=finnhub_quote",
                )
                return _us_quote_response_from_api(
                    display_symbol,
                    market_text,
                    session,
                    fh,
                    kis_tracking=kis_tracking,
                )
            fh_fail = str(fh.get("failure_reason", "api_response_empty") or "api_response_empty")
            log_intraday_quote_event(
                "intraday_quote",
                "warning",
                ticker=display_symbol,
                market=market_text,
                message=f"Finnhub fallback failed ({fh_fail}); KIS: {kis_tracking.get('kis_quote_error', '')}",
            )
            if fh_fail == "endpoint_not_configured":
                return _apply_quote_fallback(
                    display_symbol,
                    market_text,
                    session,
                    "unsupported_quote_api",
                    target_row=target_row,
                    orderbook=orderbook,
                    kis_tracking=kis_tracking,
                )
            return _apply_quote_fallback(
                display_symbol,
                market_text,
                session,
                "api_response_empty",
                target_row=target_row,
                orderbook=orderbook,
                kis_tracking=kis_tracking,
            )

        return _apply_quote_fallback(
            display_symbol,
            market_text,
            session,
            "api_response_empty" if not finnhub_key else "unsupported_quote_api",
            target_row=target_row,
            orderbook=orderbook,
            kis_tracking=kis_tracking,
        )

    code, valid = _normalize_kr_symbol(symbol)
    display_symbol = code if valid else str(symbol).strip()
    if not valid:
        meta = _quote_meta_defaults()
        meta["quote_failure_reason"] = "invalid_symbol"
        return {
            "symbol": display_symbol,
            "market": market_text,
            "intraday_data_available": False,
            "intraday_data_source": "api_unavailable_safe",
            "intraday_fetch_status": "invalid_symbol",
            "intraday_failure_reason": "invalid_symbol",
            "intraday_market_session": session,
            "market_session_status": _market_session_status_label(market),
            "intraday_updated_at": _now(),
            "intraday_warning": "종목코드 형식 확인 필요",
            **meta,
        }
    if session == "closed":
        meta = _quote_meta_defaults()
        meta["quote_failure_reason"] = "market_closed"
        return {
            "symbol": display_symbol,
            "market": market_text,
            "intraday_data_available": False,
            "intraday_data_source": "api_unavailable_safe",
            "intraday_fetch_status": "market_closed",
            "intraday_failure_reason": "market_closed",
            "intraday_market_session": session,
            "market_session_status": _market_session_status_label(market),
            "intraday_updated_at": _now(),
            "intraday_warning": "장 마감 또는 장전 시간",
            **meta,
        }

    api_result = _fetch_kis_kr_quote_api(code)
    retry_used = False
    if not api_result.get("ok"):
        retry_used = True
        api_result = _fetch_kis_kr_quote_api(code)

    if api_result.get("ok"):
        return _us_quote_response_from_api(
            display_symbol,
            market_text,
            session,
            {**api_result, "quote_source": str(api_result.get("quote_source", "kis_inquire_price"))},
            retry_used=retry_used,
        )

    failure = str(api_result.get("failure_reason", "api_response_empty") or "api_response_empty")
    if retry_used and failure == "api_response_empty":
        failure = "retry_response_empty"
    return _apply_quote_fallback(
        display_symbol,
        market_text,
        session,
        failure,
        target_row=target_row,
        orderbook=orderbook,
        retry_used=retry_used,
    )


def diagnose_intraday_fetch_result(row: dict[str, Any]) -> dict[str, Any]:
    symbol = str(row.get("symbol", "") or row.get("ticker", "")).strip()
    market = str(row.get("market", "")).strip()
    available = _truthy(row.get("intraday_data_available"))
    source = str(row.get("intraday_data_source", row.get("source", "")) or "").strip()
    session = str(_market_session(market) or row.get("intraday_market_session", "") or "unknown")
    status = str(row.get("intraday_fetch_status", "") or "").strip()
    reason = str(row.get("intraday_failure_reason", "") or "").strip()

    if available:
        status = "success"
        reason = ""
    elif not symbol:
        status = "invalid_symbol"
        reason = "종목코드 형식 확인 필요"
    elif status in {"api_error", "rate_limited", "unsupported_market", "skipped"}:
        reason = reason or {
            "api_error": "API 응답 없음",
            "rate_limited": "API 호출 제한 가능성",
            "unsupported_market": "해당 시장 장중 조회 미지원",
            "skipped": "조회 대상 아님",
        }[status]
    elif session == "closed":
        status = "market_closed"
        reason = reason or "장 마감 또는 장전 시간"
    elif not source or source == "api_unavailable_safe":
        status = status or "no_data"
        reason = reason or "장중 데이터 미수신"
    else:
        status = status or "unknown"
        reason = reason or "장중 데이터 미수신"

    return {
        "intraday_fetch_status": status,
        "intraday_failure_reason": reason,
        "intraday_market_session": session,
    }


def classify_intraday_data_status(row: dict[str, Any]) -> dict[str, Any]:
    diagnosed = diagnose_intraday_fetch_result(row)
    warning = str(row.get("intraday_warning", "") or "").strip()
    reason = diagnosed["intraday_failure_reason"]
    if reason and reason not in warning:
        warning = "; ".join([p for p in [warning, reason] if p])
    if not _truthy(row.get("intraday_data_available")) and "호가/체결강도 데이터 미지원 또는 미수신" not in warning:
        warning = "; ".join([p for p in [warning, "호가/체결강도 데이터 미지원 또는 미수신"] if p])
    return {**diagnosed, "intraday_warning": warning}


def normalize_intraday_data(raw: dict[str, Any]) -> dict[str, Any]:
    market = str(raw.get("market", "")).strip()
    symbol = str(raw.get("symbol", "") or raw.get("ticker", "")).strip()
    if _is_kr_market(market):
        normalized, valid = _normalize_kr_symbol(symbol)
        if valid:
            symbol = normalized
    last_price = _num(raw.get("last_price", raw.get("price", raw.get("current_price"))))
    change_pct = _num(raw.get("intraday_change_pct", raw.get("change_pct")), 0.0)
    volume = _num(raw.get("intraday_volume", raw.get("volume")), 0.0)
    trading_value = _num(raw.get("intraday_trading_value", raw.get("trading_value", raw.get("turnover"))), 0.0)
    volume_ratio = _num(raw.get("intraday_volume_ratio", raw.get("volume_ratio")), 0.0)
    trading_value_ratio = _num(raw.get("intraday_trading_value_ratio", raw.get("trading_value_ratio")), 0.0)
    if trading_value_ratio <= 0 and volume_ratio > 0:
        trading_value_ratio = volume_ratio
    quote_meta = _quote_meta_defaults()
    for key in quote_meta:
        if key in raw:
            quote_meta[key] = raw.get(key, quote_meta[key])
    for key in _kis_tracking_defaults():
        if key in raw:
            quote_meta[key] = raw.get(key, quote_meta[key])
    if raw.get("quote_source_label"):
        quote_meta["quote_source_label"] = raw.get("quote_source_label")
    available = raw.get("intraday_data_available")
    if available is None:
        available = _truthy(quote_meta.get("quote_full_available")) or (
            bool(symbol) and (not math.isnan(last_price) or volume > 0 or trading_value > 0)
        )

    bid = _num(raw.get("bid_total_volume"))
    ask = _num(raw.get("ask_total_volume"))
    imbalance = _num(raw.get("orderbook_imbalance"))
    execution = _num(raw.get("execution_strength"))
    current_ctx = current_session_for_market(market)
    current_session = str(current_ctx.get("session", raw.get("intraday_market_session", _market_session(market))))
    current_status = str(current_ctx.get("session_status", raw.get("market_session_status", current_session)))
    base = {
        "symbol": symbol,
        "market": market,
        "last_price": None if math.isnan(last_price) else last_price,
        "intraday_change_pct": change_pct,
        "intraday_volume": volume,
        "intraday_trading_value": trading_value,
        "intraday_volume_ratio": volume_ratio,
        "intraday_trading_value_ratio": trading_value_ratio,
        "intraday_data_available": bool(_truthy(available) or available is True),
        "intraday_data_source": str(raw.get("intraday_data_source", raw.get("source", "unknown")) or "unknown"),
        "intraday_updated_at": str(raw.get("intraday_updated_at", "") or _now()),
        "intraday_warning": str(raw.get("intraday_warning", "") or "").strip(),
        "bid_total_volume": None if math.isnan(bid) else bid,
        "ask_total_volume": None if math.isnan(ask) else ask,
        "orderbook_imbalance": None if math.isnan(imbalance) else imbalance,
        "execution_strength": None if math.isnan(execution) else execution,
        "intraday_fetch_status": raw.get("intraday_fetch_status", ""),
        "intraday_failure_reason": raw.get("intraday_failure_reason", raw.get("quote_failure_reason", "")),
        "intraday_market_session": current_session,
        "market_session_status": current_status,
        **quote_meta,
    }
    if quote_meta.get("quote_failure_reason"):
        base["intraday_failure_reason"] = str(quote_meta.get("quote_failure_reason"))
    return _finalize_quote_row({**base, **classify_intraday_data_status(base)})


def build_intraday_realtime_snapshot(candidate_files: list[str | Path] | None = None) -> pd.DataFrame:
    global SWING_CANDIDATE_FILES
    original_files = SWING_CANDIDATE_FILES
    if candidate_files is not None:
        SWING_CANDIDATE_FILES = [Path(p) for p in candidate_files]
    try:
        targets = load_intraday_targets()
    finally:
        SWING_CANDIDATE_FILES = original_files
    if targets.empty:
        return pd.DataFrame(columns=INTRADAY_SNAPSHOT_COLUMNS)

    orderbook_map = _load_orderbook_map()
    rows: list[dict[str, Any]] = []
    for _, target in targets.iterrows():
        symbol = str(target.get("symbol", "")).strip()
        market = str(target.get("market", "")).strip()
        sym_key = symbol.upper()
        if _is_kr_market(market):
            normalized, _ = _normalize_kr_symbol(symbol)
            sym_key = normalized or sym_key
        orderbook = orderbook_map.get((sym_key, market), orderbook_map.get((sym_key, ""), {}))
        try:
            raw = fetch_intraday_quote(symbol, market, target_row=target.to_dict(), orderbook=orderbook)
            rows.append(normalize_intraday_data(raw))
        except Exception as exc:
            rows.append(normalize_intraday_data({
                "symbol": symbol,
                "market": market,
                "intraday_data_available": False,
                "intraday_data_source": "error_safe",
                "intraday_fetch_status": "api_error",
                "intraday_failure_reason": f"API 응답 없음: {str(exc)[:120]}",
            }))
    return pd.DataFrame(rows, columns=INTRADAY_SNAPSHOT_COLUMNS)


def update_candidate_files_with_intraday_signals(snapshot_df: pd.DataFrame, candidate_files: list[str | Path] | None = None) -> dict[str, Any]:
    files = [Path(p) for p in (candidate_files or SWING_CANDIDATE_FILES)]
    results: list[dict[str, Any]] = []
    for path in files:
        df = read_swing_candidate_csv(path, required_columns=INTRADAY_SIGNAL_COLUMNS)
        before_cols = list(df.columns)
        updated = apply_intraday_signals_to_candidates(df, snapshot_df)
        for col in ["strategy_trade_allowed", "today_buy_allowed"]:
            if col in df.columns and col in updated.columns and "C_excluded" in path.name:
                updated[col] = df[col]
        if "C_excluded" in path.name and "intraday_entry_confirmed" in updated.columns:
            updated["intraday_entry_confirmed"] = False
        save_swing_candidate_csv(
            updated,
            path,
            required_columns=INTRADAY_SIGNAL_COLUMNS,
            preferred_columns=before_cols + [c for c in INTRADAY_SIGNAL_COLUMNS if c not in before_cols],
        )
        c_true = 0
        c_entry_true = 0
        if "C_excluded" in path.name:
            if "strategy_trade_allowed" in updated.columns:
                c_true = int(updated["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
            if "intraday_entry_confirmed" in updated.columns:
                c_entry_true = int(updated["intraday_entry_confirmed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
        results.append({
            "file": str(path),
            "rows": int(len(updated)),
            "c_strategy_trade_allowed_true": c_true,
            "c_intraday_entry_confirmed_true": c_entry_true,
        })
    return {"updated_files": results}


def build_intraday_missing_data_report(snapshot_df: pd.DataFrame) -> dict[str, Any]:
    df = pd.DataFrame() if snapshot_df is None else snapshot_df.copy()
    if df.empty:
        return {
            "intraday_missing_symbols": [],
            "intraday_failure_reason_counts": {},
            "skipped_count": 0,
            "unsupported_count": 0,
            "market_closed_count": 0,
        }
    available = df.get("intraday_data_available", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    missing = df.loc[~available].copy()
    reasons = missing.get("intraday_failure_reason", pd.Series("", index=missing.index)).astype(str).replace("", "장중 데이터 미수신")
    status = missing.get("intraday_fetch_status", pd.Series("", index=missing.index)).astype(str)
    return {
        "intraday_missing_symbols": missing.get("symbol", pd.Series(dtype=str)).astype(str).head(30).tolist(),
        "intraday_failure_reason_counts": dict(Counter(reasons.tolist())),
        "skipped_count": int(status.eq("skipped").sum()),
        "unsupported_count": int(status.isin(["unsupported", "unsupported_market"]).sum()),
        "market_closed_count": int(status.eq("market_closed").sum()),
    }


def save_intraday_realtime_snapshot(path: str | Path = SNAPSHOT_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        df = build_intraday_realtime_snapshot()
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(target, index=False, encoding="utf-8-sig")
        update_result = update_candidate_files_with_intraday_signals(df)
        return {"path": str(target), "rows": int(len(df)), "status": "OK", **update_result}
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=INTRADAY_SNAPSHOT_COLUMNS).to_csv(target, index=False, encoding="utf-8-sig")
        return {"path": str(target), "rows": 0, "status": "ERROR", "error": str(exc)}


def _summary_from_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    target_count = int(len(df))
    if target_count == 0:
        return {
            "updated_at": _now(),
            "target_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "skipped_count": 0,
            "unsupported_count": 0,
            "market_closed_count": 0,
            "data_available_rate": 0.0,
            "intraday_missing_symbols": [],
            "intraday_failure_reason_counts": {},
            "top_money_flow_symbols": [],
            "top_chase_risk_symbols": [],
            "intraday_warning_count": 0,
            "api_call_mode": "candidate_fallback_no_order",
            "overall_status": "NO_TARGETS",
            "warnings": ["조회 대상 없음"],
            "errors": [],
        }
    boolish = lambda col: df.get(col, pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    available = boolish("intraday_data_available")
    quote_any = boolish("quote_available") if "quote_available" in df.columns else available
    quote_full = boolish("quote_full_available") if "quote_full_available" in df.columns else available
    quote_partial = boolish("quote_partial_available") if "quote_partial_available" in df.columns else pd.Series(False, index=df.index)
    fallback_used = boolish("quote_fallback_used") if "quote_fallback_used" in df.columns else pd.Series(False, index=df.index)
    warning_text = df.get("intraday_warning", pd.Series("", index=df.index)).astype(str).str.strip()
    success_count = int(available.sum())
    fail_count = int(target_count - success_count)
    warning_count = int(warning_text.ne("").sum())
    missing_report = build_intraday_missing_data_report(df)
    money = df.copy()
    money["_ratio"] = pd.to_numeric(money.get("intraday_trading_value_ratio"), errors="coerce").fillna(0)
    top_money = money.sort_values("_ratio", ascending=False).head(5)["symbol"].astype(str).tolist() if "symbol" in money.columns else []
    chase = money[
        (pd.to_numeric(money.get("intraday_change_pct"), errors="coerce").fillna(0) >= 7)
        & (pd.to_numeric(money.get("intraday_trading_value_ratio"), errors="coerce").fillna(0) >= 2)
    ]
    warnings: list[str] = []
    if fail_count:
        warnings.append("일부 장중 데이터 미수신")
    if warning_count:
        warnings.append("장중 데이터 경고 존재")
    if success_count == 0 and missing_report["market_closed_count"] == target_count:
        status = "MARKET_CLOSED"
    elif success_count == 0 and missing_report["unsupported_count"] == target_count:
        status = "UNSUPPORTED"
    else:
        status = "OK" if success_count > 0 and fail_count == 0 else "WARNING"
    us_quote_counts = summarize_us_quote_source_counts(df)
    return {
        "updated_at": _now(),
        "target_count": target_count,
        "success_count": success_count,
        "fail_count": fail_count,
        "skipped_count": missing_report["skipped_count"],
        "unsupported_count": missing_report["unsupported_count"],
        "market_closed_count": missing_report["market_closed_count"],
        "data_available_rate": round(success_count / target_count, 4),
        "quote_available_rate": round(float(quote_any.mean()), 4),
        "quote_full_available_rate": round(float(quote_full.mean()), 4),
        "quote_partial_available_rate": round(float(quote_partial.mean()), 4),
        "quote_fallback_used_count": int(fallback_used.sum()),
        "quote_api_empty_count": int((~quote_any).sum()),
        "kr_quote_missing_count": int(
            (df["market"].astype(str).map(_is_kr_market) & ~quote_any).sum()
        ) if "market" in df.columns else 0,
        "kr_quote_fallback_count": int(
            (df["market"].astype(str).map(_is_kr_market) & fallback_used).sum()
        ) if "market" in df.columns else 0,
        **us_quote_counts,
        "intraday_missing_symbols": missing_report["intraday_missing_symbols"],
        "intraday_failure_reason_counts": missing_report["intraday_failure_reason_counts"],
        "top_money_flow_symbols": top_money,
        "top_chase_risk_symbols": chase["symbol"].astype(str).head(5).tolist() if "symbol" in chase.columns else [],
        "intraday_warning_count": warning_count,
        "api_call_mode": "candidate_fallback_no_order",
        "overall_status": status,
        "warnings": warnings,
        "errors": [],
    }


def save_intraday_realtime_summary(path: str | Path = SUMMARY_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        if SNAPSHOT_PATH.exists() and SNAPSHOT_PATH.stat().st_size > 0:
            df = pd.read_csv(SNAPSHOT_PATH, low_memory=False)
        else:
            df = build_intraday_realtime_snapshot()
        summary = _summary_from_snapshot(df)
    except Exception as exc:
        summary = {
            "updated_at": _now(),
            "target_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "skipped_count": 0,
            "unsupported_count": 0,
            "market_closed_count": 0,
            "data_available_rate": 0.0,
            "intraday_missing_symbols": [],
            "intraday_failure_reason_counts": {},
            "top_money_flow_symbols": [],
            "top_chase_risk_symbols": [],
            "intraday_warning_count": 0,
            "api_call_mode": "candidate_fallback_no_order",
            "overall_status": "ERROR",
            "warnings": [],
            "errors": [str(exc)],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"path": str(target), **summary}


def print_quote_source_distribution(path: str | Path = SNAPSHOT_PATH) -> None:
    """reports/intraday_realtime_snapshot.csv quote_source 분포 출력."""
    target = Path(path)
    if not target.exists() or target.stat().st_size == 0:
        print("[quote_source distribution] snapshot 없음")
        return
    df = pd.read_csv(target, dtype=str, low_memory=False).fillna("")
    if df.empty or "quote_source" not in df.columns:
        print("[quote_source distribution] quote_source 컬럼 없음")
        return
    print("\n[quote_source distribution - 전체]")
    print(df["quote_source"].value_counts().to_string())
    if "market" in df.columns:
        us = df.loc[df["market"].astype(str).map(_is_us_market)]
        if not us.empty:
            print("\n[quote_source distribution - 미국주식]")
            print(us["quote_source"].value_counts().to_string())
            if "kis_quote_success" in us.columns:
                kis_fail = us.loc[us["kis_quote_success"].astype(str).str.lower().isin(["false", "0"])]
                if not kis_fail.empty and "kis_quote_error" in kis_fail.columns:
                    print("\n[KIS 실패 샘플 - kis_quote_error]")
                    sample = kis_fail[["symbol", "quote_source", "kis_quote_error"]].head(8)
                    print(sample.to_string(index=False))


def main() -> int:
    snapshot = save_intraday_realtime_snapshot()
    print_quote_source_distribution(SNAPSHOT_PATH)
    summary = save_intraday_realtime_summary()
    result = {"snapshot": snapshot, "summary": summary}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if summary.get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
