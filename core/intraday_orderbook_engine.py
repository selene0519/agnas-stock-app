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

from core.intraday_order_strength_engine import ORDER_STRENGTH_COLUMNS, apply_order_strength_to_candidates
import core.intraday_realtime_engine as realtime_engine
from core.intraday_realtime_engine import _kr_market_session, _market_session, _num, _us_market_session
from core.market_session_engine import current_session_for_market, current_session_status
from core.intraday_signal_engine import apply_intraday_signals_to_candidates
from core.kis_token_manager import get_kis_access_token, merged_env, _parse_bool, _safe_str
from core.kis_us_orderbook import fetch_kis_us_orderbook_api
from core.swing_candidate_io import SWING_CANDIDATE_FILES, read_swing_candidate_csv, save_swing_candidate_csv


REPORT_DIR = Path("reports")
KST = ZoneInfo("Asia/Seoul")
US_ET = ZoneInfo("America/New_York")
ORDERBOOK_SNAPSHOT_PATH = REPORT_DIR / "intraday_orderbook_snapshot.csv"
ORDERBOOK_SUMMARY_PATH = REPORT_DIR / "intraday_orderbook_summary.json"
ORDERBOOK_ENDPOINT_KR = "inquire-asking-price-exp-ccn"
ORDERBOOK_TR_ID_KR = "FHKST01010200"
ORDERBOOK_SOURCE_LABELS: dict[str, str] = {
    "kis_open_api": "KIS 국내 호가",
    "kis_us_orderbook": "KIS 해외 호가",
    "unsupported_safe": "호가 미지원",
    "market_closed_safe": "장외 시간",
    "missing": "호가 미수신",
}

ORDERBOOK_FAILURE_LABELS: dict[str, str] = {
    "endpoint_not_configured": "API 연결 필요",
    "api_response_empty": "API 응답 없음",
    "no_orderbook_fields": "호가 필드 없음",
    "unsupported_market": "호가 미지원",
    "market_closed": "장 마감/장전",
    "auth_error": "인증 오류",
    "rate_limited": "호출 제한",
    "invalid_symbol": "종목코드 오류",
    "parser_error": "파싱 오류",
}

ORDERBOOK_COLUMNS = [
    "symbol",
    "market",
    "orderbook_available",
    "orderbook_data_available",
    "orderbook_fetch_status",
    "orderbook_failure_reason",
    "orderbook_market_support",
    "orderbook_endpoint_name",
    "orderbook_response_empty",
    "orderbook_parser_status",
    "market_session_status",
    "orderbook_source",
    "orderbook_source_label",
    "market_session_basis",
    "kis_kr_orderbook_attempted",
    "kis_kr_orderbook_success",
    "kis_kr_orderbook_error",
    "kis_us_orderbook_attempted",
    "kis_us_orderbook_success",
    "kis_us_orderbook_error",
    "bid_total_volume",
    "ask_total_volume",
    "bid_ask_ratio",
    "orderbook_imbalance",
    "best_bid",
    "best_ask",
    "bid_ask_spread",
    "bid_ask_spread_pct",
    "bid_ask_imbalance",
    "spread_pct",
    "kis_exchange_code",
    "execution_strength",
    "buy_execution_strength",
    "sell_execution_strength",
    "orderbook_data_source",
    "orderbook_updated_at",
    "orderbook_warning",
]


def _orderbook_source_label(source: Any) -> str:
    text = str(source or "").strip().lower()
    return ORDERBOOK_SOURCE_LABELS.get(text, text or ORDERBOOK_SOURCE_LABELS["missing"])


def _orderbook_failure_label(reason: Any) -> str:
    text = str(reason or "").strip().lower()
    return ORDERBOOK_FAILURE_LABELS.get(text, text or "호가 미수신")


def format_orderbook_failure_display(reason: Any) -> str:
    return _orderbook_failure_label(reason)


def _compute_spread_fields(
    best_bid: Any,
    best_ask: Any,
    *,
    ref_price: float | None = None,
) -> dict[str, float | None]:
    bid_v = _num(best_bid)
    ask_v = _num(best_ask)
    if math.isnan(bid_v) or math.isnan(ask_v) or bid_v <= 0 or ask_v <= 0:
        return {
            "bid_ask_spread": None,
            "bid_ask_spread_pct": None,
            "spread_pct": 0.0,
        }
    spread = ask_v - bid_v
    ref = ref_price if ref_price is not None and ref_price > 0 else (bid_v + ask_v) / 2
    spread_pct = spread / ref * 100 if ref > 0 else 0.0
    return {
        "bid_ask_spread": spread,
        "bid_ask_spread_pct": spread_pct,
        "spread_pct": spread_pct,
    }


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "yes", "y"}


def _coerce_kst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def _market_session_status(market: str, session: str, now: datetime | None = None) -> str:
    return current_session_status(market, now)


def _market_session_basis(market: str, session: str, now: datetime | None = None) -> str:
    return str(current_session_for_market(market, now).get("basis", f"unknown market session={session}"))


def _orderbook_market_session(market: str, now: datetime | None = None) -> str:
    if _is_kr_market(market):
        return _kr_market_session(now)
    if _is_us_market(market):
        return _us_market_session(now)
    return _market_session(market, now)


def _session_orderbook_failure_status(market: str, session_status: str, reason: str) -> tuple[str, str, str]:
    reason_text = str(reason or "").strip()
    if reason_text not in {"api_response_empty", "no_orderbook_fields", "no_data", "unknown"}:
        return reason_text, reason_text, "호가/체결강도 데이터 미지원 또는 미수신"
    if _is_kr_market(market) and session_status in {"장마감", "장전", "애프터마켓"}:
        return "market_closed", "market_closed", "장외 시간으로 실시간 호가 미수신 가능"
    if _is_us_market(market) and session_status in {"장전", "프리마켓"}:
        return "pre_market_not_open", "pre_market_not_open", "장외 시간으로 실시간 호가 미수신 가능"
    if _is_us_market(market) and session_status in {"장마감", "애프터마켓"}:
        return "market_closed", "market_closed", "장외 시간으로 실시간 호가 미수신 가능"
    return reason_text or "no_data", reason_text or "no_data", "호가/체결강도 데이터 미지원 또는 미수신"


def _is_kr_market(market: str) -> bool:
    text = str(market or "").strip().upper()
    return "한국" in str(market) or text in {"KR", "KRX", "KOSPI", "KOSDAQ"}


def _is_us_market(market: str) -> bool:
    text = str(market or "").strip().upper()
    return "미국" in str(market) or text in {"US", "NASDAQ", "NYSE", "AMEX"}


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


def _diagnose_symbol(symbol: str, market: str) -> dict[str, Any]:
    market_text = str(market or "").strip()
    if _is_us_market(market_text):
        normalized, valid = _normalize_us_symbol(symbol)
        return {
            "symbol": normalized or str(symbol).strip().upper(),
            "market": market_text,
            "market_bucket": "us",
            "symbol_valid": valid,
            "orderbook_market_support": "supported",
        }
    if _is_kr_market(market_text):
        normalized, valid = _normalize_kr_symbol(symbol)
        return {
            "symbol": normalized or str(symbol).strip(),
            "market": market_text,
            "market_bucket": "kr",
            "symbol_valid": valid,
            "orderbook_market_support": "supported",
        }
    return {
        "symbol": str(symbol).strip(),
        "market": market_text,
        "market_bucket": "unknown",
        "symbol_valid": bool(str(symbol).strip()),
        "orderbook_market_support": "unknown",
    }


def _kis_base_url(is_mock: bool) -> str:
    return (
        "https://openapivts.koreainvestment.com:29443"
        if is_mock
        else "https://openapi.koreainvestment.com:9443"
    )


def _kis_headers(tr_id: str, token: str, app_key: str, app_secret: str, is_mock: bool) -> dict[str, str]:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }


def _kis_configured() -> bool:
    env = merged_env()
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    enabled = _parse_bool(env.get("KIS_ENABLED"), True)
    return bool(enabled and app_key and app_secret)


def _fetch_kis_kr_orderbook(symbol: str) -> dict[str, Any]:
    if not _kis_configured():
        return {
            "ok": False,
            "failure_reason": "endpoint_not_configured",
            "parser_status": "skipped",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        return {
            "ok": False,
            "failure_reason": "auth_error",
            "parser_status": "skipped",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }
    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    code, valid = _normalize_kr_symbol(symbol)
    if not valid:
        return {
            "ok": False,
            "failure_reason": "invalid_symbol",
            "parser_status": "skipped",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }
    params = urllib.parse.urlencode(
        {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
    )
    url = f"{_kis_base_url(is_mock)}/uapi/domestic-stock/v1/quotations/{ORDERBOOK_ENDPOINT_KR}?{params}"
    request = urllib.request.Request(
        url,
        headers=_kis_headers(ORDERBOOK_TR_ID_KR, token, app_key, app_secret, is_mock),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return {
                "ok": False,
                "failure_reason": "rate_limited",
                "parser_status": "http_error",
                "response_empty": True,
                "endpoint_name": ORDERBOOK_ENDPOINT_KR,
            }
        return {
            "ok": False,
            "failure_reason": "auth_error" if exc.code in {401, 403} else "unknown",
            "parser_status": "http_error",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }
    except Exception:
        return {
            "ok": False,
            "failure_reason": "unknown",
            "parser_status": "request_error",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }

    output = payload.get("output1") or payload.get("output") or payload.get("output2")
    rows = output if isinstance(output, list) else ([output] if isinstance(output, dict) else [])
    if not rows:
        return {
            "ok": False,
            "failure_reason": "api_response_empty",
            "parser_status": "empty_output",
            "response_empty": True,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }

    bid_total = 0.0
    ask_total = 0.0
    best_bid = math.nan
    best_ask = math.nan
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid_qty = _num(
            row.get("bidp_rsqn")
            or row.get("bid_rsqn")
            or row.get("bidp1_rsqn")
            or row.get("bid_vol")
            or row.get("bidp_rsqn1"),
            0.0,
        )
        ask_qty = _num(
            row.get("askp_rsqn")
            or row.get("ask_rsqn")
            or row.get("askp1_rsqn")
            or row.get("ask_vol")
            or row.get("askp_rsqn1"),
            0.0,
        )
        bid_price = _num(row.get("bidp") or row.get("bidp1") or row.get("bid_price"))
        ask_price = _num(row.get("askp") or row.get("askp1") or row.get("ask_price"))
        bid_total += max(0.0, bid_qty)
        ask_total += max(0.0, ask_qty)
        if not math.isnan(bid_price) and bid_price > 0:
            best_bid = bid_price if math.isnan(best_bid) else max(best_bid, bid_price)
        if not math.isnan(ask_price) and ask_price > 0:
            best_ask = ask_price if math.isnan(best_ask) else min(best_ask, ask_price)

    if bid_total <= 0 and ask_total <= 0 and math.isnan(best_bid) and math.isnan(best_ask):
        return {
            "ok": False,
            "failure_reason": "no_orderbook_fields",
            "parser_status": "no_fields",
            "response_empty": False,
            "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        }

    total = bid_total + ask_total
    return {
        "ok": True,
        "failure_reason": "",
        "parser_status": "ok",
        "response_empty": False,
        "endpoint_name": ORDERBOOK_ENDPOINT_KR,
        "bid_total_volume": bid_total,
        "ask_total_volume": ask_total,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_ask_ratio": bid_total / ask_total if ask_total > 0 else (999.0 if bid_total > 0 else 0.0),
        "orderbook_imbalance": (bid_total - ask_total) / total if total > 0 else 0.0,
        "orderbook_data_source": "kis_open_api",
    }


def fetch_intraday_orderbook(
    symbol: str,
    market: str,
    target_row: dict[str, Any] | None = None,
) -> dict[str, Any]:
    diag = _diagnose_symbol(symbol, market)
    symbol_text = str(diag.get("symbol", "")).strip()
    market_text = str(diag.get("market", "")).strip()
    now_kst = datetime.now(KST)
    session = _orderbook_market_session(market_text, now_kst)
    session_status = _market_session_status(market_text, session, now_kst)
    session_basis = _market_session_basis(market_text, session, now_kst)
    base = {
        "symbol": symbol_text,
        "market": market_text,
        "orderbook_data_available": False,
        "orderbook_data_source": "unsupported_safe",
        "orderbook_fetch_status": "no_data",
        "orderbook_failure_reason": "unknown",
        "orderbook_market_support": str(diag.get("orderbook_market_support", "unknown")),
        "orderbook_endpoint_name": "",
        "orderbook_response_empty": True,
        "orderbook_parser_status": "skipped",
        "market_session_status": session_status,
        "intraday_market_session": session,
        "current_market_session_status": session_status,
        "market_session_basis": session_basis,
        "orderbook_updated_at": _now(),
        "orderbook_warning": "",
        "kis_kr_orderbook_attempted": False,
        "kis_kr_orderbook_success": False,
        "kis_kr_orderbook_error": "",
        "kis_us_orderbook_attempted": False,
        "kis_us_orderbook_success": False,
        "kis_us_orderbook_error": "",
        "bid_total_volume": 0.0,
        "ask_total_volume": 0.0,
        "bid_ask_ratio": 0.0,
        "orderbook_imbalance": 0.0,
        "best_bid": None,
        "best_ask": None,
        "spread_pct": 0.0,
        "execution_strength": 0.0,
        "buy_execution_strength": 0.0,
        "sell_execution_strength": 0.0,
    }

    if not symbol_text or not diag.get("symbol_valid"):
        base.update({
            "orderbook_fetch_status": "invalid_symbol",
            "orderbook_failure_reason": "invalid_symbol",
            "orderbook_warning": "종목코드 형식 확인 필요",
        })
        return base

    if session == "closed" and not _is_us_market(market_text):
        base.update({
            "orderbook_fetch_status": "market_closed",
            "orderbook_failure_reason": "market_closed",
            "orderbook_data_source": "market_closed_safe",
            "orderbook_source": "market_closed_safe",
            "orderbook_source_label": _orderbook_source_label("market_closed_safe"),
            "orderbook_warning": "장외 시간으로 실시간 호가 미수신 가능",
        })
        return base

    if _is_us_market(market_text):
        base.update({
            "kis_us_orderbook_attempted": bool(_kis_configured()),
            "kis_us_orderbook_success": False,
            "kis_us_orderbook_error": "",
            "orderbook_endpoint_name": "inquire-asking-price",
            "orderbook_market_support": "supported",
        })
        if not _kis_configured():
            err = "endpoint_not_configured"
            base.update({
                "orderbook_fetch_status": err,
                "orderbook_failure_reason": err,
                "orderbook_source": "missing",
                "orderbook_source_label": _orderbook_source_label("missing"),
                "kis_us_orderbook_error": "KIS_APP_KEY/KIS_APP_SECRET 미설정",
                "orderbook_warning": "KIS 해외주식 호가 API 미설정",
            })
            return base
        fetched = fetch_kis_us_orderbook_api(symbol_text, target_row=target_row)
        base["kis_us_orderbook_attempted"] = True
        base["orderbook_response_empty"] = not bool(fetched.get("ok"))
        base["orderbook_parser_status"] = "ok" if fetched.get("ok") else "no_fields"
        base["kis_exchange_code"] = str(fetched.get("kis_exchange_code", fetched.get("kis_exchange", "")) or "")
        if not fetched.get("ok"):
            reason = str(fetched.get("failure_reason", "api_response_empty") or "api_response_empty")
            fetch_status, failure_reason, session_warning = _session_orderbook_failure_status(
                market_text, session_status, reason
            )
            kis_err = str(fetched.get("kis_quote_error", "") or reason)[:500]
            warn = _orderbook_failure_label(reason)
            if reason == "no_orderbook_fields":
                warn = "호가 필드 없음 (미지원 가능)"
            if session_warning.startswith("장외 시간"):
                warn = session_warning
            base.update({
                "orderbook_fetch_status": fetch_status,
                "orderbook_failure_reason": failure_reason,
                "orderbook_data_source": str(fetched.get("orderbook_data_source", "kis_us_orderbook")),
                "orderbook_source": "kis_us_orderbook",
                "orderbook_source_label": _orderbook_source_label("kis_us_orderbook"),
                "kis_us_orderbook_success": False,
                "kis_us_orderbook_error": kis_err,
                "orderbook_warning": warn,
            })
            return base
        base["kis_us_orderbook_success"] = True
        best_bid = fetched.get("best_bid")
        best_ask = fetched.get("best_ask")
        spread_fields = _compute_spread_fields(best_bid, best_ask)
        if not math.isnan(_num(fetched.get("bid_ask_spread"))):
            spread_fields["bid_ask_spread"] = _num(fetched.get("bid_ask_spread"))
        if not math.isnan(_num(fetched.get("bid_ask_spread_pct"))):
            spread_fields["bid_ask_spread_pct"] = _num(fetched.get("bid_ask_spread_pct"))
            spread_fields["spread_pct"] = spread_fields["bid_ask_spread_pct"]
        exec_strength = _num(fetched.get("execution_strength"), math.nan)
        imbalance = fetched.get("bid_ask_imbalance", fetched.get("orderbook_imbalance"))
        base.update({
            "orderbook_data_available": True,
            "orderbook_available": True,
            "orderbook_data_source": str(fetched.get("orderbook_data_source", "kis_us_orderbook")),
            "orderbook_source": "kis_us_orderbook",
            "orderbook_source_label": _orderbook_source_label("kis_us_orderbook"),
            "orderbook_fetch_status": "success",
            "orderbook_failure_reason": "",
            "orderbook_warning": "",
            "bid_total_volume": fetched.get("bid_total_volume"),
            "ask_total_volume": fetched.get("ask_total_volume"),
            "bid_ask_ratio": fetched.get("bid_ask_ratio"),
            "orderbook_imbalance": imbalance,
            "bid_ask_imbalance": imbalance,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "execution_strength": None if math.isnan(exec_strength) else exec_strength,
            **spread_fields,
        })
        return base

    if not _is_kr_market(market_text):
        base.update({
            "orderbook_fetch_status": "unsupported_market",
            "orderbook_failure_reason": "unsupported_market",
            "orderbook_warning": "호가 미지원 시장",
        })
        return base

    if not _kis_configured():
        base.update({
            "orderbook_fetch_status": "unsupported",
            "orderbook_failure_reason": "endpoint_not_configured",
            "orderbook_endpoint_name": ORDERBOOK_ENDPOINT_KR,
            "orderbook_source": "missing",
            "orderbook_source_label": _orderbook_source_label("missing"),
            "kis_kr_orderbook_attempted": False,
            "kis_kr_orderbook_success": False,
            "kis_kr_orderbook_error": "KIS_APP_KEY/KIS_APP_SECRET 미설정",
            "orderbook_warning": "KIS 호가 endpoint 미설정",
        })
        return base

    base["kis_kr_orderbook_attempted"] = True
    fetched = _fetch_kis_kr_orderbook(symbol_text)
    base["orderbook_endpoint_name"] = str(fetched.get("endpoint_name", ORDERBOOK_ENDPOINT_KR))
    base["orderbook_response_empty"] = bool(fetched.get("response_empty", True))
    base["orderbook_parser_status"] = str(fetched.get("parser_status", "skipped"))

    if not fetched.get("ok"):
        reason = str(fetched.get("failure_reason", "unknown") or "unknown")
        fetch_status, failure_reason, warning = _session_orderbook_failure_status(
            market_text, session_status, reason
        )
        base.update({
            "orderbook_fetch_status": fetch_status if fetch_status in {
                "endpoint_not_configured", "unsupported_market", "invalid_symbol",
                "api_response_empty", "market_closed", "rate_limited", "auth_error",
                "parser_error", "no_orderbook_fields", "pre_market_not_open",
            } else "no_data",
            "orderbook_failure_reason": failure_reason,
            "orderbook_source": "kis_open_api",
            "orderbook_source_label": _orderbook_source_label("kis_open_api"),
            "orderbook_data_source": "kis_open_api",
            "kis_kr_orderbook_success": False,
            "kis_kr_orderbook_error": reason[:500],
            "orderbook_warning": warning,
        })
        return base

    best_bid = fetched.get("best_bid")
    best_ask = fetched.get("best_ask")
    spread_fields = _compute_spread_fields(best_bid, best_ask)
    total = _num(fetched.get("bid_total_volume"), 0.0) + _num(fetched.get("ask_total_volume"), 0.0)
    imbalance = fetched.get("orderbook_imbalance", 0.0)
    if total > 0 and (imbalance == 0.0 or imbalance is None):
        imbalance = (_num(fetched.get("bid_total_volume"), 0.0) - _num(fetched.get("ask_total_volume"), 0.0)) / total

    base.update({
        "orderbook_data_available": True,
        "orderbook_available": True,
        "orderbook_source": "kis_open_api",
        "orderbook_source_label": _orderbook_source_label("kis_open_api"),
        "orderbook_data_source": str(fetched.get("orderbook_data_source", "kis_open_api")),
        "orderbook_fetch_status": "success",
        "orderbook_failure_reason": "",
        "orderbook_warning": "",
        "kis_kr_orderbook_attempted": True,
        "kis_kr_orderbook_success": True,
        "kis_kr_orderbook_error": "",
        "bid_total_volume": fetched.get("bid_total_volume", 0.0),
        "ask_total_volume": fetched.get("ask_total_volume", 0.0),
        "bid_ask_ratio": fetched.get("bid_ask_ratio", 0.0),
        "orderbook_imbalance": imbalance,
        "bid_ask_imbalance": imbalance if total > 0 else None,
        "best_bid": best_bid,
        "best_ask": best_ask,
        **spread_fields,
    })
    return base


def normalize_orderbook_data(raw: dict[str, Any]) -> dict[str, Any]:
    symbol = str(raw.get("symbol", "") or raw.get("ticker", "")).strip()
    market = str(raw.get("market", "")).strip()
    bid = _num(raw.get("bid_total_volume"), 0.0)
    ask = _num(raw.get("ask_total_volume"), 0.0)
    best_bid = _num(raw.get("best_bid"))
    best_ask = _num(raw.get("best_ask"))
    spread_pct = _num(raw.get("spread_pct"), 0.0)
    bid_ask_spread = raw.get("bid_ask_spread")
    bid_ask_spread_pct = raw.get("bid_ask_spread_pct")
    if bid_ask_spread is None and bid_ask_spread_pct is None:
        spread_calc = _compute_spread_fields(best_bid, best_ask)
        bid_ask_spread = spread_calc.get("bid_ask_spread")
        bid_ask_spread_pct = spread_calc.get("bid_ask_spread_pct")
        if spread_pct <= 0:
            spread_pct = _num(spread_calc.get("spread_pct"), 0.0)
    bid_ask_imbalance = raw.get("bid_ask_imbalance")
    total = bid + ask
    bid_ask_ratio = _num(raw.get("bid_ask_ratio"), bid / ask if ask > 0 else (999.0 if bid > 0 else 0.0))
    imbalance = _num(raw.get("orderbook_imbalance"), (bid - ask) / total if total > 0 else 0.0)
    execution = _num(raw.get("execution_strength"), 0.0)
    buy_execution = _num(raw.get("buy_execution_strength"), 0.0)
    sell_execution = _num(raw.get("sell_execution_strength"), 0.0)
    available = raw.get("orderbook_data_available")
    if available is None:
        available = bool(total > 0 or execution > 0 or (not math.isnan(best_bid) and not math.isnan(best_ask)))
    status = str(raw.get("orderbook_fetch_status", "") or ("success" if _truthy(available) or available is True else "no_data"))
    reason = str(raw.get("orderbook_failure_reason", "") or "").strip() or "unknown"
    if _truthy(available) or available is True:
        reason = ""
    warning = str(raw.get("orderbook_warning", "") or "")
    if not (_truthy(available) or available is True):
        warning = warning or "호가/체결강도 데이터 미지원 또는 미수신"
    data_source = str(raw.get("orderbook_data_source", raw.get("source", "unknown")) or "unknown")
    ob_source = str(raw.get("orderbook_source", data_source) or data_source)
    return {
        "symbol": symbol,
        "market": market,
        "orderbook_available": bool(_truthy(available) or available is True),
        "orderbook_data_available": bool(_truthy(available) or available is True),
        "orderbook_fetch_status": status,
        "orderbook_failure_reason": reason,
        "orderbook_market_support": str(raw.get("orderbook_market_support", "unknown") or "unknown"),
        "orderbook_endpoint_name": str(raw.get("orderbook_endpoint_name", "") or ""),
        "orderbook_response_empty": bool(raw.get("orderbook_response_empty", True)),
        "orderbook_parser_status": str(raw.get("orderbook_parser_status", "skipped") or "skipped"),
        "market_session_status": _market_session_status(market, _orderbook_market_session(market)),
        "market_session_basis": _market_session_basis(market, _orderbook_market_session(market)),
        "bid_total_volume": bid,
        "ask_total_volume": ask,
        "bid_ask_ratio": bid_ask_ratio,
        "orderbook_imbalance": imbalance,
        "best_bid": None if math.isnan(best_bid) else best_bid,
        "best_ask": None if math.isnan(best_ask) else best_ask,
        "bid_ask_spread": bid_ask_spread,
        "bid_ask_spread_pct": bid_ask_spread_pct,
        "bid_ask_imbalance": bid_ask_imbalance,
        "spread_pct": spread_pct,
        "kis_exchange_code": str(raw.get("kis_exchange_code", "") or ""),
        "execution_strength": execution,
        "buy_execution_strength": buy_execution,
        "sell_execution_strength": sell_execution,
        "orderbook_source": ob_source,
        "orderbook_source_label": str(raw.get("orderbook_source_label", "") or _orderbook_source_label(ob_source)),
        "kis_kr_orderbook_attempted": bool(raw.get("kis_kr_orderbook_attempted", False)),
        "kis_kr_orderbook_success": bool(raw.get("kis_kr_orderbook_success", False)),
        "kis_kr_orderbook_error": str(raw.get("kis_kr_orderbook_error", "") or "")[:500],
        "kis_us_orderbook_attempted": bool(raw.get("kis_us_orderbook_attempted", False)),
        "kis_us_orderbook_success": bool(raw.get("kis_us_orderbook_success", False)),
        "kis_us_orderbook_error": str(raw.get("kis_us_orderbook_error", "") or "")[:500],
        "orderbook_data_source": data_source,
        "orderbook_updated_at": str(raw.get("orderbook_updated_at", "") or _now()),
        "orderbook_warning": warning,
    }


def build_intraday_orderbook_snapshot(candidate_files: list[str | Path] | None = None) -> pd.DataFrame:
    global SWING_CANDIDATE_FILES
    original_files = SWING_CANDIDATE_FILES
    original_realtime_files = realtime_engine.SWING_CANDIDATE_FILES
    if candidate_files is not None:
        SWING_CANDIDATE_FILES = [Path(p) for p in candidate_files]
        realtime_engine.SWING_CANDIDATE_FILES = [Path(p) for p in candidate_files]
    else:
        realtime_engine.SWING_CANDIDATE_FILES = [Path(p) for p in SWING_CANDIDATE_FILES]
    try:
        targets = realtime_engine.load_intraday_targets()
    finally:
        SWING_CANDIDATE_FILES = original_files
        realtime_engine.SWING_CANDIDATE_FILES = original_realtime_files
    if targets.empty:
        return pd.DataFrame(columns=ORDERBOOK_COLUMNS)
    rows: list[dict[str, Any]] = []
    for _, target in targets.iterrows():
        symbol = str(target.get("symbol", "")).strip()
        market = str(target.get("market", "")).strip()
        try:
            rows.append(
                normalize_orderbook_data(
                    fetch_intraday_orderbook(symbol, market, target_row=target.to_dict())
                )
            )
        except Exception as exc:
            rows.append(normalize_orderbook_data({
                "symbol": symbol,
                "market": market,
                "orderbook_data_available": False,
                "orderbook_data_source": "error_safe",
                "orderbook_fetch_status": "api_error",
                "orderbook_failure_reason": "parser_error",
                "orderbook_parser_status": "exception",
                "orderbook_warning": f"API 응답 없음: {str(exc)[:120]}",
            }))
    return pd.DataFrame(rows, columns=ORDERBOOK_COLUMNS)


def update_candidate_files_with_orderbook(orderbook_df: pd.DataFrame, candidate_files: list[str | Path] | None = None) -> dict[str, Any]:
    files = [Path(p) for p in (candidate_files or SWING_CANDIDATE_FILES)]
    results: list[dict[str, Any]] = []
    for path in files:
        required = list(dict.fromkeys(ORDER_STRENGTH_COLUMNS))
        df = read_swing_candidate_csv(path, required_columns=required)
        before_cols = list(df.columns)
        updated = apply_order_strength_to_candidates(df, orderbook_df)
        updated = apply_intraday_signals_to_candidates(updated, pd.DataFrame())
        for col in ["strategy_trade_allowed", "today_buy_allowed"]:
            if col in df.columns and col in updated.columns and "C_excluded" in path.name:
                updated[col] = df[col]
        if "C_excluded" in path.name:
            if "intraday_entry_confirmed" in updated.columns:
                updated["intraday_entry_confirmed"] = False
            if "order_strength_label" in updated.columns:
                updated["order_strength_label"] = "신규매수 금지 유지"
        save_swing_candidate_csv(
            updated,
            path,
            required_columns=required,
            preferred_columns=before_cols + [c for c in required if c not in before_cols],
        )
        c_true = 0
        c_entry_true = 0
        if "C_excluded" in path.name:
            if "strategy_trade_allowed" in updated.columns:
                c_true = int(updated["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
            if "intraday_entry_confirmed" in updated.columns:
                c_entry_true = int(updated["intraday_entry_confirmed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
        results.append({"file": str(path), "rows": int(len(updated)), "c_strategy_trade_allowed_true": c_true, "c_intraday_entry_confirmed_true": c_entry_true})
    return {"updated_files": results}


def _market_slice_stats(df: pd.DataFrame, is_kr: bool) -> dict[str, Any]:
    prefix = "kr" if is_kr else "us"
    if df.empty or "market" not in df.columns:
        return {f"{prefix}_target_count": 0, f"{prefix}_success_count": 0, f"{prefix}_data_available_rate": 0.0, f"{prefix}_orderbook_status": "NO_TARGETS"}
    mask = df["market"].astype(str).map(lambda m: _is_kr_market(m) if is_kr else _is_us_market(m))
    subset = df.loc[mask]
    target_count = int(len(subset))
    if target_count == 0:
        return {f"{prefix}_target_count": 0, f"{prefix}_success_count": 0, f"{prefix}_data_available_rate": 0.0, f"{prefix}_orderbook_status": "NO_TARGETS"}
    available = subset.get("orderbook_data_available", pd.Series(False, index=subset.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    success_count = int(available.sum())
    rate = round(float(available.mean()), 4)
    status_series = subset.get("orderbook_fetch_status", pd.Series("", index=subset.index)).astype(str)
    if success_count == target_count:
        status = "OK"
    elif int(status_series.isin(["market_closed", "pre_market_not_open", "after_market"]).sum()) == target_count:
        status = "MARKET_CLOSED"
    elif int((~available).sum()) == target_count and int(status_series.isin(["unsupported", "unsupported_market"]).sum()) == target_count:
        status = "UNSUPPORTED"
    else:
        status = "WARNING"
    return {
        f"{prefix}_target_count": target_count,
        f"{prefix}_success_count": success_count,
        f"{prefix}_data_available_rate": rate,
        f"{prefix}_orderbook_status": status,
    }


def _summary_from_snapshot(df: pd.DataFrame) -> dict[str, Any]:
    target_count = int(len(df))
    if target_count == 0:
        return {
            "updated_at": _now(),
            "target_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "unsupported_count": 0,
            "market_closed_count": 0,
            "data_available_rate": 0.0,
            "kr_target_count": 0,
            "kr_success_count": 0,
            "kr_data_available_rate": 0.0,
            "kr_orderbook_status": "NO_TARGETS",
            "us_target_count": 0,
            "us_success_count": 0,
            "us_data_available_rate": 0.0,
            "us_orderbook_status": "NO_TARGETS",
            "orderbook_warning_count": 0,
            "top_bid_imbalance_symbols": [],
            "top_ask_pressure_symbols": [],
            "top_execution_strength_symbols": [],
            "orderbook_failure_reason_counts": {},
            "overall_status": "NO_TARGETS",
            "warnings": ["조회 대상 없음"],
            "errors": [],
        }
    available = df.get("orderbook_data_available", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    status = df.get("orderbook_fetch_status", pd.Series("", index=df.index)).astype(str)
    warning_text = df.get("orderbook_warning", pd.Series("", index=df.index)).astype(str).str.strip()
    fail_count = int((~available).sum())
    unsupported_count = int(status.isin([
        "unsupported", "unsupported_market", "endpoint_not_configured", "no_data",
    ]).sum())
    market_closed_count = int(status.isin(["market_closed", "pre_market_not_open", "after_market"]).sum())
    warning_count = int(warning_text.ne("").sum())
    work = df.copy()
    work["_imbalance"] = pd.to_numeric(work.get("orderbook_imbalance", pd.Series(0, index=work.index)), errors="coerce").fillna(0)
    work["_execution"] = pd.to_numeric(work.get("execution_strength", pd.Series(0, index=work.index)), errors="coerce").fillna(0)
    if int(available.sum()) > 0:
        available_work = work.loc[available].copy()
        top_bid = available_work.sort_values("_imbalance", ascending=False).head(5)["symbol"].astype(str).tolist() if "symbol" in available_work.columns else []
        top_ask = available_work.sort_values("_imbalance", ascending=True).head(5)["symbol"].astype(str).tolist() if "symbol" in available_work.columns else []
        top_exec = available_work.sort_values("_execution", ascending=False).head(5)["symbol"].astype(str).tolist() if "symbol" in available_work.columns else []
    else:
        top_bid = []
        top_ask = []
        top_exec = []
    reason_series = df.get("orderbook_failure_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    reasons = reason_series.loc[~available].replace("", "unknown")
    if reasons.empty:
        reasons = pd.Series(dtype=str)
    warnings: list[str] = []
    if fail_count:
        warnings.append("일부 호가/체결강도 데이터 미수신")
    if unsupported_count:
        warnings.append("일부 호가/체결강도 미지원")
    if market_closed_count:
        warnings.append("일부 대상은 장외 시간으로 실시간 호가 미수신 가능")
    if int(available.sum()) == 0 and market_closed_count == target_count:
        overall = "MARKET_CLOSED"
    elif int(available.sum()) == 0 and unsupported_count == target_count:
        overall = "UNSUPPORTED"
    elif fail_count == 0:
        overall = "OK"
    else:
        overall = "WARNING"
    kr_stats = _market_slice_stats(df, is_kr=True)
    us_stats = _market_slice_stats(df, is_kr=False)
    market_col = df.get("market", pd.Series("", index=df.index)).astype(str)
    kr_mask = market_col.map(_is_kr_market)
    us_mask = market_col.map(_is_us_market)
    kr_attempted = df.get("kis_kr_orderbook_attempted", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    kr_success = df.get("kis_kr_orderbook_success", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    kr_error = df.get("kis_kr_orderbook_error", pd.Series("", index=df.index)).fillna("").astype(str)
    us_attempted = df.get("kis_us_orderbook_attempted", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    us_success = df.get("kis_us_orderbook_success", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    us_error = df.get("kis_us_orderbook_error", pd.Series("", index=df.index)).fillna("").astype(str)
    reason_all = df.get("orderbook_failure_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    return {
        "updated_at": _now(),
        "target_count": target_count,
        "success_count": int(available.sum()),
        "fail_count": fail_count,
        "unsupported_count": unsupported_count,
        "market_closed_count": market_closed_count,
        "data_available_rate": round(float(available.mean()), 4),
        **kr_stats,
        **us_stats,
        "kr_orderbook_attempt_count": int((kr_mask & kr_attempted).sum()),
        "kr_orderbook_success_count": int((kr_mask & available).sum()),
        "kr_orderbook_fail_count": int((kr_mask & ~available).sum()),
        "kr_orderbook_api_empty_count": int((kr_mask & (reason_all.eq("api_response_empty") | kr_error.str.contains("api_response_empty", na=False))).sum()),
        "kr_orderbook_no_fields_count": int((kr_mask & (reason_all.eq("no_orderbook_fields") | kr_error.str.contains("no_orderbook_fields", na=False))).sum()),
        "us_orderbook_attempt_count": int((us_mask & us_attempted).sum()),
        "us_orderbook_success_count": int((us_mask & us_success).sum()),
        "us_orderbook_fail_count": int((us_mask & us_attempted & ~us_success).sum()),
        "us_orderbook_api_empty_count": int((us_mask & (reason_all.eq("api_response_empty") | us_error.str.contains("api_response_empty", na=False))).sum()),
        "us_orderbook_no_fields_count": int((us_mask & (reason_all.eq("no_orderbook_fields") | us_error.str.contains("no_orderbook_fields", na=False))).sum()),
        "orderbook_warning_count": warning_count,
        "top_bid_imbalance_symbols": top_bid,
        "top_ask_pressure_symbols": top_ask,
        "top_execution_strength_symbols": top_exec,
        "orderbook_failure_reason_counts": dict(Counter(reasons.tolist())),
        "overall_status": overall,
        "warnings": warnings,
        "errors": [],
    }


def save_intraday_orderbook_snapshot(path: str | Path = ORDERBOOK_SNAPSHOT_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        df = build_intraday_orderbook_snapshot()
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(target, index=False, encoding="utf-8-sig")
        update_result = update_candidate_files_with_orderbook(df)
        return {"path": str(target), "rows": int(len(df)), "status": "OK", **update_result}
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=ORDERBOOK_COLUMNS).to_csv(target, index=False, encoding="utf-8-sig")
        return {"path": str(target), "rows": 0, "status": "ERROR", "error": str(exc)}


def save_intraday_orderbook_summary(path: str | Path = ORDERBOOK_SUMMARY_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        if ORDERBOOK_SNAPSHOT_PATH.exists() and ORDERBOOK_SNAPSHOT_PATH.stat().st_size > 0:
            df = pd.read_csv(ORDERBOOK_SNAPSHOT_PATH, low_memory=False)
        else:
            df = build_intraday_orderbook_snapshot()
        summary = _summary_from_snapshot(df)
    except Exception as exc:
        summary = {
            "updated_at": _now(),
            "target_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "unsupported_count": 0,
            "market_closed_count": 0,
            "data_available_rate": 0.0,
            "kr_target_count": 0,
            "kr_success_count": 0,
            "kr_data_available_rate": 0.0,
            "kr_orderbook_status": "NO_TARGETS",
            "us_target_count": 0,
            "us_success_count": 0,
            "us_data_available_rate": 0.0,
            "us_orderbook_status": "NO_TARGETS",
            "orderbook_warning_count": 0,
            "top_bid_imbalance_symbols": [],
            "top_ask_pressure_symbols": [],
            "top_execution_strength_symbols": [],
            "orderbook_failure_reason_counts": {},
            "overall_status": "ERROR",
            "warnings": [],
            "errors": [str(exc)],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"path": str(target), **summary}


def main() -> int:
    snapshot = save_intraday_orderbook_snapshot()
    summary = save_intraday_orderbook_summary()
    result = {"snapshot": snapshot, "summary": summary}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if summary.get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
