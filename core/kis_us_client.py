from __future__ import annotations

import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from core.kis_token_manager import get_kis_access_token, merged_env, _parse_bool, _safe_str


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


def kis_configured() -> bool:
    env = merged_env()
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    return bool(_parse_bool(env.get("KIS_ENABLED"), True) and app_key and app_secret)


def kis_base_url(is_mock: bool) -> str:
    return (
        "https://openapivts.koreainvestment.com:29443"
        if is_mock
        else "https://openapi.koreainvestment.com:9443"
    )


def kis_headers(tr_id: str, token: str, app_key: str, app_secret: str) -> dict[str, str]:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
    }


def kis_us_request(
    path: str,
    tr_id: str,
    params: dict[str, str],
    *,
    timeout: int = 8,
) -> dict[str, Any]:
    """KIS 해외 REST GET. 성공 시 payload dict, 실패 시 ok=False."""
    if not kis_configured():
        return {"ok": False, "failure_reason": "endpoint_not_configured", "payload": {}}
    env = merged_env()
    token_info = get_kis_access_token(env, allow_request=True)
    token = _safe_str(token_info.get("access_token"))
    if not token_info.get("valid") or not token:
        return {"ok": False, "failure_reason": "auth_error", "payload": {}}
    is_mock = _parse_bool(env.get("KIS_IS_MOCK"), True)
    app_key = _safe_str(env.get("KIS_APP_KEY") or env.get("KIS_APPKEY"))
    app_secret = _safe_str(env.get("KIS_APP_SECRET") or env.get("KIS_SECRET"))
    query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{kis_base_url(is_mock)}{path}?{query}"
    request = urllib.request.Request(
        url,
        headers=kis_headers(tr_id, token, app_key, app_secret),
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            return {"ok": False, "failure_reason": "rate_limited", "payload": {}}
        if exc.code in {401, 403}:
            return {"ok": False, "failure_reason": "auth_error", "payload": {}}
        return {"ok": False, "failure_reason": "unknown", "payload": {}}
    except Exception:
        return {"ok": False, "failure_reason": "unknown", "payload": {}}
    if not isinstance(payload, dict):
        return {"ok": False, "failure_reason": "api_response_empty", "payload": {}}
    if str(payload.get("rt_cd", "")).strip() not in {"", "0"}:
        return {"ok": False, "failure_reason": "api_response_empty", "payload": payload}
    return {"ok": True, "failure_reason": "", "payload": payload}


def payload_outputs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in ("output", "output1", "output2", "output3"):
        block = payload.get(key)
        if isinstance(block, dict):
            rows.append(block)
        elif isinstance(block, list):
            rows.extend(item for item in block if isinstance(item, dict))
    return rows


def first_num(row: dict[str, Any], *keys: str, default: float = math.nan) -> float:
    for key in keys:
        if key in row and str(row.get(key, "")).strip() not in {"", "-"}:
            value = _num(row.get(key), default)
            if not math.isnan(value):
                return value
    return default


def row_symbol(row: dict[str, Any]) -> str:
    for key in ("symb", "symbol", "rsym", "pdno", "ovrs_pdno", "ticker"):
        text = str(row.get(key, "") or "").strip().upper()
        if text:
            return text.replace(".US", "")
    return ""
