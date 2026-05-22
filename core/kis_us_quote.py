from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core.intraday_quote_log import log_intraday_quote_event
from core.kis_token_manager import get_kis_access_token, merged_env, _parse_bool, _safe_str

US_PRICE_PATH = "/uapi/overseas-price/v1/quotations/price-detail"
US_PRICE_TR_ID = "HHDFS76200200"
_EXCD_CANDIDATES = ("NAS", "NYS", "AMS")
_EXCHANGE_ALIASES = {
    "NASDAQ": "NAS",
    "NAS": "NAS",
    "NYSE": "NYS",
    "NYS": "NYS",
    "NEW YORK": "NYS",
    "AMEX": "AMS",
    "AMS": "AMS",
    "NYSE AMERICAN": "AMS",
    "ARCA": "AMS",
}


def _num(value: Any, default: float = math.nan) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "-"}:
        return default
    for token in ["$", "원", ",", "%"]:
        text = text.replace(token, "")
    try:
        return float(text)
    except Exception:
        return default


def _kis_tracking_base(*, attempted: bool, success: bool, error: str = "", exchange: str = "") -> dict[str, Any]:
    return {
        "kis_quote_attempted": bool(attempted),
        "kis_quote_success": bool(success),
        "kis_quote_error": str(error or "")[:500],
        "kis_exchange_code": str(exchange or ""),
    }


def _format_kis_attempt_error(excd: str, *, http_code: int = 0, payload: dict[str, Any] | None = None, detail: str = "") -> str:
    payload = payload or {}
    parts = [f"EXCD={excd}"]
    if http_code:
        parts.append(f"HTTP={http_code}")
    rt = str(payload.get("rt_cd", "") or "").strip()
    if rt:
        parts.append(f"rt_cd={rt}")
    msg_cd = str(payload.get("msg_cd", "") or "").strip()
    if msg_cd:
        parts.append(f"msg_cd={msg_cd}")
    msg1 = str(payload.get("msg1", "") or payload.get("msg", "") or "").strip()
    if msg1:
        parts.append(f"msg1={msg1[:160]}")
    if detail:
        parts.append(detail[:120])
    return " | ".join(parts)


def normalize_us_ticker(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    for suffix in (".US",):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
    return raw.replace("$", "").strip()


def kis_us_exchange_candidates(symbol: str, target_row: dict[str, Any] | None = None) -> list[str]:
    """종목 메타·후보 CSV exchange 정보를 우선하고 NAS→NYS→AMS로 재시도."""
    preferred: list[str] = []
    if target_row:
        for col in ("excd", "exchange", "exchange_code", "market_exchange", "listing_exchange", "ovrs_excg_cd"):
            raw = str(target_row.get(col, "") or "").strip().upper()
            if not raw:
                continue
            if raw in _EXCHANGE_ALIASES:
                preferred.append(_EXCHANGE_ALIASES[raw])
            elif raw in _EXCD_CANDIDATES:
                preferred.append(raw)
    sym = normalize_us_ticker(symbol)
    sym_map: dict[str, list[str]] = {
        "PLTR": ["NYS", "NAS", "AMS"],
        "BRK.B": ["NYS", "NAS", "AMS"],
        "BRKB": ["NYS", "NAS", "AMS"],
    }
    for ex in sym_map.get(sym, []):
        if ex not in preferred:
            preferred.append(ex)
    for ex in _EXCD_CANDIDATES:
        if ex not in preferred:
            preferred.append(ex)
    return preferred


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


def _parse_kis_us_output(output: Any, excd: str) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {
            "ok": False,
            "failure_reason": "api_response_empty",
            "parser_status": "empty_output",
            **_kis_tracking_base(attempted=True, success=False, error=f"EXCD={excd} | empty_output", exchange=excd),
        }
    last = _num(output.get("last") or output.get("stck_prpr") or output.get("last_price"))
    base = _num(output.get("base") or output.get("prdy_clpr") or output.get("prev_close"))
    volume = _num(output.get("tvol") or output.get("acml_vol") or output.get("volume"), 0.0)
    trading_value = _num(
        output.get("tr_pbmn") or output.get("tamt") or output.get("acml_tr_pbmn") or output.get("evol_amt"),
        0.0,
    )
    if math.isnan(last) or last <= 0:
        return {
            "ok": False,
            "failure_reason": "api_response_empty",
            "parser_status": "no_price_fields",
            **_kis_tracking_base(
                attempted=True,
                success=False,
                error=f"EXCD={excd} | no_price_fields in KIS output",
                exchange=excd,
            ),
        }
    change_pct = 0.0
    if not math.isnan(base) and base > 0:
        change_pct = (last / base - 1.0) * 100.0
    else:
        change_pct = _num(output.get("rate") or output.get("prdy_ctrt"), 0.0)
        if math.isnan(change_pct):
            change_pct = 0.0
    vol_ok = (not math.isnan(volume)) and volume > 0
    tv_ok = (not math.isnan(trading_value)) and trading_value > 0
    full = vol_ok or tv_ok
    return {
        "ok": True,
        "failure_reason": "",
        "last_price": last,
        "intraday_change_pct": change_pct,
        "intraday_volume": 0.0 if math.isnan(volume) else volume,
        "intraday_trading_value": 0.0 if math.isnan(trading_value) else trading_value,
        "quote_full_available": full,
        "quote_partial_available": not full,
        "quote_source": "kis_us_quote",
        "kis_exchange": excd,
        **_kis_tracking_base(attempted=True, success=True, error="", exchange=excd),
    }


def _kis_fail(
    failure_reason: str,
    *,
    error: str,
    exchange: str = "",
    attempted: bool = True,
) -> dict[str, Any]:
    return {
        "ok": False,
        "failure_reason": failure_reason,
        "quote_source": "kis_us_quote",
        **_kis_tracking_base(attempted=attempted, success=False, error=error, exchange=exchange),
    }


def fetch_kis_us_quote_api(symbol: str, target_row: dict[str, Any] | None = None) -> dict[str, Any]:
    """KIS 해외주식 현재가(price-detail). 실제 API 응답만 사용. 실패 시 kis_quote_error에 원인 기록."""
    sym = normalize_us_ticker(symbol)
    if not sym or sym.startswith("^") or "=" in sym:
        err = "invalid_symbol: unsupported ticker format for KIS overseas quote"
        out = _kis_fail("invalid_symbol", error=err, attempted=False)
        log_intraday_quote_event("intraday_quote", "warning", ticker=sym, market="미국주식", message=err)
        return out

    if not _kis_configured():
        err = "endpoint_not_configured: KIS_APP_KEY/KIS_APP_SECRET missing or KIS_ENABLED=false"
        out = _kis_fail("endpoint_not_configured", error=err, attempted=True)
        log_intraday_quote_event("intraday_quote", "error", ticker=sym, market="미국주식", message=err)
        return out

    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        err = f"auth_error: KIS token invalid ({token_info.get('failure_reason', 'no_token')})"
        out = _kis_fail("auth_error", error=err, attempted=True)
        log_intraday_quote_event("intraday_quote", "error", ticker=sym, market="미국주식", message=err)
        return out

    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    base_url = _kis_base_url(is_mock)
    attempt_errors: list[str] = []
    last_excd = ""

    for excd in kis_us_exchange_candidates(sym, target_row):
        last_excd = excd
        params = urllib.parse.urlencode({"AUTH": "", "EXCD": excd, "SYMB": sym})
        url = f"{base_url}{US_PRICE_PATH}?{params}"
        request = urllib.request.Request(
            url,
            headers=_kis_headers(US_PRICE_TR_ID, token, app_key, app_secret),
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")[:200]
            except Exception:
                body = ""
            if exc.code == 429:
                err = _format_kis_attempt_error(excd, http_code=exc.code, detail="rate_limited")
                attempt_errors.append(err)
                combined = "; ".join(attempt_errors)
                out = _kis_fail("rate_limited", error=combined, exchange=last_excd)
                log_intraday_quote_event("intraday_quote", "warning", ticker=sym, market="미국주식", message=combined)
                return out
            if exc.code in {401, 403}:
                err = _format_kis_attempt_error(excd, http_code=exc.code, detail=f"auth_http body={body[:80]}")
            else:
                err = _format_kis_attempt_error(excd, http_code=exc.code, detail=f"http_error body={body[:80]}")
            attempt_errors.append(err)
            continue
        except Exception as exc:
            attempt_errors.append(_format_kis_attempt_error(excd, detail=f"request_error:{type(exc).__name__}"))
            continue

        if not isinstance(payload, dict):
            attempt_errors.append(_format_kis_attempt_error(excd, detail="invalid_json_payload"))
            continue
        if str(payload.get("rt_cd", "")).strip() not in {"", "0"}:
            attempt_errors.append(_format_kis_attempt_error(excd, payload=payload))
            continue
        output = payload.get("output") or payload.get("output1") or {}
        if isinstance(output, list):
            output = output[0] if output else {}
        if not isinstance(output, dict):
            attempt_errors.append(_format_kis_attempt_error(excd, detail="empty_output"))
            continue
        parsed = _parse_kis_us_output(output, excd)
        if parsed.get("ok"):
            parsed["kis_exchange"] = excd
            parsed["quote_source"] = "kis_us_quote"
            return parsed
        attempt_errors.append(str(parsed.get("kis_quote_error") or parsed.get("failure_reason", "api_response_empty")))

    combined = "; ".join(attempt_errors) if attempt_errors else f"EXCD={last_excd} | all_exchange_attempts_failed"
    out = _kis_fail("api_response_empty", error=combined, exchange=last_excd)
    log_intraday_quote_event(
        "intraday_quote",
        "warning",
        ticker=sym,
        market="미국주식",
        message=f"KIS overseas quote failed for {sym}: {combined}",
        resolution="Finnhub fallback or csv_fallback may apply",
    )
    return out
