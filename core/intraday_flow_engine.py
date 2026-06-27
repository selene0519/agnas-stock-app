from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

import core.intraday_realtime_engine as realtime_engine
from core.intraday_realtime_engine import _kr_market_session, _market_session, _num
from core.intraday_flow_signal_engine import FLOW_SIGNAL_COLUMNS, apply_intraday_flow_to_candidates
from core.intraday_signal_engine import apply_intraday_signals_to_candidates
from core.kis_token_manager import get_kis_access_token, merged_env, _parse_bool, _safe_str
from core.kis_us_momentum import UsMomentumRankingCache, fetch_intraday_us_momentum_flow
from core.swing_candidate_io import SWING_CANDIDATE_FILES, read_swing_candidate_csv, save_swing_candidate_csv


REPORT_DIR = Path("reports")
LOG_DIR = Path("logs")
FLOW_SNAPSHOT_PATH = REPORT_DIR / "intraday_flow_snapshot.csv"
FLOW_SUMMARY_PATH = REPORT_DIR / "intraday_flow_summary.json"
FLOW_FAILURE_DETAIL_PATH = REPORT_DIR / "intraday_flow_failure_detail.csv"
FLOW_KR_API_LOG_PATH = LOG_DIR / "intraday_flow_kr_api.log"
KST = ZoneInfo("Asia/Seoul")
INVESTOR_ENDPOINT_KR = "inquire-investor"
INVESTOR_TR_ID_KR = "FHKST01010900"
PROGRAM_ENDPOINT_KR = "program-trade-by-stock"
PROGRAM_TR_ID_KR = "FHPPG04650101"
MAX_FLOW_TARGETS = 80

FLOW_SOURCE_LABELS: dict[str, str] = {
    "kis_inquire_investor": "KIS 투자자매매",
    "kis_program_trade": "KIS 프로그램매매",
    "kis_us_momentum": "KIS 미국 대체수급",
    "unsupported_safe": "수급 미지원",
}

FLOW_FAILURE_LABELS: dict[str, str] = {
    "endpoint_not_configured": "API 연결 필요",
    "api_response_empty": "API 응답 없음",
    "parser_error": "파싱 오류",
    "unsupported_market": "수급 미지원",
    "market_closed": "장 마감/장전",
    "auth_error": "인증 오류",
    "rate_limited": "호출 제한",
    "invalid_symbol": "종목코드 오류",
}
FLOW_FAILURE_LABELS.update({
    "kr_flow_endpoint_not_configured": "국장 수급 API 설정 필요",
    "kr_flow_request_failed": "국장 수급 API 요청 실패",
    "kr_flow_response_empty": "국장 수급 API 응답 없음",
    "kr_flow_parser_failed": "국장 수급 파싱 실패",
    "kr_flow_missing_required_fields": "국장 수급 필수 필드 없음",
    "kr_flow_symbol_format_error": "국장 종목코드 형식 오류",
    "kr_flow_market_closed": "국장 장외/장마감",
    "kr_flow_unsupported_endpoint": "국장 수급 API 미지원",
    "kr_flow_permission_or_env_error": "국장 수급 권한/환경 오류",
})

FLOW_COLUMNS = [
    "symbol",
    "market",
    "flow_mode",
    "foreign_net_buy",
    "institution_net_buy",
    "individual_net_buy",
    "program_net_buy",
    "foreign_flow_score",
    "institution_flow_score",
    "program_flow_score",
    "intraday_flow_score",
    "last_price",
    "intraday_change_pct",
    "intraday_volume",
    "intraday_trading_value",
    "volume_growth_pct",
    "trading_value_growth_pct",
    "execution_strength",
    "orderbook_pressure",
    "intraday_momentum_score",
    "flow_data_available",
    "flow_available",
    "flow_data_source",
    "flow_source",
    "flow_source_label",
    "flow_fetch_status",
    "flow_failure_reason",
    "kr_flow_attempted",
    "kr_flow_success",
    "kr_flow_error",
    "kr_flow_failure_detail",
    "kr_flow_endpoint_name",
    "kr_flow_request_params",
    "kr_flow_http_status",
    "kr_flow_api_code",
    "kr_flow_response_fields",
    "kr_flow_response_row_count",
    "kr_flow_parser_status",
    "kr_flow_session_status",
    "flow_updated_at",
    "flow_warning",
]


def _now() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


def _now_kst_iso() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S%z")


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "1.0", "yes", "y"}


def _is_kr_market(market: str) -> bool:
    return "한국" in str(market) or str(market).strip().upper() in {"KR", "KRX"}


def _is_us_market(market: str) -> bool:
    return "미국" in str(market) or str(market).strip().upper() in {"US", "NASDAQ", "NYSE"}


def _normalize_kr_symbol(symbol: str) -> tuple[str, bool]:
    digits = "".join(ch for ch in str(symbol).strip().upper() if ch.isdigit())
    if not digits:
        return str(symbol).strip(), False
    normalized = digits.zfill(6)[-6:] if len(digits) >= 6 else digits.zfill(6)
    return normalized, len(normalized) == 6


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


def _kr_flow_session_status() -> str:
    try:
        session = _kr_market_session()
        if isinstance(session, dict):
            return str(session.get("status", "") or "")
        return str(session or "")
    except Exception:
        return str(_market_session("?쒓뎅") or "")


def _kr_flow_diag_defaults(endpoint: str = INVESTOR_ENDPOINT_KR) -> dict[str, Any]:
    return {
        "kr_flow_failure_detail": "",
        "kr_flow_endpoint_name": endpoint,
        "kr_flow_request_params": "",
        "kr_flow_http_status": "",
        "kr_flow_api_code": "",
        "kr_flow_response_fields": "",
        "kr_flow_response_row_count": 0,
        "kr_flow_parser_status": "not_started",
        "kr_flow_session_status": _kr_flow_session_status(),
    }


def _mask_log_event(event: dict[str, Any]) -> dict[str, Any]:
    blocked = {"authorization", "access_token", "token", "appkey", "appsecret", "secret", "app_key", "app_secret"}
    safe: dict[str, Any] = {}
    for key, value in event.items():
        if str(key).lower() in blocked:
            safe[key] = "***"
        elif isinstance(value, dict):
            safe[key] = {k: ("***" if str(k).lower() in blocked else v) for k, v in value.items()}
        else:
            safe[key] = value
    return safe


def _log_kr_flow_api_event(**event: Any) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        payload = _mask_log_event({
            "kst_time": _now_kst_iso(),
            **event,
        })
        with FLOW_KR_API_LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def _output_rows(output: Any) -> list[dict[str, Any]]:
    if isinstance(output, list):
        return [row for row in output if isinstance(row, dict)]
    if isinstance(output, dict):
        return [output]
    return []


def _response_field_names(payload: Any, output: Any = None) -> str:
    names: list[str] = []
    if isinstance(payload, dict):
        names.extend(str(k) for k in payload.keys())
    for row in _output_rows(output):
        names.extend(str(k) for k in row.keys())
        break
    return ",".join(sorted(dict.fromkeys(names)))[:1000]


def _classify_kr_flow_failure(http_status: int | None = None, api_code: Any = "", message: Any = "") -> str:
    text = f"{api_code} {message}".lower()
    if http_status in {401, 403}:
        return "kr_flow_permission_or_env_error"
    if http_status == 429 or "rate" in text or "limit" in text or "초과" in text:
        return "rate_limited"
    if any(token in text for token in ["auth", "token", "permission", "unauthorized", "forbidden", "권한", "인증"]):
        return "kr_flow_permission_or_env_error"
    if any(token in text for token in ["unsupported", "not found", "미지원", "존재하지"]):
        return "kr_flow_unsupported_endpoint"
    return "kr_flow_request_failed"


def load_intraday_flow_targets() -> pd.DataFrame:
    original = list(realtime_engine.SWING_CANDIDATE_FILES)
    realtime_engine.SWING_CANDIDATE_FILES = [Path(p) for p in SWING_CANDIDATE_FILES]
    try:
        targets = realtime_engine.load_intraday_targets()
    finally:
        realtime_engine.SWING_CANDIDATE_FILES = original
    if targets.empty:
        return targets
    if len(targets) > MAX_FLOW_TARGETS:
        targets = targets.head(MAX_FLOW_TARGETS).copy()
    return targets.reset_index(drop=True)


def _flow_source_label(source: Any) -> str:
    text = str(source or "").strip().lower()
    return FLOW_SOURCE_LABELS.get(text, text or FLOW_SOURCE_LABELS["unsupported_safe"])


def _flow_failure_label(reason: Any) -> str:
    text = str(reason or "").strip().lower()
    return FLOW_FAILURE_LABELS.get(text, text or "수급 미수신")


def format_flow_failure_display(reason: Any) -> str:
    return _flow_failure_label(reason)


def _optional_net(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat", "-"}:
        return None
    num = _num(value, math.nan)
    if math.isnan(num):
        return None
    return num


def _first_optional_net(row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _optional_net(row.get(key))
        if value is not None:
            return value
    return None


def _net_from_fields(row: dict[str, Any], direct_keys: tuple[str, ...], buy_keys: tuple[str, ...], sell_keys: tuple[str, ...]) -> float | None:
    direct = _first_optional_net(row, direct_keys)
    if direct is not None:
        return direct
    buy = _first_optional_net(row, buy_keys)
    sell = _first_optional_net(row, sell_keys)
    if buy is not None or sell is not None:
        return float(buy or 0) - float(sell or 0)
    return None


def _parse_investor_row(row: dict[str, Any]) -> dict[str, float | None]:
    foreign = _net_from_fields(
        row,
        (
            "frgn_ntby_qty", "frgn_ntby_tr_pbmn", "frgn_fake_ntby_qty", "foreign_net_qty",
            "frgn_ntby_vol", "frgn_ntby_amt", "frgn_ntby_tr_amt", "frgn_net_buy_qty",
        ),
        ("frgn_shnu_qty", "frgn_buy_qty", "frgn_shnu_vol", "foreign_buy_qty", "frgn_buy_amt"),
        ("frgn_seln_qty", "frgn_sell_qty", "frgn_seln_vol", "foreign_sell_qty", "frgn_sell_amt"),
    )
    institution = _net_from_fields(
        row,
        (
            "orgn_ntby_qty", "orgn_ntby_tr_pbmn", "orgn_fake_ntby_qty", "institution_net_qty",
            "inst_ntby_qty", "inst_ntby_amt", "orgn_ntby_vol", "orgn_ntby_amt",
        ),
        ("orgn_shnu_qty", "inst_buy_qty", "orgn_shnu_vol", "institution_buy_qty", "inst_buy_amt"),
        ("orgn_seln_qty", "inst_sell_qty", "orgn_seln_vol", "institution_sell_qty", "inst_sell_amt"),
    )
    individual = _net_from_fields(
        row,
        (
            "prsn_ntby_qty", "prsn_ntby_tr_pbmn", "retail_net_qty", "indv_ntby_qty",
            "prsn_ntby_vol", "prsn_ntby_amt", "individual_net_qty",
        ),
        ("prsn_shnu_qty", "indv_buy_qty", "prsn_shnu_vol", "individual_buy_qty", "retail_buy_qty"),
        ("prsn_seln_qty", "indv_sell_qty", "prsn_seln_vol", "individual_sell_qty", "retail_sell_qty"),
    )
    if foreign is None and institution is None and individual is None:
        return {}
    return {
        "foreign_net_buy": foreign,
        "institution_net_buy": institution,
        "individual_net_buy": individual,
    }


def _parse_investor_output(output: Any) -> dict[str, float | None]:
    rows = _output_rows(output)
    if not rows:
        return {}
    for row in rows:
        parsed = _parse_investor_row(row)
        if parsed:
            return parsed
    return {}


def _parse_program_output(output: Any) -> float | None:
    rows = output if isinstance(output, list) else ([output] if isinstance(output, dict) else [])
    if not rows:
        return None
    latest = rows[-1] if isinstance(rows[-1], dict) else {}
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        latest = row
        break
    return _optional_net(
        latest.get("prgm_ntby_qty")
        or latest.get("prgm_ntby_tr_pbmn")
        or latest.get("pgm_ntby_qty")
        or latest.get("program_net_qty")
        or latest.get("ntby_qty")
    )


def fetch_intraday_investor_flow(symbol: str, market: str) -> dict[str, Any]:
    base = {
        "flow_mode": "kr_investor",
        "foreign_net_buy": None,
        "institution_net_buy": None,
        "individual_net_buy": None,
        "flow_fetch_status": "no_data",
        "flow_failure_reason": "unknown",
        "flow_data_source": "unsupported_safe",
        "kr_flow_attempted": False,
        "kr_flow_success": False,
        "kr_flow_error": "",
    }
    if _is_us_market(market):
        return {
            **base,
            "flow_mode": "us_momentum",
            "flow_fetch_status": "unsupported_market",
            "flow_failure_reason": "use_us_momentum_fetch",
        }
    if not _is_kr_market(market):
        base.update({"flow_fetch_status": "unsupported_market", "flow_failure_reason": "unsupported_market"})
        return base
    code, valid = _normalize_kr_symbol(symbol)
    if not valid:
        base.update({"flow_fetch_status": "invalid_symbol", "flow_failure_reason": "invalid_symbol"})
        return base
    if _market_session(market) == "closed":
        base.update({"flow_fetch_status": "market_closed", "flow_failure_reason": "market_closed"})
        return base
    if not _kis_configured():
        base.update({
            "flow_fetch_status": "endpoint_not_configured",
            "flow_failure_reason": "endpoint_not_configured",
            "kr_flow_attempted": True,
            "kr_flow_error": "KIS_APP_KEY/KIS_APP_SECRET 미설정",
        })
        return base
    base["kr_flow_attempted"] = True
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        base.update({"flow_fetch_status": "auth_error", "flow_failure_reason": "auth_error"})
        return base
    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    params = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    url = f"{_kis_base_url(is_mock)}/uapi/domestic-stock/v1/quotations/{INVESTOR_ENDPOINT_KR}?{params}"
    request = urllib.request.Request(url, headers=_kis_headers(INVESTOR_TR_ID_KR, token, app_key, app_secret), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        reason = "rate_limited" if exc.code == 429 else ("auth_error" if exc.code in {401, 403} else "unknown")
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": reason,
        })
        return base
    except Exception as exc:
        base.update({
            "flow_fetch_status": "unknown",
            "flow_failure_reason": "unknown",
            "kr_flow_error": str(exc)[:120],
        })
        return base

    if str(payload.get("rt_cd", "")).strip() not in {"", "0"}:
        msg = str(payload.get("msg1", "") or payload.get("msg_cd", "") or "rt_cd_error")[:120]
        base.update({
            "flow_fetch_status": "api_response_empty",
            "flow_failure_reason": "api_response_empty",
            "kr_flow_error": msg,
        })
        return base

    output = payload.get("output") or payload.get("output1") or payload.get("output2")
    parsed = _parse_investor_output(output)
    if not parsed:
        base.update({
            "flow_fetch_status": "api_response_empty",
            "flow_failure_reason": "api_response_empty",
            "kr_flow_error": "investor_output_empty",
        })
        return base
    base.update(parsed)
    base.update({
        "flow_fetch_status": "success",
        "flow_failure_reason": "",
        "flow_data_source": "kis_inquire_investor",
        "kr_flow_success": True,
        "kr_flow_error": "",
    })
    return base


def fetch_intraday_program_flow(symbol: str, market: str) -> dict[str, Any]:
    if _is_us_market(market) or not _is_kr_market(market):
        return {
            "program_net_buy": None,
            "program_fetch_status": "unsupported_market",
            "program_failure_reason": "unsupported_market",
        }
    code, valid = _normalize_kr_symbol(symbol)
    if not valid:
        return {
            "program_net_buy": None,
            "program_fetch_status": "invalid_symbol",
            "program_failure_reason": "invalid_symbol",
        }
    if not _kis_configured():
        return {
            "program_net_buy": None,
            "program_fetch_status": "endpoint_not_configured",
            "program_failure_reason": "endpoint_not_configured",
        }
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        return {
            "program_net_buy": None,
            "program_fetch_status": "auth_error",
            "program_failure_reason": "auth_error",
        }
    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    params = urllib.parse.urlencode({"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code})
    url = f"{_kis_base_url(is_mock)}/uapi/domestic-stock/v1/quotations/{PROGRAM_ENDPOINT_KR}?{params}"
    request = urllib.request.Request(
        url,
        headers=_kis_headers(PROGRAM_TR_ID_KR, token, app_key, app_secret),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        reason = "rate_limited" if exc.code == 429 else ("auth_error" if exc.code in {401, 403} else "unknown")
        return {
            "program_net_buy": None,
            "program_fetch_status": reason,
            "program_failure_reason": reason,
        }
    except Exception:
        return {
            "program_net_buy": None,
            "program_fetch_status": "unknown",
            "program_failure_reason": "unknown",
        }
    if str(payload.get("rt_cd", "")).strip() not in {"", "0"}:
        return {
            "program_net_buy": None,
            "program_fetch_status": "api_response_empty",
            "program_failure_reason": "api_response_empty",
        }
    output = payload.get("output") or payload.get("output1") or payload.get("output2")
    program = _parse_program_output(output)
    if program is None:
        return {
            "program_net_buy": None,
            "program_fetch_status": "api_response_empty",
            "program_failure_reason": "api_response_empty",
        }
    return {
        "program_net_buy": program,
        "program_fetch_status": "success",
        "program_failure_reason": "",
        "flow_data_source": "kis_program_trade",
    }


def fetch_intraday_investor_flow(symbol: str, market: str) -> dict[str, Any]:  # type: ignore[override]
    base = {
        "flow_mode": "kr_investor",
        "foreign_net_buy": None,
        "institution_net_buy": None,
        "individual_net_buy": None,
        "flow_fetch_status": "no_data",
        "flow_failure_reason": "unknown",
        "flow_data_source": "unsupported_safe",
        "kr_flow_attempted": False,
        "kr_flow_success": False,
        "kr_flow_error": "",
        **_kr_flow_diag_defaults(INVESTOR_ENDPOINT_KR),
    }
    if _is_us_market(market):
        return {
            **base,
            "flow_mode": "us_momentum",
            "flow_fetch_status": "unsupported_market",
            "flow_failure_reason": "use_us_momentum_fetch",
        }
    if not _is_kr_market(market):
        base.update({"flow_fetch_status": "unsupported_market", "flow_failure_reason": "unsupported_market"})
        return base

    code, valid = _normalize_kr_symbol(symbol)
    if not valid:
        reason = "kr_flow_symbol_format_error"
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": f"invalid_symbol:{symbol}",
            "kr_flow_parser_status": "symbol_format_error",
            "kr_flow_failure_detail": f"symbol={symbol}",
        })
        return base

    session_status = _kr_flow_session_status()
    safe_params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
    base.update({
        "kr_flow_session_status": session_status,
        "kr_flow_request_params": json.dumps(safe_params, ensure_ascii=False),
    })
    if session_status == "closed":
        reason = "kr_flow_market_closed"
        base.update({"flow_fetch_status": reason, "flow_failure_reason": reason, "kr_flow_error": "market_closed"})
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            attempted=False,
            parser_status="blocked_market_closed",
            failure_reason=reason,
        )
        return base

    if not _kis_configured():
        reason = "kr_flow_endpoint_not_configured"
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_attempted": True,
            "kr_flow_error": "KIS_APP_KEY/KIS_APP_SECRET missing",
            "kr_flow_parser_status": "not_configured",
            "kr_flow_failure_detail": "KIS_APP_KEY/KIS_APP_SECRET missing or KIS_ENABLED=false",
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            attempted=True,
            parser_status="not_configured",
            failure_reason=reason,
        )
        return base

    base["kr_flow_attempted"] = True
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        reason = "kr_flow_permission_or_env_error"
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": "access_token_invalid",
            "kr_flow_parser_status": "auth_error",
            "kr_flow_failure_detail": str(token_info.get("error") or "access token invalid")[:500],
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            attempted=True,
            parser_status="auth_error",
            failure_reason=reason,
        )
        return base

    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    params = urllib.parse.urlencode(safe_params)
    url = f"{_kis_base_url(is_mock)}/uapi/domestic-stock/v1/quotations/{INVESTOR_ENDPOINT_KR}?{params}"
    request = urllib.request.Request(url, headers=_kis_headers(INVESTOR_TR_ID_KR, token, app_key, app_secret), method="GET")
    http_status: int | None = None
    payload: dict[str, Any] = {}
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            http_status = int(getattr(response, "status", 0) or 0)
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        reason = _classify_kr_flow_failure(exc.code, "", exc.reason)
        detail = str(exc.reason or exc)[:500]
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": reason,
            "kr_flow_http_status": exc.code,
            "kr_flow_parser_status": "http_error",
            "kr_flow_failure_detail": detail,
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            http_status=exc.code,
            response_code="",
            response_fields="",
            response_row_count=0,
            attempted=True,
            parser_status="http_error",
            failure_reason=reason,
            failure_detail=detail,
        )
        return base
    except Exception as exc:
        reason = "kr_flow_request_failed"
        detail = str(exc)[:500]
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": detail[:120],
            "kr_flow_parser_status": "request_exception",
            "kr_flow_failure_detail": detail,
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            attempted=True,
            parser_status="request_exception",
            failure_reason=reason,
            failure_detail=detail,
        )
        return base

    api_code = str(payload.get("rt_cd", "")).strip()
    output = payload.get("output") or payload.get("output1") or payload.get("output2")
    fields = _response_field_names(payload, output)
    row_count = len(_output_rows(output))
    base.update({
        "kr_flow_http_status": http_status or "",
        "kr_flow_api_code": api_code,
        "kr_flow_response_fields": fields,
        "kr_flow_response_row_count": row_count,
    })
    if api_code not in {"", "0"}:
        msg = str(payload.get("msg1", "") or payload.get("msg_cd", "") or "rt_cd_error")[:500]
        reason = _classify_kr_flow_failure(http_status, api_code, msg)
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": msg[:120],
            "kr_flow_parser_status": "api_error",
            "kr_flow_failure_detail": msg,
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            http_status=http_status,
            response_code=api_code,
            response_fields=fields,
            response_row_count=row_count,
            attempted=True,
            parser_status="api_error",
            failure_reason=reason,
            failure_detail=msg,
        )
        return base

    if row_count <= 0:
        reason = "kr_flow_response_empty"
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": "empty_output",
            "kr_flow_parser_status": "empty_output",
            "kr_flow_failure_detail": "output/output1/output2 empty",
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            http_status=http_status,
            response_code=api_code,
            response_fields=fields,
            response_row_count=row_count,
            attempted=True,
            parser_status="empty_output",
            failure_reason=reason,
        )
        return base

    parsed = _parse_investor_output(output)
    if not parsed:
        reason = "kr_flow_missing_required_fields"
        base.update({
            "flow_fetch_status": reason,
            "flow_failure_reason": reason,
            "kr_flow_error": "investor_required_fields_missing",
            "kr_flow_parser_status": "missing_required_fields",
            "kr_flow_failure_detail": f"fields={fields}",
        })
        _log_kr_flow_api_event(
            symbol=code,
            market=market,
            kr_market_session=session_status,
            endpoint_name=INVESTOR_ENDPOINT_KR,
            request_params=safe_params,
            http_status=http_status,
            response_code=api_code,
            response_fields=fields,
            response_row_count=row_count,
            attempted=True,
            parser_status="missing_required_fields",
            failure_reason=reason,
        )
        return base

    base.update(parsed)
    base.update({
        "flow_fetch_status": "success",
        "flow_failure_reason": "",
        "flow_data_source": "kis_inquire_investor",
        "kr_flow_success": True,
        "kr_flow_error": "",
        "kr_flow_parser_status": "success",
        "kr_flow_failure_detail": "",
    })
    _log_kr_flow_api_event(
        symbol=code,
        market=market,
        kr_market_session=session_status,
        endpoint_name=INVESTOR_ENDPOINT_KR,
        request_params=safe_params,
        http_status=http_status,
        response_code=api_code,
        response_fields=fields,
        response_row_count=row_count,
        attempted=True,
        parser_status="success",
        failure_reason="",
    )
    return base


def _flow_score_from_net(net: float, scale: float = 1_000_000.0) -> int:
    if net == 0:
        return 50
    magnitude = min(35.0, abs(net) / max(scale, 1.0) * 10.0)
    return int(max(0, min(100, round(50 + (magnitude if net > 0 else -magnitude)))))


def _optional_metric(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"", "nan", "none", "nat", "-"}:
        return None
    num = _num(value, math.nan)
    if math.isnan(num):
        return None
    return num


def _safe_int_metric(value: Any) -> int:
    try:
        num = float(value or 0)
        if math.isnan(num):
            return 0
        return int(num)
    except Exception:
        return 0


def _kr_flow_diag_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "kr_flow_failure_detail": str(raw.get("kr_flow_failure_detail", "") or "")[:1000],
        "kr_flow_endpoint_name": str(raw.get("kr_flow_endpoint_name", "") or ""),
        "kr_flow_request_params": str(raw.get("kr_flow_request_params", "") or "")[:500],
        "kr_flow_http_status": raw.get("kr_flow_http_status", ""),
        "kr_flow_api_code": str(raw.get("kr_flow_api_code", "") or ""),
        "kr_flow_response_fields": str(raw.get("kr_flow_response_fields", "") or "")[:1000],
        "kr_flow_response_row_count": _safe_int_metric(raw.get("kr_flow_response_row_count", 0)),
        "kr_flow_parser_status": str(raw.get("kr_flow_parser_status", "") or ""),
        "kr_flow_session_status": str(raw.get("kr_flow_session_status", "") or ""),
    }


def normalize_intraday_flow_data(raw: dict[str, Any]) -> dict[str, Any]:
    symbol = str(raw.get("symbol", "")).strip()
    market = str(raw.get("market", "")).strip()
    flow_mode = str(raw.get("flow_mode", "") or ("us_momentum" if _is_us_market(market) else "kr_investor"))
    status = str(raw.get("flow_fetch_status", "no_data") or "no_data")
    reason = str(raw.get("flow_failure_reason", "") or "unknown").strip() or "unknown"
    available = _truthy(raw.get("flow_data_available"))
    if available is None or raw.get("flow_data_available") is None:
        if flow_mode == "us_momentum":
            available = status == "success"
        else:
            foreign = _optional_metric(raw.get("foreign_net_buy"))
            institution = _optional_metric(raw.get("institution_net_buy"))
            individual = _optional_metric(raw.get("individual_net_buy"))
            program = _optional_metric(raw.get("program_net_buy"))
            available = status == "success" and any(
                x is not None for x in (foreign, institution, individual, program)
            )
    if available and reason in {"unknown", "no_data"}:
        reason = ""
    warning = str(raw.get("flow_warning", "") or "")
    if flow_mode == "us_momentum":
        momentum = _optional_metric(raw.get("intraday_momentum_score"))
        flow_score = int(momentum) if momentum is not None else 45
        if not available:
            warning = warning or "미국주식 장중 수급 대체 지표 미수신"
            flow_score = max(35, min(50, flow_score))
        data_source = str(raw.get("flow_data_source", "kis_us_momentum") or "kis_us_momentum")
        return {
            "symbol": symbol,
            "market": market,
            "flow_mode": flow_mode,
            "foreign_net_buy": None,
            "institution_net_buy": None,
            "individual_net_buy": None,
            "program_net_buy": None,
            "foreign_flow_score": None,
            "institution_flow_score": None,
            "program_flow_score": None,
            "intraday_flow_score": flow_score,
            "last_price": _optional_metric(raw.get("last_price")),
            "intraday_change_pct": _optional_metric(raw.get("intraday_change_pct")),
            "intraday_volume": _optional_metric(raw.get("intraday_volume")),
            "intraday_trading_value": _optional_metric(raw.get("intraday_trading_value")),
            "volume_growth_pct": _optional_metric(raw.get("volume_growth_pct")),
            "trading_value_growth_pct": _optional_metric(raw.get("trading_value_growth_pct")),
            "execution_strength": _optional_metric(raw.get("execution_strength")),
            "orderbook_pressure": _optional_metric(raw.get("orderbook_pressure")),
            "intraday_momentum_score": momentum,
            "flow_data_available": bool(available),
            "flow_available": bool(available),
            "flow_data_source": data_source,
            "flow_source": data_source,
            "flow_source_label": str(raw.get("flow_source_label", "") or _flow_source_label(data_source)),
            "flow_fetch_status": status,
            "flow_failure_reason": reason,
            "kr_flow_attempted": bool(raw.get("kr_flow_attempted", False)),
            "kr_flow_success": bool(raw.get("kr_flow_success", False)),
            "kr_flow_error": str(raw.get("kr_flow_error", "") or "")[:500],
            **_kr_flow_diag_from_raw(raw),
            "flow_updated_at": str(raw.get("flow_updated_at", "") or _now()),
            "flow_warning": warning,
        }

    foreign = _optional_metric(raw.get("foreign_net_buy"))
    institution = _optional_metric(raw.get("institution_net_buy"))
    individual = _optional_metric(raw.get("individual_net_buy"))
    program = _optional_metric(raw.get("program_net_buy"))
    foreign_score = _flow_score_from_net(float(foreign or 0)) if foreign is not None else 50
    institution_score = _flow_score_from_net(float(institution or 0)) if institution is not None else 50
    program_score = _flow_score_from_net(float(program or 0), scale=500_000.0) if program is not None else 50
    individual_score = _flow_score_from_net(float(individual or 0), 800_000.0) if individual is not None else 50
    flow_score = int(max(0, min(100, round(
        foreign_score * 0.35 + institution_score * 0.35 + program_score * 0.2 + individual_score * 0.1
    ))))
    if not available:
        warning = warning or "수급/프로그램 데이터 미지원 또는 미수신"
        flow_score = max(35, min(50, flow_score))
        if status in {"endpoint_not_configured", "unsupported", "unsupported_market"}:
            foreign = institution = individual = program = None
    data_source = str(raw.get("flow_data_source", "kis_inquire_investor") or "kis_inquire_investor")
    return {
        "symbol": symbol,
        "market": market,
        "flow_mode": flow_mode,
        "foreign_net_buy": foreign,
        "institution_net_buy": institution,
        "individual_net_buy": individual,
        "program_net_buy": program,
        "foreign_flow_score": foreign_score,
        "institution_flow_score": institution_score,
        "program_flow_score": program_score,
        "intraday_flow_score": flow_score,
        "last_price": _optional_metric(raw.get("last_price")),
        "intraday_change_pct": _optional_metric(raw.get("intraday_change_pct")),
        "intraday_volume": _optional_metric(raw.get("intraday_volume")),
        "intraday_trading_value": _optional_metric(raw.get("intraday_trading_value")),
        "volume_growth_pct": None,
        "trading_value_growth_pct": None,
        "execution_strength": None,
        "orderbook_pressure": None,
        "intraday_momentum_score": None,
        "flow_data_available": bool(available),
        "flow_available": bool(available),
        "flow_data_source": data_source,
        "flow_source": str(raw.get("flow_source", data_source) or data_source),
        "flow_source_label": str(raw.get("flow_source_label", "") or _flow_source_label(data_source)),
        "flow_fetch_status": status,
        "flow_failure_reason": reason,
        "kr_flow_attempted": bool(raw.get("kr_flow_attempted", False)),
        "kr_flow_success": bool(raw.get("kr_flow_success", False)),
        "kr_flow_error": str(raw.get("kr_flow_error", "") or "")[:500],
        **_kr_flow_diag_from_raw(raw),
        "flow_updated_at": str(raw.get("flow_updated_at", "") or _now()),
        "flow_warning": warning or (_flow_failure_label(reason) if not available else ""),
    }


def _load_snapshot_map(path: Path, key_cols: tuple[str, str] = ("symbol", "market")) -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    try:
        if not path.exists() or path.stat().st_size == 0:
            return out
        df = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        return out
    if df.empty or key_cols[0] not in df.columns:
        return out
    if key_cols[1] not in df.columns:
        df = df.copy()
        df[key_cols[1]] = ""
    for _, row in df.iterrows():
        sym = str(row.get(key_cols[0], "")).strip().upper()
        mkt = str(row.get(key_cols[1], "")).strip()
        if sym:
            out[(sym, mkt)] = row.to_dict()
            out[(sym, "")] = row.to_dict()
    return out


def build_intraday_flow_snapshot(candidate_files: list[str | Path] | None = None) -> pd.DataFrame:
    if candidate_files is not None:
        original = list(realtime_engine.SWING_CANDIDATE_FILES)
        realtime_engine.SWING_CANDIDATE_FILES = [Path(p) for p in candidate_files]
        try:
            targets = load_intraday_flow_targets()
        finally:
            realtime_engine.SWING_CANDIDATE_FILES = original
    else:
        targets = load_intraday_flow_targets()
    if targets.empty:
        return pd.DataFrame(columns=FLOW_COLUMNS)
    realtime_map = _load_snapshot_map(realtime_engine.SNAPSHOT_PATH)
    orderbook_map = _load_snapshot_map(REPORT_DIR / "intraday_orderbook_snapshot.csv")
    us_ranking_cache = UsMomentumRankingCache()
    rows: list[dict[str, Any]] = []
    for _, target in targets.iterrows():
        symbol = str(target.get("symbol", "")).strip()
        market = str(target.get("market", "")).strip()
        sym_key = symbol.upper()
        try:
            if _is_us_market(market):
                raw = fetch_intraday_us_momentum_flow(
                    symbol,
                    market,
                    target_row=target.to_dict(),
                    ranking_cache=us_ranking_cache,
                    realtime_row=realtime_map.get((sym_key, market), realtime_map.get((sym_key, ""))),
                    orderbook_row=orderbook_map.get((sym_key, market), orderbook_map.get((sym_key, ""))),
                )
                raw["symbol"] = symbol
                raw["market"] = market
                raw["flow_data_available"] = raw.get("flow_fetch_status") == "success"
                rows.append(normalize_intraday_flow_data(raw))
                continue
            investor = fetch_intraday_investor_flow(symbol, market)
            program = fetch_intraday_program_flow(symbol, market)
            merged_status = investor.get("flow_fetch_status", "no_data")
            merged_reason = investor.get("flow_failure_reason", "unknown")
            investor_ok = investor.get("flow_fetch_status") == "success"
            program_ok = program.get("program_fetch_status") == "success"
            if not investor_ok and program_ok:
                merged_status = "success"
                merged_reason = ""
            elif investor_ok and not program_ok:
                merged_reason = ""
            elif not investor_ok and not program_ok:
                merged_reason = investor.get("flow_failure_reason") or program.get("program_failure_reason", "unknown")
            sources = []
            if investor_ok:
                sources.append(str(investor.get("flow_data_source", "kis_inquire_investor")))
            if program_ok:
                sources.append(str(program.get("flow_data_source", "kis_program_trade")))
            flow_source = "+".join(sources) if sources else str(investor.get("flow_data_source", "unsupported_safe"))
            raw = {
                "symbol": symbol,
                "market": market,
                "flow_mode": "kr_investor",
                **investor,
                "program_net_buy": program.get("program_net_buy"),
                "flow_fetch_status": merged_status,
                "flow_failure_reason": merged_reason,
                "flow_data_available": investor_ok or program_ok,
                "flow_data_source": flow_source,
                "flow_source_label": _flow_source_label(flow_source.split("+")[0] if flow_source else ""),
                "kr_flow_attempted": bool(investor.get("kr_flow_attempted", False)),
                "kr_flow_success": bool(investor.get("kr_flow_success", False) or program_ok),
                "kr_flow_error": "" if (investor_ok or program_ok) else str(investor.get("kr_flow_error", "") or program.get("program_failure_reason", ""))[:500],
            }
            rows.append(normalize_intraday_flow_data(raw))
        except Exception as exc:
            rows.append(normalize_intraday_flow_data({
                "symbol": symbol,
                "market": market,
                "flow_data_available": False,
                "flow_fetch_status": "parser_error",
                "flow_failure_reason": "parser_error",
                "flow_warning": str(exc)[:120],
            }))
    return pd.DataFrame(rows, columns=FLOW_COLUMNS)


def update_candidate_files_with_flow(flow_df: pd.DataFrame, sector_flow_df: pd.DataFrame | None = None) -> dict[str, Any]:
    from core.intraday_sector_flow_engine import build_intraday_sector_flow

    sector_df = sector_flow_df
    if sector_df is None:
        sector_df = build_intraday_sector_flow(flow_df=flow_df)
    intraday_snapshot = pd.DataFrame()
    if realtime_engine.SNAPSHOT_PATH.exists() and realtime_engine.SNAPSHOT_PATH.stat().st_size > 0:
        intraday_snapshot = pd.read_csv(realtime_engine.SNAPSHOT_PATH, low_memory=False)

    results: list[dict[str, Any]] = []
    for path in SWING_CANDIDATE_FILES:
        required = list(dict.fromkeys(FLOW_SIGNAL_COLUMNS))
        df = read_swing_candidate_csv(path, required_columns=required)
        before_cols = list(df.columns)
        updated = apply_intraday_flow_to_candidates(df, flow_df, sector_df)
        updated = apply_intraday_signals_to_candidates(updated, intraday_snapshot)
        for col in ["strategy_trade_allowed", "today_buy_allowed"]:
            if col in df.columns and col in updated.columns and "C_excluded" in Path(path).name:
                updated[col] = df[col]
        if "C_excluded" in Path(path).name:
            if "intraday_entry_confirmed" in updated.columns:
                updated["intraday_entry_confirmed"] = False
        save_swing_candidate_csv(
            updated,
            path,
            required_columns=required,
            preferred_columns=before_cols + [c for c in required if c not in before_cols],
        )
        c_true = 0
        c_entry = 0
        if "C_excluded" in Path(path).name:
            if "strategy_trade_allowed" in updated.columns:
                c_true = int(updated["strategy_trade_allowed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
            if "intraday_entry_confirmed" in updated.columns:
                c_entry = int(updated["intraday_entry_confirmed"].astype(str).str.lower().isin(["true", "1", "1.0"]).sum())
        results.append({"file": str(path), "rows": int(len(updated)), "c_strategy_trade_allowed_true": c_true, "c_intraday_entry_confirmed_true": c_entry})
    return {"updated_files": results}


def _market_slice_stats(df: pd.DataFrame, is_kr: bool) -> dict[str, Any]:
    if df.empty:
        prefix = "kr" if is_kr else "us"
        return {f"{prefix}_target_count": 0, f"{prefix}_success_count": 0, f"{prefix}_data_available_rate": 0.0}
    mask = df["market"].astype(str).map(lambda m: _is_kr_market(m) if is_kr else _is_us_market(m))
    subset = df.loc[mask]
    target = int(len(subset))
    if target == 0:
        prefix = "kr" if is_kr else "us"
        return {f"{prefix}_target_count": 0, f"{prefix}_success_count": 0, f"{prefix}_data_available_rate": 0.0}
    available = subset.get("flow_data_available", pd.Series(False, index=subset.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    prefix = "kr" if is_kr else "us"
    return {
        f"{prefix}_target_count": target,
        f"{prefix}_success_count": int(available.sum()),
        f"{prefix}_data_available_rate": round(float(available.mean()), 4),
    }


def _kr_flow_detail_stats(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty or "market" not in df.columns:
        return {
            "kr_flow_target_count": 0,
            "kr_flow_attempt_count": 0,
            "kr_flow_success_count": 0,
            "kr_flow_fail_count": 0,
            "kr_flow_failure_reason_counts": {},
            "kr_flow_last_updated_at": "",
            "kr_market_session_status": _kr_flow_session_status(),
            "kr_flow_failure_detail_path": str(FLOW_FAILURE_DETAIL_PATH),
        }
    kr_mask = df["market"].astype(str).map(_is_kr_market)
    kr = df.loc[kr_mask].copy()
    if kr.empty:
        return {
            "kr_flow_target_count": 0,
            "kr_flow_attempt_count": 0,
            "kr_flow_success_count": 0,
            "kr_flow_fail_count": 0,
            "kr_flow_failure_reason_counts": {},
            "kr_flow_last_updated_at": "",
            "kr_market_session_status": _kr_flow_session_status(),
            "kr_flow_failure_detail_path": str(FLOW_FAILURE_DETAIL_PATH),
        }
    available = kr.get("flow_data_available", pd.Series(False, index=kr.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    attempted = kr.get("kr_flow_attempted", pd.Series(False, index=kr.index)).astype(str).str.lower().isin(["true", "1", "1.0", "yes", "y"])
    success = kr.get("kr_flow_success", available).astype(str).str.lower().isin(["true", "1", "1.0", "yes", "y"]) | available
    reasons = kr.get("flow_failure_reason", pd.Series("", index=kr.index)).fillna("").astype(str).str.strip()
    detail_reasons = reasons.loc[~success & reasons.ne("") & reasons.ne("unknown")]
    if detail_reasons.empty:
        errors = kr.get("kr_flow_error", pd.Series("", index=kr.index)).fillna("").astype(str).str.strip()
        detail_reasons = errors.loc[~success & errors.ne("")]
    updated = kr.get("flow_updated_at", pd.Series("", index=kr.index)).fillna("").astype(str).str.strip()
    return {
        "kr_flow_target_count": int(len(kr)),
        "kr_flow_attempt_count": int(attempted.sum()),
        "kr_flow_success_count": int(success.sum()),
        "kr_flow_fail_count": int((~success).sum()),
        "kr_flow_failure_reason_counts": dict(Counter(detail_reasons.tolist())),
        "kr_flow_last_updated_at": str(updated.iloc[-1]) if not updated.empty else "",
        "kr_market_session_status": _kr_flow_session_status(),
        "kr_flow_failure_detail_path": str(FLOW_FAILURE_DETAIL_PATH),
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
            **_kr_flow_detail_stats(df),
            "us_target_count": 0,
            "us_success_count": 0,
            "us_data_available_rate": 0.0,
            "flow_warning_count": 0,
            "top_foreign_buy_symbols": [],
            "top_institution_buy_symbols": [],
            "top_program_buy_symbols": [],
            "top_flow_score_symbols": [],
            "flow_failure_reason_counts": {},
            "overall_status": "NO_TARGETS",
            "warnings": ["조회 대상 없음"],
            "errors": [],
        }
    available = df.get("flow_data_available", pd.Series(False, index=df.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
    status = df.get("flow_fetch_status", pd.Series("", index=df.index)).astype(str)
    warning_text = df.get("flow_warning", pd.Series("", index=df.index)).astype(str).str.strip()
    fail_count = int((~available).sum())
    unsupported_count = int(status.isin([
        "unsupported", "unsupported_market", "endpoint_not_configured",
        "kr_flow_endpoint_not_configured", "kr_flow_unsupported_endpoint",
        "kr_flow_permission_or_env_error",
    ]).sum())
    market_closed_count = int(status.isin(["market_closed", "kr_flow_market_closed"]).sum())
    work = df.copy()
    work["_foreign"] = pd.to_numeric(work.get("foreign_net_buy", 0), errors="coerce").fillna(0)
    work["_inst"] = pd.to_numeric(work.get("institution_net_buy", 0), errors="coerce").fillna(0)
    work["_program"] = pd.to_numeric(work.get("program_net_buy", 0), errors="coerce").fillna(0)
    work["_flow_score"] = pd.to_numeric(work.get("intraday_flow_score", 0), errors="coerce").fillna(0)
    sym_col = "symbol" if "symbol" in work.columns else None
    top_foreign = work.sort_values("_foreign", ascending=False).head(5)[sym_col].astype(str).tolist() if sym_col else []
    top_inst = work.sort_values("_inst", ascending=False).head(5)[sym_col].astype(str).tolist() if sym_col else []
    top_program = work.sort_values("_program", ascending=False).head(5)[sym_col].astype(str).tolist() if sym_col else []
    top_flow = work.sort_values("_flow_score", ascending=False).head(5)[sym_col].astype(str).tolist() if sym_col else []
    reason_series = df.get("flow_failure_reason", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
    reasons = reason_series.loc[~available & reason_series.ne("") & reason_series.ne("unknown")]
    if reasons.empty:
        reasons = reason_series.loc[~available].replace("", "unknown")
    if reasons.empty:
        kr_error_series = df.get("kr_flow_error", pd.Series("", index=df.index)).fillna("").astype(str).str.strip()
        kr_error_series = kr_error_series.str.replace("program:", "", regex=False)
        reasons = kr_error_series.loc[~available & kr_error_series.ne("")]
    if reasons.empty:
        reasons = pd.Series(dtype=str)
    warnings: list[str] = []
    if fail_count:
        warnings.append("일부 수급 데이터 미수신")
    if unsupported_count:
        warnings.append("일부 수급/프로그램 API 미지원")
    kr_detail = _kr_flow_detail_stats(df)
    if kr_detail.get("kr_flow_target_count") and not kr_detail.get("kr_flow_attempt_count") and kr_detail.get("kr_market_session_status") != "closed":
        warnings.append("kr_flow_attempt_count is 0 during Korean market session")
    if int(available.sum()) == 0 and market_closed_count == target_count:
        overall = "MARKET_CLOSED"
    elif int(available.sum()) == 0 and unsupported_count >= target_count:
        overall = "UNSUPPORTED"
    elif fail_count == 0:
        overall = "OK"
    else:
        overall = "WARNING"
    return {
        "updated_at": _now(),
        "target_count": target_count,
        "success_count": int(available.sum()),
        "fail_count": fail_count,
        "unsupported_count": unsupported_count,
        "market_closed_count": market_closed_count,
        "data_available_rate": round(float(available.mean()), 4),
        **_market_slice_stats(df, is_kr=True),
        **kr_detail,
        **_market_slice_stats(df, is_kr=False),
        "flow_warning_count": int(warning_text.ne("").sum()),
        "top_foreign_buy_symbols": top_foreign,
        "top_institution_buy_symbols": top_inst,
        "top_program_buy_symbols": top_program,
        "top_flow_score_symbols": top_flow,
        "flow_failure_reason_counts": dict(Counter(reasons.tolist())),
        "overall_status": overall,
        "warnings": warnings,
        "errors": [],
    }


def save_intraday_flow_failure_detail(df: pd.DataFrame, path: str | Path | None = None) -> dict[str, Any]:
    target = Path(path or FLOW_FAILURE_DETAIL_PATH)
    columns = [
        "symbol", "market", "flow_fetch_status", "flow_failure_reason", "kr_flow_attempted",
        "kr_flow_success", "kr_flow_error", "kr_flow_failure_detail", "kr_flow_session_status",
        "kr_flow_endpoint_name", "kr_flow_request_params", "kr_flow_http_status", "kr_flow_api_code",
        "kr_flow_response_fields", "kr_flow_response_row_count", "kr_flow_parser_status",
        "flow_updated_at",
    ]
    try:
        if df.empty or "market" not in df.columns:
            detail = pd.DataFrame(columns=columns)
        else:
            kr = df.loc[df["market"].astype(str).map(_is_kr_market)].copy()
            success = kr.get("kr_flow_success", pd.Series(False, index=kr.index)).astype(str).str.lower().isin(["true", "1", "1.0", "yes", "y"])
            available = kr.get("flow_data_available", pd.Series(False, index=kr.index)).astype(str).str.lower().isin(["true", "1", "1.0"])
            detail = kr.loc[~(success | available)].copy()
            for col in columns:
                if col not in detail.columns:
                    detail[col] = ""
            detail = detail[columns]
        target.parent.mkdir(parents=True, exist_ok=True)
        detail.to_csv(target, index=False, encoding="utf-8-sig")
        return {"flow_failure_detail_path": str(target), "flow_failure_detail_rows": int(len(detail))}
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(target, index=False, encoding="utf-8-sig")
        return {"flow_failure_detail_path": str(target), "flow_failure_detail_rows": 0, "flow_failure_detail_error": str(exc)[:200]}


def save_intraday_flow_snapshot(path: str | Path = FLOW_SNAPSHOT_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        df = build_intraday_flow_snapshot()
        target.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(target, index=False, encoding="utf-8-sig")
        detail_result = save_intraday_flow_failure_detail(df)
        update_result = update_candidate_files_with_flow(df)
        return {"path": str(target), "rows": int(len(df)), "status": "OK", **detail_result, **update_result}
    except Exception as exc:
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(columns=FLOW_COLUMNS).to_csv(target, index=False, encoding="utf-8-sig")
        save_intraday_flow_failure_detail(pd.DataFrame(columns=FLOW_COLUMNS))
        return {"path": str(target), "rows": 0, "status": "ERROR", "error": str(exc)}


def save_intraday_flow_summary(path: str | Path = FLOW_SUMMARY_PATH) -> dict[str, Any]:
    target = Path(path)
    try:
        sibling_snapshot = target.with_name("flow.csv")
        if target != FLOW_SUMMARY_PATH and sibling_snapshot.exists() and sibling_snapshot.stat().st_size > 0:
            df = pd.read_csv(sibling_snapshot, low_memory=False)
        elif FLOW_SNAPSHOT_PATH.exists() and FLOW_SNAPSHOT_PATH.stat().st_size > 0:
            df = pd.read_csv(FLOW_SNAPSHOT_PATH, low_memory=False)
        else:
            df = build_intraday_flow_snapshot()
        summary = _summary_from_snapshot(df)
    except Exception as exc:
        summary = {
            "updated_at": _now(),
            "target_count": 0,
            "overall_status": "ERROR",
            "warnings": [],
            "errors": [str(exc)],
        }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {"path": str(target), **summary}


def main() -> int:
    from core.intraday_sector_flow_engine import save_intraday_sector_flow_report, save_intraday_sector_flow_summary

    snapshot = save_intraday_flow_snapshot()
    sector_report = save_intraday_sector_flow_report()
    sector_summary = save_intraday_sector_flow_summary()
    summary = save_intraday_flow_summary()
    result = {"snapshot": snapshot, "sector_report": sector_report, "sector_summary": sector_summary, "summary": summary}
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if summary.get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
