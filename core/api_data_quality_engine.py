from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


API_CACHE_DIR = Path("reports") / "api_cache"
REPORT_DIR = Path("reports")
API_DATA_QUALITY_SUMMARY_JSON = REPORT_DIR / "api_data_quality_summary.json"

API_KEY_ENV_VARS = {
    "kis": ["KIS_APP_KEY", "KIS_APP_SECRET"],
    "dart": ["DART_API_KEY"],
    "finnhub": ["FINNHUB_API_KEY"],
    "sec": ["SEC_USER_AGENT"],
}
API_FALLBACK_ENV_VARS = {
    "kis": ["KIS_APPKEY", "KIS_SECRET"],
    "dart": ["OPEN_DART_API_KEY"],
    "finnhub": ["FINNHUB_TOKEN"],
    "sec": ["SEC_API_USER_AGENT"],
}


def load_dotenv_values(path: str | Path = ".env") -> dict[str, str]:
    env_path = Path(path)
    if not env_path.exists() or env_path.stat().st_size <= 0:
        return {}
    values: dict[str, str] = {}
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    except Exception:
        return {}
    return values


def _merged_env(env: dict[str, str] | None = None) -> dict[str, str]:
    if env is not None:
        return dict(env)
    merged = load_dotenv_values()
    merged.update(dict(os.environ))
    return merged


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def get_api_key_status(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Report whether optional API credentials are available without exposing values."""
    source = _merged_env(env)
    details: dict[str, Any] = {}
    fallback_names_used: list[str] = []
    for provider, keys in API_KEY_ENV_VARS.items():
        present = [key for key in keys if _safe_str(source.get(key))]
        fallback_present = [key for key in API_FALLBACK_ENV_VARS.get(provider, []) if _safe_str(source.get(key))]
        configured = all(key in present for key in keys)
        if provider == "kis" and not configured:
            configured = all(key in fallback_present for key in API_FALLBACK_ENV_VARS.get(provider, []))
        if provider != "kis" and not configured:
            configured = bool(present or fallback_present)
        if fallback_present and not all(key in present for key in keys):
            fallback_names_used.extend(fallback_present)
        details[provider] = {
            "configured": bool(configured),
            "present_keys": present,
            "missing_keys": [] if configured else [key for key in keys if key not in present],
            "fallback_keys_present": fallback_present,
        }
    return {
        "configured_count": sum(1 for item in details.values() if item["configured"]),
        "providers": details,
        "fallback_key_names_used": fallback_names_used,
    }


def build_api_data_quality_summary(
    env: dict[str, str] | None = None,
    warning_count: int = 0,
    error_count: int = 0,
    fallback_used: bool | None = None,
    attempt_kis_token: bool | None = None,
    warning_reasons: list[str] | None = None,
) -> dict[str, Any]:
    status = get_api_key_status(env)
    source = _merged_env(env)
    providers = status.get("providers", {})
    kis_available = bool(providers.get("kis", {}).get("configured"))
    dart_available = bool(providers.get("dart", {}).get("configured"))
    finnhub_available = bool(providers.get("finnhub", {}).get("configured"))
    sec_available = bool(providers.get("sec", {}).get("configured"))
    kis_token_info: dict[str, Any] = {}
    kis_failure_reasons: list[str] = []
    api_warning_reasons: list[str] = list(warning_reasons or [])
    if attempt_kis_token is None:
        attempt_kis_token = env is None
    try:
        from core.kis_token_manager import get_kis_access_token

        kis_token_info = get_kis_access_token(source, allow_request=bool(attempt_kis_token))
    except Exception as exc:
        kis_token_info = {
            "status": "failed",
            "valid": False,
            "auto_issued": False,
            "is_mock": True,
            "failure_reason": f"KIS token manager failed: {exc}",
        }
    kis_token_status = _safe_str(kis_token_info.get("status")) or "missing"
    kis_token_valid = bool(kis_token_info.get("valid"))
    kis_token_auto_issued = bool(kis_token_info.get("auto_issued") or kis_token_status == "issued")
    kis_access_token_loaded = bool(_safe_str(source.get("KIS_ACCESS_TOKEN") or source.get("KIS_TOKEN"))) or kis_token_status in {"cached", "loaded", "issued"}
    if _safe_str(kis_token_info.get("failure_reason")):
        kis_failure_reasons.append(_safe_str(kis_token_info.get("failure_reason")))
    missing_env_keys: list[str] = []
    for provider in providers.values():
        missing_env_keys.extend(provider.get("missing_keys", []))
    resolved_fallback_used = bool(fallback_used) if fallback_used is not None else bool(status.get("fallback_key_names_used"))
    if kis_available and not kis_token_valid:
        resolved_fallback_used = True
        warning_count += 1
        api_warning_reasons.append("KIS access token unavailable: fallback 점수 사용")
    if not all([kis_available, dart_available, finnhub_available, sec_available]):
        warning_count += 1
        api_warning_reasons.append("일부 API 키가 없어 해당 데이터는 fallback 처리")
    if kis_failure_reasons:
        warning_count += 1
        api_warning_reasons.extend(kis_failure_reasons)
    kis_is_mock = bool(kis_token_info.get("is_mock", True))
    if kis_available and kis_token_valid and not kis_is_mock:
        warning_count += 1
        api_warning_reasons.append("KIS 실전 서버 모드: 주문 기능 없음, 데이터 조회만 사용")
    api_status = "OK" if error_count == 0 and warning_count == 0 else ("ERROR" if error_count else "WARNING")
    return {
        "overall_status": api_status,
        "api_status": api_status,
        "kis_available": kis_available,
        "dart_available": dart_available,
        "finnhub_available": finnhub_available,
        "sec_available": sec_available,
        "missing_env_keys": sorted(set(missing_env_keys)),
        "fallback_key_names_used": sorted(set(status.get("fallback_key_names_used", []))),
        "fallback_used": resolved_fallback_used,
        "kis_key_loaded": bool(_safe_str(source.get("KIS_APP_KEY") or source.get("KIS_APPKEY"))),
        "kis_secret_loaded": bool(_safe_str(source.get("KIS_APP_SECRET") or source.get("KIS_SECRET"))),
        "kis_access_token_loaded": kis_access_token_loaded,
        "kis_access_token_auto_issued": kis_token_auto_issued,
        "kis_access_token_valid": kis_token_valid,
        "kis_is_mock": kis_is_mock,
        "kis_token_status": kis_token_status,
        "api_failure_reasons": list(dict.fromkeys(kis_failure_reasons)),
        "api_warning_reasons": list(dict.fromkeys([reason for reason in api_warning_reasons if _safe_str(reason)])),
        "warning_reasons": list(dict.fromkeys([reason for reason in api_warning_reasons if _safe_str(reason)])),
        "warning_count": int(warning_count),
        "error_count": int(error_count),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_api_data_quality_summary(
    path: str | Path | None = None,
    env: dict[str, str] | None = None,
    warning_count: int = 0,
    error_count: int = 0,
    fallback_used: bool | None = None,
    attempt_kis_token: bool | None = None,
    warning_reasons: list[str] | None = None,
) -> dict[str, Any]:
    summary = build_api_data_quality_summary(
        env,
        warning_count,
        error_count,
        fallback_used,
        attempt_kis_token,
        warning_reasons,
    )
    target = Path(path) if path is not None else API_DATA_QUALITY_SUMMARY_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


def cache_key_for_symbol(symbol: str, market: str = "") -> str:
    raw = f"{_safe_str(market).upper()}::{_safe_str(symbol).upper()}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()[:16]


def _cache_path(symbol: str, market: str = "", cache_dir: Path | str = API_CACHE_DIR) -> Path:
    return Path(cache_dir) / f"{cache_key_for_symbol(symbol, market)}.json"


def load_cached_api_context(
    symbol: str,
    market: str = "",
    cache_dir: Path | str = API_CACHE_DIR,
    max_age_hours: int = 12,
) -> dict[str, Any]:
    path = _cache_path(symbol, market, cache_dir)
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    if age_hours > max_age_hours:
        return {"api_warnings": [f"cache stale: {age_hours:.1f}h"], "cache_stale": True}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"api_warnings": [f"cache read failed: {exc}"]}


def save_cached_api_context(
    symbol: str,
    market: str,
    context: dict[str, Any],
    cache_dir: Path | str = API_CACHE_DIR,
) -> Path:
    path = _cache_path(symbol, market, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context or {}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return path


def merge_api_context(row: dict[str, Any], base_context: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge cached/API context with row-derived fallback data."""
    context = dict(base_context or {})
    for key in [
        "news",
        "disclosures",
        "filings",
        "earnings",
        "fundamentals",
        "supply",
        "api_errors",
        "api_warnings",
    ]:
        context.setdefault(key, [])
    context.setdefault("row_fallback", {})
    context["row_fallback"].update(
        {
            "volume_ratio": row.get("volume_ratio"),
            "trading_value": row.get("trading_value") or row.get("turnover"),
            "sector": row.get("sector") or row.get("theme"),
            "earnings_growth_score": row.get("earnings_growth_score"),
            "news_momentum_score": row.get("news_momentum_score"),
            "catalyst_score": row.get("catalyst_score"),
        }
    )
    return context


def safe_api_get_json(
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 8,
) -> tuple[dict[str, Any] | list[Any] | None, str]:
    """Small standard-library GET helper. It never raises and never embeds API keys."""
    try:
        full_url = url
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            full_url = f"{url}?{query}" if query else url
        request = urllib.request.Request(full_url, headers=headers or {})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
        return json.loads(raw), ""
    except urllib.error.HTTPError as exc:
        return None, f"api http error: {exc.code}"
    except Exception as exc:
        return None, f"api request failed: {exc}"
