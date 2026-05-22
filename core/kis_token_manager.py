from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


KIS_TOKEN_CACHE_PATH = Path("reports") / "kis_token_cache.json"
KIS_MOCK_TOKEN_URL = "https://openapivts.koreainvestment.com:29443/oauth2/tokenP"
KIS_REAL_TOKEN_URL = "https://openapi.koreainvestment.com:9443/oauth2/tokenP"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_bool(value: Any, default: bool = True) -> bool:
    text = _safe_str(value).lower()
    if text in {"true", "1", "yes", "y", "mock", "paper"}:
        return True
    if text in {"false", "0", "no", "n", "real", "prod", "production"}:
        return False
    return default


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


def merged_env(env: dict[str, str] | None = None) -> dict[str, str]:
    if env is not None:
        return dict(env)
    merged = load_dotenv_values()
    merged.update(dict(os.environ))
    return merged


def _token_response(
    *,
    status: str,
    access_token: str = "",
    token_type: str = "",
    expires_at: str = "",
    is_mock: bool = True,
    auto_issued: bool = False,
    valid: bool = False,
    failure_reason: str = "",
) -> dict[str, Any]:
    return {
        "status": status,
        "access_token": access_token,
        "token_type": token_type,
        "expires_at": expires_at,
        "is_mock": bool(is_mock),
        "auto_issued": bool(auto_issued),
        "valid": bool(valid),
        "failure_reason": failure_reason,
        "updated_at": _now().isoformat(),
    }


def _parse_expires_at(value: Any) -> datetime | None:
    text = _safe_str(value)
    if not text:
        return None
    for fmt in ["%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"]:
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def load_cached_kis_token(path: str | Path = KIS_TOKEN_CACHE_PATH) -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or target.stat().st_size <= 0:
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_cached_kis_token(token_info: dict[str, Any], path: str | Path = KIS_TOKEN_CACHE_PATH) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "access_token": _safe_str(token_info.get("access_token")),
        "expires_at": _safe_str(token_info.get("expires_at")),
        "token_type": _safe_str(token_info.get("token_type") or "Bearer"),
        "is_mock": bool(token_info.get("is_mock", True)),
        "updated_at": _safe_str(token_info.get("updated_at") or _now().isoformat()),
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def is_kis_token_valid(token_info: dict[str, Any] | None) -> bool:
    if not isinstance(token_info, dict):
        return False
    if not _safe_str(token_info.get("access_token")):
        return False
    expires_at = _parse_expires_at(token_info.get("expires_at"))
    if expires_at is None:
        return False
    return expires_at > _now() + timedelta(minutes=5)


def request_new_kis_token(
    env: dict[str, str] | None = None,
    timeout: int = 8,
) -> dict[str, Any]:
    source = merged_env(env)
    app_key = _safe_str(source.get("KIS_APP_KEY") or source.get("KIS_APPKEY"))
    app_secret = _safe_str(source.get("KIS_APP_SECRET") or source.get("KIS_SECRET"))
    is_mock = _parse_bool(source.get("KIS_IS_MOCK"), True)
    if not app_key or not app_secret:
        return _token_response(status="missing", is_mock=is_mock, failure_reason="KIS app key/secret missing")

    url = KIS_MOCK_TOKEN_URL if is_mock else KIS_REAL_TOKEN_URL
    body = json.dumps(
        {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "appsecret": app_secret,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json; charset=UTF-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        access_token = _safe_str(payload.get("access_token"))
        token_type = _safe_str(payload.get("token_type") or "Bearer")
        expires_at = _safe_str(payload.get("access_token_token_expired"))
        if not expires_at:
            expires_in = int(float(payload.get("expires_in", 0) or 0))
            expires_at = (_now() + timedelta(seconds=max(0, expires_in - 60))).isoformat()
        if not access_token:
            return _token_response(status="failed", token_type=token_type, expires_at=expires_at, is_mock=is_mock, failure_reason="KIS token response missing access_token")
        return _token_response(
            status="issued",
            access_token=access_token,
            token_type=token_type,
            expires_at=expires_at,
            is_mock=is_mock,
            auto_issued=True,
            valid=True,
        )
    except urllib.error.HTTPError as exc:
        return _token_response(status="failed", is_mock=is_mock, failure_reason=f"KIS token HTTP error: {exc.code}")
    except Exception as exc:
        return _token_response(status="failed", is_mock=is_mock, failure_reason=f"KIS token request failed: {exc}")


def get_kis_access_token(
    env: dict[str, str] | None = None,
    cache_path: str | Path = KIS_TOKEN_CACHE_PATH,
    force_refresh: bool = False,
    allow_request: bool = True,
) -> dict[str, Any]:
    source = merged_env(env)
    is_mock = _parse_bool(source.get("KIS_IS_MOCK"), True)
    env_token = _safe_str(source.get("KIS_ACCESS_TOKEN") or source.get("KIS_TOKEN"))
    if env_token and not force_refresh:
        return _token_response(status="loaded", access_token=env_token, token_type="Bearer", is_mock=is_mock, valid=True)

    cached = load_cached_kis_token(cache_path)
    if cached and not force_refresh and is_kis_token_valid(cached):
        return _token_response(
            status="cached",
            access_token=_safe_str(cached.get("access_token")),
            token_type=_safe_str(cached.get("token_type") or "Bearer"),
            expires_at=_safe_str(cached.get("expires_at")),
            is_mock=bool(cached.get("is_mock", is_mock)),
            valid=True,
        )

    app_key = _safe_str(source.get("KIS_APP_KEY") or source.get("KIS_APPKEY"))
    app_secret = _safe_str(source.get("KIS_APP_SECRET") or source.get("KIS_SECRET"))
    if not app_key or not app_secret:
        return _token_response(status="missing", is_mock=is_mock, failure_reason="KIS app key/secret missing")
    if not allow_request:
        return _token_response(status="missing", is_mock=is_mock, failure_reason="KIS token request skipped")

    issued = request_new_kis_token(source)
    if issued.get("valid") and _safe_str(issued.get("access_token")):
        save_cached_kis_token(issued, cache_path)
    return issued
