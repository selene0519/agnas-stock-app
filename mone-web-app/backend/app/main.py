from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.routing import APIRoute

from app.engine import backtest, correction, data_quality, risk, session
from app.services import advanced
from app.services import chart_accuracy
from app.services import data_loader as data
from app.services import final_engine
from app.services import insights
from app.services import operation_history
from app.services import quotes
from app.services import runtime_limits
from app.services import user_data
from app import db as _db


app = FastAPI(title="MONE Web API", version="3.6.1-operational-stable")
_APP_STARTED_AT = time.time()
_HEALTH_CACHE: dict[str, object] = {"ts": 0.0, "payload": None}

# 자동 동기화 초기화
try:
    from app.engine.auto_sync import register_auto_sync_routes, start_background_sync, startup_sync
    register_auto_sync_routes(app)
    if runtime_limits.heavy_jobs_enabled():
        startup_sync()           # MONE_STARTUP_SYNC=1 환경변수 설정 시 시작 시 pull
        start_background_sync()  # 백그라운드 30분마다 pull (GIT_AUTO_SYNC_INTERVAL_MIN 환경변수로 조정)
except Exception as _auto_sync_err:
    print("[AutoSync] 초기화 실패:", _auto_sync_err)

_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
_extra = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = _default_origins + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "Authorization", "x-mone-user"],
)

# ── 글로벌 예외 핸들러 ────────────────────────────────────────────────────────
# FastAPI가 처리하지 못한 모든 500 에러를 HTML이 아닌 JSON으로 반환
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    import traceback
    return JSONResponse(
        status_code=500,
        content={
            "ok": False,
            "status": "ERROR",
            "error": str(exc),
            "path": str(request.url.path),
            "trace": traceback.format_exc()[-800:],
        },
    )

# ── 인메모리 Rate Limiter ──────────────────────────────────────────────────────
# 무거운 수집/갱신 엔드포인트 보호: IP당 최대 1회/60초
def _status_rank(status: object) -> int:
    value = str(status or "").upper()
    if value in {"OK", "GOOD", "NORMAL"}:
        return 0
    if value in {
        "PARTIAL",
        "PARTIAL_PRICE",
        "PRICE_PENDING",
        "DATA_PENDING",
        "PREVIOUS_CLOSE_BASIS",
        "INTRADAY_OBSERVE",
    }:
        return 1
    if value in {"STALE", "NO_DATA", "NO_REALTIME", "TIMEOUT"}:
        return 2
    if value in {"ERROR", "FAILED"}:
        return 3
    return 1


def _status_from_rank(rank: int) -> str:
    if rank <= 0:
        return "GOOD"
    if rank == 1:
        return "PARTIAL"
    if rank == 2:
        return "STALE"
    return "ERROR"


def _get_recommendation_data_versions() -> dict:
    """Return ISO timestamps of when KR and US recommendation files were last modified."""
    from datetime import datetime
    import glob as _glob
    result: dict = {}
    for market in ("kr", "us"):
        pattern = str(data.REPO_ROOT / "reports" / f"mone_v36_final_recommendations_{market}_*.csv")
        files = _glob.glob(pattern)
        if files:
            latest_mtime = max(os.path.getmtime(f) for f in files)
            result[market] = datetime.fromtimestamp(latest_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            result[market] = None
    return result


def _health_step(name: str, status: str, detail: str, *, source: str = "", next_action: str = "") -> dict:
    return {
        "name": name,
        "status": status,
        "detail": detail,
        "source": source,
        "nextAction": next_action,
    }


def _registered_api_paths() -> set[str]:
    return {
        str(getattr(route, "path", ""))
        for route in app.router.routes
        if isinstance(route, APIRoute)
    }


def _build_health_payload() -> dict:
    now = time.time()
    cached_payload = _HEALTH_CACHE.get("payload")
    if isinstance(cached_payload, dict) and now - float(_HEALTH_CACHE.get("ts") or 0) < 30:
        return {**cached_payload, "cached": True}

    route_paths = _registered_api_paths()
    required_routes = [
        "/api/final/data-quality",
        "/api/final/data-quality-live",
        "/api/holdings-clean",
        "/api/final/portfolio-risk",
        "/api/chart/debug/{symbol}",
        "/api/final/recommendations",
        "/api/health/data-sources",
        "/api/data/audit",
    ]
    missing_routes = [path for path in required_routes if path not in route_paths]
    steps: list[dict] = [
        _health_step(
            "api-route-registry",
            "GOOD" if not missing_routes else "ERROR",
            "Required operational API routes are registered." if not missing_routes else f"Missing routes: {', '.join(missing_routes)}",
            source="FastAPI route registry",
            next_action="" if not missing_routes else "Check route registration order and duplicate route removal.",
        )
    ]

    market_quality: dict[str, dict] = {}
    for market in ("kr", "us"):
        try:
            quality = data_quality.data_quality(market, mode="quick")
            status = str(quality.get("dataStatus") or quality.get("status") or "PARTIAL").upper()
            root_causes = list(quality.get("rootCauses") or [])
            next_actions = list(quality.get("nextActions") or [])
            summary = str(quality.get("summary") or "").strip()
            market_quality[market] = {
                "status": quality.get("status"),
                "dataStatus": status,
                "summary": summary,
                "rootCauses": root_causes,
                "nextActions": next_actions,
                "latestDataDate": quality.get("latestDataDate"),
                "latestFileModifiedAt": quality.get("latestFileModifiedAt"),
                "rowCount": quality.get("rowCount"),
                "candidateCount": quality.get("candidateCount"),
                "warnings": list(quality.get("warnings") or [])[:5],
                "warningsDetail": quality.get("warningsDetail") or {},
                "recommendationStatus": quality.get("recommendationStatus"),
                "recommendationBasisStatus": quality.get("recommendationBasisStatus"),
                "source": "/api/final/data-quality",
            }
            steps.append(_health_step(
                f"{market}-data-quality",
                _status_from_rank(_status_rank(status)),
                summary or f"dataStatus={status}, latestDataDate={quality.get('latestDataDate') or '-'}, rows={quality.get('rowCount') or 0}",
                source="/api/final/data-quality",
                next_action=next_actions[0] if next_actions else "Refresh collector/GitHub Actions data if status is STALE or ERROR.",
            ))
        except Exception as exc:
            market_quality[market] = {"status": "ERROR", "error": str(exc), "source": "/api/final/data-quality"}
            steps.append(_health_step(
                f"{market}-data-quality",
                "ERROR",
                str(exc)[:240],
                source="/api/final/data-quality",
                next_action="Inspect backend logs and data_quality.data_quality().",
            ))

    try:
        data_sources = api_data_sources()
        sources = data_sources.get("sources") or {}
        steps.append(_health_step(
            "source-tracking",
            "GOOD" if sources else "PARTIAL",
            f"Detected source groups: {', '.join(sorted(sources.keys())) if sources else 'none'}",
            source="/api/health/data-sources",
            next_action="" if sources else "Check reports/local_collector_status.json and GitHub Actions status files.",
        ))
    except Exception as exc:
        data_sources = {"status": "ERROR", "error": str(exc)}
        steps.append(_health_step(
            "source-tracking",
            "ERROR",
            str(exc)[:240],
            source="/api/health/data-sources",
            next_action="Inspect source status JSON files.",
        ))

    active_gaps: list[str] = []
    gap_next_actions: dict[str, str] = {}
    for quality in market_quality.values():
        for gap in quality.get("rootCauses") or []:
            if gap not in active_gaps:
                active_gaps.append(gap)
        for gap, action in zip(quality.get("rootCauses") or [], quality.get("nextActions") or []):
            if action and gap not in gap_next_actions:
                gap_next_actions[gap] = action

    checklist = [
        {"range": "11-15", "status": "PARTIAL", "coverage": ["performance guardrails", "deployment config", "debug APIs"], "gap": "Need live latency samples per endpoint.", "activeGaps": []},
        {"range": "16-25", "status": "PARTIAL", "coverage": ["dataStatus", "source fields", "user data storage", "error JSON"], "gap": "Remaining data-quality gaps are listed explicitly.", "activeGaps": active_gaps, "gapNextActions": gap_next_actions},
        {"range": "26-35", "status": "PARTIAL", "coverage": ["market regime", "session", "currency helpers", "asset type labels"], "gap": "Need formal over-optimization and identifier test suite.", "activeGaps": []},
        {"range": "36-45", "status": "PARTIAL", "coverage": ["portfolio risk", "correlation", "validation ledger", "admin page"], "gap": "Need broker cash/unsettled funds and fee/tax model completion.", "activeGaps": []},
    ]

    worst_rank = max((_status_rank(step.get("status")) for step in steps), default=1)
    payload = {
        "ok": worst_rank < 3,
        "status": "OK" if worst_rank < 3 else "ERROR",
        "dataStatus": _status_from_rank(worst_rank),
        "service": "mone-web-api",
        "version": app.version,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "uptimeSec": round(now - _APP_STARTED_AT, 1),
        "heavyJobsEnabled": runtime_limits.heavy_jobs_enabled(),
        "routes": {
            "required": required_routes,
            "missing": missing_routes,
            "registeredCount": len(route_paths),
        },
        "marketQuality": market_quality,
        "activeGaps": active_gaps,
        "gapNextActions": gap_next_actions,
        "dataSources": data_sources,
        "steps": steps,
        "checklist11to45": checklist,
        "dataVersions": _get_recommendation_data_versions(),
    }
    _HEALTH_CACHE["ts"] = now
    _HEALTH_CACHE["payload"] = payload
    return payload


@app.get("/health")
def health_root() -> dict:
    return _build_health_payload()


@app.get("/api/health")
def api_health_root() -> dict:
    return _build_health_payload()


@app.get("/api/ops/checklist")
def api_ops_checklist() -> dict:
    payload = _build_health_payload()
    return {
        "status": payload.get("status"),
        "dataStatus": payload.get("dataStatus"),
        "generatedAt": payload.get("generatedAt"),
        "activeGaps": payload.get("activeGaps"),
        "gapNextActions": payload.get("gapNextActions"),
        "checklist11to45": payload.get("checklist11to45"),
        "steps": payload.get("steps"),
        "source": "/api/health",
    }


_rate_limit_store: dict[str, float] = defaultdict(float)
_RATE_LIMITED_PREFIXES = ("/api/news/refresh", "/api/disclosures/refresh",
                          "/api/quotes/refresh", "/api/final/generate-reports")
_RATE_LIMIT_WINDOW_SEC = 60


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


DEFAULT_ADMIN_ID = "AGNAS"
DEFAULT_ADMIN_PASSWORD_SHA256 = "45dbe2462bb307fd71cb0b586670343398f2278892ad7f194704e25ff790eb88"


def _admin_password_hash() -> str:
    configured_hash = os.environ.get("MONE_ADMIN_PASSWORD_SHA256", "").strip().lower()
    if configured_hash:
        return configured_hash
    password = os.environ.get("MONE_ADMIN_PASSWORD", "")
    return hashlib.sha256(password.encode("utf-8")).hexdigest() if password else DEFAULT_ADMIN_PASSWORD_SHA256


def _admin_id() -> str:
    return (os.environ.get("MONE_ADMIN_ID") or os.environ.get("MONE_ADMIN_USERNAME") or DEFAULT_ADMIN_ID).strip()


def _admin_auth_secret() -> bytes:
    secret = os.environ.get("MONE_AUTH_SECRET", "").strip()
    if secret:
        return secret.encode("utf-8")
    return _admin_password_hash().encode("utf-8")


def _admin_auth_configured() -> bool:
    return bool(_admin_id() and _admin_password_hash())


def _check_admin_credentials(admin_id: str, password: str) -> bool:
    expected_id = _admin_id()
    expected = _admin_password_hash()
    if not expected_id or not expected:
        return False
    if not hmac.compare_digest(str(admin_id or "").strip(), expected_id):
        return False
    actual = hashlib.sha256(str(password).encode("utf-8")).hexdigest()
    return hmac.compare_digest(actual, expected)


def _create_admin_token() -> tuple[str, int]:
    ttl_seconds = int(os.environ.get("MONE_ADMIN_TOKEN_TTL_SECONDS", str(12 * 60 * 60)))
    expires_at = int(time.time() + ttl_seconds)
    payload = {"role": "admin", "adminId": _admin_id(), "exp": expires_at}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_admin_auth_secret(), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}", expires_at


def _extract_bearer_token(authorization: str | None) -> str:
    value = str(authorization or "").strip()
    if value.lower().startswith("bearer "):
        return value[7:].strip()
    return ""


def _verify_user_token(token: str) -> dict | None:
    """OAuth 사용자 토큰을 검증하고 payload를 반환한다. 유효하지 않으면 None."""
    if not token:
        return None
    try:
        body, signature = token.split(".", 1)
        secret = _admin_auth_secret() or b"mone-user"
        expected_sig = hmac.new(secret, body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), signature):
            return None
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return None
    if payload.get("role") != "user":
        return None
    if int(payload.get("exp", 0)) <= int(time.time()):
        return None
    return payload


def _verify_admin_token(token: str) -> bool:
    if not token or not _admin_auth_configured():
        return False
    try:
        body, signature = token.split(".", 1)
        expected_sig = hmac.new(_admin_auth_secret(), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), signature):
            return False
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return False
    return (
        payload.get("role") == "admin"
        and hmac.compare_digest(str(payload.get("adminId") or ""), _admin_id())
        and int(payload.get("exp", 0)) > int(time.time())
    )


def _public_frontend_base(request: Request) -> str:
    configured = os.environ.get("MONE_FRONTEND_URL", "").strip().rstrip("/")
    if configured:
        return configured
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or "localhost:3001"
    proto = request.headers.get("x-forwarded-proto") or ("http" if "localhost" in host or "127.0.0.1" in host else "https")
    return f"{proto}://{host}".rstrip("/")


def _public_oauth_callback(request: Request, provider: str) -> str:
    override = os.environ.get(f"{provider.upper()}_OAUTH_REDIRECT_URI", "").strip()
    if override:
        return override
    return f"{_public_frontend_base(request)}/api/auth/callback/{provider}"


def _signed_auth_state(provider: str) -> str:
    payload = {"provider": provider, "exp": int(time.time() + 10 * 60)}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_admin_auth_secret() or b"mone-oauth", body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}"


def _verify_auth_state(state: str, provider: str) -> bool:
    try:
        body, signature = str(state or "").split(".", 1)
        expected_sig = hmac.new(_admin_auth_secret() or b"mone-oauth", body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_encode(expected_sig), signature):
            return False
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except Exception:
        return False
    return payload.get("provider") == provider and int(payload.get("exp", 0)) > int(time.time())


def _create_user_token(provider: str, subject: str, email: str = "", name: str = "") -> tuple[str, int, str]:
    ttl_seconds = int(os.environ.get("MONE_USER_TOKEN_TTL_SECONDS", str(30 * 24 * 60 * 60)))
    expires_at = int(time.time() + ttl_seconds)
    user_id = f"{provider}:{subject}"
    payload = {"role": "user", "provider": provider, "sub": subject, "userId": user_id, "email": email, "name": name, "exp": expires_at}
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(_admin_auth_secret() or b"mone-user", body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(signature)}", expires_at, user_id


def _post_form(url: str, form: dict[str, str]) -> dict:
    import urllib.error as _ue
    data_bytes = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=data_bytes, headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except _ue.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} | {body}") from exc


def _get_json(url: str, token: str) -> dict:
    import urllib.error as _ue
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            return json.loads(res.read().decode("utf-8"))
    except _ue.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HTTP {exc.code} {exc.reason} | {body}") from exc


def _oauth_config(provider: str) -> dict[str, str]:
    if provider == "google":
        return {
            "client_id": os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
            "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "token_url": "https://oauth2.googleapis.com/token",
            "userinfo_url": "https://www.googleapis.com/oauth2/v3/userinfo",
            "scope": "openid email profile",
        }
    if provider == "kakao":
        return {
            "client_id": (os.environ.get("KAKAO_REST_API_KEY") or os.environ.get("KAKAO_CLIENT_ID") or "").strip(),
            "client_secret": os.environ.get("KAKAO_CLIENT_SECRET", "").strip(),
            "auth_url": "https://kauth.kakao.com/oauth/authorize",
            "token_url": "https://kauth.kakao.com/oauth/token",
            "userinfo_url": "https://kapi.kakao.com/v2/user/me",
            "scope": "profile_nickname profile_image",
        }
    return {}


def _normalize_oauth_user(provider: str, payload: dict) -> dict[str, str]:
    if provider == "google":
        return {
            "sub": str(payload.get("sub") or ""),
            "email": str(payload.get("email") or ""),
            "name": str(payload.get("name") or payload.get("email") or "Google user"),
        }
    kakao_account = payload.get("kakao_account") or {}
    profile = kakao_account.get("profile") or {}
    # account_email scope를 요청하지 않으므로 email 필드 없음 (KOE205 방지)
    return {
        "sub": str(payload.get("id") or ""),
        "email": "",  # account_email 미승인 — scope에서 제거됨
        "name": str(profile.get("nickname") or "Kakao user"),
        "picture": str(profile.get("profile_image_url") or profile.get("thumbnail_image_url") or ""),
    }

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "POST" and any(path.startswith(p) for p in _RATE_LIMITED_PREFIXES):
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{path}"
        now = time.time()
        last = _rate_limit_store.get(key, 0.0)
        if now - last < _RATE_LIMIT_WINDOW_SEC:
            remaining = int(_RATE_LIMIT_WINDOW_SEC - (now - last))
            return JSONResponse(
                status_code=429,
                content={"ok": False, "error": f"요청이 너무 잦습니다. {remaining}초 후 재시도하세요.",
                         "retryAfter": remaining},
                headers={"Retry-After": str(remaining)},
            )
        _rate_limit_store[key] = now
    return await call_next(request)


@app.middleware("http")
async def admin_auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "GET" and path == "/api/admin/pipeline":
        return await call_next(request)
    if path.startswith("/api/admin/"):
        token = _extract_bearer_token(request.headers.get("authorization"))
        if not _verify_admin_token(token):
            status_code = 503 if not _admin_auth_configured() else 401
            return JSONResponse(
                status_code=status_code,
                content={
                    "ok": False,
                    "status": "AUTH_REQUIRED",
                    "code": "ADMIN_AUTH_NOT_CONFIGURED" if status_code == 503 else "ADMIN_AUTH_REQUIRED",
                    "message": "Admin login is required.",
                },
            )
    return await call_next(request)


def _market(value: str) -> str:
    return "us" if str(value).lower() == "us" else "kr"


def _ensure_status(payload: dict, default_status: str = "OK") -> dict:
    if not isinstance(payload, dict):
        return {"status": "ERROR", "items": [], "count": 0, "error": "Invalid API payload"}
    if not payload.get("status"):
        count = payload.get("count")
        items = payload.get("items")
        if isinstance(items, list):
            payload["status"] = default_status if items else "NO_DATA"
            payload.setdefault("count", len(items))
        elif isinstance(count, int):
            payload["status"] = default_status if count > 0 else "NO_DATA"
        else:
            payload["status"] = default_status
    return payload


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict:
    from pathlib import Path
    import datetime as _dt
    checks: dict[str, object] = {}
    # OHLCV 파일 존재 여부
    ohlcv_dir = data.REPO_ROOT / "data" / "market" / "ohlcv"
    ohlcv_files = list(ohlcv_dir.glob("kr_*_daily.csv")) if ohlcv_dir.exists() else []
    checks["ohlcv_files"] = len(ohlcv_files)
    checks["ohlcv_ok"] = len(ohlcv_files) > 0
    # 추천 파일 최신성 (kr_balanced_swing 기준)
    reco_path = data.REPO_ROOT / "reports" / "mone_v36_final_recommendations_kr_balanced_swing.csv"
    if reco_path.exists():
        mtime = reco_path.stat().st_mtime
        age_hours = (_dt.datetime.now().timestamp() - mtime) / 3600
        checks["reco_file_age_hours"] = round(age_hours, 1)
        checks["reco_stale"] = age_hours > 48
    else:
        checks["reco_stale"] = True
        checks["reco_file_age_hours"] = None
    # DB 연결 상태
    try:
        db_info = _db.backend_info()
        checks["db"] = db_info
        checks["db_ok"] = db_info.get("status") not in {"ERROR", "DISCONNECTED"}
    except Exception as exc:
        checks["db"] = {"status": "ERROR", "error": str(exc)[:100]}
        checks["db_ok"] = False
    overall = "OK" if checks.get("ohlcv_ok") and not checks.get("reco_stale") else "DEGRADED"
    return {
        "status": overall,
        "app": "mone-web-app",
        "repoRoot": str(data.REPO_ROOT),
        "updatedAt": data.latest_updated_at(),
        "checks": checks,
    }



@app.post("/api/auth/admin-login")
def api_admin_login(payload: dict = Body(...)):
    if not _admin_auth_configured():
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "status": "ERROR",
                "code": "ADMIN_AUTH_NOT_CONFIGURED",
                "message": "Set MONE_ADMIN_ID and MONE_ADMIN_PASSWORD or MONE_ADMIN_PASSWORD_SHA256.",
            },
        )
    admin_id = str(payload.get("adminId") or payload.get("username") or payload.get("id") or "")
    password = str(payload.get("password") or "")
    if not _check_admin_credentials(admin_id, password):
        return JSONResponse(
            status_code=401,
            content={"ok": False, "status": "ERROR", "code": "INVALID_ADMIN_CREDENTIALS"},
        )
    token, expires_at = _create_admin_token()
    return {"ok": True, "status": "OK", "role": "admin", "adminId": _admin_id(), "token": token, "expiresAt": expires_at}


@app.get("/api/auth/admin-status")
def api_admin_status(authorization: str | None = Header(None)) -> dict:
    token = _extract_bearer_token(authorization)
    return {
        "ok": True,
        "status": "OK",
        "configured": _admin_auth_configured(),
        "adminIdConfigured": bool(_admin_id()),
        "authenticated": _verify_admin_token(token),
    }


@app.get("/api/auth/oauth/{provider}/start")
def api_oauth_start(provider: str, request: Request):
    provider = provider.lower().strip()
    cfg = _oauth_config(provider)
    if provider not in {"google", "kakao"}:
        return JSONResponse(status_code=404, content={"ok": False, "status": "ERROR", "code": "UNKNOWN_PROVIDER"})
    if not cfg.get("client_id") or (provider == "google" and not cfg.get("client_secret")):
        return JSONResponse(
            status_code=503,
            content={"ok": False, "status": "ERROR", "code": "OAUTH_NOT_CONFIGURED", "provider": provider},
        )
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": _public_oauth_callback(request, provider),
        "response_type": "code",
        "scope": cfg["scope"],
        "state": _signed_auth_state(provider),
    }
    if provider == "google":
        params["access_type"] = "offline"
        params["prompt"] = "select_account"
    url = f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"
    return RedirectResponse(url)


@app.get("/api/auth/oauth/{provider}/callback")
def api_oauth_callback(provider: str, request: Request, code: str = Query(""), state: str = Query("")):
    provider = provider.lower().strip()
    frontend = _public_frontend_base(request)
    if provider not in {"google", "kakao"} or not code or not _verify_auth_state(state, provider):
        return RedirectResponse(f"{frontend}/auth/callback?error=oauth_state")
    cfg = _oauth_config(provider)
    try:
        token_form = {
            "grant_type": "authorization_code",
            "client_id": cfg["client_id"],
            "redirect_uri": _public_oauth_callback(request, provider),
            "code": code,
        }
        if cfg.get("client_secret"):
            token_form["client_secret"] = cfg["client_secret"]
        token_payload = _post_form(cfg["token_url"], token_form)
        access_token = str(token_payload.get("access_token") or "")
        if not access_token:
            raise RuntimeError("missing access token")
        user_payload = _get_json(cfg["userinfo_url"], access_token)
        user = _normalize_oauth_user(provider, user_payload)
        if not user.get("sub"):
            raise RuntimeError("missing user subject")
        user_token, expires_at, user_id = _create_user_token(provider, user["sub"], user.get("email", ""), user.get("name", ""))
    except Exception as exc:
        detail = urllib.parse.quote(str(exc)[:160])
        return RedirectResponse(f"{frontend}/auth/callback?error=oauth_failed&detail={detail}")

    params = urllib.parse.urlencode({
        "token": user_token,
        "userId": user_id,
        "provider": provider,
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "expiresAt": str(expires_at),
    })
    return RedirectResponse(f"{frontend}/auth/callback?{params}")






@app.get("/api/final/recommendations")
def api_final_recommendations(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
    limit: int = Query(20, ge=1, le=50),
) -> dict:
    return final_engine.final_recommendations(_market(market), mode, horizon, limit=limit)


@app.get("/api/final/recommendation-detail")
def api_final_recommendation_detail(
    market: str = Query("kr", pattern="^(kr|us)$"),
    symbol: str = Query(..., min_length=1),
) -> dict:
    return final_engine.recommendation_detail(_market(market), symbol)


@app.get("/api/final/conditional-executions")
def api_final_conditional_executions(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.conditional_execution_summary(_market(market), mode, horizon)


@app.get("/api/final/prediction-validation")
def api_final_prediction_validation(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.prediction_validation(_market(market))


@app.get("/api/final/trade-validation")
def api_final_trade_validation(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.trade_validation(_market(market), mode, horizon)


@app.get("/api/final/data-center")
def api_final_data_center(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.data_center(_market(market))


@app.get("/api/final/discovery")
def api_final_discovery(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.discovery(_market(market), mode, horizon)


@app.get("/api/final/macro-events")
def api_final_macro_events(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.macro_event_risk(_market(market))


# ── Pattern Strategy Learning Engine v1 ──────────────────────────────────

@app.get("/api/pattern/strategy")
def api_pattern_strategy(
    market: str = Query("kr", pattern="^(kr|us)$"),
    symbol: str = Query(..., min_length=1, max_length=20),
) -> dict:
    """단일 종목 패턴 전략 분석."""
    try:
        from app.engine.pattern_strategy import analyze as _ps_analyze
        from app.services import data_loader as _dl
        df, _ = _dl._load_ohlcv(symbol, _market(market))
        if df.empty or len(df) < 5:
            return {"status": "NO_DATA", "symbol": symbol, "market": market}
        rows = df.to_dict("records")
        result = _ps_analyze(symbol, _market(market), rows)
        return {"status": "OK", **result}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


@app.get("/api/pattern/summary")
def api_pattern_summary(
    market: str = Query("kr", pattern="^(kr|us)$"),
    limit:  int  = Query(20, ge=1, le=100),
) -> dict:
    """추천 종목들의 패턴 전략 요약 (현재 추천 목록 기준)."""
    try:
        from app.engine.pattern_strategy import analyze as _ps_analyze
        from app.services import data_loader as _dl
        from app.services import final_engine as _fe
        recs = _fe.final_recommendations(_market(market), limit=limit)
        items = recs.get("items", [])
        summary = []
        for item in items:
            sym = str(item.get("symbol", ""))
            ps  = item.get("patternStrategy")
            if ps:
                summary.append({
                    "symbol":          sym,
                    "name":            item.get("name", ""),
                    "marketStructure": ps.get("marketStructure"),
                    "trendPhase":      ps.get("trendPhase"),
                    "primaryPattern":  ps.get("primaryPattern"),
                    "action":          ps.get("action"),
                    "riskStatus":      ps.get("riskStatus"),
                    "isBlocked":       ps.get("isBlocked"),
                    "confidence":      ps.get("confidence"),
                    "message":         ps.get("message"),
                    "finalRankScore":  item.get("finalRankScore"),
                })
        return {"status": "OK", "market": market, "count": len(summary), "items": summary}
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


@app.get("/api/validation/pattern-walkforward")
def api_pattern_walkforward(
    market:       str = Query("kr", pattern="^(kr|us)$"),
    from_date:    str = Query(None),
    to_date:      str = Query(None),
    horizon_days: int = Query(5, ge=1, le=20),
) -> dict:
    """패턴 Walk-Forward 검증 (미래 데이터 누출 없이 과거 성과 측정)."""
    try:
        from app.engine.pattern_strategy import run_walkforward
        return run_walkforward(
            market       = _market(market),
            from_date    = from_date,
            to_date      = to_date,
            horizon_days = horizon_days,
        )
    except Exception as e:
        return {"status": "ERROR", "message": str(e)}


# ── 캘린더 통합 API (event_calendar 서비스) ──────────────────────────────

from app.services import event_calendar as _ec_cal


@app.get("/api/calendar/today")
def api_calendar_today(market: str = Query("us", pattern="^(kr|us|all)$")) -> dict:
    """오늘 + 내일 HIGH/MEDIUM 이벤트 요약 (프론트 배너용)"""
    try:
        if market == "all":
            kr = _ec_cal.today_high_impact("kr")
            us = _ec_cal.today_high_impact("us")
            combined_level = "high" if kr["riskLevel"] == "high" or us["riskLevel"] == "high" else \
                             "medium" if kr["riskLevel"] == "medium" or us["riskLevel"] == "medium" else "low"
            return {
                "status": "OK", "market": "all",
                "riskLevel": combined_level,
                "kr": kr, "us": us,
                "hasHighAlert": kr["hasHighAlert"] or us["hasHighAlert"],
                "hasMedAlert":  kr["hasMedAlert"]  or us["hasMedAlert"],
            }
        result = _ec_cal.today_high_impact(_market(market))
        return {"status": "OK", **result}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "riskLevel": "low", "hasHighAlert": False}


@app.get("/api/calendar/macro")
def api_calendar_macro(
    market: str = Query("us", pattern="^(kr|us)$"),
    days: int = Query(30, ge=1, le=90),
    impact: str = Query("low"),
) -> dict:
    """매크로 경제지표 일정 목록"""
    try:
        items = _ec_cal.upcoming_macro(_market(market), days=days, impact_min=impact)
        return {"status": "OK", "market": market, "days": days, "count": len(items), "items": items}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


@app.get("/api/calendar/earnings")
def api_calendar_earnings_v2(
    market: str = Query("us", pattern="^(kr|us)$"),
    days: int = Query(14, ge=1, le=60),
    tracked: bool = Query(False),
) -> dict:
    """실적발표 일정 (CSV 기반 — generate_event_calendar.py 데이터)"""
    try:
        items = _ec_cal.upcoming_earnings(_market(market), days=days, tracked_only=tracked)
        return {"status": "OK", "market": market, "days": days, "count": len(items), "items": items}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


@app.get("/api/final/portfolio-risk")
def api_final_portfolio_risk(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
    x_mone_user: str = Header(default="", alias="x-mone-user"),
) -> dict:
    result = final_engine.portfolio_risk(_market(market), mode, horizon)
    uid = _db.sanitize_uid(x_mone_user)
    if uid:
        bridge_rows = _db.get_holdings(uid, _market(market))
        if bridge_rows:
            bridge_items = [
                {
                    "symbol": r.get("symbol", ""),
                    "name": r.get("name", ""),
                    "market": r.get("market", market),
                    "quantity": r.get("quantity"),
                    "avgPrice": r.get("avgPrice"),
                    "currentPrice": r.get("currentPrice"),
                    "evalAmount": r.get("evalAmount") or r.get("valuation"),
                    "profitLoss": r.get("profitLoss"),
                    "profitLossRate": r.get("profitLossRate"),
                    "broker": r.get("broker") or r.get("source") or "manual",
                    "source": "local_bridge" if (r.get("broker") or "") not in ("manual", "") else "user_holdings",
                    "brokerSource": r.get("broker") or "",
                    "syncedAt": r.get("syncedAt"),
                }
                for r in bridge_rows if r.get("symbol")
            ]
            result["actualHoldings"] = bridge_items
            result["actualHoldingCount"] = len(bridge_items)
            result["userId"] = uid
    return result


@app.post("/api/final/generate-reports")
def api_final_generate_reports() -> dict:
    return final_engine.write_final_reports()


@app.get("/api/final/operational-readiness")
def api_final_operational_readiness() -> dict:
    return final_engine.operational_readiness()


@app.get("/api/status")
def api_status() -> dict:
    files = data.status_files()
    env = data.status_env()
    return {"status": "OK", "files": files, "env": env, "updatedAt": data.latest_updated_at()}


@app.get("/api/market-home")
def api_market_home_compat(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.market_summary(_market(market))

@app.get("/api/status/files")
def api_status_files() -> dict:
    return data.status_files()


@app.get("/api/status/env")
def api_status_env() -> dict:
    return data.status_env()


@app.get("/api/status/data-sources")
def api_status_data_sources() -> dict:
    return data.data_source_status()


@app.get("/api/status/github-actions")
def api_status_github_actions() -> dict:
    return data.github_actions_status()


@app.get("/api/status/stockapp-bridge")
def api_status_stockapp_bridge() -> dict:
    return data.stockapp_bridge_status()


@app.get("/api/market/summary")
def api_market_summary(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.market_summary(_market(market))


@app.get("/api/sector-strength")
def api_sector_strength(
    market: str = Query("kr", pattern="^(kr|us)$"),
    period: int = Query(5, ge=1, le=20),
) -> dict:
    """섹터별 강도 점수 반환 (5일 수익률 기반)."""
    try:
        from app.engine.dsg_signal_engine import sector_strength
        rows = sector_strength(market, period=period)
        return {"ok": True, "market": market, "period": period, "data": rows}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": []}


@app.get("/api/symbols")
def api_symbols(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    try:
        return data.symbols(_market(market))
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc), "items": [], "count": 0}


@app.get("/api/symbols/{symbol}")
def api_symbol_detail(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    try:
        return data.symbol_detail(symbol, _market(market))
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc)}


def _chart_rows(payload: dict) -> list:
    rows = payload.get("items") or payload.get("rows") or []
    return rows if isinstance(rows, list) else []


def _latest_chart_date(rows: list) -> str:
    for row in reversed(rows or []):
        value = str(row.get("date") or row.get("Date") or row.get("날짜") or "").strip()
        if value:
            if len(value) == 8 and value.isdigit():
                return f"{value[:4]}-{value[4:6]}-{value[6:]}"
            return value[:10]
    return ""


def _chart_needs_backfill(rows: list, market: str) -> bool:
    if market != "us":
        return False
    latest = _latest_chart_date(rows)
    if not latest:
        return True
    try:
        from datetime import datetime, timedelta
        latest_day = datetime.strptime(latest, "%Y-%m-%d").date()
        return latest_day < (datetime.now().date() - timedelta(days=3))
    except Exception:
        return False


def _chart_data_with_backfill(symbol: str, market: str, days: int = 180) -> dict:
    payload = data.chart_data(symbol, market)
    rows = _chart_rows(payload)
    if _chart_needs_backfill(rows, market):
        try:
            backfill = quotes.backfill_daily_ohlcv(symbol, market, days=days)
            if str(backfill.get("status", "")).upper() == "OK":
                payload = data.chart_data(symbol, market)
                payload["backfill"] = backfill
            else:
                payload["backfill"] = backfill
        except Exception as exc:
            payload["backfill"] = {"status": "ERROR", "error": str(exc)[:160]}
    payload["latestDate"] = _latest_chart_date(_chart_rows(payload))
    return payload


def _chart_float(value) -> float | None:
    try:
        if value in (None, ""):
            return None
        number = float(str(value).replace(",", "").replace("%", "").strip())
        return number if number > 0 else None
    except Exception:
        return None


def _chart_first(row: dict, keys: list[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _chart_precision_type(item: dict) -> str:
    ps = item.get("patternStrategy") if isinstance(item.get("patternStrategy"), dict) else {}
    action = str(ps.get("action") or item.get("patternStrategyAction") or item.get("buyTiming") or "").lower()
    reason = " ".join([
        str(ps.get("primary") or ps.get("primaryPattern") or ""),
        str(item.get("decisionReason") or ""),
        str(item.get("entryBasis") or ""),
    ]).lower()
    if "stop" in action or "stop" in reason or "손절" in reason:
        return "stop"
    if "breakout" in action or "breakout" in reason or "돌파" in reason:
        return "breakout_base"
    if "pullback" in action or "pullback" in reason or "눌림" in reason:
        return "pullback_entry"
    if "trendline" in reason:
        return "trendline"
    return "support"


_CHART_OVERLAY_POLICY_VERSION = "chart-overlay-policy-v2"
_CHART_OVERLAY_MAX_DEFAULT = 6
_CHART_OVERLAY_CORE_TYPES = {
    "currentPrice",
    "entryPrice",
    "stopLine",
    "stopPrice",
    "targetLine",
    "targetPrice",
    "riskLine",
    "takeProfitLine",
    "rebalanceLine",
    "rebalanceTargetLine",
}
_CHART_OVERLAY_DEBUG_TYPES = {"precision", "extension", "overheated"}
_CHART_OVERLAY_RANKS = {
    "currentPrice": 10,
    "entryPrice": 20,
    "stopLine": 30,
    "stopPrice": 31,
    "riskLine": 32,
    "rebalanceLine": 33,
    "targetLine": 40,
    "targetPrice": 41,
    "takeProfitLine": 42,
    "rebalanceTargetLine": 43,
    "supportLine": 50,
    "resistanceLine": 60,
    "historicalSupportLevels": 70,
    "precision": 900,
}


def _chart_overlay_rank(overlay_type: str) -> int:
    return _CHART_OVERLAY_RANKS.get(str(overlay_type or ""), 500)


def _chart_overlay(
    overlay_type: str,
    price: float | None,
    base_date: str,
    source: str,
    future_bars: int,
    *,
    precision_type: str = "",
    reason: str = "",
    gap_pct: float | None = None,
    stale: bool = False,
    warnings: list[str] | None = None,
    extra: dict | None = None,
    display_by_default: bool = True,
    debug_only: bool = False,
    hide_reason: str | None = None,
) -> dict | None:
    if price is None or price <= 0:
        return None
    overlay = {
        "type": overlay_type,
        "precisionType": precision_type or overlay_type,
        "price": round(price, 4),
        "basePrice": round(price, 4),
        "baseDate": base_date,
        "source": source,
        "precisionGapPct": round(gap_pct, 3) if gap_pct is not None else None,
        "stale": stale,
        "extendFutureBars": future_bars,
        "extendedFutureBars": future_bars,
        "reason": reason,
        "warnings": warnings or [],
        "valid": True,
        "invalidReason": None,
        "displayByDefault": display_by_default,
        "debugOnly": debug_only,
        "hideReason": hide_reason,
        "gapPctFromCurrent": round(gap_pct, 3) if gap_pct is not None else None,
        "displayRank": _chart_overlay_rank(overlay_type),
    }
    if extra:
        overlay.update(extra)
    return overlay


def _chart_row_date(row: dict) -> str:
    return _chart_first(row, ["date", "Date", "tradeDate", "time"], "")[:10]


def _chart_pivots(rows: list[dict], source: str, window: int = 2) -> tuple[list[dict], list[dict]]:
    lows: list[dict] = []
    highs: list[dict] = []
    if len(rows) < window * 2 + 1:
        return lows, highs
    for idx in range(window, len(rows) - window):
        row = rows[idx]
        low = _chart_float(row.get("low") or row.get("Low"))
        high = _chart_float(row.get("high") or row.get("High"))
        if low is None or high is None:
            continue
        neighbors = rows[idx - window:idx + window + 1]
        neighbor_lows = [_chart_float(r.get("low") or r.get("Low")) for r in neighbors]
        neighbor_highs = [_chart_float(r.get("high") or r.get("High")) for r in neighbors]
        clean_lows = [v for v in neighbor_lows if v is not None]
        clean_highs = [v for v in neighbor_highs if v is not None]
        date = _chart_row_date(row)
        if clean_lows and low <= min(clean_lows):
            next_low = min([v for i, v in enumerate(clean_lows) if i != window] or clean_lows)
            strength = ((next_low - low) / low * 100) if low > 0 else 0
            lows.append({
                "date": date,
                "index": idx,
                "price": round(low, 4),
                "type": "low",
                "strength": round(max(0.0, strength), 3),
                "source": source or "ohlcv",
            })
        if clean_highs and high >= max(clean_highs):
            next_high = max([v for i, v in enumerate(clean_highs) if i != window] or clean_highs)
            strength = ((high - next_high) / high * 100) if high > 0 else 0
            highs.append({
                "date": date,
                "index": idx,
                "price": round(high, 4),
                "type": "high",
                "strength": round(max(0.0, strength), 3),
                "source": source or "ohlcv",
            })
    return lows, highs


def _line_from_pivots(
    line_type: str,
    pivots: list[dict],
    current_price: float | None,
    future_bars: int,
    source: str,
    rows: list[dict] | None = None,
) -> dict | None:
    required_type = "low" if line_type == "supportLine" else "high"
    label = "low-low support" if line_type == "supportLine" else "high-high resistance"
    recent = [p for p in pivots if p.get("type") == required_type][-5:]
    best: dict | None = None
    if len(recent) < 2:
        return {
            "type": line_type,
            "label": label,
            "valid": False,
            "invalidReason": f"{line_type}_requires_two_{required_type}_pivots",
            "points": recent,
            "pivotTypes": [p.get("type") for p in recent],
            "source": source or "pivot_detector",
            "baseDate": recent[-1].get("date") if recent else "",
            "basePrice": recent[-1].get("price") if recent else None,
            "currentPrice": current_price,
            "gapPctFromCurrent": None,
            "extendFutureBars": future_bars,
            "extendedFutureBars": future_bars,
            "warnings": ["insufficient_pivots"],
        }

    for i in range(len(recent) - 1):
        for j in range(i + 1, len(recent)):
            p1, p2 = recent[i], recent[j]
            i1, i2 = int(p1.get("index", 0)), int(p2.get("index", 0))
            if i2 <= i1 or i2 - i1 < 3:
                continue
            price1, price2 = _chart_float(p1.get("price")), _chart_float(p2.get("price"))
            if price1 is None or price2 is None:
                continue
            slope = (price2 - price1) / (i2 - i1)
            last_idx = max(int(recent[-1].get("index", i2)), i2)
            base_price = price1 + slope * (last_idx - i1)
            if base_price <= 0:
                continue
            gap = ((current_price - base_price) / current_price * 100) if current_price else None
            warnings: list[str] = []
            valid = True
            invalid_reason = None
            if any(p.get("type") != required_type for p in (p1, p2)):
                valid = False
                invalid_reason = "support_requires_low_low" if line_type == "supportLine" else "resistance_requires_high_high"
            # OrderFlow 명세: 중간 캔들 종가 기준으로 이탈 여부 확인
            violated = False
            if rows:
                for ri in range(i1 + 1, i2):
                    if ri >= len(rows):
                        break
                    close = _chart_float(rows[ri].get("close") or rows[ri].get("Close"))
                    if close is None:
                        continue
                    line_price = price1 + slope * (ri - i1)
                    if line_type == "supportLine" and close < line_price * 0.995:
                        violated = True
                        break
                    elif line_type == "resistanceLine" and close > line_price * 1.005:
                        violated = True
                        break
            else:
                between = [p for p in recent if i1 < int(p.get("index", 0)) < i2]
                if line_type == "supportLine":
                    violated = any(_chart_float(p.get("price")) is not None and float(p.get("price")) < (price1 + slope * (int(p.get("index", 0)) - i1)) * 0.995 for p in between)
                else:
                    violated = any(_chart_float(p.get("price")) is not None and float(p.get("price")) > (price1 + slope * (int(p.get("index", 0)) - i1)) * 1.005 for p in between)
            if violated:
                valid = False
                if line_type == "supportLine":
                    invalid_reason = "support_intermediate_close_broken"
                    warnings.append("support_intermediate_close_broken")
                else:
                    invalid_reason = "resistance_intermediate_close_broken"
                    warnings.append("resistance_intermediate_close_broken")
            if current_price and line_type == "supportLine":
                if base_price > current_price * 1.005:
                    valid = False
                    invalid_reason = "support_above_current_price"
                if gap is not None and gap > 35:
                    valid = False
                    invalid_reason = "support_far_below_current"
                    warnings.append("support_far_below_current")
            if current_price and line_type == "resistanceLine":
                if base_price < current_price * 0.995:
                    valid = False
                    invalid_reason = "resistance_below_current_price"
                gap_above = (base_price - current_price) / current_price * 100
                if gap_above > 35:
                    valid = False
                    invalid_reason = "resistance_far_above_current"
                    warnings.append("resistance_far_above_current")
            score = (1 if valid else 0) * 1000 + float(p1.get("strength") or 0) + float(p2.get("strength") or 0) + i2
            candidate = {
                "type": line_type,
                "label": label,
                "valid": valid,
                "invalidReason": invalid_reason,
                "points": [p1, p2],
                "pivotTypes": [p1.get("type"), p2.get("type")],
                "source": source or "pivot_detector",
                "baseDate": p2.get("date"),
                "basePrice": round(base_price, 4),
                "price": round(base_price, 4),
                "currentPrice": round(current_price, 4) if current_price else None,
                "gapPctFromCurrent": round(gap, 3) if gap is not None else None,
                "slope": round(slope, 8),
                "intercept": round(price1 - slope * i1, 4),
                "extendFutureBars": future_bars,
                "extendedFutureBars": future_bars,
                "warnings": warnings,
                "displayByDefault": valid,
                "debugOnly": not valid,
                "hideReason": None if valid else (invalid_reason or "invalid_line"),
            }
            if best is None or score > float(best.get("_score", -1)):
                best = {**candidate, "_score": score}
    if best is None:
        return None
    best.pop("_score", None)
    return best


def _validate_overlay(overlay: dict) -> dict:
    out = dict(overlay)
    warnings = list(out.get("warnings") or [])
    current = _chart_float(out.get("currentPrice"))
    price = _chart_float(out.get("basePrice") or out.get("price"))
    otype = str(out.get("type") or "")
    points = out.get("points") if isinstance(out.get("points"), list) else []
    if otype == "supportLine" and any(p.get("type") != "low" for p in points):
        out["valid"] = False
        out["invalidReason"] = "support_requires_low_low"
    elif otype == "resistanceLine" and any(p.get("type") != "high" for p in points):
        out["valid"] = False
        out["invalidReason"] = "resistance_requires_high_high"
    elif otype == "supportLine" and current and price and price > current * 1.005:
        out["valid"] = False
        out["invalidReason"] = "support_above_current_price"
    elif otype == "resistanceLine" and current and price and price < current * 0.995:
        out["valid"] = False
        out["invalidReason"] = "resistance_below_current_price"
    elif otype in {"stopPrice", "stopLine"} and current and price and price >= current:
        out["valid"] = False
        out["invalidReason"] = "stop_above_current_price"
    elif otype in {"riskLine", "rebalanceLine"} and current and price and price >= current:
        out["valid"] = False
        out["invalidReason"] = "downside_line_above_current"
    elif otype in {"targetPrice", "targetLine", "takeProfitLine", "rebalanceTargetLine"} and current and price and price <= current:
        out["valid"] = False
        out["invalidReason"] = "upside_line_below_current"
    elif otype == "precision" and current and price and abs((current - price) / current * 100) >= 15:
        warnings.append("precision_far_from_current")
    out.setdefault("valid", not bool(out.get("invalidReason")))
    out.setdefault("invalidReason", None)
    out.setdefault("displayByDefault", False)
    out.setdefault("debugOnly", not bool(out.get("displayByDefault")))
    out.setdefault("hideReason", None if out.get("displayByDefault") else out.get("invalidReason"))
    out.setdefault("displayRank", _chart_overlay_rank(otype))
    if current and price and out.get("gapPctFromCurrent") is None:
        out["gapPctFromCurrent"] = round((price - current) / current * 100, 3)
    out["warnings"] = list(dict.fromkeys(warnings))
    return out


def _finalize_chart_overlays(overlays: list[dict], current_price: float | None) -> list[dict]:
    current = _chart_float(current_price)
    checked = [_validate_overlay(o) for o in overlays]
    historical_support: list[tuple[int, float]] = []

    for idx, overlay in enumerate(checked):
        otype = str(overlay.get("type") or "")
        price = _chart_float(overlay.get("price") or overlay.get("basePrice"))
        valid = bool(overlay.get("valid"))
        overlay["displayRank"] = int(overlay.get("displayRank") or _chart_overlay_rank(otype))
        overlay.setdefault("invalidReason", None)
        overlay.setdefault("warnings", [])
        overlay["displayByDefault"] = False
        overlay["debugOnly"] = True
        overlay["hideReason"] = overlay.get("hideReason") or overlay.get("invalidReason")

        gap_abs = None
        if current and price:
            gap_signed = (price - current) / current * 100
            overlay["gapPctFromCurrent"] = round(gap_signed, 3)
            gap_abs = abs(gap_signed)
        elif overlay.get("gapPctFromCurrent") is None:
            overlay["gapPctFromCurrent"] = None

        if otype in _CHART_OVERLAY_DEBUG_TYPES or "precision" in otype.lower():
            overlay["displayByDefault"] = False
            overlay["debugOnly"] = True
            overlay["hideReason"] = overlay.get("hideReason") or "precision_evidence"
            continue

        if otype in _CHART_OVERLAY_CORE_TYPES:
            overlay["displayByDefault"] = bool(price and price > 0)
            overlay["debugOnly"] = False
            overlay["hideReason"] = None if overlay["displayByDefault"] else "missing_price"
            continue

        if otype == "supportLine":
            if not valid:
                overlay["hideReason"] = overlay.get("invalidReason") or "invalid_line"
            elif current and price and price >= current:
                overlay["hideReason"] = "support_above_current"
            elif gap_abs is not None and gap_abs > 30:
                overlay["hideReason"] = "far_from_current"
            else:
                overlay["displayByDefault"] = True
                overlay["debugOnly"] = False
                overlay["hideReason"] = None
            continue

        if otype == "resistanceLine":
            if not valid:
                overlay["hideReason"] = overlay.get("invalidReason") or "invalid_line"
            elif current and price and price <= current:
                overlay["hideReason"] = "resistance_below_current"
            elif gap_abs is not None and gap_abs > 30:
                overlay["hideReason"] = "far_from_current"
            else:
                overlay["displayByDefault"] = True
                overlay["debugOnly"] = False
                overlay["hideReason"] = None
            continue

        if otype == "historicalSupportLevels":
            if not valid:
                overlay["hideReason"] = overlay.get("invalidReason") or "invalid_line"
            elif current and price and price >= current:
                overlay["hideReason"] = "support_above_current"
            elif gap_abs is not None and gap_abs > 30:
                overlay["hideReason"] = "far_from_current"
            else:
                historical_support.append((idx, gap_abs if gap_abs is not None else 999999.0))
                overlay["hideReason"] = "historical_support_extra"
            continue

        overlay["hideReason"] = overlay.get("hideReason") or "extension_hidden"

    if historical_support:
        keep_idx = sorted(historical_support, key=lambda item: item[1])[0][0]
        for idx, _ in historical_support:
            overlay = checked[idx]
            if idx == keep_idx:
                overlay["displayByDefault"] = True
                overlay["debugOnly"] = False
                overlay["hideReason"] = None
            else:
                overlay["displayByDefault"] = False
                overlay["debugOnly"] = True
                overlay["hideReason"] = "historical_support_extra"

    default_indices = [
        idx for idx, overlay in enumerate(checked)
        if overlay.get("displayByDefault")
    ]
    default_indices.sort(key=lambda idx: (
        int(checked[idx].get("displayRank") or _chart_overlay_rank(str(checked[idx].get("type") or ""))),
        abs(float(checked[idx].get("gapPctFromCurrent") or 0)),
    ))
    for idx in default_indices[_CHART_OVERLAY_MAX_DEFAULT:]:
        checked[idx]["displayByDefault"] = False
        checked[idx]["debugOnly"] = True
        checked[idx]["hideReason"] = "display_limit_exceeded"

    return checked


def _overlay_validation_summary(overlays: list[dict]) -> dict:
    checked = [_validate_overlay(o) for o in overlays]
    default_overlays = [o for o in checked if o.get("displayByDefault")]
    core_overlays = [o for o in checked if str(o.get("type") or "") in _CHART_OVERLAY_CORE_TYPES]
    return {
        "policyVersion": _CHART_OVERLAY_POLICY_VERSION,
        "total": len(checked),
        "valid": sum(1 for o in checked if o.get("valid")),
        "invalid": sum(1 for o in checked if not o.get("valid")),
        "warnings": sum(1 for o in checked if o.get("warnings")),
        "coreOverlayCount": len(core_overlays),
        "rangeDerivedOverlayCount": len(checked) - len(core_overlays),
        "displayOverlayCount": len(default_overlays),
        "debugOverlayCount": sum(1 for o in checked if o.get("debugOnly")),
        "maxDefaultOverlays": _CHART_OVERLAY_MAX_DEFAULT,
        "coreOverlayPrices": {
            str(o.get("type")): o.get("price")
            for o in core_overlays
            if o.get("price") is not None
        },
    }


_ETF_BRANDS_KR = (
    "KODEX", "TIGER", "ACE", "KBSTAR", "ARIRANG", "HANARO", "KOSEF",
    "SOL", "TIMEFOLIO", "RISE", "PLUS", "WOORI", "FOCUS",
)
_BROAD_ETF_MARKERS = (
    "SPY", "QQQ", "VOO", "IVV", "VTI", "DIA", "KOSPI", "KOSDAQ",
    "S&P500", "S&P 500", "NASDAQ", "나스닥", "코스피", "코스닥", "200",
)
_LEVERAGED_ETF_MARKERS = (
    "TQQQ", "SQQQ", "SOXL", "SOXS", "QLD", "TNA", "TZA", "UVXY",
    "레버리지", "인버스", "곱버스", "2X", "3X", "LEVERAGED", "INVERSE",
    "BULL", "BEAR", "SHORT", "ULTRA",
)
_DIVIDEND_ETF_MARKERS = ("SCHD", "DIVIDEND", "배당", "고배당", "월배당")
_BOND_ETF_MARKERS = ("TLT", "IEF", "SHY", "BND", "AGG", "BOND", "TREASURY", "채권", "국채")
_THEME_ETF_MARKERS = (
    "SOXX", "SMH", "XLE", "XLF", "XLK", "반도체", "2차전지", "바이오",
    "로봇", "AI", "소프트웨어", "은행", "금융", "에너지", "테마",
)
_MONE_SYMBOL_NAME_CACHE: dict[str, dict[str, str]] = {}


def _mone_symbol_name(symbol: str, market: str = "") -> str:
    mk = "us" if str(market or "").lower() == "us" else "kr"
    symbol_key = str(symbol or "").upper().strip()
    if not symbol_key:
        return ""
    if mk not in _MONE_SYMBOL_NAME_CACHE:
        root = __import__("pathlib").Path(__file__).resolve().parents[3]
        paths = [root / "data" / "symbol_master_kr_full.csv", root / "data" / "stock_master_kr.csv"]
        names: dict[str, str] = {}
        csv_mod = __import__("csv")
        for path in paths:
            if not path.exists():
                continue
            for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
                try:
                    with path.open("r", encoding=enc, newline="") as handle:
                        for row in csv_mod.DictReader(handle):
                            code = str(row.get("symbol") or row.get("code") or "").upper().strip()
                            code = code.replace(".KS", "").replace(".KQ", "")
                            name = str(row.get("name") or row.get("name_kr") or row.get("company") or "").strip()
                            if code and name and code not in names:
                                names[code] = name
                    break
                except Exception:
                    continue
        _MONE_SYMBOL_NAME_CACHE[mk] = names
    return _MONE_SYMBOL_NAME_CACHE.get(mk, {}).get(symbol_key, "")


def _mone_asset_type(symbol: str, name: str = "", market: str = "", row: dict | None = None) -> str:
    row = row or {}
    explicit = str(row.get("assetType") or row.get("instrumentType") or "").strip().lower()
    allowed = {
        "stock", "broad_etf", "sector_etf", "theme_etf", "leveraged_etf",
        "inverse_etf", "bond_etf", "dividend_etf", "long_term_etf", "unknown",
    }
    if explicit in allowed:
        return explicit
    symbol_u = str(symbol or "").upper().strip()
    resolved_name = str(name or row.get("name") or row.get("company") or _mone_symbol_name(symbol_u, market) or "")
    name_u = resolved_name.upper()
    haystack = f"{symbol_u} {name_u}"
    is_etf = (
        "ETF" in haystack
        or any(marker in haystack for marker in _ETF_BRANDS_KR)
        or symbol_u in {
            "SPY", "QQQ", "VOO", "IVV", "VTI", "DIA", "IWM", "SCHD", "TLT",
            "BND", "AGG", "GLD", "SLV", "SOXX", "SMH", "XLE", "XLF", "XLK",
            "TQQQ", "SQQQ", "SOXL", "SOXS", "QLD", "TNA", "TZA", "UVXY",
        }
    )
    if not is_etf:
        return "stock" if symbol_u else "unknown"
    if "INVERSE" in haystack or "인버스" in haystack or symbol_u in {"SQQQ", "SOXS", "TZA"}:
        return "inverse_etf"
    if any(marker in haystack for marker in _LEVERAGED_ETF_MARKERS):
        return "leveraged_etf"
    if any(marker in haystack for marker in _DIVIDEND_ETF_MARKERS):
        return "dividend_etf"
    if any(marker in haystack for marker in _BOND_ETF_MARKERS):
        return "bond_etf"
    if any(marker in haystack for marker in _THEME_ETF_MARKERS):
        return "theme_etf"
    if any(marker in haystack for marker in _BROAD_ETF_MARKERS):
        return "broad_etf"
    return "sector_etf"


def _mone_holding_purpose(asset_type: str, row: dict | None = None) -> str:
    row = row or {}
    explicit = str(row.get("holdingPurpose") or row.get("strategyType") or row.get("purpose") or "").strip().lower()
    allowed = {"short_trade", "swing", "long_term", "savings_plan", "dividend", "unknown"}
    if explicit in allowed:
        return explicit
    if asset_type == "stock":
        return "swing"
    if asset_type in {"leveraged_etf", "inverse_etf"}:
        return "short_trade"
    if asset_type == "dividend_etf":
        return "dividend"
    if asset_type in {"broad_etf", "sector_etf", "theme_etf", "bond_etf", "long_term_etf"}:
        return "long_term"
    return "unknown"


def _mone_line_defaults(asset_type: str, holding_purpose: str) -> dict:
    if asset_type == "stock":
        return {
            "downside_label": "손절선",
            "downside_type": "stopLine",
            "downside_mode": "stop",
            "downside_ratio": 0.92,
            "upside_label": "목표가",
            "upside_type": "targetLine",
            "target_mode": "take_profit",
            "upside_ratio": 1.12,
            "reason": "일반 종목 리스크 기준 계산값",
        }
    if asset_type in {"leveraged_etf", "inverse_etf"}:
        return {
            "downside_label": "ETF 단기 손절선",
            "downside_type": "stopLine",
            "downside_mode": "stop",
            "downside_ratio": 0.94,
            "upside_label": "ETF 단기 목표가",
            "upside_type": "takeProfitLine",
            "target_mode": "take_profit",
            "upside_ratio": 1.07,
            "reason": "레버리지/인버스 ETF 단기 리스크 기준",
        }
    if holding_purpose in {"long_term", "savings_plan", "dividend"} or asset_type in {"broad_etf", "dividend_etf", "bond_etf", "long_term_etf"}:
        return {
            "downside_label": "리밸런싱 기준선",
            "downside_type": "rebalanceLine",
            "downside_mode": "rebalance",
            "downside_ratio": 0.88,
            "upside_label": "비중 조절 목표선",
            "upside_type": "rebalanceTargetLine",
            "target_mode": "rebalance",
            "upside_ratio": 1.15,
            "reason": "장기 ETF 비중 조절 기준",
        }
    return {
        "downside_label": "ETF 리스크 기준선",
        "downside_type": "riskLine",
        "downside_mode": "risk",
        "downside_ratio": 0.90,
        "upside_label": "ETF 수익실현 기준선",
        "upside_type": "takeProfitLine",
        "target_mode": "take_profit",
        "upside_ratio": 1.12,
        "reason": "ETF 리스크/수익실현 기준",
    }


def _mone_gap_pct(current: float, price: float, direction: str) -> float | None:
    if not current or not price:
        return None
    if direction == "upside":
        return round((price - current) / current * 100, 2)
    return round((current - price) / current * 100, 2)


def _mone_holding_lines(
    current: float,
    avg: float,
    stop: float,
    target: float,
    asset_type: str,
    holding_purpose: str,
    source_hint: str = "",
) -> dict:
    if asset_type == "unknown" and stop <= 0 and target <= 0:
        base_price = current if current > 0 else avg
        return {
            "downsideLine": None,
            "downsideLineLabel": "기준선 확인 필요",
            "downsideLineType": "unknownLine",
            "downsideMode": "unknown",
            "downsideSource": "",
            "downsideBasePrice": base_price if base_price > 0 else None,
            "downsideGapPct": None,
            "downsideReason": "종목 유형 또는 가격 데이터 부족",
            "upsideLine": None,
            "upsideLineLabel": "목표 기준 확인 필요",
            "upsideLineType": "unknownLine",
            "targetMode": "unknown",
            "targetSource": "",
            "targetBasePrice": base_price if base_price > 0 else None,
            "targetGapPct": None,
            "targetReason": "종목 유형 또는 가격 데이터 부족",
        }
    defaults = _mone_line_defaults(asset_type, holding_purpose)
    base_price = current if current > 0 else avg
    source = source_hint or "computed_holding_rule"
    downside = stop if stop > 0 else 0
    upside = target if target > 0 else 0
    if base_price > 0:
        if downside <= 0:
            downside = round(base_price * defaults["downside_ratio"], 4)
            source = "computed_holding_rule"
        if upside <= 0:
            upside = round(base_price * defaults["upside_ratio"], 4)
    return {
        "downsideLine": downside if downside > 0 else None,
        "downsideLineLabel": defaults["downside_label"],
        "downsideLineType": defaults["downside_type"],
        "downsideMode": defaults["downside_mode"],
        "downsideSource": source if downside > 0 else "",
        "downsideBasePrice": base_price if base_price > 0 else None,
        "downsideGapPct": _mone_gap_pct(current, downside, "downside") if downside > 0 else None,
        "downsideReason": defaults["reason"] if downside > 0 else "가격 데이터 부족",
        "upsideLine": upside if upside > 0 else None,
        "upsideLineLabel": defaults["upside_label"],
        "upsideLineType": defaults["upside_type"],
        "targetMode": defaults["target_mode"],
        "targetSource": source if upside > 0 else "",
        "targetBasePrice": base_price if base_price > 0 else None,
        "targetGapPct": _mone_gap_pct(current, upside, "upside") if upside > 0 else None,
        "targetReason": defaults["reason"] if upside > 0 else "가격 데이터 부족",
    }


def _enrich_chart_precision(payload: dict, symbol: str, market: str, future_bars: int = 12) -> dict:
    rows = _chart_rows(payload)
    ohlcv_latest_date = payload.get("latestDate") or _latest_chart_date(rows)
    ohlcv_source = str(payload.get("source") or "")
    target = data.normalize_symbol(symbol, market)
    latest = rows[-1] if rows else {}
    latest_close = _chart_float(latest.get("close") or latest.get("Close"))

    try:
        detail = final_engine.recommendation_detail(market, target)
    except Exception as exc:
        detail = {"status": "ERROR", "error": str(exc), "item": None, "source": ""}
    item = detail.get("item") if isinstance(detail.get("item"), dict) else {}
    rec_symbol = data.normalize_symbol(item.get("symbol") or detail.get("symbol") or target, market) if item else target
    symbol_mismatch = bool(item and rec_symbol and rec_symbol != target)

    recommendation_date = _chart_first(
        item,
        ["recoGeneratedAt", "generatedAt", "recommendationDate", "sourceDate", "priceSourceDate"],
        str(detail.get("generatedAt") or ""),
    )[:10]
    recommendation_source = str(detail.get("source") or item.get("sourceFile") or "final_recommendations")
    current_price = _chart_float(item.get("currentPrice")) or latest_close
    current_price_source = _chart_first(
        item,
        ["currentPriceSource", "priceSourceFile", "priceSource", "priceSourceType"],
        "ohlcv_latest_close" if latest_close else "",
    )
    current_price_date = _chart_first(item, ["currentPriceDate", "priceSourceDate", "priceTime"], ohlcv_latest_date)[:10]
    # Direct snapshot override — bypass stale recommendation cache for current price
    _snap_missing_reason = ""
    _snap_status_override = ""
    try:
        _snap_phase = data._market_price_phase(market)
        _snap = data._realtime_snapshot_price_candidate(target, market, _snap_phase)
        if _snap and str(_snap.get("status", "")).upper() not in ("STALE", ""):
            _snap_price = _chart_float(_snap.get("currentPrice"))
            if _snap_price and _snap_price > 0:
                current_price = _snap_price
                current_price_source = (
                    _snap.get("priceSourceFile")
                    or _snap.get("source")
                    or current_price_source
                )
                current_price_date = (
                    str(_snap.get("priceSourceDate") or _snap.get("priceTime") or current_price_date)
                )[:10]
                _snap_status_override = "NORMAL"
        else:
            if market == "us":
                _snap_missing_reason = "US snapshot 미수집 — collect_us_prices.py 재실행 후 push 필요"
            if current_price and current_price == latest_close:
                current_price_source = (
                    f"ohlcv_close · {ohlcv_source}".strip(" ·")
                    if ohlcv_source else "ohlcv_close"
                )
                _snap_status_override = "PARTIAL"
    except Exception:
        pass
    asset_type = _mone_asset_type(target, _chart_first(item, ["name", "company", "stockName"], ""), market, item)
    holding_purpose = _mone_holding_purpose(asset_type, item)

    precision_base_price = _chart_float(item.get("entry") or item.get("entryPrice"))
    precision_source = "final_recommendations"
    ps = item.get("patternStrategy") if isinstance(item.get("patternStrategy"), dict) else {}
    if ps and str(ps.get("status") or "").upper() not in {"", "ERROR"}:
        precision_source = "pattern_strategy"
    precision_base_date = ohlcv_latest_date if precision_source == "pattern_strategy" else (recommendation_date or ohlcv_latest_date)
    precision_type = _chart_precision_type(item)
    precision_reason = _chart_first(
        {**item, **ps},
        ["message", "decisionReason", "primary", "primaryPattern", "entryBasis", "chartSignalTag"],
        precision_type,
    )
    precision_gap_pct = None
    if current_price and precision_base_price:
        precision_gap_pct = (current_price - precision_base_price) / current_price * 100

    warnings: list[str] = []
    if symbol_mismatch:
        warnings.append("symbol_mismatch")
    if not current_price:
        warnings.append("missing_currentPrice")
    if not precision_base_price:
        warnings.append("missing_precisionBasePrice")
    if precision_gap_pct is not None and abs(precision_gap_pct) >= 10:
        warnings.append("precision_gap_large")
    if precision_base_date and ohlcv_latest_date and precision_base_date < ohlcv_latest_date:
        warnings.append("precision_base_stale")
    if current_price_date and ohlcv_latest_date and current_price_date[:10] != ohlcv_latest_date:
        warnings.append("current_ohlcv_date_mismatch")

    data_status = str(payload.get("dataStatus") or payload.get("status") or "OK").upper()
    if any(w in warnings for w in ("current_ohlcv_date_mismatch", "precision_base_stale")):
        data_status = "PARTIAL" if data_status == "OK" else data_status
    if not rows:
        data_status = "NO_DATA"
    if _snap_status_override:
        if _snap_status_override == "NORMAL" and data_status not in ("NO_DATA",):
            data_status = "NORMAL"
            _snap_missing_reason = ""
        elif _snap_status_override == "PARTIAL" and data_status == "OK":
            data_status = "PARTIAL"

    # If chart/debug is already using a realtime snapshot source, the price status must
    # be NORMAL and the missing reason must be cleared. This prevents contradictory
    # responses such as currentPriceSource=reports/kis_current_price_us.csv with
    # priceDataStatus=PARTIAL.
    current_price_source_lc = str(current_price_source or "").lower()
    if market == "us" and current_price and any(
        token in current_price_source_lc
        for token in (
            "kis_current_price_us.csv",
            "intraday_realtime_snapshot_us.csv",
            "us_kis_current.json",
            "us_intraday_snapshot.csv",
            "kis_snapshot",
            "finnhub",
            "yfinance",
        )
    ):
        data_status = "NORMAL"
        _snap_missing_reason = ""

    pivot_lows, pivot_highs = _chart_pivots(rows, ohlcv_source)
    stale = "precision_base_stale" in warnings
    overlays: list[dict] = []
    current_overlay = _chart_overlay(
        "currentPrice",
        current_price,
        current_price_date or ohlcv_latest_date,
        current_price_source or "current_price",
        future_bars,
        precision_type="currentPrice",
        reason="current price",
        extra={
            "label": "current price",
            "currentPrice": round(current_price, 4) if current_price else None,
        },
    )
    if current_overlay:
        overlays.append(current_overlay)
    support_line = _line_from_pivots("supportLine", pivot_lows, current_price, future_bars, "pivot_detector", rows)
    resistance_line = _line_from_pivots("resistanceLine", pivot_highs, current_price, future_bars, "pivot_detector", rows)
    for line in (support_line, resistance_line):
        if line and line.get("valid"):
            overlays.append(line)
    precision_overlay = None if symbol_mismatch or not precision_base_price else _chart_overlay(
        "precision",
        precision_base_price,
        precision_base_date,
        precision_source,
        future_bars,
        precision_type=precision_type,
        reason=precision_reason,
        gap_pct=precision_gap_pct,
        stale=stale,
        warnings=warnings,
        display_by_default=False,
        debug_only=True,
        hide_reason="precision_evidence",
        extra={
            "label": "precision evidence",
            "valid": not bool({"symbol_mismatch", "missing_currentPrice", "missing_precisionBasePrice"} & set(warnings)),
            "invalidReason": None,
            "currentPrice": round(current_price, 4) if current_price else None,
            "gapPctFromCurrent": round(precision_gap_pct, 3) if precision_gap_pct is not None else None,
        },
    )
    if precision_overlay:
        overlays.append(precision_overlay)
    entry_overlay = _chart_overlay(
        "entryPrice",
        _chart_float(item.get("entry") or item.get("entryPrice")),
        recommendation_date or precision_base_date or ohlcv_latest_date,
        recommendation_source,
        future_bars,
        precision_type="entryPrice",
        warnings=["symbol_mismatch"] if symbol_mismatch else [],
        extra={
            "label": "진입가",
            "currentPrice": round(current_price, 4) if current_price else None,
            "assetType": asset_type,
            "holdingPurpose": holding_purpose,
        },
    )
    if entry_overlay and not symbol_mismatch:
        overlays.append(entry_overlay)

    line_fields = _mone_holding_lines(
        current_price or 0,
        _chart_float(item.get("avgPrice") or item.get("averagePrice")) or 0,
        _chart_float(item.get("stop") or item.get("stopPrice")) or 0,
        _chart_float(item.get("target") or item.get("targetPrice")) or 0,
        asset_type,
        holding_purpose,
        recommendation_source,
    )
    for overlay_type, price_key, label_key, gap_key, reason_key in (
        (line_fields.get("downsideLineType"), "downsideLine", "downsideLineLabel", "downsideGapPct", "downsideReason"),
        (line_fields.get("upsideLineType"), "upsideLine", "upsideLineLabel", "targetGapPct", "targetReason"),
    ):
        overlay = _chart_overlay(
            str(overlay_type or ""),
            _chart_float(line_fields.get(price_key)),
            recommendation_date or precision_base_date or ohlcv_latest_date,
            recommendation_source if item else str(line_fields.get("downsideSource") or line_fields.get("targetSource") or "computed_holding_rule"),
            future_bars,
            precision_type=str(overlay_type or ""),
            warnings=["symbol_mismatch"] if symbol_mismatch else [],
            extra={
                "label": line_fields.get(label_key),
                "reason": line_fields.get(reason_key),
                "gapPctFromCurrent": line_fields.get(gap_key),
                "currentPrice": round(current_price, 4) if current_price else None,
                "assetType": asset_type,
                "holdingPurpose": holding_purpose,
                "downsideMode": line_fields.get("downsideMode"),
                "targetMode": line_fields.get("targetMode"),
            },
        )
        if overlay and not symbol_mismatch:
            overlays.append(overlay)
    for level in (ps.get("historicalSupportLevels") or [])[:5]:
        if isinstance(level, dict):
            level_price = _chart_float(level.get("level") or level.get("price"))
            level_warnings: list[str] = []
            invalid_reason = None
            if current_price and level_price and level_price > current_price:
                invalid_reason = "historical_support_above_current"
                level_warnings.append("historical_support_above_current")
            overlay = _chart_overlay(
                "historicalSupportLevels",
                level_price,
                str(level.get("date") or precision_base_date or ohlcv_latest_date)[:10],
                "pattern_strategy",
                future_bars,
                precision_type=str(level.get("role") or "support"),
                warnings=(warnings if symbol_mismatch else []) + level_warnings,
                extra={
                    "label": "historical support",
                    "valid": invalid_reason is None,
                    "invalidReason": invalid_reason,
                    "currentPrice": round(current_price, 4) if current_price else None,
                    "gapPctFromCurrent": round((current_price - level_price) / current_price * 100, 3) if current_price and level_price else None,
                },
            )
            if overlay and not symbol_mismatch:
                overlays.append(overlay)
    overlays = _finalize_chart_overlays(overlays, current_price)

    payload.update({
        "precisionBaseDate": precision_base_date,
        "precisionBasePrice": round(precision_base_price, 4) if precision_base_price else None,
        "precisionSource": precision_source,
        "precisionReason": precision_reason,
        "precisionType": precision_type,
        "currentPrice": round(current_price, 4) if current_price else None,
        "currentPriceSource": current_price_source,
        "currentPriceDate": current_price_date,
        "ohlcvSource": ohlcv_source,
        "ohlcvLatestDate": ohlcv_latest_date,
        "recommendationDate": recommendation_date,
        "recommendationSource": recommendation_source,
        "precisionGapPct": round(precision_gap_pct, 3) if precision_gap_pct is not None else None,
        "assetType": asset_type,
        "instrumentType": asset_type,
        "holdingPurpose": holding_purpose,
        "strategyType": holding_purpose,
        **line_fields,
        "futureProjectionBars": future_bars,
        "dataStatus": data_status,
        "priceDataStatus": data_status,
        "missingPriceReason": _snap_missing_reason,
        "overlayWarnings": warnings,
        "symbolMismatch": symbol_mismatch,
        "pivotLow": pivot_lows,
        "pivotHigh": pivot_highs,
        "lineCandidates": {
            "supportLine": _validate_overlay(support_line) if support_line else None,
            "resistanceLine": _validate_overlay(resistance_line) if resistance_line else None,
        },
        "overlays": overlays,
        "overlayValidationSummary": _overlay_validation_summary(overlays),
    })
    return payload


def _chart_bar_touch(row: dict, price: float, tolerance_pct: float = 0.005) -> bool:
    high = _chart_float(row.get("high") or row.get("High"))
    low = _chart_float(row.get("low") or row.get("Low"))
    if high is None or low is None or price <= 0:
        return False
    return low <= price * (1 + tolerance_pct) and high >= price * (1 - tolerance_pct)


def _chart_line_validation_stats(items: list[dict], line_type: str) -> dict:
    subset = [item for item in items if item.get("type") == line_type]
    scores = [float(item.get("confidenceScore") or 0) for item in subset]
    return {
        "evaluated": len(subset),
        "touches": sum(int(item.get("forwardTouchCount") or 0) for item in subset),
        "bounces": sum(int(item.get("forwardBounceCount") or 0) for item in subset),
        "breaks": sum(int(item.get("forwardBreakCount") or 0) for item in subset),
        "pending": sum(1 for item in subset if item.get("validationResult") == "NO_FUTURE_BARS"),
        "avgConfidenceScore": round(sum(scores) / len(scores), 3) if scores else None,
    }


def _chart_target_stop_stats(items: list[dict]) -> dict:
    target_stop_types = {
        "stopLine", "stopPrice", "targetLine", "targetPrice", "takeProfitLine",
        "rebalanceTargetLine", "riskLine", "rebalanceLine",
    }
    subset = [item for item in items if item.get("type") in target_stop_types]
    return {
        "evaluated": len(subset),
        "hit": sum(1 for item in subset if item.get("validationResult") in {"TARGET_HIT", "STOP_HIT"}),
        "pending": sum(1 for item in subset if item.get("validationResult") == "NO_FUTURE_BARS"),
    }


def _chart_line_validation_from_enriched(
    enriched: dict,
    symbol: str,
    market: str,
    lookback: int = 250,
    forward_bars: int = 20,
) -> dict:
    rows = _chart_rows(enriched)[-max(1, lookback):]
    overlays = enriched.get("overlays") if isinstance(enriched.get("overlays"), list) else []
    warnings: list[str] = []
    empty_stats = _chart_line_validation_stats([], "supportLine")
    if not rows:
        return {
            "status": "NO_OHLCV",
            "symbol": symbol,
            "market": market,
            "lookback": lookback,
            "forwardBars": forward_bars,
            "evaluatedLineCount": 0,
            "supportLineStats": empty_stats,
            "resistanceLineStats": _chart_line_validation_stats([], "resistanceLine"),
            "historicalSupportStats": _chart_line_validation_stats([], "historicalSupportLevels"),
            "targetStopStats": _chart_target_stop_stats([]),
            "overallAccuracyScore": None,
            "warnings": ["missing_ohlcv"],
            "items": [],
        }

    date_to_index = {_chart_row_date(row): idx for idx, row in enumerate(rows) if _chart_row_date(row)}
    evaluable_types = {
        "supportLine", "resistanceLine", "historicalSupportLevels", "entryPrice",
        "stopLine", "stopPrice", "targetLine", "targetPrice", "takeProfitLine",
        "rebalanceTargetLine", "riskLine", "rebalanceLine",
    }
    downside_types = {"supportLine", "historicalSupportLevels", "entryPrice", "stopLine", "stopPrice", "riskLine", "rebalanceLine"}
    items: list[dict] = []

    for overlay in overlays:
        otype = str(overlay.get("type") or "")
        if otype not in evaluable_types:
            continue
        price = _chart_float(overlay.get("price") or overlay.get("basePrice"))
        if not price or price <= 0:
            continue
        base_date = str(overlay.get("baseDate") or "")[:10]
        base_idx = date_to_index.get(base_date)
        if base_idx is None:
            base_idx = len(rows) - 1
            if base_date:
                warnings.append(f"base_date_not_found:{otype}:{base_date}")

        before = rows[max(0, base_idx - lookback):base_idx + 1]
        future = rows[base_idx + 1:base_idx + 1 + max(0, forward_bars)]
        touch_before = sum(1 for row in before if _chart_bar_touch(row, price))
        future_touch = 0
        future_bounce = 0
        future_break = 0
        future_close_break = 0
        highs: list[float] = []
        lows: list[float] = []

        for row in future:
            high = _chart_float(row.get("high") or row.get("High"))
            low = _chart_float(row.get("low") or row.get("Low"))
            close = _chart_float(row.get("close") or row.get("Close"))
            if high is not None:
                highs.append(high)
            if low is not None:
                lows.append(low)
            touched = _chart_bar_touch(row, price)
            if touched:
                future_touch += 1
            if otype in downside_types:
                if touched and close is not None and close >= price:
                    future_bounce += 1
                if low is not None and low < price * 0.985:
                    future_break += 1
                if close is not None and close < price * 0.985:
                    future_close_break += 1
            else:
                if touched and close is not None and close <= price:
                    future_bounce += 1
                if high is not None and high > price * 1.015:
                    future_break += 1
                if close is not None and close > price * 1.015:
                    future_close_break += 1

        if lows and highs and otype in downside_types:
            max_adverse = max((price - low) / price * 100 for low in lows)
            max_favorable = max((high - price) / price * 100 for high in highs)
        elif lows and highs:
            max_adverse = max((high - price) / price * 100 for high in highs)
            max_favorable = max((price - low) / price * 100 for low in lows)
        else:
            max_adverse = None
            max_favorable = None

        if not future:
            validation_result = "NO_FUTURE_BARS"
            reason = "No OHLCV bars after baseDate yet."
        elif otype in {"targetLine", "targetPrice", "takeProfitLine", "rebalanceTargetLine"} and any(high >= price for high in highs):
            validation_result = "TARGET_HIT"
            reason = "Future high touched or exceeded target."
        elif otype in {"stopLine", "stopPrice", "riskLine", "rebalanceLine"} and any(low <= price for low in lows):
            validation_result = "STOP_HIT"
            reason = "Future low touched or fell below stop/risk line."
        elif future_close_break > 0:
            validation_result = "CLOSE_BREAK"
            reason = "Future close broke the line."
        elif future_break > 0:
            validation_result = "INTRADAY_BREAK"
            reason = "Future intraday range broke the line."
        elif future_bounce > 0:
            validation_result = "BOUNCE_CONFIRMED"
            reason = "Future bar touched and closed back on the expected side."
        elif future_touch > 0:
            validation_result = "TOUCHED"
            reason = "Future bar touched the line."
        else:
            validation_result = "NOT_TOUCHED"
            reason = "Future bars did not touch the line."

        confidence = 0.0
        if validation_result in {"BOUNCE_CONFIRMED", "TARGET_HIT", "STOP_HIT"}:
            confidence = 1.0
        elif validation_result in {"TOUCHED", "INTRADAY_BREAK"}:
            confidence = 0.55
        elif validation_result == "NOT_TOUCHED":
            confidence = 0.35
        if overlay.get("displayByDefault"):
            confidence += 0.1
        if touch_before >= 2:
            confidence += 0.1

        items.append({
            "label": overlay.get("label") or otype,
            "type": otype,
            "price": round(price, 4),
            "baseDate": base_date,
            "displayByDefault": bool(overlay.get("displayByDefault")),
            "debugOnly": bool(overlay.get("debugOnly")),
            "touchCountBefore": touch_before,
            "forwardTouchCount": future_touch,
            "forwardBounceCount": future_bounce,
            "forwardBreakCount": future_break,
            "forwardCloseBreakCount": future_close_break,
            "maxAdverseMovePct": round(max_adverse, 3) if max_adverse is not None else None,
            "maxFavorableMovePct": round(max_favorable, 3) if max_favorable is not None else None,
            "validationResult": validation_result,
            "confidenceScore": round(max(0.0, min(1.0, confidence)), 3),
            "reason": reason,
        })

    scores = [float(item.get("confidenceScore") or 0) for item in items if item.get("validationResult") != "NO_FUTURE_BARS"]
    return {
        "status": "OK" if items else "NO_LINES",
        "symbol": enriched.get("symbol") or symbol,
        "market": enriched.get("market") or market,
        "lookback": lookback,
        "forwardBars": forward_bars,
        "evaluatedLineCount": len(items),
        "supportLineStats": _chart_line_validation_stats(items, "supportLine"),
        "resistanceLineStats": _chart_line_validation_stats(items, "resistanceLine"),
        "historicalSupportStats": _chart_line_validation_stats(items, "historicalSupportLevels"),
        "targetStopStats": _chart_target_stop_stats(items),
        "overallAccuracyScore": round(sum(scores) / len(scores), 3) if scores else None,
        "warnings": list(dict.fromkeys(warnings)),
        "items": items,
    }


def _chart_line_validation(symbol: str, market: str, lookback: int = 250, forward_bars: int = 20) -> dict:
    normalized_market = _market(market)
    payload = _chart_data_with_backfill(symbol, normalized_market)
    enriched = _enrich_chart_precision(payload, symbol, normalized_market, forward_bars)
    return _chart_line_validation_from_enriched(enriched, symbol, normalized_market, lookback, forward_bars)


@app.get("/api/chart/{symbol}")
def api_chart_data(
    symbol: str,
    market: str = Query("kr", pattern="^(kr|us)$"),
    futureProjectionBars: int = Query(12, ge=0, le=60),
) -> dict:
    normalized_market = _market(market)
    payload = _chart_data_with_backfill(symbol, normalized_market)
    return _enrich_chart_precision(payload, symbol, normalized_market, futureProjectionBars)


@app.get("/api/chart/line-validation/{symbol}")
def api_chart_line_validation(
    symbol: str,
    market: str = Query("kr", pattern="^(kr|us)$"),
    lookback: int = Query(250, ge=20, le=1000),
    forwardBars: int = Query(20, ge=0, le=120),
) -> dict:
    return _chart_line_validation(symbol, market, lookback, forwardBars)


@app.get("/api/chart/debug/{symbol}")
def api_chart_debug(
    symbol: str,
    market: str = Query("kr", pattern="^(kr|us)$"),
    futureProjectionBars: int = Query(12, ge=0, le=60),
) -> dict:
    normalized_market = _market(market)
    payload = _chart_data_with_backfill(symbol, normalized_market)
    enriched = _enrich_chart_precision(payload, symbol, normalized_market, futureProjectionBars)
    return {
        "status": enriched.get("status"),
        "symbol": enriched.get("symbol"),
        "market": enriched.get("market"),
        "currentPrice": enriched.get("currentPrice"),
        "currentPriceSource": enriched.get("currentPriceSource"),
        "priceDataStatus": enriched.get("priceDataStatus") or enriched.get("dataStatus"),
        "missingPriceReason": enriched.get("missingPriceReason", ""),
        "ohlcvSource": enriched.get("ohlcvSource"),
        "ohlcvLatestDate": enriched.get("ohlcvLatestDate"),
        "precisionBaseDate": enriched.get("precisionBaseDate"),
        "precisionBasePrice": enriched.get("precisionBasePrice"),
        "precisionSource": enriched.get("precisionSource"),
        "precisionGapPct": enriched.get("precisionGapPct"),
        "assetType": enriched.get("assetType"),
        "holdingPurpose": enriched.get("holdingPurpose"),
        "downsideLine": enriched.get("downsideLine"),
        "downsideLineLabel": enriched.get("downsideLineLabel"),
        "downsideLineType": enriched.get("downsideLineType"),
        "downsideGapPct": enriched.get("downsideGapPct"),
        "upsideLine": enriched.get("upsideLine"),
        "upsideLineLabel": enriched.get("upsideLineLabel"),
        "upsideLineType": enriched.get("upsideLineType"),
        "targetGapPct": enriched.get("targetGapPct"),
        "pivotLow": enriched.get("pivotLow", []),
        "pivotHigh": enriched.get("pivotHigh", []),
        "lineCandidates": enriched.get("lineCandidates", {}),
        "overlays": enriched.get("overlays", []),
        "overlayValidationSummary": enriched.get("overlayValidationSummary", {}),
        "lineValidation": _chart_line_validation_from_enriched(
            enriched,
            symbol,
            normalized_market,
            250,
            max(1, futureProjectionBars or 20),
        ),
    }


@app.get("/api/chart/analysis/{symbol}")
def api_chart_analysis(
    symbol: str,
    market: str = Query("kr", pattern="^(kr|us)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    """
    Phase 6 차트 분석 엔진 — Core Analysis (T) + Forward Projection (T+H).
    FSM 신호 상태, 컨플루언스 점수, 추천 통합용 chartSignalScore 반환.
    """
    try:
        from app.engine.chart_analysis_engine import build_chart_analysis, state_to_dict
        from app.engine.quant_scanner import load_ohlcv, load_market_regime

        market_key = _market(market)
        _chart_data_with_backfill(symbol, market_key)
        rows = load_ohlcv(data.REPO_ROOT, market_key, symbol)
        if not rows:
            return {"ok": False, "error": "OHLCV 데이터 없음", "symbol": symbol, "market": market_key}

        regime = load_market_regime(data.REPO_ROOT, market_key)
        regime_score = 50.0 + regime.get("scoreAdjust", 0.0)

        horizon_bars = {"short": 20, "swing": 50, "mid": 100}.get(horizon, 50)

        try:
            from app.engine.news_sentiment_engine import load_sentiment_cache, score_news_sentiment
            _scache2 = load_sentiment_cache(market_key)
            news_pen2 = float(score_news_sentiment(market_key, symbol, symbol, cache=_scache2).get("penalty", 0.0))
        except Exception:
            news_pen2 = 0.0

        chart_state = build_chart_analysis(
            rows=rows,
            symbol=symbol,
            market=market_key,
            market_regime_score=max(0.0, min(100.0, regime_score)),
            horizon_bars=horizon_bars,
            news_penalty=news_pen2,
        )
        result = state_to_dict(chart_state)
        result["ok"] = True
        result["regime"] = regime.get("regime", "SIDE")
        result["regimeLabel"] = regime.get("label", "횡보장")
        return result
    except Exception as exc:
        import traceback
        return {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-500:]}


@app.get("/api/candidates")
def api_candidates(
    market: str = Query("kr", pattern="^(kr|us)$"),
    type: str = Query("action", pattern="^(action|pullback|flow|risk)$"),
) -> dict:
    try:
        return data.candidate_rows(_market(market), type)
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc), "items": [], "count": 0}


@app.get("/api/positions")
def api_positions(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    try:
        return data.positions(_market(market))
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc), "items": [], "count": 0}




@app.get("/api/watchlist")
def api_watchlist(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    try:
        return user_data.get_watchlist(_market(market))
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc), "items": [], "count": 0}


@app.post("/api/watchlist")
def api_watchlist_add(payload: dict) -> dict:
    try:
        return user_data.add_watchlist(payload)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/watchlist/auto-candidates")
def api_watchlist_auto_candidates(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    limitPerMarket: int = Query(12, ge=3, le=30),
) -> dict:
    return user_data.auto_watchlist_candidates(market, limitPerMarket)


@app.post("/api/watchlist/auto-curate")
def api_watchlist_auto_curate(payload: dict = Body(default={})) -> dict:
    market = str((payload or {}).get("market") or "all").lower()
    if market not in {"all", "kr", "us"}:
        market = "all"
    limit_per_market = int((payload or {}).get("limitPerMarket") or 12)
    return user_data.apply_auto_watchlist(market, limit_per_market)


@app.delete("/api/watchlist/{symbol}")
def api_watchlist_delete(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.delete_watchlist(symbol, _market(market))


@app.get("/api/holdings")
def api_holdings(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    try:
        return user_data.get_holdings(_market(market))
    except Exception as exc:
        return {"ok": False, "status": "ERROR", "error": str(exc), "items": [], "count": 0}


@app.post("/api/holdings")
def api_holdings_add(payload: dict) -> dict:
    try:
        return user_data.upsert_holding(payload, mode="post")
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.patch("/api/holdings/{symbol}")
def api_holdings_patch(symbol: str, payload: dict) -> dict:
    try:
        return user_data.upsert_holding(payload, mode="patch", symbol_arg=symbol)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


@app.delete("/api/holdings/{symbol}")
def api_holdings_delete(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.delete_holding(symbol, _market(market))

@app.get("/api/news")
def api_news(
    market: str = Query("kr", pattern="^(kr|us)$"),
    watch_only: bool = Query(False),
    watchOnly: bool | None = Query(None),
) -> dict:
    from pathlib import Path as _NP
    import csv as _NC

    mk = _market(market)
    result = _ensure_status(data.news_rows(mk))
    effective_watch_only = watch_only if watchOnly is None else watchOnly
    if not effective_watch_only:
        return result

    relevant: set[str] = set()
    repo = _NP(__file__).resolve().parents[3]

    def _read_symbols(path: _NP) -> None:
        if not path.exists():
            return
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    for row in _NC.DictReader(f):
                        sym = data.normalize_symbol(
                            row.get("symbol") or row.get("종목코드") or row.get("ticker") or "", mk
                        )
                        if sym:
                            relevant.add(sym)
                return
            except Exception:
                continue

    for fname in (f"holdings_{mk}.csv", f"data/holdings_{mk}.csv", f"watchlist_{mk}.csv", f"data/watchlist_{mk}.csv"):
        _read_symbols(repo / fname)

    if not relevant:
        return {**result, "items": [], "count": 0, "watchOnly": True, "relevantSymbols": 0}

    filtered = [
        item for item in result.get("items", [])
        if data.normalize_symbol(item.get("symbol", ""), mk) in relevant
    ]
    return {**result, "items": filtered, "count": len(filtered), "watchOnly": True, "relevantSymbols": len(relevant)}


@app.get("/api/disclosures")
def api_disclosures(
    market: str = Query("kr", pattern="^(kr|us)$"),
    watch_only: bool = Query(True),
    watchOnly: bool | None = Query(None),
) -> dict:
    from pathlib import Path as _DP
    import csv as _DC

    mk = _market(market)
    result = data.disclosure_rows(mk)
    effective_watch_only = watch_only if watchOnly is None else watchOnly

    if effective_watch_only:
        # 보유종목 + 관심종목 심볼 수집
        relevant: set[str] = set()
        repo = _DP(__file__).resolve().parents[3]

        def _read_symbols(path: _DP) -> None:
            if not path.exists():
                return
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with path.open("r", encoding=enc, newline="") as f:
                        for row in _DC.DictReader(f):
                            sym = data.normalize_symbol(
                                row.get("symbol") or row.get("종목코드") or row.get("ticker") or "", mk
                            )
                            if sym:
                                relevant.add(sym)
                    return
                except Exception:
                    continue

        # 보유종목 CSV
        for fname in (f"holdings_{mk}.csv", f"data/holdings_{mk}.csv"):
            _read_symbols(repo / fname)
        # 관심종목 CSV
        for fname in (f"watchlist_{mk}.csv", f"data/watchlist_{mk}.csv"):
            _read_symbols(repo / fname)
        # 추천 종목 (balanced swing 기준)
        for fname in (f"reports/mone_v36_final_recommendations_{mk}_balanced_swing.csv",):
            _read_symbols(repo / fname)

        if relevant:
            filtered = [
                item for item in result.get("items", [])
                if data.normalize_symbol(item.get("symbol", ""), mk) in relevant
            ]
            result = {**result, "items": filtered, "count": len(filtered),
                      "watchOnly": True, "relevantSymbols": len(relevant)}
        else:
            result = {**result, "watchOnly": True, "relevantSymbols": 0}

    return result


@app.post("/api/disclosures/refresh")
def api_disclosures_refresh(market: str = Query("all", pattern="^(kr|us|all)$"), days: int = Query(30, ge=1, le=365)) -> dict:
    return data.refresh_disclosures(market=market, days=days)


@app.post("/api/news/refresh")
def api_news_refresh(market: str = Query("all", pattern="^(kr|us|all)$")) -> dict:
    """GNews(일반) + Finnhub(종목별) 뉴스를 수집해 CSV에 저장한다."""
    gnews_result = data.collect_gnews(market=market)
    # US 종목별 뉴스 추가 수집 (Finnhub company-news)
    if market in ("us", "all"):
        try:
            finnhub_result = data._collect_us_company_news(days=7)
            gnews_result["finnhub_news"] = finnhub_result
        except Exception as exc:
            gnews_result["finnhub_news"] = {"status": "ERROR", "error": str(exc)}
    return gnews_result


@app.post("/api/news/sentiment/refresh")
def api_news_sentiment_refresh(market: str = Query("all", pattern="^(kr|us|all)$")) -> dict:
    """뉴스/공시 감성 캐시를 재빌드한다. 공시 CSV + 뉴스 CSV → reports/news_sentiment_cache_{market}.json"""
    from app.engine.news_sentiment_engine import build_sentiment_cache
    markets = ["kr", "us"] if market == "all" else [market]
    results = []
    for mk in markets:
        # 워치리스트 + 추천 종목 전체로 캐시 빌드
        symbols: list[tuple[str, str]] = []
        try:
            wl = data.watchlist_rows(mk)
            for item in wl.get("items", []):
                sym = str(item.get("symbol", "") or "")
                name = str(item.get("name", "") or "")
                if sym:
                    symbols.append((sym, name))
        except Exception:
            pass
        payload = build_sentiment_cache(mk, symbols)
        results.append({"market": mk, "count": payload.get("count", 0), "status": "OK"})
    # 다음 score_candidate 호출 시 캐시 재로드되도록 플래그 초기화
    try:
        from app.engine.quant_scanner import score_candidate
        if hasattr(score_candidate, "_sentiment_cache"):
            del score_candidate._sentiment_cache  # type: ignore[attr-defined]
    except Exception:
        pass
    return {"ok": True, "results": results}


@app.get("/api/company-analysis")
def api_company_analysis(
    market: str = Query("kr", pattern="^(kr|us)$"),
    q: str = Query(""),       # 종목코드 또는 종목명 필터
    limit: int = Query(120),
) -> dict:
    result = data.company_analysis(_market(market))
    if q.strip():
        q_norm = q.strip().upper().lstrip("0") or q.strip()
        filtered = [
            item for item in result.get("items", [])
            if (
                str(item.get("symbol", "")).lstrip("0").upper() == q_norm
                or str(item.get("symbol", "")).upper() == q.strip().upper()
                or q.strip().lower() in str(item.get("name", "")).lower()
            )
        ]
        result = {**result, "items": filtered[:limit], "count": len(filtered)}
    else:
        items = result.get("items", [])
        result = {**result, "items": items[:limit], "count": len(items)}
    return result


@app.get("/api/virtual/preview")
def api_virtual_preview(market: str = Query("kr", pattern="^(kr|us)$"), mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$")) -> dict:
    return data.virtual_operation_preview(_market(market), mode)


@app.get("/api/virtual/conditional")
def api_virtual_conditional(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    # v3.6-final: keep the old endpoint path, but return the final conditional execution engine.
    return final_engine.conditional_execution_summary(_market(market), mode, horizon)


@app.get("/api/virtual/portfolio")
def api_virtual_portfolio(market: str = Query("kr", pattern="^(kr|us)$"), mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$")) -> dict:
    return data.virtual_portfolio_summary(_market(market), mode)


@app.get("/api/virtual/portfolios")
def api_virtual_portfolios(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    mk = _market(market)
    modes = ["conservative", "balanced", "aggressive"]
    items = {mode: data.virtual_portfolio_summary(mk, mode) for mode in modes}
    return {
        "market": mk,
        "modes": items,
        "counts": {mode: items[mode].get("count", 0) for mode in modes},
        "source": "virtual_portfolio_summary",
    }


@app.get("/api/history/files")
def api_history_files() -> dict:
    return operation_history.history_file_summary()


@app.get("/api/history/virtual-operations")
def api_virtual_operation_history(
    market: str | None = Query(None, pattern="^(kr|us)$"),
    mode: str | None = Query(None, pattern="^(conservative|balanced|aggressive)$"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return operation_history.virtual_operation_history(market, mode, limit)


@app.get("/api/history/prediction-snapshots")
def api_prediction_snapshot_history(
    market: str | None = Query(None, pattern="^(kr|us)$"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return operation_history.prediction_snapshot_history(market, limit)


@app.post("/api/history/snapshot")
def api_save_history_snapshot(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    modes: str = Query("all"),
    source: str = Query("manual"),
    backfill_existing: bool = Query(False),
) -> dict:
    return operation_history.save_current_snapshot(market=market, modes=modes, source=source, include_backfill=backfill_existing)


@app.post("/api/history/backfill")
def api_backfill_existing_history(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    modes: str = Query("all"),
) -> dict:
    return operation_history.backfill_existing_records(market=market, modes=modes)


@app.post("/api/history/evaluate")
def api_evaluate_virtual_history() -> dict:
    evaluation = operation_history.evaluate_virtual_operations(write=True)
    correction = operation_history.build_auto_correction_summary(write=True)
    return {"status": "OK", "evaluation": evaluation, "autoCorrection": correction}


@app.get("/api/history/auto-correction")
def api_auto_correction_summary() -> dict:
    return operation_history.build_auto_correction_summary(write=False)


@app.get("/api/predictions")
def api_predictions(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.predictions(_market(market))


@app.get("/api/reports/premarket")
def api_report_premarket(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.premarket_report(_market(market))


@app.get("/api/reports/intraday")
def api_report_intraday(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.intraday_report(_market(market))


@app.get("/api/reports/closing")
def api_report_closing(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.closing_report(_market(market))


@app.get("/api/reports/files")
def api_report_files() -> dict:
    return data.report_files()


@app.get("/api/reports/preview")
def api_report_preview(path: str = Query(..., min_length=1)) -> dict:
    return data.report_preview(path)


@app.get("/api/advanced/backtest")
def api_advanced_backtest(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_backtest(_market(market))


@app.get("/api/advanced/scanner")
def api_advanced_scanner(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(24, ge=24, le=200),
    deep: bool = Query(False),
) -> dict:
    return _ensure_status(advanced.advanced_scanner(_market(market), mode, horizon, limit, deep))


@app.post("/api/advanced/calculator/kelly")
def api_calculator_kelly(payload: dict) -> dict:
    return advanced.kelly(payload)


@app.post("/api/advanced/calculator/var")
def api_calculator_var(payload: dict) -> dict:
    return advanced.var_cvar(payload)


@app.post("/api/advanced/calculator/risk-reward")
def api_calculator_risk_reward(payload: dict) -> dict:
    return advanced.risk_reward(payload)


@app.post("/api/advanced/monte-carlo")
def api_monte_carlo(payload: dict) -> dict:
    return advanced.monte_carlo(payload)


@app.get("/api/advanced/correlation")
def api_advanced_correlation(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return advanced.correlation(_market(market))


@app.get("/api/insights/prediction")
def api_prediction_insights(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_prediction_insights(_market(market))


@app.get("/api/insights/prediction-accuracy")
def api_prediction_accuracy(market: str = Query("all", pattern="^(kr|us|all)$")) -> dict:
    mk = None if market == "all" else _market(market)
    return final_engine.prediction_accuracy_stats(mk)


@app.get("/api/insights/chart-analysis-accuracy")
def api_chart_analysis_accuracy(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    futureBars: int = Query(20, ge=5, le=60),
    symbolLimit: int = Query(8, ge=2, le=30),
    maxCutoffs: int = Query(4, ge=1, le=12),
) -> dict:
    return chart_accuracy.chart_analysis_accuracy(market, futureBars, symbolLimit, maxCutoffs)


@app.get("/api/insights/trendline-accuracy")
def api_trendline_accuracy(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    futureBars: int = Query(20, ge=5, le=60),
    symbolLimit: int = Query(12, ge=2, le=30),
    maxCutoffs: int = Query(6, ge=1, le=12),
    includeItems: bool = Query(False),
) -> dict:
    return chart_accuracy.trendline_accuracy(market, futureBars, symbolLimit, maxCutoffs, include_items=includeItems)


@app.get("/api/insights/supply-zone-accuracy")
def api_supply_zone_accuracy(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    futureBars: int = Query(20, ge=5, le=60),
    symbolLimit: int = Query(12, ge=2, le=30),
    maxCutoffs: int = Query(6, ge=1, le=12),
    includeItems: bool = Query(False),
) -> dict:
    return chart_accuracy.supply_zone_accuracy(market, futureBars, symbolLimit, maxCutoffs, include_items=includeItems)


@app.get("/api/insights/trendline-anchor-learning")
def api_trendline_anchor_learning(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    symbol: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    from app.services import trendline_learning

    return trendline_learning.learning_report(market.lower(), symbol.upper().strip(), limit)


# ── 5차: adaptive weights ─────────────────────────────────────────────────

@app.get("/api/insights/adaptive-weights")
def api_adaptive_weights(
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    from app.services import adaptive_weights as _aw
    from datetime import datetime

    max_allowed = min(200, runtime_limits.clamp_limit(limit, 50, 200))
    try:
        table = _aw.load_adaptive_weights()
        summary = _aw.weight_summary(table)
        return {
            "status": "OK" if table else "NO_DATA",
            "totalSignals": summary["totalSignals"],
            "eligibleSignals": summary["eligibleSignals"],
            "bySignalKey": summary["bySignalKey"][:max_allowed],
            "bySignalType": summary["bySignalType"],
            "byHorizon": summary["byHorizon"],
            "byMode": summary["byMode"],
            "byMarket": summary["byMarket"],
            "source": str(_aw.ADAPTIVE_WEIGHT_CSV),
            "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": str(exc),
            "totalSignals": 0,
            "eligibleSignals": 0,
            "bySignalKey": [],
            "bySignalType": {},
            "byHorizon": {},
            "byMode": {},
            "byMarket": {},
        }


@app.get("/api/validation/self-correction")
def api_validation_self_correction(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    """현재 적용 중인 보정값과 샘플 통계 조회."""
    from app.engine import correction_store as _cs, self_correction_v2 as _scv2
    try:
        params = _cs.load_params()
        key = f"{_market(market)}_{mode}_{horizon}"
        correction = params.get("markets", {}).get(key) or _cs.load_correction(_market(market), mode, horizon)
        return {
            "status": "OK",
            "market": _market(market),
            "mode": mode,
            "horizon": horizon,
            "version": params.get("version", 0),
            "generatedAt": params.get("generatedAt"),
            "totalSamples": params.get("totalSamples", 0),
            "sampleCount": correction.get("sampleCount", 0),
            "confidence": correction.get("confidence", 0.0),
            "correctionActive": correction.get("confidence", 0.0) >= 0.3,
            "activeAdjustments": {
                "weightAdjustments": correction.get("weightAdjustments", {}),
                "priceAdjustments": correction.get("priceAdjustments", {}),
                "filterAdjustments": correction.get("filterAdjustments", {}),
            },
            "topFailureReasons": correction.get("topFailureReasons", []),
            "reasonCounts": correction.get("reasonCounts", {}),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


@app.post("/api/validation/self-correction/rebuild")
def api_validation_self_correction_rebuild(
    market: str = Query("kr", pattern="^(kr|us)$"),
) -> dict:
    """검증 CSV에서 보정 파라미터를 재생성한다 (관리자 전용)."""
    from app.engine import self_correction_v2 as _scv2
    try:
        result = _scv2.build_correction_params(_market(market))
        return {
            "status": "OK",
            "version": result.get("version"),
            "totalSamples": result.get("totalSamples", 0),
            "generatedAt": result.get("generatedAt"),
            "marketKeys": list(result.get("markets", {}).keys()),
        }
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


@app.get("/api/validation/outcomes")
def api_validation_outcomes(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query(""),
    horizon: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    """최근 추천 검증 결과와 outcomeReason 조회."""
    import csv as _oc_csv
    from app.engine import outcome_analyzer as _oa
    mk = _market(market)
    rows: list[dict] = []
    reports = __import__("pathlib").Path(__file__).resolve().parents[3] / "reports"
    pattern = f"mone_v36_final_trade_validation_{mk}_*.csv"
    for path in sorted(reports.glob(pattern))[:9]:
        try:
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with path.open("r", encoding=enc, newline="") as f:
                        for row in _oc_csv.DictReader(f):
                            if mode and str(row.get("mode", "")) != mode:
                                continue
                            if horizon and str(row.get("horizon", "")) != horizon:
                                continue
                            row["outcomeReason"] = _oa.classify_outcome(row, row)
                            rows.append(row)
                    break
                except UnicodeDecodeError:
                    continue
        except Exception:
            pass
    rows = rows[-limit:]
    reason_counts = _oa.reason_counts(rows)
    return {
        "status": "OK",
        "market": mk,
        "count": len(rows),
        "reasonCounts": reason_counts,
        "topFailureReasons": _oa.top_failure_reasons(rows),
        "items": rows,
    }


@app.get("/api/admin/correction-preview")
def api_admin_correction_preview(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(10, ge=1, le=30),
) -> dict:
    """보정 적용 전/후 추천 차이 미리보기."""
    import csv as _cp_csv
    from app.engine import self_correction_v2 as _scv2, correction_store as _cs
    mk = _market(market)
    reports = __import__("pathlib").Path(__file__).resolve().parents[3] / "reports"
    csv_path = reports / f"mone_v36_final_recommendations_{mk}_{mode}_{horizon}.csv"
    rows: list[dict] = []
    if csv_path.exists():
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with csv_path.open("r", encoding=enc, newline="") as f:
                    rows = list(_cp_csv.DictReader(f))[:limit]
                break
            except UnicodeDecodeError:
                continue

    def _num_safe(v: object) -> float:
        try: return float(str(v or "").replace(",", "").replace("₩", "").replace("$", "").replace("%", ""))
        except Exception: return 0.0

    diff_rows = []
    for row in rows:
        entry_before = _num_safe(row.get("entry"))
        target_before = _num_safe(row.get("target"))
        stop_before = _num_safe(row.get("stop"))
        score_before = _num_safe(row.get("finalRankScore"))
        corr = _scv2.apply_correction(
            {"finalRankScore": score_before, "riskScore": _num_safe(row.get("riskScore"))},
            entry_before, target_before, stop_before, mk, mode, horizon
        )
        diff_rows.append({
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "correctionApplied": corr.get("correctionApplied"),
            "before": {"entry": entry_before, "target": target_before, "stop": stop_before, "finalRankScore": score_before},
            "after": {"entry": corr["adjustedEntry"], "target": corr["adjustedTarget"], "stop": corr["adjustedStop"]},
            "entryDeltaPct": round((corr["adjustedEntry"] - entry_before) / max(entry_before, 1) * 100, 3) if entry_before else 0,
            "targetDeltaPct": round((corr["adjustedTarget"] - target_before) / max(target_before, 1) * 100, 3) if target_before else 0,
            "stopDeltaPct": round((corr["adjustedStop"] - stop_before) / max(stop_before, 1) * 100, 3) if stop_before else 0,
            "correctionSummary": corr.get("correctionSummary"),
        })
    params = _cs.load_params()
    key = f"{mk}_{mode}_{horizon}"
    correction = params.get("markets", {}).get(key, {})
    return {
        "status": "OK",
        "market": mk, "mode": mode, "horizon": horizon,
        "correctionEnabled": __import__("os").environ.get("SELF_CORRECTION_ENABLED", "true").lower() not in {"false", "0", "no", "off"},
        "correctionStrength": float(__import__("os").environ.get("CORRECTION_STRENGTH", "1.0")),
        "sampleCount": correction.get("sampleCount", 0),
        "confidence": correction.get("confidence", 0.0),
        "topFailureReasons": correction.get("topFailureReasons", []),
        "items": diff_rows,
    }


@app.get("/api/admin/correction-dashboard")
def api_admin_correction_dashboard(
    market: str = Query("kr", pattern="^(kr|us)$"),
) -> dict:
    """자가보정 종합 대시보드 — 성과 지표, 보정 상태, 데이터 품질."""
    import csv as _db_csv, os as _db_os
    from app.engine import correction_store as _cs, outcome_analyzer as _oa
    mk = _market(market)
    reports = __import__("pathlib").Path(__file__).resolve().parents[3] / "reports"

    # 보정 파라미터 전체
    params = _cs.load_params()
    all_corrections = params.get("markets", {})
    corrections_by_key = {
        k: {
            "sampleCount": v.get("sampleCount", 0),
            "learnableSampleCount": v.get("learnableSampleCount", 0),
            "confidence": v.get("confidence", 0.0),
            "correctionActive": v.get("confidence", 0.0) >= 0.3,
            "topFailureReasons": v.get("topFailureReasons", []),
            "priceAdjustments": v.get("priceAdjustments", {}),
            "weightAdjustments": v.get("weightAdjustments", {}),
        }
        for k, v in all_corrections.items()
        if k.startswith(mk)
    }

    # 성과 지표 집계 (virtual_validation_results.csv)
    perf_stats: dict[str, Any] = {}
    vvr_path = reports / "virtual_validation_results.csv"
    if vvr_path.exists():
        rows: list[dict] = []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with vvr_path.open("r", encoding=enc, newline="") as f:
                    rows = [r for r in _db_csv.DictReader(f) if (r.get("market") or "").lower() == mk]
                break
            except UnicodeDecodeError:
                continue
        settled = [r for r in rows if (r.get("status") or "").upper() in {"WIN", "LOSS", "CLOSED", "SETTLED", "EXPIRED"}]
        executed = [r for r in settled if str(r.get("isExecuted") or "").lower() == "true"]
        wins = [r for r in executed if str(r.get("targetHit") or "").lower() == "true" and str(r.get("stopHit") or "").lower() != "true"]
        stops = [r for r in executed if str(r.get("result") or "").upper() in {"STOP", "STOP_HIT", "STOP_FIRST", "LOSS"}]
        pnls = []
        for r in executed:
            try: pnls.append(float(r.get("returnPct") or 0))
            except Exception: pass
        perf_stats = {
            "totalSamples": len(rows),
            "settledCount": len(settled),
            "executedCount": len(executed),
            "winCount": len(wins),
            "stopCount": len(stops),
            "winRate": round(len(wins) / max(len(executed), 1) * 100, 1),
            "stopRate": round(len(stops) / max(len(executed), 1) * 100, 1),
            "missRate": round((len(settled) - len(executed)) / max(len(settled), 1) * 100, 1),
            "avgNetPnl": round(sum(pnls) / max(len(pnls), 1), 3),
        }

    return {
        "status": "OK",
        "market": mk,
        "correctionEnabled": _db_os.environ.get("SELF_CORRECTION_ENABLED", "true").lower() not in {"false", "0", "no", "off"},
        "correctionStrength": float(_db_os.environ.get("CORRECTION_STRENGTH", "1.0")),
        "paramsVersion": params.get("version", 0),
        "paramsGeneratedAt": params.get("generatedAt"),
        "totalSamples": params.get("totalSamples", 0),
        "correctionsByKey": corrections_by_key,
        "performanceStats": perf_stats,
    }


@app.get("/api/admin/correction-history")
def api_admin_correction_history() -> dict:
    """보정 파라미터 버전 이력 조회."""
    from app.engine import correction_store as _cs
    try:
        versions = _cs.list_versions()
        return {"status": "OK", "count": len(versions), "versions": versions}
    except Exception as exc:
        return {"status": "ERROR", "error": str(exc)}


@app.get("/api/validation/walkforward")
def api_validation_walkforward(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("", description="비어 있으면 모든 mode"),
    horizon: str = Query("", description="비어 있으면 모든 horizon"),
    run: bool = Query(False, description="True이면 즉시 재실행 (느림)"),
) -> dict:
    """Walk-Forward 자가보정 검증 결과 반환. run=true이면 재계산."""
    import json as _wf_json
    from pathlib import Path as _WFPath
    from app.engine import walkforward_backtest as _wfb

    mk = _market(market)
    reports = _WFPath(__file__).resolve().parents[3] / "reports"
    summary_path = reports / f"walkforward_summary_{mk}.json"

    if run:
        try:
            if mode and horizon:
                result = _wfb.run_walkforward(mk, mode, horizon)
                return result
            else:
                result = _wfb.run_all(mk)
                return result
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}

    # 저장된 결과 반환
    if summary_path.exists():
        try:
            data = _wf_json.loads(summary_path.read_text(encoding="utf-8"))
            if mode and horizon:
                key = f"{mk}_{mode}_{horizon}"
                combo = data.get("combos", {}).get(key)
                if combo:
                    return combo
                return {"status": "NOT_FOUND", "key": key}
            # 요약만 반환 (전체 raw는 크므로)
            combos_summary = {
                k: {
                    "status":           v.get("status"),
                    "windowCount":      v.get("windowCount"),
                    "dataRange":        v.get("dataRange"),
                    "baselineStats":    v.get("baselineStats"),
                    "correctedStats":   v.get("correctedStats"),
                    "diff":             v.get("diff"),
                }
                for k, v in data.get("combos", {}).items()
            }
            return {
                "status":      "OK",
                "market":      mk,
                "generatedAt": data.get("generatedAt"),
                "combos":      combos_summary,
            }
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)}

    return {
        "status":  "NOT_RUN",
        "message": f"결과 없음. ?run=true 로 실행하거나 scripts/run_walkforward.py 를 실행하세요.",
        "summaryPath": str(summary_path),
    }


@app.get("/api/validation/recommendations/summary")
def api_validation_recommendations_summary(
    market: str = Query("kr", pattern="^(kr|us|all)$"),
    mode: str = Query(""),
    horizon: str = Query(""),
) -> dict:
    """검증 결과 다차원 집계 요약 — bySignalKey, bySignalType, byHorizon, byMode, byMarket, byEventTag 등."""
    import csv as _sum_csv
    from pathlib import Path as _SumPath
    from datetime import datetime as _SumDT
    from collections import defaultdict as _sdd

    def _safe_num(v: object) -> float | None:
        try:
            fv = float(str(v).replace(",", "").strip())
            import math
            return fv if math.isfinite(fv) else None
        except Exception:
            return None

    def _truth(v: object) -> bool:
        return str(v).lower() in {"true", "1", "yes", "1.0"}

    reports = _SumPath(__file__).resolve().parents[3] / "reports"
    rows_v: list[dict] = []
    rows_l: list[dict] = []

    for fname in ("virtual_validation_results.csv", "virtual_prediction_ledger.csv"):
        fpath = reports / fname
        if not fpath.exists():
            continue
        try:
            with open(fpath, newline="", encoding="utf-8") as f:
                reader = _sum_csv.DictReader(f)
                for row in reader:
                    mk = str(row.get("market", "")).lower()
                    if market not in {"all", ""} and mk != market:
                        continue
                    if mode and mode not in {"all", ""} and str(row.get("mode", "")).lower() != mode.lower():
                        continue
                    if horizon and horizon not in {"all", ""} and str(row.get("horizon", "")).lower() != horizon.lower():
                        continue
                    if fname.startswith("virtual_validation"):
                        rows_v.append(row)
                    else:
                        rows_l.append(row)
        except Exception:
            pass

    all_rows = rows_v or rows_l

    by_signal_key: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_signal_type: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_horizon: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_mode_d: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_market_d: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_event_tag: dict[str, dict] = _sdd(lambda: {"count": 0, "wins": 0, "returnSum": 0.0})
    by_trendline: dict[str, int] = _sdd(int)
    by_data_src: dict[str, int] = _sdd(int)

    from app.services import adaptive_weights as _aw_sum

    for row in all_rows:
        pnl = _safe_num(row.get("pnlPct") or row.get("returnPct") or row.get("virtual_return_pct"))
        is_win = pnl is not None and pnl >= 0
        ret = pnl or 0.0

        keys = _aw_sum._make_signal_keys(row)
        for k in keys:
            st = _aw_sum._signal_type(k)
            by_signal_key[k]["count"] += 1
            by_signal_type[st]["count"] += 1
            if is_win:
                by_signal_key[k]["wins"] += 1
                by_signal_type[st]["wins"] += 1
            by_signal_key[k]["returnSum"] = round(by_signal_key[k]["returnSum"] + ret, 4)
            by_signal_type[st]["returnSum"] = round(by_signal_type[st]["returnSum"] + ret, 4)

        h = str(row.get("horizon") or "all").lower()
        m = str(row.get("mode") or "all").lower()
        mk = str(row.get("market") or "all").lower()
        by_horizon[h]["count"] += 1
        by_mode_d[m]["count"] += 1
        by_market_d[mk]["count"] += 1
        if is_win:
            by_horizon[h]["wins"] += 1
            by_mode_d[m]["wins"] += 1
            by_market_d[mk]["wins"] += 1
        by_horizon[h]["returnSum"] = round(by_horizon[h]["returnSum"] + ret, 4)
        by_mode_d[m]["returnSum"] = round(by_mode_d[m]["returnSum"] + ret, 4)
        by_market_d[mk]["returnSum"] = round(by_market_d[mk]["returnSum"] + ret, 4)

        for tf in ("newsEventTag", "disclosureEventTag", "earningsEventTag", "macroEventTag", "sectorEventTag"):
            tag = str(row.get(tf) or "").lower()
            if tag and tag not in {"unknown", "none", "neutral", ""}:
                by_event_tag[tag]["count"] += 1
                if is_win:
                    by_event_tag[tag]["wins"] += 1
                by_event_tag[tag]["returnSum"] = round(by_event_tag[tag]["returnSum"] + ret, 4)

        tl_status = str(row.get("trendlineLearningStatus") or "").upper() or "UNKNOWN"
        by_trendline[tl_status] += 1

        ds = str(row.get("dataSourceType") or row.get("chartDataSourceType") or "unknown").lower()
        by_data_src[ds] += 1

    def _fmt(d: dict) -> dict:
        return {k: {
            "count": v["count"],
            "winRate": round(v["wins"] / v["count"], 4) if v["count"] else 0.0,
            "avgReturn": round(v["returnSum"] / v["count"], 4) if v["count"] else 0.0,
        } for k, v in d.items()}

    return {
        "status": "OK" if all_rows else "NO_DATA",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "totalRows": len(all_rows),
        "bySignalKey": _fmt(by_signal_key),
        "bySignalType": _fmt(by_signal_type),
        "byHorizon": _fmt(by_horizon),
        "byMode": _fmt(by_mode_d),
        "byMarket": _fmt(by_market_d),
        "byEventTag": _fmt(by_event_tag),
        "byTrendlineLearningStatus": dict(by_trendline),
        "byDataSourceType": dict(by_data_src),
        "generatedAt": _SumDT.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/history/predictions")
def api_prediction_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_prediction_history(_market(market) if market else None)


@app.get("/api/history/outcomes")
def api_outcome_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_outcome_history(_market(market) if market else None)


@app.post("/api/quotes/refresh")
def api_quotes_refresh(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    symbols: str | None = Query(None),
    max_symbols: int = Query(80, ge=1, le=150),
) -> dict:
    return quotes.refresh_quotes(market=market, symbols=symbols, max_symbols=max_symbols)


def _remove_routes(paths: set[str]) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (isinstance(route, APIRoute) and getattr(route, "path", "") in paths)
    ]


_remove_routes(
    {
        "/api/session",
        "/api/final/data-quality",
        "/api/v1/candidates",
        "/api/backtest/trades",
        "/api/backtest/summary",
        "/api/virtual/summary",
        "/api/admin/pipeline",
        "/api/admin/correction",
        "/api/ohlcv",
    }
)


@app.get("/api/session")
def api_session_core(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return {"status": "OK", **session.get_price_session(_market(market))}


@app.get("/api/final/data-quality")
def api_final_data_quality_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("quick", pattern="^(quick|full)$"),
) -> dict:
    return data_quality.data_quality(_market(market), mode=mode)


@app.get("/api/v1/candidates")
def api_v1_candidates_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    strategy: str = Query("balanced"),
    term: str = Query("swing"),
    cash: float = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    return risk.candidates(_market(market), strategy, term, cash, limit)


@app.get("/api/backtest/trades")
def api_backtest_trades_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return backtest.trades(_market(market), mode, horizon, limit)


@app.get("/api/backtest/summary")
def api_backtest_summary_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return backtest.summary(_market(market), mode, horizon)


def _safe_pct(value: object) -> float | None:
    try:
        text = str(value).replace("%", "").replace(",", "").strip()
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _portfolio_return_pct(returns: list[float], allocation_pct: float = 10.0) -> float:
    """Equal-slot virtual portfolio return. Avoids misleading raw return sums."""
    if not returns:
        return 0.0
    slot = max(0.0, min(allocation_pct, 100.0)) / 100.0
    capital = 1.0
    for value in returns:
        capital *= max(0.0, 1.0 + (float(value) / 100.0) * slot)
    return (capital - 1.0) * 100.0


def _virtual_summary_from_reports(market: str, mode: str = "balanced", horizon: str = "swing") -> dict:
    def _truth(value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "filled", "executed", "체결"}

    def _num(value: object) -> float | None:
        try:
            text = str(value).replace("%", "").replace(",", "").strip()
            if not text:
                return None
            return float(text)
        except Exception:
            return None

    def _rows(name: str) -> list[dict]:
        path = data.REPORT_DIR / name
        if not path.exists() or path.stat().st_size <= 0:
            return []
        return data.dataframe_records(data.read_csv(path))

    market = _market(market)
    validations = [
        row for row in _rows("virtual_validation_results.csv")
        if str(row.get("market", "")).lower() == market
    ]
    ledger = [
        row for row in _rows("virtual_prediction_ledger.csv")
        if str(row.get("market", "")).lower() == market
    ]
    if mode and mode not in {"all", ""}:
        validations = [row for row in validations if str(row.get("mode", "")).lower() == mode.lower()]
        ledger = [row for row in ledger if str(row.get("mode", "")).lower() == mode.lower()]
    if horizon and horizon not in {"all", ""}:
        validations = [row for row in validations if str(row.get("horizon", "")).lower() == horizon.lower()]
        ledger = [row for row in ledger if str(row.get("horizon", "")).lower() == horizon.lower()]

    executed = [row for row in validations if _truth(row.get("isExecuted"))]
    unexecuted = [row for row in validations if not _truth(row.get("isExecuted"))]
    returns = [_num(row.get("returnPct")) for row in executed]
    returns = [value for value in returns if value is not None]
    wins = [value for value in returns if value > 0]
    raw_sum = sum(returns)
    cumulative = _portfolio_return_pct(returns)
    avg = raw_sum / len(returns) if returns else 0.0
    pending = [
        row for row in ledger
        if str(row.get("status", "")).strip().upper() in {"", "PENDING", "DATA_PENDING"}
    ]
    latest_date = ""
    for row in validations:
        latest_date = max(latest_date, str(row.get("validatedAt") or row.get("validationDate") or row.get("createdAt") or ""))
    return {
        "status": "OK" if validations or ledger else "NO_DATA",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "source": "virtual_validation_results.csv + virtual_prediction_ledger.csv",
        "returnBasis": "executed rows; cumulativeReturnPct is a 10% equal-slot virtual portfolio compound return, not raw return sum",
        "pnlCurveScope": "portfolio_aggregate",
        "rawReturnSumPct": round(raw_sum, 3),
        "totalRecommendations": len(ledger) or len(validations),
        "latestRecommendations": len(validations),
        "executedTrades": len(executed),
        "latestExecutedTrades": len(executed),
        "unexecutedCount": len(unexecuted),
        "latestUnexecutedCount": len(unexecuted),
        "pendingCount": len(pending),
        "executionRate": round((len(executed) / len(validations)) * 100, 2) if validations else 0,
        "latestExecutionRate": round((len(executed) / len(validations)) * 100, 2) if validations else 0,
        "winRate": round((len(wins) / len(returns)) * 100, 2) if returns else 0,
        "latestWinRate": round((len(wins) / len(returns)) * 100, 2) if returns else 0,
        "executedReturnPct": round(avg, 3),
        "cumulativeReturnPct": round(cumulative, 3),
        "latestCumulativeReturnPct": round(cumulative, 3),
        "latestDate": latest_date[:10],
        "items": validations[:300],
        "count": len(validations),
    }


@app.get("/api/virtual/summary")
def api_virtual_summary_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return _virtual_summary_from_reports(_market(market), mode, horizon)


@app.get("/api/admin/pipeline")
def api_admin_pipeline_core(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data_quality.admin_pipeline(_market(market))


@app.get("/api/admin/correction")
def api_admin_correction_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return correction.correction_summary(_market(market), mode, horizon)


@app.get("/api/ohlcv")
def api_ohlcv_core(
    symbol: str = Query(..., min_length=1),
    market: str = Query("kr"),
    limit: int = Query(120, ge=1, le=500),
    futureProjectionBars: int = Query(12, ge=0, le=60),
) -> dict:
    normalized_market = _market(market)
    payload = data.chart_data(symbol, normalized_market)
    rows = payload.get("items") or payload.get("rows") or []
    if not rows:
        try:
            backfill = quotes.backfill_daily_ohlcv(symbol, normalized_market, days=max(limit, 120))
            if str(backfill.get("status", "")).upper() == "OK":
                payload = data.chart_data(symbol, normalized_market)
                rows = payload.get("items") or payload.get("rows") or []
                payload["backfill"] = backfill
        except Exception as exc:
            payload["backfill"] = {"status": "ERROR", "error": str(exc)[:160]}
    payload["items"] = rows[-limit:] if len(rows) > limit else rows
    payload["count"] = len(payload["items"])
    payload["latestDate"] = _latest_chart_date(payload["items"])
    return _enrich_chart_precision(payload, symbol, normalized_market, futureProjectionBars)


try:
    from app.engine.mone_v55_backend_aliases import register_mone_v55_backend_aliases
    register_mone_v55_backend_aliases(app)
except Exception as exc:
    print("[MONE v5.5] backend alias registration failed:", exc)

try:
    from app.engine.mone_v61_virtual_summary import register_mone_v61_virtual_summary
    register_mone_v61_virtual_summary(app)
except Exception as exc:
    print("[MONE v6.1] virtual summary registration failed:", exc)

try:
    from app.engine.mone_v65_api_stabilizer import register_mone_v65_api_stabilizer
    register_mone_v65_api_stabilizer(app)
except Exception as exc:
    print("[MONE v6.5] api stabilizer registration failed:", exc)

try:
    from app.engine.mone_v75_session_guard import register_mone_v75_session_guard_routes
    register_mone_v75_session_guard_routes(app)
except Exception as exc:
    print("[MONE v7.5] session guard registration failed:", exc)

try:
    from app.engine.mone_v77_holdings_risk import register_mone_v77_holdings_routes
    register_mone_v77_holdings_routes(app)
except Exception as exc:
    print("[MONE v7.7] holdings risk registration failed:", exc)

try:
    from app.engine.mone_v80_company_prediction import register_mone_v80_company_prediction_routes
    register_mone_v80_company_prediction_routes(app)
except Exception as exc:
    print("[MONE v8.0] company/prediction route registration failed:", exc)

try:
    from app.engine.mone_v65_api_stabilizer import register_mone_v65_api_stabilizer
    register_mone_v65_api_stabilizer(app)
except Exception as exc:
    print("[MONE v6.5 final] api stabilizer registration failed:", exc)

try:
    from app.engine.mone_v802_holdings_clean import register_mone_v802_holdings_clean_routes
    register_mone_v802_holdings_clean_routes(app)
except Exception as exc:
    print("[MONE v8.0.2] holdings clean final route failed:", exc)

try:
    from app.engine.mone_v803_holdings_clean_guard import register_mone_v803_holdings_clean_guard
    register_mone_v803_holdings_clean_guard(app)
except Exception as exc:
    print("[MONE v8.0.3] holdings clean guard route failed:", exc)

# ── v8.0.4: POST/PATCH/DELETE /api/holdings 복원 ──────────────────────────────
# mone_v802가 GET만 남기고 나머지를 삭제하므로 여기서 다시 등록
from fastapi.routing import APIRoute as _APIR
_HOLDINGS_RESTORE_PATHS = {"/api/holdings"}
app.router.routes = [
    r for r in app.router.routes
    if not (isinstance(r, _APIR) and getattr(r, "path", "") in _HOLDINGS_RESTORE_PATHS
            and bool(getattr(r, "methods", set()) - {"GET", "HEAD"}))
]

@app.post("/api/holdings")
def _api_holdings_add_v804(payload: dict) -> dict:
    """보유종목 추가 (v8.0.4 복원)"""
    return user_data.upsert_holding(payload, mode="post")

@app.patch("/api/holdings/{symbol}")
def _api_holdings_patch_v804(symbol: str, payload: dict) -> dict:
    """보유종목 수정 (v8.0.4 복원)"""
    return user_data.upsert_holding(payload, mode="patch", symbol_arg=symbol)

@app.delete("/api/holdings/{symbol}")
def _api_holdings_delete_v804(symbol: str, market: str = Query("kr")) -> dict:
    """보유종목 삭제 (v8.0.4 복원)"""
    return user_data.delete_holding(symbol, _market(market))

# --- MONE live data-quality route patch v2 ascii ---
from pathlib import Path as _MONE_DQ_Path
from datetime import datetime as _MONE_DQ_Datetime
import csv as _MONE_DQ_csv
import re as _MONE_DQ_re

def _mone_dq_repo_root() -> _MONE_DQ_Path:
    return _MONE_DQ_Path(__file__).resolve().parents[3]

def _mone_dq_read_rows(path: _MONE_DQ_Path, max_rows: int = 5000):
    if not path.exists() or not path.is_file():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(_MONE_DQ_csv.DictReader(f))[:max_rows]
        except Exception:
            continue
    return []

def _mone_dq_symbol(row: dict) -> str:
    for key in ("symbol", "ticker", "code", "stock_code", "Symbol", "Ticker"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value.upper()
    return ""

def _mone_dq_time_value(row: dict) -> str:
    for key in (
        "timestamp", "updatedAt", "updated_at", "datetime", "dateTime",
        "time", "createdAt", "created_at", "date", "tradeDate",
        "asOfDate", "baseDate"
    ):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""

def _mone_dq_parse_time(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    cleaned = value.replace("KST", "").replace("kst", "").strip().replace("/", "-")
    if _MONE_DQ_re.fullmatch(r"\d{8}", cleaned):
        cleaned = f"{cleaned[0:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return _MONE_DQ_Datetime.strptime(cleaned, fmt)
        except Exception:
            pass
    try:
        return _MONE_DQ_Datetime.fromisoformat(cleaned)
    except Exception:
        return None

def _mone_dq_file_summary(path: _MONE_DQ_Path, role: str, market: str) -> dict:
    rows = _mone_dq_read_rows(path)
    symbols = set()
    latest_raw = ""
    latest_dt = None

    for row in rows:
        sym = _mone_dq_symbol(row)
        if sym:
            symbols.add(sym)

        raw = _mone_dq_time_value(row)
        dt = _mone_dq_parse_time(raw)
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt
            latest_raw = raw

    mtime = None
    try:
        mtime = _MONE_DQ_Datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        pass

    return {
        "name": path.name,
        "role": role,
        "market": market,
        "path": str(path),
        "exists": path.exists(),
        "status": "NORMAL" if rows else "NO_DATA",
        "rowCount": len(rows),
        "uniqueSymbolCount": len(symbols),
        "sampleSymbols": sorted(symbols)[:12],
        "latestTimestamp": latest_raw,
        "mtime": mtime,
    }

def _mone_dq_market(market: str) -> dict:
    repo = _mone_dq_repo_root()
    market = (market or "kr").lower()

    price_files = [
        (repo / "data" / "stockapp" / f"kis_current_price_{market}.csv", "price_current_stockapp"),
        (repo / "reports" / f"kis_current_price_{market}.csv", "price_current_reports"),
        (repo / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv", "intraday_quote_stockapp"),
        (repo / "reports" / f"intraday_quote_snapshot_{market}.csv", "intraday_quote_reports"),
        (repo / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv", "intraday_realtime_stockapp"),
        (repo / "reports" / f"intraday_realtime_snapshot_{market}.csv", "intraday_realtime_reports"),
    ]

    files = [_mone_dq_file_summary(path, role, market) for path, role in price_files]
    good_files = [x for x in files if int(x.get("rowCount") or 0) > 0]

    all_symbols = set()
    for path, _role in price_files:
        for row in _mone_dq_read_rows(path):
            sym = _mone_dq_symbol(row)
            if sym:
                all_symbols.add(sym)

    warnings = []
    failures_path = repo / "reports" / "data_collection_failures_latest.csv"
    failures = _mone_dq_read_rows(failures_path, max_rows=1000)
    if failures:
        warnings.append(f"collection failures present: {len(failures)} rows")

    if good_files:
        data_status = "NORMAL"
        kill_switch = False
        message = "core price data found"
    else:
        data_status = "NO_DATA"
        kill_switch = True
        message = "core price csv not found"

    if good_files and len(all_symbols) < 5:
        data_status = "PARTIAL"
        warnings.append("price coverage is small")

    coverage = {}
    try:
        import json as _mone_dq_json
        summary_path = repo / "reports" / "kis_collection_coverage_summary.json"
        if summary_path.exists():
            coverage = _mone_dq_json.loads(summary_path.read_text(encoding="utf-8")).get("markets", {}).get(market, {})
    except Exception:
        coverage = {}

    return {
        "status": "OK",
        "market": market,
        "dataStatus": data_status,
        "priceDataStatus": "OK" if good_files else "NO_DATA",
        "killSwitch": kill_switch,
        "reviewMode": False,
        "message": message,
        "candidateCount": len(all_symbols),
        "targetCount": coverage.get("targetCount"),
        "currentPriceCount": coverage.get("currentPriceCount"),
        "missingTargetCount": coverage.get("missingTargetCount"),
        "currentPriceCoveragePct": coverage.get("currentPriceCoveragePct"),
        "files": files,
        "warnings": warnings,
        "errors": [] if good_files else ["core price data not found"],
        "updatedAt": _MONE_DQ_Datetime.now().astimezone().isoformat(),
    }

@app.get("/api/final/data-quality-live")
def api_final_data_quality_live(market: str = "kr"):
    market = (market or "kr").lower()

    if market == "all":
        kr = _mone_dq_market("kr")
        us = _mone_dq_market("us")
        kill = bool(kr.get("killSwitch")) or bool(us.get("killSwitch"))

        if kr.get("dataStatus") == "NORMAL" and us.get("dataStatus") == "NORMAL":
            data_status = "NORMAL"
        elif kr.get("dataStatus") == "NO_DATA" and us.get("dataStatus") == "NO_DATA":
            data_status = "NO_DATA"
        else:
            data_status = "PARTIAL"

        return {
            "status": "OK",
            "market": "all",
            "dataStatus": data_status,
            "priceDataStatus": data_status,
            "killSwitch": kill,
            "reviewMode": False,
            "message": "combined kr/us data quality",
            "targetCount": int(kr.get("targetCount") or 0) + int(us.get("targetCount") or 0),
            "currentPriceCount": int(kr.get("currentPriceCount") or 0) + int(us.get("currentPriceCount") or 0),
            "missingTargetCount": int(kr.get("missingTargetCount") or 0) + int(us.get("missingTargetCount") or 0),
            "currentPriceCoveragePct": round(
                ((int(kr.get("currentPriceCount") or 0) + int(us.get("currentPriceCount") or 0))
                 / max(1, int(kr.get("targetCount") or 0) + int(us.get("targetCount") or 0))) * 100,
                2,
            ),
            "markets": {"kr": kr, "us": us},
            "warnings": list(kr.get("warnings", [])) + list(us.get("warnings", [])),
            "errors": list(kr.get("errors", [])) + list(us.get("errors", [])),
            "updatedAt": _MONE_DQ_Datetime.now().astimezone().isoformat(),
        }

    if market not in ("kr", "us"):
        market = "kr"

    return _mone_dq_market(market)
# --- end MONE live data-quality route patch v2 ascii ---


# __MONE_AUTHORITATIVE_HOLDINGS_CLEAN_OVERRIDE_V3__
def _install_mone_authoritative_holdings_clean_v3():
    from pathlib import Path as _MonePath
    import csv as _mone_csv
    import re as _mone_re
    from datetime import datetime as _mone_datetime
    from fastapi import Query as _MoneQuery

    def _root() -> _MonePath:
        return _MonePath(__file__).resolve().parents[3]

    def _read_csv(path: _MonePath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _num(value, default=0.0) -> float:
        s = str(value or "").strip().replace(",", "").replace("₩", "").replace("$", "")
        s = _mone_re.sub(r"[^0-9.\\-]", "", s)
        try:
            return float(s) if s not in ("", "-", ".", "-.") else float(default)
        except Exception:
            return float(default)

    def _text(row: dict, keys: list[str], default: str = "") -> str:
        lower = {str(k).lower(): k for k in row.keys()}
        for key in keys:
            if key in row and str(row.get(key, "")).strip():
                return str(row.get(key, "")).strip()
            actual = lower.get(str(key).lower())
            if actual is not None and str(row.get(actual, "")).strip():
                return str(row.get(actual, "")).strip()
        return default

    def _symbol(value, market: str) -> str:
        raw = str(value or "").strip()
        if market == "kr":
            digits = _mone_re.sub(r"\\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return raw.upper()

    def _row_symbol(row: dict, market: str) -> str:
        value = _text(row, ["symbol", "ticker", "code", "stock_code", "stockCode", "종목코드", "Symbol", "Ticker"], "")
        if not value and row:
            value = row.get(next(iter(row.keys())), "")
        return _symbol(value, market)

    def _name(row: dict, symbol: str) -> str:
        return _text(row, ["name", "companyName", "company_name", "corp_name", "종목명", "Name"], symbol)

    def _price_index(market: str) -> dict[str, dict]:
        paths = [
            _root() / "data" / "stockapp" / f"kis_current_price_{market}.csv",
            _root() / "reports" / f"kis_current_price_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_realtime_snapshot_{market}.csv",
        ]
        out: dict[str, dict] = {}
        for path in paths:
            for row in _read_csv(path):
                sym = _row_symbol(row, market)
                if not sym:
                    continue
                price = _num(_text(row, ["currentPrice", "current_price", "price", "last", "close", "현재가"], ""), 0)
                if price <= 0:
                    price = _num(_text(row, ["currentPriceText", "priceText"], ""), 0)
                if price <= 0:
                    continue
                prev_close = _num(_text(row, ["prevClose", "previousClose", "prev_close", "basePrice", "stck_prdy_clpr", "전일종가", "기준가"], ""), 0)
                change_pct = _num(_text(row, ["changePct", "changeRate", "prdy_ctrt", "등락률"], ""), 0)
                if not change_pct and price > 0 and prev_close > 0:
                    change_pct = (price - prev_close) / prev_close * 100
                out[sym] = {
                    "currentPrice": price,
                    "currentPriceText": f"${price:,.2f}" if market == "us" else f"{round(price):,}원",
                    "priceSource": path.name,
                    "prevClose": prev_close,
                    "prevCloseText": f"${prev_close:,.2f}" if market == "us" and prev_close > 0 else f"{round(prev_close):,}원" if prev_close > 0 else "",
                    "changePct": change_pct,
                    "changePctText": f"{change_pct:+.2f}%" if change_pct else "",
                    "prevCloseSource": path.name if prev_close > 0 else "",
                    "quoteTimestamp": _text(row, ["timestamp", "time", "updatedAt", "datetime", "date"], ""),
                }
        return out

    def _v93_index(market: str) -> dict[str, dict]:
        path = _root() / "reports" / f"v93_position_cards_{market}.csv"
        out = {}
        for row in _read_csv(path):
            sym = _row_symbol(row, market)
            if sym:
                out[sym] = row
        return out

    def _ohlcv_prev_close(market: str, symbol: str) -> dict:
        paths = [
            _root() / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
            _root() / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
            _root() / "reports" / f"{market}_{symbol}_daily.csv",
        ]
        def _read_prev_close() -> dict:
            for path in paths:
                closes = []
                for row in _read_csv(path):
                    close = _num(_text(row, ["close", "Close", "종가"], ""), 0)
                    date = _text(row, ["date", "Date", "날짜"], "")
                    if close > 0:
                        closes.append((date, close))
                closes.sort(key=lambda item: item[0])
                if len(closes) >= 2:
                    return {"prevClose": closes[-2][1], "prevCloseSource": "ohlcv_prev_close", "prevCloseDate": closes[-2][0]}
            return {}

        found = _read_prev_close()
        if found:
            return found

        try:
            backfill = quotes.backfill_daily_ohlcv(symbol, market, days=120)
            if str(backfill.get("status", "")).upper() == "OK":
                found = _read_prev_close()
                if found:
                    found["prevCloseSource"] = "kis_ohlcv_backfill"
                    found["ohlcvBackfill"] = backfill
                    return found
        except Exception:
            pass
        return {}

    def _ohlcv_price_ref(market: str, symbol: str) -> dict:
        paths = [
            _root() / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
            _root() / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
            _root() / "reports" / f"{market}_{symbol}_daily.csv",
        ]
        for path in paths:
            closes = []
            for row in _read_csv(path):
                close = _num(_text(row, ["close", "Close", "stck_clpr", "종가"], ""), 0)
                date = _text(row, ["date", "Date", "tradeDate", "일자"], "")
                if close > 0:
                    closes.append((date, close))
            closes.sort(key=lambda item: item[0])
            if closes:
                prev = closes[-2][1] if len(closes) >= 2 else 0
                prev_date = closes[-2][0] if len(closes) >= 2 else ""
                return {
                    "currentPrice": closes[-1][1],
                    "currentPriceSource": "ohlcv_close",
                    "currentPriceDate": closes[-1][0],
                    "prevClose": prev,
                    "prevCloseSource": "ohlcv_prev_close",
                    "prevCloseDate": prev_date,
                    "ohlcvCount": len(closes),
                    "ohlcvSource": path.name,
                }
        return {}

    def _read_authoritative_holdings(market: str) -> list[dict]:
        markets = ["kr", "us"] if market == "all" else [market]
        rows = []
        seen_keys = set()
        for mk in markets:
            path = _root() / f"holdings_{mk}.csv"
            for row in _read_csv(path):
                sym = _row_symbol(row, mk)
                if not sym:
                    continue
                key = (mk, sym)
                if key in seen_keys:
                    continue
                qty = _num(_text(row, ["quantity", "qty", "수량"], ""), 0)
                avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평균단가", "매입가"], ""), 0)
                if qty <= 0:
                    continue
                seen_keys.add(key)
                stop_csv = _num(_text(row, ["stopPrice", "stop_price", "stop", "손절가"], ""), 0)
                target_csv = _num(_text(row, ["targetPrice", "target_price", "target", "목표가"], ""), 0)
                rows.append({
                    "symbol": sym,
                    "name": _name(row, sym),
                    "market": mk,
                    "quantity": qty,
                    "avgPrice": avg,
                    "stopPriceCsv": stop_csv,
                    "targetPriceCsv": target_csv,
                    "source": path.name,
                    "holdingAuthority": "holdings_csv",
                    "holdingAuthoritySource": path.name,
                })
        return rows

    def _sanitize_user_id(raw: str) -> str:
        return _mone_re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))[:64]

    def _read_personal_holdings(user_id: str, market: str) -> list[dict]:
        rows = []
        for row in _db.get_holdings(user_id, market):
            mk = "us" if str(row.get("market", "kr")).lower() == "us" else "kr"
            sym = _row_symbol(row, mk)
            qty = _num(_text(row, ["quantity", "qty"], ""), 0)
            avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice"], ""), 0)
            broker = str(row.get("broker") or row.get("source") or "manual").strip() or "manual"
            is_bridge = broker not in ("manual", "user_holdings", "")
            # bridge 항목: avgPrice=0 허용 (KIS CSV에서 누락 가능); manual: qty>0, avg>0 모두 필요
            if not sym or qty <= 0 or (avg <= 0 and not is_bridge):
                continue
            bridge_current = _num(row.get("currentPrice"), 0)
            # avgPrice가 없는 bridge 항목은 currentPrice를 임시 사용
            effective_avg = avg if avg > 0 else bridge_current
            rows.append({
                "symbol": sym,
                "name": _name(row, sym),
                "market": mk,
                "quantity": qty,
                "avgPrice": effective_avg,
                "stopPriceCsv": _num(_text(row, ["stopPrice", "stop_price", "stop"], ""), 0),
                "targetPriceCsv": _num(_text(row, ["targetPrice", "target_price", "target"], ""), 0),
                "source": "local_bridge" if is_bridge else "user_holdings",
                "broker": broker,
                "brokerSource": broker if is_bridge else "",
                "holdingAuthority": "personal_user_holdings",
                "holdingAuthoritySource": f"local_bridge_{broker}" if is_bridge else "user_holdings",
                # bridge에서 가져온 가격 데이터 (live quote 없을 때 fallback)
                "_bridgeCurrentPrice": bridge_current,
                "_bridgeProfitLoss": _num(row.get("profitLoss"), 0),
                "_bridgeProfitLossRate": _num(row.get("profitLossRate"), 0),
                "_bridgeEvalAmount": _num(row.get("evalAmount") or row.get("valuation"), 0),
            })
        return rows

    def _payload(market: str = "all", limit: int = 100, rows_override: list[dict] | None = None, authority: str = "holdings_kr.csv/holdings_us.csv") -> dict:
        market_key = str(market or "all").lower()
        if market_key not in ("all", "kr", "us"):
            market_key = "all"

        rows = rows_override if rows_override is not None else _read_authoritative_holdings(market_key)
        quote_kr = _price_index("kr") if market_key in ("all", "kr") else {}
        quote_us = _price_index("us") if market_key in ("all", "us") else {}
        v93_kr = _v93_index("kr") if market_key in ("all", "kr") else {}
        v93_us = _v93_index("us") if market_key in ("all", "us") else {}

        items = []
        for row in rows:
            mk = row["market"]
            sym = row["symbol"]
            qty = _num(row.get("quantity"), 0)
            avg = _num(row.get("avgPrice"), 0)
            q = (quote_kr if mk == "kr" else quote_us).get(sym, {})
            v = (v93_kr if mk == "kr" else v93_us).get(sym, {})

            current = _num(q.get("currentPrice"), 0) or _num(_text(v, ["currentPrice", "current", "price", "현재가"], ""), 0)
            ohlcv_ref = {}
            price_source_type = "live_quote" if _num(q.get("currentPrice"), 0) > 0 else ""
            price_source = q.get("priceSource") or ""
            if current <= 0:
                ohlcv_ref = _ohlcv_price_ref(mk, sym)
                current = _num(ohlcv_ref.get("currentPrice"), 0)
                if current > 0:
                    price_source_type = "ohlcv_close"
                    price_source = ohlcv_ref.get("ohlcvSource", "")
            # bridge snapshot 가격 최후 fallback
            if current <= 0:
                _bp = _num(row.get("_bridgeCurrentPrice"), 0)
                if _bp > 0:
                    current = _bp
                    price_source_type = "bridge_snapshot"
                    price_source = str(row.get("brokerSource") or row.get("broker") or "bridge")
            current_text = q.get("currentPriceText") or (f"${current:,.2f}" if mk == "us" and current > 0 else f"{round(current):,}원" if current > 0 else "-")
            prev_close = _num(q.get("prevClose"), 0) or _num(_text(v, ["prevClose", "previousClose", "prev_close", "전일종가", "기준가"], ""), 0)
            prev_close_source = q.get("prevCloseSource") or ""
            if prev_close <= 0 and ohlcv_ref:
                prev_close = _num(ohlcv_ref.get("prevClose"), 0)
                prev_close_source = ohlcv_ref.get("prevCloseSource", "")
            if prev_close <= 0:
                ohlcv_prev = _ohlcv_prev_close(mk, sym)
                prev_close = _num(ohlcv_prev.get("prevClose"), 0)
                prev_close_source = ohlcv_prev.get("prevCloseSource", "")
            change_pct = _num(q.get("changePct"), 0)
            if not change_pct and current > 0 and prev_close > 0:
                change_pct = (current - prev_close) / prev_close * 100
            change_value = _num(q.get("change"), 0)
            if not change_value and current > 0 and prev_close > 0:
                change_value = current - prev_close
            change_text = f"{change_value:+,.2f}" if mk == "us" and change_value else (f"{round(change_value):+,}" if change_value else "")
            change_pct_text = f"{change_pct:+.2f}%" if change_pct else ("전일 기준 없음" if current > 0 else "현재가 수집 대기")
            pnl = (current - avg) * qty if current > 0 and avg > 0 else 0
            invested = avg * qty if avg > 0 else 0
            pnl_pct = (pnl / invested * 100) if invested > 0 else 0
            # bridge P&L fallback: 계산값이 0이고 bridge 제공값이 있으면 사용
            if pnl == 0 and row.get("_bridgeProfitLoss"):
                pnl = _num(row.get("_bridgeProfitLoss"), 0)
                pnl_pct = _num(row.get("_bridgeProfitLossRate"), 0)

            asset_type = _mone_asset_type(sym, row.get("name") or _text(v, ["name", "company"], ""), mk, {**v, **row})
            holding_purpose = _mone_holding_purpose(asset_type, {**v, **row})

            # 손절/목표: holdings CSV 값 우선, 없으면 v93_position_cards
            stop_from_v93 = _num(_text(v, ["stopPrice", "stop", "stopText", "손절가"], ""), 0)
            target_from_v93 = _num(_text(v, ["targetPrice", "target", "targetText", "목표가"], ""), 0)
            stop = _num(row.get("stopPriceCsv"), 0) or stop_from_v93
            target = _num(row.get("targetPriceCsv"), 0) or target_from_v93
            line_source = "holdings_csv" if _num(row.get("stopPriceCsv"), 0) > 0 or _num(row.get("targetPriceCsv"), 0) > 0 else ("v93_position_cards" if stop_from_v93 > 0 or target_from_v93 > 0 else "")
            if asset_type == "stock" and current > 0:
                if stop <= 0:
                    stop = round(current * 0.92, 4)
                    line_source = line_source or "computed_stock_risk"
                if target <= 0:
                    target = round(current * 1.12, 4)
                    line_source = line_source or "computed_stock_risk"
            line_fields = _mone_holding_lines(current, avg, stop, target, asset_type, holding_purpose, line_source)
            stop_gap_pct = round((current - stop) / current * 100, 2) if current > 0 and stop > 0 else None
            target_gap_pct = round((target - current) / current * 100, 2) if current > 0 and target > 0 else None
            if current <= 0:
                risk_status = "WATCH"
            elif stop_gap_pct is not None and stop_gap_pct <= 2:
                risk_status = "HIGH"
            elif stop <= 0 or target <= 0 or (stop_gap_pct is not None and stop_gap_pct <= 5) or (target_gap_pct is not None and 0 <= target_gap_pct <= 3):
                risk_status = "WATCH"
            else:
                risk_status = "NORMAL"

            item = dict(row)
            item.update({
                "avgPriceText": f"${avg:,.2f}" if mk == "us" and avg > 0 else f"{round(avg):,}원" if avg > 0 else "-",
                "currentPrice": current,
                "currentPriceText": current_text,
                "prevClose": prev_close if prev_close > 0 else None,
                "prevCloseText": f"${prev_close:,.2f}" if mk == "us" and prev_close > 0 else f"{round(prev_close):,}원" if prev_close > 0 else "",
                "change": change_value if change_value else None,
                "changeText": change_text,
                "changePct": change_pct if current > 0 and prev_close > 0 else None,
                "changePctText": change_pct_text,
                "changePercent": change_pct if current > 0 and prev_close > 0 else None,
                "priceChange": change_value if change_value else None,
                "priceChangeText": change_text,
                "priceChangePercent": change_pct if current > 0 and prev_close > 0 else None,
                "priceChangePercentText": change_pct_text,
                "marketValue": current * qty if current > 0 else 0,
                "marketValueText": f"${current * qty:,.2f}" if mk == "us" and current > 0 else f"{round(current * qty):,}원" if current > 0 else "-",
                "pnl": pnl,
                "pnlText": f"${pnl:,.2f}" if mk == "us" else f"{round(pnl):,}원",
                "pnlPct": pnl_pct,
                "pnlPctText": f"{pnl_pct:+.2f}%",
                "stopPrice": stop,
                "stopText": f"${stop:,.2f}" if mk == "us" and stop > 0 else f"{round(stop):,}원" if stop > 0 else "-",
                "stopGapPct": stop_gap_pct,
                "targetPrice": target,
                "targetText": f"${target:,.2f}" if mk == "us" and target > 0 else f"{round(target):,}원" if target > 0 else "-",
                "targetGapPct": target_gap_pct,
                "assetType": asset_type,
                "instrumentType": asset_type,
                "holdingPurpose": holding_purpose,
                "strategyType": holding_purpose,
                **line_fields,
                "riskLevel": _text(v, ["riskLevel", "risk", "status", "판정"], "NORMAL") or "NORMAL",
                "riskStatus": risk_status,
                "dataStatus": "NORMAL" if price_source_type == "live_quote" else ("PARTIAL" if current > 0 else "NO_PRICE"),
                "source": row["source"],
                "broker": row.get("broker", ""),
                "brokerSource": row.get("brokerSource", ""),
                "enrichSource": "v93_position_cards" if v else "",
                "priceSource": price_source,
                "priceSourceType": price_source_type or ("missing" if current <= 0 else "derived"),
                "ohlcvCount": ohlcv_ref.get("ohlcvCount", ""),
                "ohlcvDate": ohlcv_ref.get("currentPriceDate", ""),
                "prevCloseSource": prev_close_source,
                "quoteTimestamp": q.get("quoteTimestamp") or "",
            })
            # 내부 전달용 bridge 키 제거
            for _bk in ("_bridgeCurrentPrice", "_bridgeProfitLoss", "_bridgeProfitLossRate", "_bridgeEvalAmount"):
                item.pop(_bk, None)
            items.append(item)

        totals_by_market: dict[str, float] = {}
        for item in items:
            mk = "us" if str(item.get("market", "")).lower() == "us" else "kr"
            totals_by_market[mk] = totals_by_market.get(mk, 0.0) + _num(item.get("marketValue"), 0)
        total_all_value = sum(totals_by_market.values())
        for item in items:
            mk = "us" if str(item.get("market", "")).lower() == "us" else "kr"
            market_value = _num(item.get("marketValue"), 0)
            market_total = totals_by_market.get(mk, 0.0)
            weight_pct = (market_value / market_total * 100) if market_total > 0 else None
            all_weight_pct = (market_value / total_all_value * 100) if total_all_value > 0 else None
            item["weightPct"] = round(weight_pct, 2) if weight_pct is not None else None
            item["weightText"] = f"{weight_pct:.1f}%" if weight_pct is not None else "-"
            item["portfolioWeightPct"] = round(all_weight_pct, 2) if all_weight_pct is not None else None
            item["portfolioWeightText"] = f"{all_weight_pct:.1f}%" if all_weight_pct is not None else "-"

        def _money(amount: float, mk: str) -> str:
            if mk == "us":
                return f"${amount:,.2f}"
            return f"{round(amount):,}원"

        def _summary(rows: list[dict]) -> dict:
            by_market: dict[str, dict] = {
                "kr": {"market": "kr", "count": 0, "totalValue": 0.0, "totalPnl": 0.0, "missingPriceCount": 0, "missingStopCount": 0, "missingTargetCount": 0},
                "us": {"market": "us", "count": 0, "totalValue": 0.0, "totalPnl": 0.0, "missingPriceCount": 0, "missingStopCount": 0, "missingTargetCount": 0},
            }
            for it in rows:
                mk = "us" if str(it.get("market", "")).lower() == "us" else "kr"
                bucket = by_market[mk]
                bucket["count"] += 1
                bucket["totalValue"] += _num(it.get("marketValue"), 0)
                bucket["totalPnl"] += _num(it.get("pnl"), 0)
                if _num(it.get("currentPrice"), 0) <= 0:
                    bucket["missingPriceCount"] += 1
                if _num(it.get("stopPrice"), 0) <= 0:
                    bucket["missingStopCount"] += 1
                if _num(it.get("targetPrice"), 0) <= 0:
                    bucket["missingTargetCount"] += 1
            active = [v for v in by_market.values() if v["count"] > 0]
            for bucket in active:
                mk = bucket["market"]
                bucket["totalValueText"] = _money(bucket["totalValue"], mk)
                bucket["totalPnlText"] = _money(bucket["totalPnl"], mk)
            mixed = len(active) > 1
            if mixed:
                total_value_text = " / ".join(v["totalValueText"] for v in active)
                total_pnl_text = " / ".join(v["totalPnlText"] for v in active)
                total_pnl = sum(v["totalPnl"] for v in active)
            elif active:
                total_value_text = active[0]["totalValueText"]
                total_pnl_text = active[0]["totalPnlText"]
                total_pnl = active[0]["totalPnl"]
            else:
                total_value_text = "-"
                total_pnl_text = "-"
                total_pnl = 0.0
            return {
                "count": len(rows),
                "totalValue": sum(v["totalValue"] for v in active),
                "totalValueText": total_value_text,
                "totalPnl": total_pnl,
                "totalPnlText": total_pnl_text,
                "mixedCurrency": mixed,
                "marketBreakdown": active,
                "missingPriceCount": sum(v["missingPriceCount"] for v in active),
                "missingStopCount": sum(v["missingStopCount"] for v in active),
                "missingTargetCount": sum(v["missingTargetCount"] for v in active),
                "riskCount": sum(1 for it in rows if str(it.get("riskStatus", "")).upper() in {"HIGH", "WATCH"}),
            }

        unique = {(i["market"], i["symbol"]) for i in items}
        limit = max(1, min(int(limit or 100), 10000))
        limited_items = items[:limit]
        return {
            "status": "OK",
            "routeVersion": "holdings-authoritative-csv-v3",
            "market": market_key,
            "count": len(limited_items),
            "totalCount": len(items),
            "uniqueCount": len(unique),
            "items": limited_items,
            "summary": _summary(limited_items),
            "updatedAt": _mone_datetime.now().isoformat(),
            "authority": authority,
        }

    def _personal_payload(user_id: str, market: str = "all", limit: int = 100) -> dict:
        rows = _read_personal_holdings(user_id, market)
        payload = _payload(market, limit, rows_override=rows, authority="personal_user_holdings")
        payload["userId"] = user_id
        payload["storage"] = _db.backend_info().get("backend", "user_db")
        return payload

    global app
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in {"/api/holdings-clean", "/api/final/holdings-clean"}
    ]

    @app.get("/api/holdings-clean")
    def mone_authoritative_holdings_clean_v3(
        market: str = _MoneQuery("all"),
        limit: int = _MoneQuery(100),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ) -> dict:
        uid = _sanitize_user_id(x_mone_user)
        if uid:
            return _personal_payload(uid, market, limit)
        return _payload(market, limit)

    @app.get("/api/final/holdings-clean")
    def mone_authoritative_final_holdings_clean_v3(
        market: str = _MoneQuery("all"),
        limit: int = _MoneQuery(100),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ) -> dict:
        uid = _sanitize_user_id(x_mone_user)
        if uid:
            return _personal_payload(uid, market, limit)
        return _payload(market, limit)

try:
    _install_mone_authoritative_holdings_clean_v3()
except Exception as _mone_holdings_override_error:
    print("[MONE] holdings-clean override v3 failed:", _mone_holdings_override_error)


# __MONE_SYMBOLS_EXTRA_MASTER_OVERRIDE_V2__
def _install_mone_symbols_extra_master_v2():
    from pathlib import Path as _MonePath
    import csv as _mone_csv
    import re as _mone_re
    from datetime import datetime as _mone_datetime
    from fastapi import Query as _MoneQuery

    def _root() -> _MonePath:
        return _MonePath(__file__).resolve().parents[3]

    def _read_csv(path: _MonePath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _text(row: dict, keys: list[str], default: str = "") -> str:
        lower = {str(k).lower(): k for k in row.keys()}
        for key in keys:
            if key in row and str(row.get(key, "")).strip():
                return str(row.get(key, "")).strip()
            actual = lower.get(str(key).lower())
            if actual is not None and str(row.get(actual, "")).strip():
                return str(row.get(actual, "")).strip()
        return default

    def _num(value, default=0.0) -> float:
        s = str(value or "").strip().replace(",", "").replace("₩", "").replace("$", "")
        s = _mone_re.sub(r"[^0-9.\-]", "", s)
        try:
            return float(s) if s not in ("", "-", ".", "-.") else float(default)
        except Exception:
            return float(default)

    def _market(value: str, symbol: str = "") -> str:
        v = str(value or "").strip().lower()
        if v in ("kr", "kospi", "kosdaq", "konex", "국장", "한국", "korea"):
            return "kr"
        if v in ("us", "nasdaq", "nyse", "amex", "미장", "미국", "usa"):
            return "us"
        return "kr" if str(symbol).isdigit() else "us"

    def _symbol(value: str, market: str) -> str:
        raw = str(value or "").strip()
        if market == "kr":
            digits = _mone_re.sub(r"\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return raw.upper()

    def _row_symbol(row: dict, fallback_market: str = "") -> tuple[str, str]:
        raw = _text(row, ["symbol", "ticker", "code", "stock_code", "stockCode", "종목코드", "종목", "Symbol", "Ticker"], "")
        guessed_market = _market(_text(row, ["market", "시장", "exchange", "marketType"], fallback_market), raw)
        if not raw and row:
            raw = str(row.get(next(iter(row.keys())), "")).strip()
        sym = _symbol(raw, guessed_market)
        return sym, guessed_market

    def _name(row: dict, symbol: str) -> str:
        return _text(row, ["name", "companyName", "company_name", "corp_name", "종목명", "한글명", "Name"], symbol)

    def _price_index(market: str) -> dict[str, dict]:
        paths = [
            _root() / "data" / "stockapp" / f"kis_current_price_{market}.csv",
            _root() / "reports" / f"kis_current_price_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_realtime_snapshot_{market}.csv",
        ]
        out: dict[str, dict] = {}
        for path in paths:
            for row in _read_csv(path):
                sym, mk = _row_symbol(row, market)
                if not sym or mk != market:
                    continue
                price = _num(_text(row, ["currentPrice", "current_price", "price", "last", "close", "현재가"], ""), 0)
                if price <= 0:
                    price = _num(_text(row, ["currentPriceText", "priceText"], ""), 0)
                if price <= 0:
                    continue
                out[sym] = {
                    "currentPrice": price,
                    "currentPriceText": f"${price:,.2f}" if market == "us" else f"{round(price):,}원",
                    "priceSource": path.name,
                }
        return out

    def _symbol_source_files() -> list[_MonePath]:
        root = _root()
        files: list[_MonePath] = [
            root / "holdings_kr.csv",
            root / "holdings_us.csv",
            root / "watchlist_kr.csv",
            root / "watchlist_us.csv",
            root / "watchlist_kr_growth.csv",
            root / "watchlist_us_growth.csv",
            root / "candidate_universe_kr.csv",
            root / "candidate_universe_us.csv",
            root / "data" / "symbol_master_kr_full.csv",
            root / "data" / "symbol_master_kr_extra.csv",
            root / "data" / "symbol_master_us_full.csv",
            root / "data" / "symbol_master_us_extra.csv",
            root / "data" / "stock_master_kr.csv",
            root / "data" / "stock_master_us.csv",
            root / "data" / "holdings_kr.csv",
            root / "data" / "holdings_us.csv",
            root / "data" / "watchlist_kr.csv",
            root / "data" / "watchlist_us.csv",
            root / "data" / "watchlist_kr_growth.csv",
            root / "data" / "watchlist_us_growth.csv",
            root / "data" / "candidate_universe_kr.csv",
            root / "data" / "candidate_universe_us.csv",
            root / "data" / "stockapp" / "kis_current_price_kr.csv",
            root / "data" / "stockapp" / "kis_current_price_us.csv",
            root / "data" / "stockapp" / "intraday_quote_snapshot_kr.csv",
            root / "data" / "stockapp" / "intraday_quote_snapshot_us.csv",
            root / "data" / "stockapp" / "intraday_realtime_snapshot_kr.csv",
            root / "data" / "stockapp" / "intraday_realtime_snapshot_us.csv",
            root / "reports" / "candidate_universe_kr.csv",
            root / "reports" / "candidate_universe_us.csv",
            root / "reports" / "kis_current_price_kr.csv",
            root / "reports" / "kis_current_price_us.csv",
            root / "reports" / "intraday_quote_snapshot_kr.csv",
            root / "reports" / "intraday_quote_snapshot_us.csv",
        ]
        if (root / "reports").exists():
            files.extend(sorted((root / "reports").glob("v*_symbol_snapshot_kr.csv")))
            files.extend(sorted((root / "reports").glob("v*_symbol_snapshot_us.csv")))
            files.extend(sorted((root / "reports").glob("v*_master_investors_kr.csv")))
            files.extend(sorted((root / "reports").glob("v*_master_investors_us.csv")))
            files.extend(sorted((root / "reports").glob("mone_v36_final_recommendations_kr_*.csv")))
            files.extend(sorted((root / "reports").glob("mone_v36_final_recommendations_us_*.csv")))
        return [p for p in files if p.exists()]

    def _symbols_payload(market: str = "all", q: str = "", limit: int = 10000) -> dict:
        market_key = str(market or "all").lower()
        if market_key not in ("all", "kr", "us"):
            market_key = "all"
        query = str(q or "").strip().lower()
        query_digits = _mone_re.sub(r"\D", "", query)
        price_kr = _price_index("kr") if market_key in ("all", "kr") else {}
        price_us = _price_index("us") if market_key in ("all", "us") else {}

        items_by_key: dict[tuple[str, str], dict] = {}

        for path in _symbol_source_files():
            lower_name = path.name.lower()
            fallback_market = "kr" if "_kr" in lower_name or "kr_" in lower_name else "us" if "_us" in lower_name or "us_" in lower_name else ""
            for row in _read_csv(path):
                sym, mk = _row_symbol(row, fallback_market)
                if not sym or mk not in ("kr", "us"):
                    continue
                if market_key != "all" and mk != market_key:
                    continue
                name = _name(row, sym)
                key = (mk, sym)
                base = items_by_key.get(key, {})
                source = _text(row, ["source"], path.name) or path.name
                items_by_key[key] = {
                    **base,
                    "symbol": sym,
                    "name": name if name and name != sym else base.get("name", name or sym),
                    "market": mk,
                    "source": base.get("source") or source,
                }

        for mk, pidx in [("kr", price_kr), ("us", price_us)]:
            if market_key not in ("all", mk):
                continue
            for sym in pidx.keys():
                key = (mk, sym)
                if key not in items_by_key:
                    items_by_key[key] = {"symbol": sym, "name": sym, "market": mk, "source": "price_snapshot"}

        rows = []
        for item in items_by_key.values():
            mk = item["market"]
            sym = item["symbol"]
            price = (price_kr if mk == "kr" else price_us).get(sym, {})
            row = {**item, **price}
            hay = f"{row.get('symbol','')} {row.get('name','')}".lower()
            sym_digits = _mone_re.sub(r"\D", "", str(row.get("symbol", "")))
            if query:
                if query not in hay and (not query_digits or query_digits not in sym_digits):
                    continue
            if not row.get("currentPrice"):
                row["currentPrice"] = None
            row.setdefault("currentPriceText", "")
            row.setdefault("priceSource", "")
            row["dataStatus"] = "NORMAL" if row.get("currentPrice") else "PRICE_PENDING"
            rows.append(row)

        def _search_rank(row: dict) -> tuple:
            symbol = str(row.get("symbol") or "").lower()
            name = str(row.get("name") or "").lower()
            q = query
            q_digits = query_digits
            exact_symbol = bool(q and (symbol == q or (q_digits and symbol == q_digits.zfill(6))))
            exact_name = bool(q and name == q)
            starts_name = bool(q and name.startswith(q))
            starts_symbol = bool(q and symbol.startswith(q))
            contains_name = bool(q and q in name)
            contains_symbol = bool(q and q in symbol)
            derivative_words = ("우", "2우", "3우", "리츠", "etf", "etn", "스팩", "증권", "인버스", "레버리지")
            derivative_penalty = 1 if any(word in name for word in derivative_words) and not exact_name else 0
            has_price_penalty = 0 if row.get("currentPrice") else 1
            return (
                0 if exact_symbol else 1,
                0 if exact_name else 1,
                0 if starts_name else 1,
                0 if starts_symbol else 1,
                0 if contains_name else 1,
                0 if contains_symbol else 1,
                derivative_penalty,
                has_price_penalty,
                row.get("market", ""),
                symbol,
            )

        rows.sort(key=_search_rank)
        limit = max(1, min(int(limit or 10000), 10000))
        return {
            "status": "OK",
            "routeVersion": "symbols-extra-master-v2",
            "market": market_key,
            "query": q,
            "count": len(rows[:limit]),
            "totalCount": len(rows),
            "items": rows[:limit],
            "updatedAt": _mone_datetime.now().isoformat(),
            "sources": [p.name for p in _symbol_source_files()],
        }

    global app
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in {"/api/symbols", "/api/final/symbols"}
    ]

    @app.get("/api/symbols")
    def mone_symbols_extra_master_v2(
        market: str = _MoneQuery("all"),
        q: str = _MoneQuery(""),
        limit: int = _MoneQuery(10000),
        watchOnly: bool = _MoneQuery(False),
    ) -> dict:
        return _symbols_payload(market, q, limit)

    @app.get("/api/final/symbols")
    def mone_final_symbols_extra_master_v2(
        market: str = _MoneQuery("all"),
        q: str = _MoneQuery(""),
        limit: int = _MoneQuery(10000),
        watchOnly: bool = _MoneQuery(False),
    ) -> dict:
        return _symbols_payload(market, q, limit)

try:
    _install_mone_symbols_extra_master_v2()
except Exception as _mone_symbols_extra_error:
    print("[MONE] symbols extra master override failed:", _mone_symbols_extra_error)


# __MONE_QUOTE_REFRESH_PATCH_V1__
def _install_mone_quote_refresh_routes_v1():
    from datetime import datetime as _MoneQrDatetime
    from pathlib import Path as _MoneQrPath
    import csv as _mone_qr_csv
    import json as _mone_qr_json
    import re as _mone_qr_re
    from fastapi import Body as _MoneQrBody, Query as _MoneQrQuery

    root = _MoneQrPath(__file__).resolve().parents[3]
    stockapp = root / "data" / "stockapp"
    reports = root / "reports"
    fields = [
        "symbol", "market", "ok", "currentPrice", "current_price", "last_price", "priceTime",
        "priceSource", "source", "priceSourceType", "priceSourceFile", "priceSourceDate",
        "kis_quote_success", "quote_available", "error", "updated_at",
    ]

    def _read_csv(path: _MoneQrPath) -> list[dict]:
        if not path.exists() or path.stat().st_size <= 0:
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_qr_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _write_csv(path: _MoneQrPath, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = _mone_qr_csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    def _market(value: str, symbol: str = "") -> str:
        raw = str(value or "").strip().lower()
        if raw == "us":
            return "us"
        if raw == "kr":
            return "kr"
        return "kr" if _mone_qr_re.fullmatch(r"\d{1,6}", str(symbol or "")) else "us"

    def _symbol(value: str, market: str) -> str:
        raw = str(value or "").strip().upper()
        if market == "kr":
            digits = _mone_qr_re.sub(r"\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return _mone_qr_re.sub(r"[^A-Z0-9.\-]", "", raw)

    def _add_target(market: str, symbol: str, name: str, reason: str) -> None:
        path = stockapp / f"kis_collection_targets_{market}.csv"
        rows = _read_csv(path)
        keyed = {}
        for row in rows:
            sym = _symbol(row.get("symbol", ""), market)
            if sym:
                keyed[sym] = {
                    "market": market,
                    "symbol": sym,
                    "name": row.get("name") or sym,
                    "reason": row.get("reason") or "existing",
                    "updatedAt": row.get("updatedAt") or "",
                }
        keyed[symbol] = {
            "market": market,
            "symbol": symbol,
            "name": name or symbol,
            "reason": reason,
            "updatedAt": _MoneQrDatetime.now().isoformat(timespec="seconds"),
        }
        _write_csv(path, ["market", "symbol", "name", "reason", "updatedAt"], sorted(keyed.values(), key=lambda row: row["symbol"]))

    def _snapshot_row(market: str, symbol: str, quote: dict) -> dict:
        price = quote.get("price") or quote.get("currentPrice") or quote.get("current_price") or quote.get("last_price") or ""
        now = _MoneQrDatetime.now().strftime("%Y-%m-%d %H:%M:%S KST")
        source = quote.get("priceSource") or quote.get("source") or ("KIS 현재가" if market == "kr" else "KIS/Finnhub 현재가")
        return {
            "symbol": symbol,
            "market": market,
            "ok": "true" if quote.get("ok") else "false",
            "currentPrice": price,
            "current_price": price,
            "last_price": price,
            "priceTime": quote.get("priceTime") or now,
            "priceSource": source,
            "source": source,
            "priceSourceType": "manual_refresh",
            "priceSourceFile": f"data/stockapp/kis_current_price_{market}.csv",
            "priceSourceDate": quote.get("priceSourceDate") or now,
            "kis_quote_success": "true" if quote.get("ok") else "false",
            "quote_available": "true" if quote.get("ok") else "false",
            "error": quote.get("error") or "",
            "updated_at": now,
        }

    def _upsert_snapshot(market: str, row: dict) -> None:
        for path in [
            stockapp / f"kis_current_price_{market}.csv",
            stockapp / f"intraday_realtime_snapshot_{market}.csv",
            stockapp / f"intraday_quote_snapshot_{market}.csv",
            reports / f"kis_current_price_{market}.csv",
            reports / f"intraday_realtime_snapshot_{market}.csv",
            reports / f"intraday_quote_snapshot_{market}.csv",
        ]:
            rows = _read_csv(path)
            keyed = {str(existing.get("symbol") or "").upper(): existing for existing in rows}
            keyed[str(row["symbol"]).upper()] = row
            _write_csv(path, fields, sorted(keyed.values(), key=lambda item: str(item.get("symbol") or "")))

    def _refresh_one(payload: dict) -> dict:
        market = _market(payload.get("market", ""), payload.get("symbol", ""))
        symbol = _symbol(payload.get("symbol", ""), market)
        name = str(payload.get("name") or symbol).strip()
        if not symbol:
            return {"status": "ERROR", "error": "symbol is empty", "dataStatus": "PRICE_PENDING"}
        _add_target(market, symbol, name, "manual_refresh_one")
        quote = quotes._fetch_quote(symbol, market)
        if quote.get("ok"):
            row = _snapshot_row(market, symbol, quote)
            _upsert_snapshot(market, row)
            status = "OK"
            data_status = "NORMAL"
        else:
            status = "ERROR"
            data_status = "PRICE_PENDING"
        return {
            "status": status,
            "market": market,
            "symbol": symbol,
            "name": name,
            "dataStatus": data_status,
            "quote": quote,
            "error": quote.get("error", ""),
            "updatedAt": _MoneQrDatetime.now().isoformat(),
        }

    def _targets(market: str) -> list[dict]:
        paths = [
            root / f"holdings_{market}.csv",
            root / "data" / f"holdings_{market}.csv",
            root / f"watchlist_{market}.csv",
            root / "data" / f"watchlist_{market}.csv",
            stockapp / f"kis_collection_targets_{market}.csv",
            stockapp / f"price_collection_universe_{market}.csv",
        ]
        keyed = {}
        for path in paths:
            for row in _read_csv(path):
                sym = _symbol(row.get("symbol") or row.get("ticker") or row.get("code") or row.get("종목코드") or "", market)
                if sym and sym not in keyed:
                    keyed[sym] = {"market": market, "symbol": sym, "name": row.get("name") or row.get("종목명") or sym}
        return list(keyed.values())

    def _write_batch_status(payload: dict) -> None:
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "quote_refresh_batch_status.json").write_text(_mone_qr_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    global app
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/quotes/refresh-one", "/api/quotes/refresh-targets"}
    ]

    @app.post("/api/quotes/refresh-one")
    def mone_quote_refresh_one(payload: dict = _MoneQrBody(...)) -> dict:
        return _refresh_one(payload)

    @app.post("/api/quotes/refresh-targets")
    def mone_quote_refresh_targets(
        payload: dict = _MoneQrBody(default={}),
        market: str = _MoneQrQuery("all"),
        limit: int = _MoneQrQuery(20),
        max_symbols: int | None = _MoneQrQuery(None),
    ) -> dict:
        body_market = str((payload or {}).get("market") or market or "all").lower()
        markets = ["kr", "us"] if body_market == "all" else [_market(body_market)]
        requested_limit = (payload or {}).get("max_symbols") or (payload or {}).get("limit") or max_symbols or limit or 20
        max_count = max(1, min(int(requested_limit), 50))
        refreshed = []
        failed = []
        pending = 0
        for mk in markets:
            for target in _targets(mk)[:max_count]:
                result = _refresh_one(target)
                if result.get("status") == "OK":
                    refreshed.append(result)
                else:
                    failed.append(result)
            pending += max(0, len(_targets(mk)) - max_count)
        out = {
            "status": "OK" if refreshed else ("PARTIAL" if failed else "NO_DATA"),
            "market": body_market,
            "requestedLimit": max_count,
            "successCount": len(refreshed),
            "failureCount": len(failed),
            "pendingCount": pending,
            "lastRefreshAt": _MoneQrDatetime.now().isoformat(),
            "items": refreshed[:20],
            "failedItems": failed[:20],
        }
        _write_batch_status(out)
        return out

try:
    _install_mone_quote_refresh_routes_v1()
except Exception as _mone_quote_refresh_error:
    print("[MONE] quote refresh patch failed:", _mone_quote_refresh_error)


# __MONE_CLOSE_VALIDATION_ROUTES_V1__
def _install_mone_close_validation_routes_v1():
    from pathlib import Path as _MoneClosePath
    import csv as _mone_close_csv
    import json as _mone_close_json
    import re as _mone_close_re
    from collections import Counter as _MoneCloseCounter
    from datetime import datetime as _MoneCloseDateTime, timedelta as _MoneCloseTimedelta
    from fastapi import Query as _MoneCloseQuery

    root = _MoneClosePath(__file__).resolve().parents[3]
    reports = root / "reports"
    ohlcv_dir = root / "data" / "market" / "ohlcv"

    def _read_csv(path: _MoneClosePath) -> list[dict]:
        if not path.exists() or path.stat().st_size == 0:
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_close_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _num(value):
        try:
            text = str(value if value is not None else "").replace(",", "").replace("%", "").strip()
            text = _mone_close_re.sub(r"[^0-9.\-]", "", text)
            return float(text) if text not in {"", "-", "None", "nan", "NaN"} else None
        except Exception:
            return None

    def _truth(value) -> bool:
        return str(value if value is not None else "").strip().lower() in {
            "1", "true", "yes", "y", "executed", "filled", "hit", "체결", "泥닿껐"
        }

    def _first(row: dict, keys: tuple[str, ...], default: str = ""):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return default

    def _parse_day(value) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        if _mone_close_re.fullmatch(r"\d{8}", text[:8]):
            return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
        match = _mone_close_re.search(r"(20\d{2})[-/.]?(\d{2})[-/.]?(\d{2})", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return ""

    def _row_recommendation_date(row: dict, fallback: str) -> str:
        for key in ("recommendationDate", "generatedAt", "date", "asOfDate", "createdAt", "validationDate"):
            parsed = _parse_day(row.get(key))
            if parsed:
                return parsed
        return _parse_day(fallback)

    def _ohlcv_path(market: str, symbol: str) -> _MoneClosePath | None:
        raw = str(symbol or "").strip().upper()
        if not raw:
            return None
        candidates: list[_MoneClosePath] = []
        if market == "kr":
            digits = _mone_close_re.sub(r"[^0-9]", "", raw)
            if digits:
                candidates.append(ohlcv_dir / f"kr_{digits.zfill(6)[-6:]}_daily.csv")
                candidates.append(ohlcv_dir / f"kr_{digits}_daily.csv")
        else:
            candidates.append(ohlcv_dir / f"us_{raw}_daily.csv")
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def _read_ohlcv_window(market: str, symbol: str, start_day: str, horizon: str) -> tuple[list[dict], str, str]:
        path = _ohlcv_path(market, symbol)
        if not path:
            return [], "", ""
        rows = _read_csv(path)
        if not rows:
            return [], path.name, ""
        parsed_rows: list[tuple[str, dict]] = []
        for item in rows:
            day = _parse_day(item.get("date") or item.get("Date") or item.get("timestamp"))
            if day:
                parsed_rows.append((day, item))
        latest_day = max((day for day, _ in parsed_rows), default="")
        if not start_day:
            return ([parsed_rows[-1][1]] if parsed_rows else rows[-1:]), path.name, latest_day
        try:
            start = _MoneCloseDateTime.strptime(start_day[:10], "%Y-%m-%d").date()
        except Exception:
            return ([parsed_rows[-1][1]] if parsed_rows else rows[-1:]), path.name, latest_day
        days = {"short": 5, "swing": 20, "mid": 60}.get(str(horizon).lower(), 20)
        end = start + _MoneCloseTimedelta(days=days)
        window = []
        for day, item in parsed_rows:
            try:
                current = _MoneCloseDateTime.strptime(day[:10], "%Y-%m-%d").date()
            except Exception:
                continue
            if start < current <= end:
                window.append(item)
        return window, path.name, latest_day

    def _market_latest_ohlcv_date(market: str) -> str:
        latest = ""
        for path in ohlcv_dir.glob(f"{market}_*_daily.csv"):
            rows = _read_csv(path)
            if rows:
                latest = max(latest, _parse_day(rows[-1].get("date") or rows[-1].get("Date")))
        return latest

    def _enrich_trade(row: dict, base: dict, date_text: str, market: str, horizon: str) -> dict:
        recommendation_date = _row_recommendation_date(row, date_text)
        symbol = str(base.get("symbol") or "").strip()
        entry = _num(_first(row, ("entryPrice", "entry", "expectedEntryPrice")))
        target = _num(_first(row, ("targetPrice", "target")))
        stop = _num(_first(row, ("stopPrice", "stop")))
        actual_low = _num(_first(row, ("actualLow", "low", "validationLow")))
        actual_high = _num(_first(row, ("actualHigh", "high", "validationHigh")))
        actual_close = _num(_first(row, ("actualClose", "close", "validationClose")))
        ohlcv_source = str(_first(row, ("ohlcvSource", "sourceFile"), ""))
        latest_ohlcv_date = ""
        holding_days = _num(_first(row, ("holdingDays", "holding_days")))
        pending_status = ""
        pending_reason = ""

        if actual_low is None or actual_high is None or actual_close is None or not ohlcv_source or holding_days is None:
            window, source, source_latest_day = _read_ohlcv_window(market, symbol, recommendation_date, horizon)
            if source:
                ohlcv_source = ohlcv_source or source
            if source_latest_day:
                latest_ohlcv_date = source_latest_day
            if source and recommendation_date and source_latest_day and source_latest_day <= recommendation_date and not window:
                pending_status = "PENDING_NEXT_OHLCV"
                pending_reason = (
                    "No OHLCV bars after recommendationDate yet. "
                    f"latestOhlcvDate={source_latest_day}, recommendationDate={recommendation_date}"
                )
            lows = [_num(item.get("low") or item.get("Low")) for item in window]
            highs = [_num(item.get("high") or item.get("High")) for item in window]
            closes = [_num(item.get("close") or item.get("Close")) for item in window]
            days = [_parse_day(item.get("date") or item.get("Date")) for item in window]
            lows = [value for value in lows if value is not None]
            highs = [value for value in highs if value is not None]
            closes = [value for value in closes if value is not None]
            days = [value for value in days if value]
            if lows:
                actual_low = min(lows)
            if highs:
                actual_high = max(highs)
            if closes:
                actual_close = closes[-1]
            if days:
                holding_days = len(set(days))
                latest_ohlcv_date = max(days)

        has_range = actual_low is not None and actual_high is not None
        filled = bool(has_range and entry is not None and actual_low <= entry <= actual_high)
        target_hit = bool(filled and target is not None and actual_high is not None and actual_high >= target)
        stop_hit = bool(filled and stop is not None and actual_low is not None and actual_low <= stop)
        if pending_status:
            data_status = pending_status
            result_status = pending_status
            reason = pending_reason
        elif not ohlcv_source and not has_range:
            data_status = "NO_OHLCV"
            result_status = "PENDING_OHLCV"
            reason = "OHLCV file is missing, so touch validation is pending"
        elif not has_range:
            data_status = "PENDING_OHLCV"
            result_status = "PENDING_OHLCV"
            reason = "OHLCV range is unavailable, so touch validation is pending"
        elif target_hit and stop_hit:
            data_status = str(base.get("dataStatus") or row.get("dataStatus") or "NORMAL")
            result_status = "STOP_FIRST_ASSUMED"
            reason = "Target and stop were both touched in the validation window"
        elif stop_hit:
            data_status = str(base.get("dataStatus") or row.get("dataStatus") or "NORMAL")
            result_status = "STOP_HIT"
            reason = str(base.get("reason") or row.get("failure_reason") or "")
        elif target_hit:
            data_status = str(base.get("dataStatus") or row.get("dataStatus") or "NORMAL")
            result_status = "TARGET_HIT"
            reason = str(base.get("reason") or "")
        elif filled:
            data_status = str(base.get("dataStatus") or row.get("dataStatus") or "NORMAL")
            result_status = "FILLED_OPEN"
            reason = str(base.get("reason") or "")
        else:
            data_status = str(base.get("dataStatus") or row.get("dataStatus") or "NORMAL")
            result_status = "NOT_FILLED"
            reason = str(base.get("reason") or "Entry was not touched in the validation window")

        return {
            **base,
            "recommendationDate": recommendation_date,
            "generatedAt": row.get("generatedAt") or base.get("generatedAt") or "",
            "filled": filled,
            "targetHit": target_hit,
            "stopHit": stop_hit,
            "resultStatus": result_status,
            "actualLow": actual_low,
            "actualHigh": actual_high,
            "actualClose": actual_close,
            "holdingDays": int(holding_days) if holding_days is not None else None,
            "priceSource": row.get("priceSource") or base.get("priceSource") or "",
            "ohlcvSource": ohlcv_source,
            "dataStatus": data_status,
            "is_executed": filled,
            "is_win": target_hit,
            "is_loss": stop_hit,
            "virtual_return_pct": _num(base.get("returnPct")) or 0,
            "failure_reason": reason,
            "reason": reason,
            "latestOhlcvDate": latest_ohlcv_date,
        }

    def _validation_files(market: str, mode: str, horizon: str) -> list[_MoneClosePath]:
        files = []
        patterns = [
            f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}_*.csv",
            f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv",
        ]
        for pattern in patterns:
            files.extend(sorted(reports.glob(pattern), key=lambda p: p.name, reverse=True))
        return list(dict.fromkeys(files))

    def _date_from_file(path: _MoneClosePath) -> str:
        m = _mone_close_re.search(r"(20\d{6})", path.name)
        if not m:
            return ""
        raw = m.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"

    def _latest_validation(market: str, mode: str, horizon: str) -> tuple[_MoneClosePath | None, list[dict]]:
        for path in _validation_files(market, mode, horizon):
            rows = _read_csv(path)
            if rows:
                return path, rows
        return None, []

    def _normalize_trade(row: dict, date_text: str, market: str, mode: str, horizon: str) -> dict:
        base = {
            **row,
            "date": row.get("date") or date_text,
            "symbol": row.get("symbol") or row.get("ticker") or "",
            "name": row.get("name") or row.get("companyName") or row.get("symbol") or "",
            "market": row.get("market") or market,
            "mode": row.get("mode") or mode,
            "horizon": row.get("horizon") or horizon,
            "executed": row.get("executed") if row.get("executed") not in (None, "") else row.get("체결", "false"),
            "entryPrice": row.get("entryPrice") or row.get("entry") or "",
            "entryText": row.get("entryText") or "",
            "exitPrice": row.get("exitPrice") or "",
            "exitText": row.get("exitText") or "",
            "returnPct": row.get("returnPct") or row.get("수익률") or "",
            "returnPctText": row.get("returnPctText") or "",
            "result": row.get("result") or row.get("결과") or "검증 대기",
            "dataStatus": row.get("dataStatus") or "NORMAL",
            "reason": row.get("reason") or "",
            "source": row.get("source") or "",
        }
        return _enrich_trade(row, base, date_text, market, horizon)

    def _summary_payload(market: str, mode: str, horizon: str) -> dict:
        path, rows = _latest_validation(market, mode, horizon)
        if not path:
            status_path = reports / "kr_close_validation_status.json" if market == "kr" else reports / "us_close_validation_status.json"
            status = {}
            if status_path.exists():
                try:
                    status = _mone_close_json.loads(status_path.read_text(encoding="utf-8"))
                except Exception:
                    status = {}
            return {
                "status": "OK",
                "market": market,
                "mode": mode,
                "horizon": horizon,
                "todayStatus": "NO_DATA",
                "todayDate": "",
                "todayMessage": "오늘 장마감 원본 없음",
                "latestDate": "",
                "recommendationDate": "",
                "generatedAt": "",
                "checkedCount": 0,
                "virtualFilledCount": 0,
                "fillRate": 0,
                "avgReturnPct": 0,
                "cumulativeReturnPct": 0,
                "targetHitRate": 0,
                "stopHitRate": 0,
                "pendingCount": 0,
                "pendingNextOhlcvCount": 0,
                "failedCount": 0,
                "failedReasonTop": [],
                "dataStatus": "NO_DATA",
                "sourceFile": "",
                "latestOhlcvDate": _market_latest_ohlcv_date(market),
                "updatedAt": _MoneCloseDateTime.now(session.KST).isoformat(),
                "total_trades": 0,
                "executed_trades": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0,
                "profit_loss_ratio": 0,
                "total_return_pct": 0,
                "count": 0,
                "items": [],
                "closeValidationStatus": status,
            }
        date_text = _date_from_file(path) or str(rows[0].get("date") or "")
        normalized = [_normalize_trade(row, date_text, market, mode, horizon) for row in rows]
        recommendation_date = (
            date_text
            or str((normalized[0] if normalized else {}).get("recommendationDate") or "")
            or _parse_day(rows[0].get("generatedAt") if rows else "")
        )
        executed = [row for row in normalized if str(row.get("executed", "")).lower() in {"true", "1", "yes", "체결"}]
        executed = [row for row in normalized if bool(row.get("filled"))]
        returns = [_num(row.get("returnPct")) for row in executed]
        returns = [r for r in returns if r is not None]
        win_count = sum(1 for r in returns if r > 0)
        target_count = sum(1 for row in normalized if bool(row.get("targetHit")))
        stop_count = sum(1 for row in normalized if bool(row.get("stopHit")))
        pending_count = sum(1 for row in normalized if str(row.get("dataStatus", "")).upper() in {"PENDING_NEXT_OHLCV", "PENDING_OHLCV", "NO_OHLCV", "DATA_PENDING"})
        next_ohlcv_pending_count = sum(1 for row in normalized if str(row.get("dataStatus", "")).upper() == "PENDING_NEXT_OHLCV")
        failed_rows = [
            row for row in normalized
            if str(row.get("resultStatus", "")).upper() in {"NOT_FILLED", "STOP_FIRST_ASSUMED", "STOP_HIT"}
        ]
        failed_reasons = _MoneCloseCounter(
            str(row.get("failure_reason") or row.get("reason") or row.get("resultStatus") or "unknown")[:80]
            for row in failed_rows
        )
        avg_return = sum(returns) / len(returns) if returns else 0.0
        cumulative_return = _portfolio_return_pct(returns)
        avg_win = sum(r for r in returns if r > 0) / win_count if win_count else 0.0
        loss_values = [abs(r) for r in returns if r < 0]
        avg_loss = sum(loss_values) / len(loss_values) if loss_values else 0.0
        data_status = "OK"
        if pending_count:
            data_status = "PARTIAL"
        if normalized and next_ohlcv_pending_count == len(normalized):
            data_status = "PENDING_NEXT_OHLCV"
        elif normalized and pending_count == len(normalized):
            data_status = "PENDING_OHLCV"
        latest_ohlcv = max([str(row.get("latestOhlcvDate") or "") for row in normalized] + [_market_latest_ohlcv_date(market)])
        return {
            "status": "OK",
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "todayStatus": "NORMAL" if rows else "NO_DATA",
            "todayDate": date_text,
            "todayMessage": "장마감 검증 파일 연결됨" if rows else "오늘 장마감 원본 없음",
            "latestDate": date_text,
            "latestSource": path.name,
            "recommendationDate": recommendation_date,
            "generatedAt": rows[0].get("generatedAt") if rows else "",
            "checkedCount": len(normalized),
            "virtualFilledCount": len(executed),
            "fillRate": round(len(executed) / len(normalized) * 100, 2) if normalized else 0,
            "avgReturnPct": round(avg_return, 4),
            "cumulativeReturnPct": round(cumulative_return, 4),
            "targetHitRate": round(target_count / len(executed) * 100, 2) if executed else 0,
            "stopHitRate": round(stop_count / len(executed) * 100, 2) if executed else 0,
            "pendingCount": pending_count,
            "pendingNextOhlcvCount": next_ohlcv_pending_count,
            "failedCount": len(failed_rows),
            "failedReasonTop": [{"reason": reason, "count": count} for reason, count in failed_reasons.most_common(5)],
            "dataStatus": data_status,
            "sourceFile": path.name,
            "latestOhlcvDate": latest_ohlcv,
            "updatedAt": _MoneCloseDateTime.now(session.KST).isoformat(),
            "total_trades": len(normalized),
            "executed_trades": len(executed),
            "win_count": win_count,
            "loss_count": len(loss_values),
            "win_rate": round((win_count / len(returns)) * 100, 2) if returns else 0,
            "profit_loss_ratio": round(avg_win / avg_loss, 2) if avg_loss > 0 else (round(avg_win, 2) if avg_win else 0),
            "total_return_pct": round(sum(returns), 4),
            "latestRecommendations": len(normalized),
            "latestExecutedTrades": len(executed),
            "latestUnexecutedCount": max(0, len(normalized) - len(executed)),
            "latestExecutionRate": round(len(executed) / len(normalized) * 100, 2) if normalized else 0,
            "latestWinRate": round((win_count / len(returns)) * 100, 2) if returns else 0,
            "latestAverageReturnPct": round(avg_return, 4),
            "latestCumulativeReturnPct": round(cumulative_return, 4),
            "rawReturnSumPct": round(sum(returns), 4),
            "items": normalized[:100],
            "count": len(normalized),
        }

    global app
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/backtest/trades", "/api/backtest/summary", "/api/final/backtest-summary"}
    ]

    @app.get("/api/backtest/trades")
    def mone_close_backtest_trades(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
        limit: int = _MoneCloseQuery(250, ge=1, le=1000),
    ) -> dict:
        payload = _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)
        return {**payload, "items": payload.get("items", [])[:limit], "count": min(len(payload.get("items", [])), limit)}

    @app.get("/api/backtest/summary")
    def mone_close_backtest_summary(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
    ) -> dict:
        return _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)

    @app.get("/api/final/backtest-summary")
    def mone_close_final_backtest_summary(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
    ) -> dict:
        return _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)

    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") != "/api/final/operation-summary"
    ]

    @app.get("/api/final/operation-summary")
    def mone_operation_summary(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
    ) -> dict:
        normalized_market = "us" if str(market).lower() == "us" else "kr"

        def safe_section(name: str, loader):
            try:
                payload = loader()
                if isinstance(payload, dict):
                    return payload
                return {"status": "ERROR", "section": name, "error": "non-dict payload"}
            except Exception as exc:
                return {"status": "ERROR", "section": name, "error": str(exc)[:240]}

        quality = safe_section("dataQuality", lambda: data_quality.data_quality(normalized_market, mode="quick"))
        backtest_summary = safe_section("backtestSummary", lambda: _summary_payload(normalized_market, mode, horizon))
        pipeline_summary = safe_section("pipelineSummary", lambda: data_quality.admin_pipeline(normalized_market))
        active_gaps = []
        for source in (quality, pipeline_summary):
            values = source.get("activeGaps") or source.get("rootCauses") or source.get("warnings") or []
            if isinstance(values, list):
                active_gaps.extend([str(value) for value in values if value])
        next_actions = []
        for source in (quality, pipeline_summary):
            values = source.get("nextActions") or []
            if isinstance(values, list):
                next_actions.extend([str(value) for value in values if value])
        session_state = session.get_price_session(normalized_market)
        recommendation_basis_date = (
            pipeline_summary.get("recommendationLatestDate")
            or quality.get("latestDataDate")
            or backtest_summary.get("recommendationDate")
            or backtest_summary.get("latestDate")
        )
        current_price_basis_date = (
            pipeline_summary.get("snapshotLatestDate")
            or quality.get("currentPriceLatestDate")
            or quality.get("latestDataDate")
        )
        ohlcv_basis_date = (
            pipeline_summary.get("ohlcvLatestDate")
            or backtest_summary.get("latestOhlcvDate")
        )
        basis_dates = {
            "recommendation": recommendation_basis_date,
            "currentPrice": current_price_basis_date,
            "ohlcv": ohlcv_basis_date,
            "validation": backtest_summary.get("recommendationDate") or backtest_summary.get("latestDate"),
        }
        comparable_basis_dates = [str(value)[:10] for value in (recommendation_basis_date, current_price_basis_date, ohlcv_basis_date) if value]
        unique_basis_dates = sorted(set(comparable_basis_dates))
        basis_aligned = len(unique_basis_dates) <= 1
        if basis_aligned:
            basis_alignment_status = "ALIGNED"
            basis_alignment_message = f"All primary bases are {unique_basis_dates[0]}." if unique_basis_dates else "Basis dates unavailable."
        else:
            basis_alignment_status = "MIXED_BASIS"
            basis_alignment_message = (
                f"Recommendation/current/OHLCV bases differ: "
                f"recommendation={recommendation_basis_date or '-'}, "
                f"current={current_price_basis_date or '-'}, "
                f"ohlcv={ohlcv_basis_date or '-'}. "
                "This can be normal intraday before the daily OHLCV close is collected."
            )
            active_gaps.append("basis_dates_mixed")
            next_actions.append("After market close, refresh OHLCV and regenerate validation to fully align basis dates.")
        return {
            "status": "OK",
            "market": normalized_market,
            "autoResolvedMarket": normalized_market,
            "sessionLabel": session_state.get("label") or session_state.get("phase") or "",
            "reviewMode": bool(quality.get("reviewMode")),
            "dataStatus": quality.get("dataStatus") or pipeline_summary.get("dataStatus") or "UNKNOWN",
            "priceDataStatus": quality.get("priceDataStatus") or pipeline_summary.get("currentPriceSourceStatus") or "UNKNOWN",
            "recommendationStatus": quality.get("recommendationStatus") or pipeline_summary.get("recommendationStatus") or "UNKNOWN",
            "recommendationDate": recommendation_basis_date,
            "generatedAt": backtest_summary.get("generatedAt") or quality.get("latestFileModifiedAt") or "",
            "currentPriceBasisDate": current_price_basis_date,
            "ohlcvLatestDate": ohlcv_basis_date,
            "snapshotLatestDate": pipeline_summary.get("snapshotLatestDate"),
            "basisDates": basis_dates,
            "basisAligned": basis_aligned,
            "basisAlignmentStatus": basis_alignment_status,
            "basisAlignmentMessage": basis_alignment_message,
            "activeGaps": list(dict.fromkeys(active_gaps))[:8],
            "nextActions": list(dict.fromkeys(next_actions))[:8],
            "backtestSummary": backtest_summary,
            "pipelineSummary": pipeline_summary,
            "updatedAt": _MoneCloseDateTime.now(session.KST).isoformat(),
        }

try:
    _install_mone_close_validation_routes_v1()
except Exception as _mone_close_validation_error:
    print("[MONE] close validation route patch failed:", _mone_close_validation_error)


# ════════════════════════════════════════════════════════════════════════
# MONE v10.2 — 누락 API 엔드포인트 일괄 구현 (2026-06-04)
# 프론트엔드에서 호출하지만 백엔드에 없던 28개 엔드포인트 추가
# ════════════════════════════════════════════════════════════════════════

import csv as _csv
import json as _json
import os as _os
import re as _re
import uuid as _uuid
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Any as _Any

_REPO = data.REPO_ROOT
_DATA = _REPO / "data"
_REPORTS = _REPO / "reports"
_OHLCV_DIR = _DATA / "market" / "ohlcv"
_JOURNAL_FILE = _DATA / "journal.csv"
_JOURNAL_COLS = ["id", "date", "market", "symbol", "name", "action", "price", "qty", "memo", "review", "result", "returnPct", "tags", "createdAt"]


def _read_csv_safe(path: _Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in _csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv_safe_v2(path: _Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def _safe_float_v2(v: _Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip()) if v not in (None, "", "nan") else default
    except Exception:
        return default


def _normalize_sym(sym: _Any, market: str = "kr") -> str:
    s = str(sym or "").strip()
    if market == "kr":
        return _re.sub(r"[^0-9]", "", s).zfill(6)[-6:] if _re.search(r"\d", s) else s
    return s.upper()


import re as _uid_re
from fastapi import Header as _Header

def _sanitize_uid(raw: str) -> str:
    return _uid_re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))[:64]

def _user_holdings_dir(user_id: str) -> "Path":
    uid = _sanitize_uid(user_id)
    if not uid:
        return _REPO
    d = _REPO / "data" / "users" / uid
    d.mkdir(parents=True, exist_ok=True)
    return d

def _holdings_path(mk: str, user_id: str = "") -> "Path":
    return _user_holdings_dir(user_id) / f"holdings_{mk}.csv"

# ── 1. holdings-edit ──────────────────────────────────────────────────

@app.get("/api/holdings-edit")
def api_holdings_edit(
    market: str = Query("all"),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    uid = _sanitize_uid(x_mone_user)

    # uid가 있으면 사용자별 저장소만 사용한다. 공용 CSV는 개인 모바일 화면에 노출하지 않는다.
    if uid:
        items = _db.get_holdings(uid, market)
        return {"status": "OK", "count": len(items), "items": items, "userId": uid, "storage": "sqlite"}

    # uid 없으면 기존 CSV (관리자 모드)
    items_csv: list[dict] = []
    for mk in (["kr", "us"] if market == "all" else [market]):
        path = _REPO / f"holdings_{mk}.csv"
        for row in _read_csv_safe(path):
            sym = str(row.get("symbol", "")).strip()
            if not sym:
                continue
            items_csv.append({"market": mk, "symbol": sym,
                "name": str(row.get("name", sym)).strip(),
                "quantity": str(row.get("quantity", "0")).strip(),
                "avgPrice": str(row.get("avgPrice", "0")).strip(),
                "stopPrice": str(row.get("stopPrice", "")).strip(),
                "targetPrice": str(row.get("targetPrice", "")).strip()})
    return {"status": "OK", "count": len(items_csv), "items": items_csv, "userId": "default", "storage": "csv"}


# ── holdings-edit GET 중복 라우트 정리 ────────────────────────────────────
# stabilizer가 먼저 /api/holdings-edit GET을 등록(first-match 승리)하므로
# 우리 핸들러(마지막 등록, stopPrice/targetPrice 포함)만 남기고 나머지 제거
_HDEDIT_DUPE_PATH = "/api/holdings-edit"
_hde_all = [r for r in app.router.routes
            if isinstance(r, _APIR) and getattr(r, "path", "") == _HDEDIT_DUPE_PATH
            and "GET" in (getattr(r, "methods", None) or set())]
if len(_hde_all) > 1:
    for _r in _hde_all[:-1]:
        try:
            app.router.routes.remove(_r)
        except ValueError:
            pass


@app.post("/api/holdings-edit/save")
def api_holdings_edit_save(
    payload: dict = Body(...),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    uid = _sanitize_uid(x_mone_user)
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "ERROR", "error": "items must be a list"}

    # uid가 있으면 SQLite에 저장
    if uid:
        saved = _db.save_holdings(uid, items)
        return {"status": "OK", "saved": saved, "userId": uid, "storage": "sqlite"}

    # uid 없으면 CSV (관리자 모드)
    by_market: dict[str, list] = {"kr": [], "us": []}
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        by_market[mk].append(item)
    cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
    for mk, rows in by_market.items():
        path = _REPO / f"holdings_{mk}.csv"
        norm_rows = []
        for r in rows:
            sym = _normalize_sym(r.get("symbol", ""), mk)
            if not sym:
                continue
            norm_rows.append({"symbol": sym, "name": str(r.get("name", sym)).strip(), "market": mk,
                "quantity": str(r.get("quantity", "0")).strip(), "avgPrice": str(r.get("avgPrice", "0")).strip(),
                "stopPrice": str(r.get("stopPrice", "")).strip(), "targetPrice": str(r.get("targetPrice", "")).strip()})
        _write_csv_safe_v2(path, norm_rows, cols)
        data_copy = _REPO / "data" / f"holdings_{mk}.csv"
        if data_copy.exists():
            _write_csv_safe_v2(data_copy, norm_rows, cols)
    return {"status": "OK", "saved": len(items), "userId": "default", "storage": "csv"}


# ── holdings-edit/save POST 중복 라우트 정리 ──────────────────────────────
# stabilizer의 _save_edit_rows가 stopPrice/targetPrice를 누락하므로 우리 핸들러만 유지
_HDESAVE_DUPE_PATH = "/api/holdings-edit/save"
_hds_all = [r for r in app.router.routes
            if isinstance(r, _APIR) and getattr(r, "path", "") == _HDESAVE_DUPE_PATH
            and "POST" in (getattr(r, "methods", None) or set())]
if len(_hds_all) > 1:
    for _r in _hds_all[:-1]:
        try:
            app.router.routes.remove(_r)
        except ValueError:
            pass


# ── KIS 보유종목 가져오기 ───────────────────────────────────────────────

@app.get("/api/kis/holdings")
def api_kis_holdings_preview() -> dict:
    """KIS 계좌 잔고 조회 (미리보기 — CSV 저장 안 함)"""
    return quotes.fetch_kis_holdings_kr()


@app.post("/api/kis/holdings/sync")
def api_kis_holdings_sync(
    payload: dict = Body(default={}),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    """KIS 계좌 잔고를 가져와 SQLite(uid 있음) 또는 CSV(관리자)에 병합 저장."""
    uid = _sanitize_uid(x_mone_user)
    mode = str(payload.get("mode", "merge"))
    result = quotes.fetch_kis_holdings_kr()
    if result.get("status") != "OK":
        return result

    kis_items = result.get("items", [])
    if not kis_items:
        return {"status": "NO_DATA", "error": "KIS 계좌에 보유종목이 없습니다."}

    added, updated = 0, 0

    if uid:
        # SQLite: 기존 보유 로드 후 병합
        existing_list = _db.get_holdings(uid, "kr") if mode == "merge" else []
        existing: dict[str, dict] = {r["symbol"]: r for r in existing_list}
        for item in kis_items:
            sym = str(item["symbol"]).strip()
            if not sym:
                continue
            if sym in existing:
                existing[sym]["quantity"] = str(item["quantity"])
                existing[sym]["avgPrice"] = str(item["avgPrice"])
                updated += 1
            else:
                existing[sym] = {"symbol": sym, "name": item.get("name", sym), "market": "kr",
                    "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                    "stopPrice": "", "targetPrice": ""}
                added += 1
        _db.save_holdings(uid, list(existing.values()))
        storage = "sqlite"
    else:
        # CSV 관리자 모드
        cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
        path = _REPO / "holdings_kr.csv"
        existing_csv: dict[str, dict] = {}
        if mode == "merge":
            for row in _read_csv_safe(path):
                sym = str(row.get("symbol", "")).strip()
                if sym:
                    existing_csv[sym] = row
        for item in kis_items:
            sym = str(item["symbol"]).strip()
            if not sym:
                continue
            if sym in existing_csv:
                existing_csv[sym]["quantity"] = str(item["quantity"])
                existing_csv[sym]["avgPrice"] = str(item["avgPrice"])
                updated += 1
            else:
                existing_csv[sym] = {"symbol": sym, "name": item.get("name", sym), "market": "kr",
                    "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                    "stopPrice": "", "targetPrice": ""}
                added += 1
        norm_rows = list(existing_csv.values())
        _write_csv_safe_v2(path, norm_rows, cols)
        data_copy = _REPO / "data" / "holdings_kr.csv"
        if data_copy.exists():
            _write_csv_safe_v2(data_copy, norm_rows, cols)
        storage = "csv"

    return {
        "status": "OK",
        "mode": mode,
        "added": added,
        "updated": updated,
        "total": added + updated,
        "isMock": result.get("isMock", False),
        "storage": storage,
    }


@app.post("/api/holdings/import-csv")
def api_holdings_import_csv(payload: dict = Body(...)) -> dict:
    """나무·토스 등에서 붙여넣은 CSV/탭 텍스트를 파싱해 holdings에 병합.
    body: { market: 'kr'|'us', csv_text: '...', mode: 'merge'|'replace' }
    필수 컬럼: symbol(종목코드), quantity(수량), avgPrice(평균단가)
    선택 컬럼: name(종목명)
    헤더 없이 붙여넣을 경우 열 순서: symbol, name, quantity, avgPrice
    """
    import io
    import csv as _csv

    market = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
    mode = str(payload.get("mode", "merge"))
    raw = str(payload.get("csv_text", "")).strip()
    if not raw:
        return {"status": "ERROR", "error": "csv_text가 비어 있습니다."}

    # 탭/콤마/파이프 자동 감지
    sample = raw[:500]
    delimiter = "\t" if raw.count("\t") >= raw.count(",") else ","

    reader = _csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows_raw = [r for r in reader if any(c.strip() for c in r)]
    if not rows_raw:
        return {"status": "ERROR", "error": "파싱 가능한 행이 없습니다."}

    # 헤더 감지 (숫자가 있으면 데이터행, 없으면 헤더)
    def _is_header(row: list[str]) -> bool:
        return not any(c.strip().replace(".", "").replace("-", "").isdigit() for c in row)

    header_aliases = {
        "symbol": ["symbol", "종목코드", "code", "ticker", "종목번호"],
        "name": ["name", "종목명", "종목", "company"],
        "quantity": ["quantity", "수량", "qty", "보유수량", "잔량"],
        "avgPrice": ["avgprice", "평균단가", "avg", "평단가", "매입단가", "단가", "평균가"],
    }

    col_map: dict[str, int] = {}
    data_rows: list[list[str]] = []

    if _is_header(rows_raw[0]):
        header = [c.strip().lower() for c in rows_raw[0]]
        for field, aliases in header_aliases.items():
            for alias in aliases:
                if alias.lower() in header:
                    col_map[field] = header.index(alias.lower())
                    break
        data_rows = rows_raw[1:]
    else:
        # 헤더 없음: symbol, name, quantity, avgPrice 순 가정
        ncols = len(rows_raw[0])
        if ncols >= 4:
            col_map = {"symbol": 0, "name": 1, "quantity": 2, "avgPrice": 3}
        elif ncols == 3:
            col_map = {"symbol": 0, "quantity": 1, "avgPrice": 2}
        elif ncols == 2:
            col_map = {"symbol": 0, "quantity": 1}
        data_rows = rows_raw

    if "symbol" not in col_map or "quantity" not in col_map:
        return {"status": "ERROR", "error": "종목코드(symbol)와 수량(quantity) 컬럼을 찾지 못했습니다. 헤더를 포함해 붙여넣어 주세요."}

    parsed: list[dict] = []
    for row in data_rows:
        try:
            sym_raw = row[col_map["symbol"]].strip().replace(",", "").replace(" ", "")
            if not sym_raw:
                continue
            sym = _normalize_sym(sym_raw, market)
            qty_raw = row[col_map["quantity"]].strip().replace(",", "") if len(row) > col_map["quantity"] else "0"
            qty = int(float(qty_raw)) if qty_raw else 0
            if qty <= 0:
                continue
            avg_raw = row[col_map.get("avgPrice", -1)].strip().replace(",", "") if col_map.get("avgPrice") is not None and len(row) > col_map["avgPrice"] else "0"
            avg = float(avg_raw) if avg_raw else 0
            name = row[col_map["name"]].strip() if "name" in col_map and len(row) > col_map["name"] else sym
            parsed.append({"symbol": sym, "name": name, "market": market, "quantity": qty, "avgPrice": avg})
        except Exception:
            continue

    if not parsed:
        return {"status": "ERROR", "error": "유효한 종목 데이터를 파싱하지 못했습니다. 형식을 확인해 주세요."}

    cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
    path = _REPO / f"holdings_{market}.csv"

    existing: dict[str, dict] = {}
    if mode == "merge":
        for row in _read_csv_safe(path):
            s = str(row.get("symbol", "")).strip()
            if s:
                existing[s] = row

    added, updated = 0, 0
    for item in parsed:
        sym = item["symbol"]
        if sym in existing:
            existing[sym]["quantity"] = str(item["quantity"])
            existing[sym]["avgPrice"] = str(item["avgPrice"])
            if item["name"] and item["name"] != sym:
                existing[sym]["name"] = item["name"]
            updated += 1
        else:
            existing[sym] = {
                "symbol": sym, "name": item["name"], "market": market,
                "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                "stopPrice": "", "targetPrice": "",
            }
            added += 1

    norm_rows = list(existing.values())
    _write_csv_safe_v2(path, norm_rows, cols)
    data_copy = _REPO / "data" / f"holdings_{market}.csv"
    if data_copy.exists():
        _write_csv_safe_v2(data_copy, norm_rows, cols)

    return {"status": "OK", "market": market, "mode": mode, "added": added, "updated": updated, "total": len(norm_rows), "parsed": len(parsed)}


# ── 2. watchlist-edit ─────────────────────────────────────────────────

@app.get("/api/watchlist-edit")
def api_watchlist_edit(market: str = Query("all")) -> dict:
    markets = ["kr", "us"] if market == "all" else [market]
    items: list[dict] = []
    for mk in markets:
        path = _REPO / f"watchlist_{mk}.csv"
        for row in _read_csv_safe(path):
            sym = str(row.get("symbol", "")).strip()
            if not sym:
                continue
            items.append({
                "market": mk,
                "symbol": sym,
                "name": str(row.get("name", sym)).strip(),
                "memo": str(row.get("memo", "")).strip(),
                "group": str(row.get("group", row.get("memo", ""))).strip(),
                "targetReason": str(row.get("targetReason", "")).strip(),
                "finalScore": _safe_float_v2(row.get("finalScore")),
                "mode": str(row.get("mode", "")).strip(),
                "horizon": str(row.get("horizon", "")).strip(),
            })
    return {"status": "OK", "count": len(items), "items": items}


@app.post("/api/watchlist-edit/save")
def api_watchlist_edit_save(payload: dict = Body(...)) -> dict:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "ERROR", "error": "items must be a list"}
    by_market: dict[str, list] = {"kr": [], "us": []}
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        by_market[mk].append(item)
    cols = ["market", "symbol", "name", "memo", "targetReason", "autoWatchCategory",
            "autoWatchScore", "finalScore", "expectedValue", "mode", "horizon",
            "decisionBucket", "timingLabel", "candidateTypeLabel", "updated_at", "group"]
    for mk, rows in by_market.items():
        path = _REPO / f"watchlist_{mk}.csv"
        existing = {str(r.get("symbol", "")).strip(): r for r in _read_csv_safe(path)}
        norm_rows = []
        for r in rows:
            sym = _normalize_sym(r.get("symbol", ""), mk)
            if not sym:
                continue
            base = existing.get(sym, {})
            norm_rows.append({**base, **{
                "market": mk,
                "symbol": sym,
                "name": str(r.get("name", base.get("name", sym))).strip(),
                "memo": str(r.get("memo", base.get("memo", ""))).strip(),
                "group": str(r.get("group", base.get("group", ""))).strip(),
                "updated_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            }})
        _write_csv_safe_v2(path, norm_rows, cols)
    return {"status": "OK", "saved": len(items)}


# ── 3. predictions/table ──────────────────────────────────────────────

@app.get("/api/predictions/table")
def api_predictions_table(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    strategy: str = Query(""),
    term: str = Query(""),
    limit: int = Query(300),
) -> dict:
    # strategy/term 파라미터 폴백 처리
    eff_mode = strategy or mode
    eff_horizon = term or horizon
    try:
        rec = final_engine.final_recommendations(_market(market), eff_mode, eff_horizon)
        items = rec.get("items", [])
        return {"status": "OK", "count": len(items[:limit]), "items": items[:limit], "market": market}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0}


# ── 4. virtual/ledger ─────────────────────────────────────────────────

@app.get("/api/virtual/ledger")
def api_virtual_ledger(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(300),
) -> dict:
    try:
        result = operation_history.virtual_operation_history(
            market=None if market == "all" else _market(market),
            mode=None,
            limit=limit,
        )
        return _ensure_status(result)
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0}


# ── 5. virtual/validation ─────────────────────────────────────────────
# reports/virtual_validation_results.csv 를 소스로 사용
# (virtual_operation_history.csv 에는 result/returnPct 필드가 없어 항상 빈 배열 반환됐음)

@app.get("/api/virtual/validation")
def api_virtual_validation(
    market: str = Query("kr"),
    mode: str = Query(""),
    horizon: str = Query(""),
    limit: int = Query(300),
) -> dict:
    import csv as _vv_csv
    from pathlib import Path as _VVPath

    def _read_vv_csv(path: "_VVPath") -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _vv_csv.DictReader(f)]
            except Exception:
                continue
        return []

    try:
        reports_dir = _VVPath(__file__).resolve().parents[3] / "reports"
        rows = _read_vv_csv(reports_dir / "virtual_validation_results.csv")

        # 깨진 행 제거: symbol 비어있거나 market 이 정상 값이 아닌 행
        def _valid_row(r: dict) -> bool:
            sym = str(r.get("symbol", "")).strip()
            mkt = str(r.get("market", "")).strip().lower()
            return bool(sym) and mkt in ("kr", "us")

        rows = [r for r in rows if _valid_row(r)]

        mk = _market(market)
        if market not in ("all", ""):
            rows = [r for r in rows if str(r.get("market", "")).lower() == mk]

        # mode/horizon 는 선택 필터 (비어있으면 전체)
        if mode and mode not in ("all", ""):
            rows = [r for r in rows if str(r.get("mode", "")).lower() == mode.lower()]
        if horizon and horizon not in ("all", ""):
            rows = [r for r in rows if str(r.get("horizon", "")).lower() == horizon.lower()]

        pending   = [r for r in rows if str(r.get("status", r.get("result", ""))).upper() in ("PENDING", "DATA_PENDING", "")]
        validated = [r for r in rows if str(r.get("status", r.get("result", ""))).upper() not in ("PENDING", "DATA_PENDING", "")]

        return {
            "status": "OK",
            "count": len(validated),
            "items": rows[:limit],
            "totalCount": len(rows),
            "pendingCount": len(pending),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0, "pendingCount": 0}


# ── 6. validation/dashboard ───────────────────────────────────────────

@app.get("/api/validation/dashboard")
def api_validation_dashboard(market: str = Query("kr")) -> dict:
    import csv as _vd_csv
    from pathlib import Path as _VDPath

    def _read_vd_csv(path: _VDPath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _vd_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _vd_pct(v) -> float | None:
        try:
            return float(str(v or "").replace(",", "").replace("%", "").replace("+", "").strip())
        except Exception:
            return None

    try:
        mk = _market(market)
        reports_dir = _VDPath(__file__).resolve().parents[3] / "reports"

        modes = ["conservative", "balanced", "aggressive"]
        horizons = ["short", "swing", "mid"]

        stats: dict = {}
        total_completed = 0
        total_pending = 0
        all_win_rates: list[float] = []

        for mode in modes:
            for horizon in horizons:
                key = f"{mode}_{horizon}"
                files = sorted(
                    reports_dir.glob(f"mone_v36_final_trade_validation_{mk}_{mode}_{horizon}_*.csv"),
                    key=lambda p: p.name, reverse=True,
                )
                if not files:
                    fallback = reports_dir / f"mone_v36_final_trade_validation_{mk}_{mode}_{horizon}.csv"
                    files = [fallback] if fallback.exists() else []
                rows = _read_vd_csv(files[0]) if files else []
                executed = [r for r in rows if str(r.get("executed", "")).lower() in {"true", "1", "yes", "체결"}]
                pending_count = max(0, len(rows) - len(executed))
                returns = [_vd_pct(r.get("returnPct")) for r in executed]
                returns = [r for r in returns if r is not None]
                wins = sum(1 for r in returns if r > 0)
                win_rate = round(wins / len(returns) * 100, 1) if returns else None
                avg_return = round(sum(returns) / len(returns), 2) if returns else None
                stats[key] = {
                    "completed": len(executed),
                    "pending": pending_count,
                    "pendingCount": pending_count,
                    "wins": wins,
                    "winRate": win_rate,
                    "avgReturn": avg_return,
                }
                total_completed += len(executed)
                total_pending += pending_count
                if win_rate is not None:
                    all_win_rates.append(win_rate)

        overall_win_rate = round(sum(all_win_rates) / len(all_win_rates), 1) if all_win_rates else None

        ledger_path = reports_dir / "virtual_prediction_ledger.csv"
        lifecycle: list[dict] = []
        for r in _read_vd_csv(ledger_path)[:100]:
            if market != "all" and r.get("market", "").lower() != mk:
                continue
            lifecycle.append({
                "predictionId": r.get("predictionId", ""),
                "symbol": r.get("symbol", ""),
                "name": r.get("name", ""),
                "market": r.get("market", ""),
                "mode": r.get("mode", ""),
                "horizon": r.get("horizon", ""),
                "createdAt": r.get("createdAt", ""),
                "status": r.get("status", "PENDING"),
                "returnPct": _vd_pct(r.get("returnPct")),
            })

        return {
            "status": "OK",
            "summary": {
                "overallWinRate": overall_win_rate,
                "totalCompleted": total_completed,
                "totalPending": total_pending,
            },
            "stats": stats,
            "lifecycle": lifecycle,
            "market": market,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "summary": None, "stats": {}, "lifecycle": []}


# ── 7. risk/sector-exposure ───────────────────────────────────────────

@app.get("/api/risk/sector-exposure")
def api_risk_sector_exposure(market: str = Query("kr")) -> dict:
    try:
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(_market(market) if market != "all" else "all", 200)
        items = hp.get("items", [])
        # 기업분석에서 섹터 가져오기
        ca = data.company_analysis(_market(market) if market != "all" else "kr")
        sector_map = {str(r.get("symbol", "")).strip(): str(r.get("sector", "기타")) for r in ca.get("items", [])}
        by_sector: dict[str, dict] = {}
        total_val = 0.0
        for h in items:
            sym = str(h.get("symbol", "")).strip()
            val = _safe_float_v2(h.get("valuation", 0) or h.get("marketValue", 0))
            stop = _safe_float_v2(h.get("stop", 0) or h.get("stopPrice", 0))
            current = _safe_float_v2(h.get("currentPrice", 0))
            sector = sector_map.get(sym, "기타")
            total_val += val
            if sector not in by_sector:
                by_sector[sector] = {"sector": sector, "value": 0.0, "symbols": [], "maxLoss": 0.0}
            by_sector[sector]["value"] += val
            by_sector[sector]["symbols"].append(sym)
            if stop > 0 and current > 0:
                by_sector[sector]["maxLoss"] += (current - stop) * _safe_float_v2(h.get("quantity", 0))
        sectors = []
        for s in sorted(by_sector.values(), key=lambda x: x["value"], reverse=True):
            pct = (s["value"] / total_val * 100) if total_val > 0 else 0
            sectors.append({**s, "pct": round(pct, 1)})
        top1 = sectors[0]["pct"] if sectors else 0
        total_loss = sum(s["maxLoss"] for s in by_sector.values())
        total_loss_pct = (total_loss / total_val * 100) if total_val > 0 else 0
        return {
            "status": "OK",
            "sectors": sectors,
            "concentration": {"top1Pct": round(top1, 1), "warning": top1 > 40},
            "maxLossSimulation": {"totalLoss": round(total_loss), "totalLossPct": round(total_loss_pct, 1)},
            "market": market,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "sectors": []}


# ── 8. risk/benchmark ────────────────────────────────────────────────

@app.get("/api/risk/benchmark")
def api_risk_benchmark(market: str = Query("kr")) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(mk, 200)
        items = hp.get("items", [])
        # 벤치마크: KOSPI (kr) / SPY (us)
        bench_sym = "KOSPI" if mk == "kr" else "SPY"
        bench_prefix = "kr" if mk == "kr" else "us"
        bench_path = _OHLCV_DIR / f"{bench_prefix}_{bench_sym}_daily.csv"
        bench_rows = _read_csv_safe(bench_path)[-30:]
        bench_latest = _safe_float_v2(bench_rows[-1].get("close", 0) if bench_rows else 0)
        bench_base = _safe_float_v2(bench_rows[0].get("close", 0) if bench_rows else 0)
        bench_return = ((bench_latest - bench_base) / bench_base * 100) if bench_base > 0 else 0.0
        result_items = []
        total_port_val = 0.0
        total_port_cost = 0.0
        for h in items:
            sym = str(h.get("symbol", "")).strip()
            name = str(h.get("name", sym)).strip()
            qty = _safe_float_v2(h.get("quantity", 0))
            avg = _safe_float_v2(h.get("avgPrice", 0))
            current = _safe_float_v2(h.get("currentPrice", 0))
            if qty <= 0 or avg <= 0:
                continue
            val = qty * current if current > 0 else qty * avg
            cost = qty * avg
            port_ret = ((current - avg) / avg * 100) if avg > 0 and current > 0 else 0.0
            alpha = port_ret - bench_return
            total_port_val += val
            total_port_cost += cost
            result_items.append({
                "symbol": sym, "name": name,
                "portfolioReturn": round(port_ret, 1),
                "benchmarkReturn": round(bench_return, 1),
                "alpha": round(alpha, 1),
            })
        total_port_return = ((total_port_val - total_port_cost) / total_port_cost * 100) if total_port_cost > 0 else 0.0
        return {
            "status": "OK" if result_items else "NO_DATA",
            "benchmark": bench_sym,
            "benchmarkReturn": round(bench_return, 1),
            "totalPortfolioReturn": round(total_port_return, 1),
            "benchmarkLatestDate": bench_rows[-1].get("date", "") if bench_rows else "",
            "items": result_items,
            "count": len(result_items),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 9. risk/correlation ───────────────────────────────────────────────

@app.get("/api/risk/correlation")
def api_risk_correlation(market: str = Query("kr"), days: int = Query(60)) -> dict:
    try:
        result = advanced.correlation(_market(market) if market != "all" else "kr")
        return _ensure_status(result)
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matrix": []}


# ── 10. risk/near-alerts ──────────────────────────────────────────────

@app.get("/api/risk/near-alerts")
def api_risk_near_alerts(
    market: str = Query("all"),
    thresholdPct: float = Query(1.0),
    limit: int = Query(5),
) -> dict:
    try:
        from app.engine.mone_v77_holdings_risk import holdings_payload
        markets = ["kr", "us"] if market == "all" else [_market(market)]
        alerts = []
        for mk in markets:
            hp = holdings_payload(mk, 100)
            for h in hp.get("items", []):
                current = _safe_float_v2(h.get("currentPrice", 0))
                stop = _safe_float_v2(h.get("stop", 0) or h.get("stopPrice", 0))
                target = _safe_float_v2(h.get("target", 0) or h.get("targetPrice", 0))
                sym = str(h.get("symbol", "")).strip()
                name = str(h.get("name", sym)).strip()
                if current > 0 and stop > 0:
                    gap_pct = (current - stop) / current * 100
                    if 0 < gap_pct <= thresholdPct * 5:
                        alerts.append({
                            "type": "STOP", "symbol": sym, "name": name, "market": mk,
                            "currentPrice": current, "stopPrice": stop,
                            "gapPct": round(gap_pct, 2),
                            "message": f"손절가 {gap_pct:.1f}% 이내",
                        })
                if current > 0 and target > 0 and current < target:
                    gap_pct = (target - current) / current * 100
                    if 0 < gap_pct <= thresholdPct * 5:
                        alerts.append({
                            "type": "TARGET", "symbol": sym, "name": name, "market": mk,
                            "currentPrice": current, "targetPrice": target,
                            "gapPct": round(gap_pct, 2),
                            "message": f"목표가 {gap_pct:.1f}% 근접",
                        })
        alerts.sort(key=lambda x: x["gapPct"])
        return {"status": "OK" if alerts else "NO_DATA", "count": len(alerts[:limit]), "items": alerts[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 11. chart/index/{symbol} ──────────────────────────────────────────

@app.get("/api/chart/index/{index_symbol}")
def api_chart_index(
    index_symbol: str,
    market: str = Query("kr"),
    limit: int = Query(520),
) -> dict:
    try:
        mk = "kr" if str(market).lower() == "kr" else "us"
        sym = index_symbol.upper()
        path = _OHLCV_DIR / f"{mk}_{sym}_daily.csv"
        if not path.exists():
            # fallback: kr=KOSPI, us=SPY
            fallback = "KOSPI" if mk == "kr" else "SPY"
            path = _OHLCV_DIR / f"{mk}_{fallback}_daily.csv"
        rows = _read_csv_safe(path)
        items = []
        for r in rows[-limit:]:
            date = str(r.get("date") or r.get("Date") or "").strip()
            close = _safe_float_v2(r.get("close") or r.get("Close") or 0)
            if date and close > 0:
                items.append({"date": date, "close": close,
                               "open": _safe_float_v2(r.get("open") or close),
                               "high": _safe_float_v2(r.get("high") or close),
                               "low": _safe_float_v2(r.get("low") or close)})
        return {"status": "OK" if items else "NO_DATA", "count": len(items), "items": items, "symbol": sym}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 12. portfolio/nav ─────────────────────────────────────────────────

@app.get("/api/portfolio/nav")
def api_portfolio_nav(market: str = Query("kr"), days: int = Query(180)) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(mk, 100)
        holdings = hp.get("items", [])
        if not holdings:
            return {"status": "NO_DATA", "items": [], "count": 0}
        # 각 보유종목의 OHLCV 읽어서 NAV 시계열 계산
        prefix = "kr" if mk == "kr" else "us"
        date_nav: dict[str, float] = {}
        date_cost: dict[str, float] = {}
        for h in holdings:
            sym = str(h.get("symbol", "")).strip()
            qty = _safe_float_v2(h.get("quantity", 0))
            avg = _safe_float_v2(h.get("avgPrice", 0))
            if qty <= 0 or avg <= 0:
                continue
            cost = qty * avg
            ohlcv_path = _OHLCV_DIR / f"{prefix}_{sym}_daily.csv"
            rows = _read_csv_safe(ohlcv_path)[-days:]
            for r in rows:
                date = str(r.get("date") or r.get("Date") or "").strip()
                close = _safe_float_v2(r.get("close") or r.get("Close") or 0)
                if date and close > 0:
                    date_nav[date] = date_nav.get(date, 0) + qty * close
                    date_cost[date] = date_cost.get(date, 0) + cost
        if not date_nav:
            return {"status": "NO_DATA", "items": [], "count": 0}
        first_nav = None
        items = []
        for date in sorted(date_nav.keys()):
            nav = date_nav[date]
            cost = date_cost.get(date, nav)
            if first_nav is None:
                first_nav = cost
            cum_return = ((nav - first_nav) / first_nav * 100) if first_nav > 0 else 0.0
            items.append({
                "date": date,
                "nav": round(nav),
                "cumulative_return": round(cum_return, 2),
                "is_backfill": "false",
            })
        return {"status": "OK", "count": len(items), "items": items}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 13. home/summary ──────────────────────────────────────────────────

def _empty_home_holdings(market: str) -> dict:
    return {
        "status": "OK",
        "routeVersion": "personal-user-holdings-empty",
        "market": market,
        "count": 0,
        "totalCount": 0,
        "uniqueCount": 0,
        "items": [],
        "summary": {
            "count": 0,
            "totalValue": 0,
            "totalValueText": "-",
            "totalPnl": 0,
            "totalPnlText": "0",
            "riskCount": 0,
            "mixedCurrency": False,
            "marketBreakdown": [],
        },
        "authority": "personal_user_holdings",
    }


def _clean_user_id(raw: str) -> str:
    return "".join(ch for ch in str(raw or "") if ch.isalnum() or ch in "_-")[:64]


app.router.routes = [
    r for r in app.router.routes
    if getattr(r, "path", "") != "/api/home/summary"
]


@app.get("/api/home/summary")
def api_home_summary(
    market: str = Query("kr"),
    limit: int = Query(12),
    x_mone_user: str = Header(default="", alias="x-mone-user"),
) -> dict:
    """HomePage 3×3 매트릭스용 통합 응답 — 9개 전략 셀 + 보유종목 + 마켓 레짐"""
    try:
        mk = _market(market) if market != "all" else "kr"
        MODES = ("conservative", "balanced", "aggressive")
        HORIZONS = ("short", "swing", "mid")

        # 마켓 레짐 (KOSPI/SPY 20일선 기반 — priority 9)
        regime = "UNKNOWN"
        regime_detail: dict = {}
        try:
            bench_sym = "KOSPI" if mk == "kr" else "SPY"
            bench_rows = _read_csv_safe(_OHLCV_DIR / f"{mk}_{bench_sym}_daily.csv")[-60:]
            closes = [_safe_float_v2(r.get("close") or r.get("Close") or 0) for r in bench_rows]
            closes = [c for c in closes if c > 0]
            if len(closes) >= 20:
                ma20 = sum(closes[-20:]) / 20
                ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else ma20
                current = closes[-1]
                if current > ma20 * 1.02:
                    regime = "BULL"
                elif current < ma20 * 0.98:
                    regime = "BEAR"
                else:
                    regime = "SIDEWAYS"
                regime_detail = {
                    "regime": regime,
                    "current": round(current, 2),
                    "ma20": round(ma20, 2),
                    "ma60": round(ma60, 2),
                    "distanceMa20Pct": round((current - ma20) / ma20 * 100, 2),
                    "benchmark": bench_sym,
                    "label": {"BULL": "강세장 (MA20 상회)", "BEAR": "약세장 (MA20 하회)", "SIDEWAYS": "중립"}[regime],
                    "description": {
                        "BULL": f"{bench_sym} 현재가 {current:,.0f} > MA20 {ma20:,.0f} (+{abs((current-ma20)/ma20*100):.1f}%) — 공격적 진입 허용",
                        "BEAR": f"{bench_sym} 현재가 {current:,.0f} < MA20 {ma20:,.0f} (-{abs((current-ma20)/ma20*100):.1f}%) — 보수적 접근 권장",
                        "SIDEWAYS": f"{bench_sym} 현재가 {current:,.0f} ≈ MA20 {ma20:,.0f} (±2%) — 중립, 종목별 선별",
                    }[regime],
                }
        except Exception:
            pass

        # 3×3 매트릭스 — 사전 생성 CSV 직접 읽기 (재계산 없이 <100ms)
        def _csv_matrix_cell(mode_: str, horizon_: str) -> tuple[str, dict]:
            import csv as _csv_mod
            key_ = f"{mode_}_{horizon_}"
            try:
                csv_path = data.ensure_fresh(
                    data.REPORT_DIR / f"mone_v36_final_recommendations_{mk}_{mode_}_{horizon_}.csv",
                    max_age_hours=6.0,
                )
                if not csv_path.exists() or csv_path.stat().st_size < 20:
                    return key_, {"status": "NO_DATA", "items": [], "count": 0, "positiveEvCount": 0, "source": "csv_missing"}
                rows_: list[dict] = []
                for enc_ in ("utf-8-sig", "utf-8", "cp949"):
                    try:
                        with csv_path.open("r", encoding=enc_) as _fh:
                            rows_ = [dict(r) for r in _csv_mod.DictReader(_fh)]
                        break
                    except Exception:
                        continue
                if not rows_:
                    return key_, {"status": "NO_DATA", "items": [], "count": 0, "positiveEvCount": 0, "source": "csv_empty"}
                # ── CSV rows 신규 필드 보강 (riskReason 등 live 계산) ───────
                try:
                    _lev_kw = ("레버리지", "인버스", "2x", "3x", "곱버스")
                    _wf_cache = final_engine._load_walkforward_metrics(mk)
                    _wf_cell  = _wf_cache.get(f"{mode_}_{horizon_}", {})
                    for _r in rows_:
                        # riskReason
                        if not _r.get("riskReason"):
                            _sc = {
                                "riskScore":        float(_r.get("riskScore") or 0),
                                "opportunityScore": float(_r.get("opportunityScore") or 0),
                            }
                            _r["riskReason"] = final_engine._risk_reason(
                                _sc,
                                int(float(_r.get("eventRiskScore") or 0)),
                                str(_r.get("surgeLabel") or ""),
                            )
                        # priceLevelWarning
                        if not _r.get("priceLevelWarning"):
                            def _pf(v: object) -> "float | None":
                                try:
                                    f = float(v or 0); return f if f > 0 else None
                                except Exception: return None
                            _r["priceLevelWarning"] = final_engine._price_level_warning(
                                _pf(_r.get("entry")), _pf(_r.get("stop")), _pf(_r.get("target"))
                            )
                        # dataAsOf
                        if not _r.get("dataAsOf"):
                            _r["dataAsOf"] = str(
                                _r.get("ohlcvLatestDate") or _r.get("latestDataDate") or _r.get("dataDate") or ""
                            )
                        # gapWarningPct
                        if _r.get("gapWarningPct") is None:
                            try:
                                _g = float(_r.get("gap") or 0)
                                _r["gapWarningPct"] = round(abs(_g) * 100, 1) if _g else None
                            except Exception:
                                _r["gapWarningPct"] = None
                        # currentPriceSource
                        if not _r.get("currentPriceSource"):
                            _r["currentPriceSource"] = str(
                                _r.get("priceSourceType") or _r.get("dataSourceType") or "OHLCV"
                            )
                        # isLeveragedEtf / leverageWarning
                        if "isLeveragedEtf" not in _r:
                            _nm_l = str(_r.get("name", "")).lower()
                            _is_lev = any(kw in _nm_l for kw in _lev_kw)
                            _r["isLeveragedEtf"] = _is_lev
                            _r["leverageWarning"] = (
                                "레버리지/인버스 ETF — 단기 변동성 매우 크며 복리 손실 위험 있음"
                                if _is_lev else ""
                            )
                        # walkforwardMetrics
                        if not _r.get("walkforwardMetrics"):
                            _r["walkforwardMetrics"] = _wf_cell
                        # walkforwardAdjustment
                        if _r.get("walkforwardAdjustment") is None:
                            _r["walkforwardAdjustment"] = round(float(_wf_cell.get("adjustment", 0.0)), 1)
                except Exception:
                    pass
                # ─────────────────────────────────────────────────────────────
                # 이름 보정: name == symbol 인 경우 sector_map에서 조회
                try:
                    sm_path = data.REPO_ROOT / "data" / f"sector_map_{mk}.csv"
                    nm_map_: dict[str, str] = {}
                    if sm_path.exists():
                        with sm_path.open("r", encoding="utf-8-sig") as _smf:
                            for _smr in _csv_mod.DictReader(_smf):
                                _s, _n = str(_smr.get("symbol", "")).strip(), str(_smr.get("name", "")).strip()
                                if _s and _n:
                                    nm_map_[_s] = _n
                    for _row in rows_:
                        _sym, _nm = str(_row.get("symbol", "")).strip(), str(_row.get("name", "")).strip()
                        if (_nm == _sym or not _nm) and _sym in nm_map_:
                            _row["name"] = nm_map_[_sym]
                except Exception:
                    pass
                # EV 양수 우선 정렬
                def _fv(v: object) -> float:
                    try:
                        return float(v or 0)  # type: ignore[arg-type]
                    except Exception:
                        return 0.0
                rows_.sort(key=lambda r: (_fv(r.get("expectedValue", 0)) > 0, _fv(r.get("finalRankScore") or r.get("finalScore") or 0)), reverse=True)
                pos_ev_ = [r for r in rows_ if _fv(r.get("expectedValue", 0)) > 0]
                display_ = (pos_ev_ if pos_ev_ else rows_)[:5]
                return key_, {"status": "OK", "items": display_, "count": len(rows_), "positiveEvCount": len(pos_ev_), "source": "csv"}
            except Exception as exc_:
                return key_, {"status": "ERROR", "error": str(exc_), "items": [], "count": 0, "positiveEvCount": 0}

        matrix: dict = {}
        # CSV 읽기: 각 셀 <5ms → 9셀 전체 <50ms
        _csv_ok = any(
            (data.REPORT_DIR / f"mone_v36_final_recommendations_{mk}_{m}_{h}.csv").exists()
            for m in MODES for h in HORIZONS
        )
        if _csv_ok:
            for _m, _h in [(m, h) for m in MODES for h in HORIZONS]:
                _ck, _cv = _csv_matrix_cell(_m, _h)
                matrix[_ck] = _cv
        else:
            # CSV 없으면 실시간 계산 (ThreadPool 병렬)
            def _fetch_matrix_cell(args: tuple[str, str]) -> tuple[str, dict]:
                _mode, _horizon = args
                _key = f"{_mode}_{_horizon}"
                try:
                    rec = final_engine.final_recommendations(mk, _mode, _horizon)
                    cell_items = rec.get("items", [])
                    pos_ev = [i for i in cell_items if _safe_float_v2(i.get("expectedValue", 0)) > 0]
                    display = (pos_ev if pos_ev else cell_items)[:5]
                    return _key, {"status": "OK" if display else "NO_DATA", "items": display, "count": len(cell_items), "positiveEvCount": len(pos_ev)}
                except Exception as exc:
                    return _key, {"status": "ERROR", "error": str(exc), "items": [], "count": 0}
            with ThreadPoolExecutor(max_workers=4) as _pool:
                for _cell_key, _cell_val in _pool.map(_fetch_matrix_cell, [(m, h) for m in MODES for h in HORIZONS]):
                    matrix[_cell_key] = _cell_val

        # 보유종목 (holdingsClean 엔드포인트 재사용)
        holdings_payload: dict = _empty_home_holdings(mk)
        try:
            uid = _clean_user_id(x_mone_user)
            if uid:
                personal_rows = _db.get_holdings(uid, mk)
                if personal_rows:
                    from app.engine.mone_v802_holdings_clean import holdings_clean_payload_for_user
                    holdings_payload = holdings_clean_payload_for_user(uid, market=mk, limit=50)
        except Exception:
            holdings_payload = _empty_home_holdings(mk)

        # 데이터 헬스
        data_health: dict = {}
        try:
            data_health = data.runner_status(mk)
        except Exception:
            pass
        # runner_status에 ohlcvLatestDate 없거나 data_health 자체가 비어 있으면 _scan_coverage로 보완
        if not data_health or not data_health.get("ohlcvLatestDate"):
            try:
                from app.engine.mone_v65_api_stabilizer import _scan_coverage, _repo_root as _stab_root
                import json as _dh_json
                _cov = _scan_coverage(mk)
                _repo = _stab_root()
                _ohlcv_dates: list[str] = []
                _ohlcv_dir = _repo / "data" / "market" / "ohlcv"
                if _ohlcv_dir.exists():
                    for _p in _ohlcv_dir.glob(f"{mk}_*_daily.csv"):
                        try:
                            import csv as _dh_csv
                            # utf-8-sig: BOM 있는 CSV도 첫 컬럼명 'date' 로 정상 파싱
                            with _p.open("r", encoding="utf-8-sig") as _f:
                                _rows = list(_dh_csv.DictReader(_f))
                            if _rows:
                                # 마지막 행부터 역순으로 유효한 날짜 탐색
                                for _row in reversed(_rows):
                                    _d = str(_row.get("date") or _row.get("Date") or "").strip()[:10]
                                    if _d and len(_d) == 10 and _d[4] == "-":
                                        _ohlcv_dates.append(_d)
                                        break
                        except Exception:
                            pass
                _reco_gen: str | None = None
                for _sp in [_repo / "reports" / f"{mk}_recommendation_gen_status.json", _repo / f"{mk}_recommendation_gen_status.json"]:
                    if _sp.exists():
                        try:
                            _st = _dh_json.loads(_sp.read_text(encoding="utf-8"))
                            _reco_gen = _st.get("generatedAt") or _st.get("completedAt")
                        except Exception:
                            pass
                        break
                data_health = {
                    "kisLiveCount":    _cov.get("quoteCoverageCount", 0),
                    "kisTargetCount":  _cov.get("quoteTargetCount", 0),
                    "ohlcvCount":      _cov.get("ohlcvSymbolCount", 0),
                    "ohlcvLatestDate": max(_ohlcv_dates) if _ohlcv_dates else None,
                    "recoGeneratedAt": _reco_gen,
                    "scanScope":       _cov.get("universeScope", "CURATED_UNIVERSE"),
                }
            except Exception:
                pass

        # 최후 fallback: _scan_coverage 실패해도 gen_status JSON에서 recoGeneratedAt 직접 보완
        if not data_health.get("recoGeneratedAt"):
            import json as _fj2
            _repo_root_fb = data.APP_DIR.parent
            for _fb_path in [
                _repo_root_fb / "reports" / f"{mk}_recommendation_gen_status.json",
                data.APP_DIR / "reports" / f"{mk}_recommendation_gen_status.json",
            ]:
                if _fb_path.exists():
                    try:
                        _fst = _fj2.loads(_fb_path.read_text(encoding="utf-8"))
                        if not isinstance(data_health, dict):
                            data_health = {}
                        data_health["recoGeneratedAt"] = (
                            _fst.get("generatedAt") or _fst.get("completedAt") or ""
                        )
                    except Exception:
                        pass
                    break

        return {
            "status": "OK",
            "market": mk,
            "matrix": matrix,
            "holdings": holdings_payload,
            "marketRegime": regime_detail if regime_detail else {"regime": regime},
            "dataHealth": data_health,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matrix": {}, "holdings": {"items": []}}


# ── 14. sectors ───────────────────────────────────────────────────────

@app.get("/api/sectors")
def api_sectors(market: str = Query("kr")) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        ca = data.company_analysis(mk)
        sector_map: dict[str, list] = {}
        for r in ca.get("items", []):
            sector = str(r.get("sector", "기타")).strip() or "기타"
            sym = str(r.get("symbol", "")).strip()
            name = str(r.get("name", sym)).strip()
            if sym:
                sector_map.setdefault(sector, []).append({"symbol": sym, "name": name})
        items = [{"sector": s, "count": len(v), "symbols": v} for s, v in sorted(sector_map.items())]
        return {"status": "OK", "count": len(items), "items": items, "market": mk}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 15. watchlist/groups ──────────────────────────────────────────────

@app.get("/api/watchlist/groups")
def api_watchlist_groups(market: str = Query("kr")) -> dict:
    try:
        markets = ["kr", "us"] if market == "all" else [_market(market) if market != "all" else "kr"]
        group_map: dict[str, list] = {}
        for mk in markets:
            path = _REPO / f"watchlist_{mk}.csv"
            for r in _read_csv_safe(path):
                sym = str(r.get("symbol", "")).strip()
                group = str(r.get("group", r.get("memo", "기본"))).strip() or "기본"
                if sym:
                    group_map.setdefault(group, []).append({
                        "market": mk, "symbol": sym,
                        "name": str(r.get("name", sym)).strip(),
                        "group": group,
                        "finalScore": _safe_float_v2(r.get("finalScore", 0)),
                    })
        items = [{"group": g, "count": len(v), "items": v} for g, v in sorted(group_map.items())]
        return {"status": "OK", "count": len(items), "items": items, "groups": list(group_map.keys())}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 16. watchlist/set-group ───────────────────────────────────────────

@app.post("/api/watchlist/set-group")
def api_watchlist_set_group(payload: dict = Body(...)) -> dict:
    try:
        sym = str(payload.get("symbol", "")).strip()
        group = str(payload.get("group", "기본")).strip() or "기본"
        mk = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
        path = _REPO / f"watchlist_{mk}.csv"
        rows = _read_csv_safe(path)
        updated = False
        for r in rows:
            if str(r.get("symbol", "")).strip() == sym:
                r["group"] = group
                updated = True
        if not updated:
            return {"status": "NOT_FOUND", "error": f"{sym} not in watchlist_{mk}"}
        # 기존 컬럼 유지 + group 추가
        existing_cols = []
        if rows:
            existing_cols = list(rows[0].keys())
        if "group" not in existing_cols:
            existing_cols.append("group")
        _write_csv_safe_v2(path, rows, existing_cols)
        return {"status": "OK", "symbol": sym, "group": group, "market": mk}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 17. watchlist/scored ──────────────────────────────────────────────

@app.get("/api/watchlist/scored")
def api_watchlist_scored(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        # 관심종목 심볼 목록
        watch_syms: set[str] = set()
        for wm in (["kr", "us"] if market == "all" else [mk]):
            for r in _read_csv_safe(_REPO / f"watchlist_{wm}.csv"):
                s = str(r.get("symbol", "")).strip()
                if s:
                    watch_syms.add(s)
        # 추천 리스트에서 관심종목만 필터
        rec = final_engine.final_recommendations(mk, mode, horizon)
        items = [i for i in rec.get("items", []) if str(i.get("symbol", "")).strip() in watch_syms]
        if not items:
            items = rec.get("items", [])[:20]
        return {"status": "OK", "count": len(items), "items": items, "watchlistCount": len(watch_syms)}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 18. disclosure-calendar ───────────────────────────────────────────

@app.get("/api/disclosure-calendar")
def api_disclosure_calendar(market: str = Query("kr"), days: int = Query(30)) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        disc = data.disclosure_rows(mk)
        items = disc.get("items", []) if isinstance(disc, dict) else []
        result = []
        for d in items[:50]:
            date_str = str(d.get("date") or d.get("disclosedAt") or d.get("publishedAt") or "").strip()
            result.append({
                "date": date_str,
                "title": str(d.get("title") or d.get("reportName") or "").strip(),
                "symbol": str(d.get("symbol", "")).strip(),
                "name": str(d.get("name") or d.get("company") or "").strip(),
                "type": str(d.get("type") or d.get("category") or "공시").strip(),
            })
        return {"status": "OK" if result else "NO_DATA", "count": len(result), "items": result}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 19-0. earnings-calendar (실적발표 일정) ───────────────────────────

@app.get("/api/earnings-calendar")
def api_earnings_calendar(market: str = Query("all"), days: int = Query(14)) -> dict:
    """CSV 우선 + Finnhub(US) / Alpha Vantage(KR) 폴백."""
    # ── 1차: CSV 파일 (generate_event_calendar.py 데이터) ──
    try:
        csv_items: list[dict] = []
        for mkt in (["kr", "us"] if market == "all" else [market]):
            csv_items.extend(_ec_cal.upcoming_earnings(mkt, days=days))
        if csv_items:
            csv_items.sort(key=lambda x: x.get("date", ""))
            return {"status": "OK", "count": len(csv_items), "days": days, "items": csv_items, "source": "csv"}
    except Exception:
        pass

    # ── 2차: 라이브 API 폴백 ──
    import urllib.request as _ur
    import csv as _ecsv

    av_key = os.environ.get("ALPHA_VANTAGE_KEY", "").strip()
    fh_key = os.environ.get("FINNHUB_API_KEY", "").strip()
    now = __import__("datetime").datetime.now()
    today_s = now.strftime("%Y-%m-%d")
    end_s   = (now + __import__("datetime").timedelta(days=days)).strftime("%Y-%m-%d")
    items: list[dict] = []

    # ── 국장 (Alpha Vantage) ──
    if market in ("kr", "all") and av_key:
        # 추천 종목 심볼 수집
        symbols: list[str] = []
        for mode in ("conservative", "balanced", "aggressive"):
            for horizon in ("short", "swing", "mid"):
                p = _REPO / "reports" / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
                for row in _read_csv_safe(p):
                    s = str(row.get("symbol", "")).strip()
                    if s and s not in symbols:
                        symbols.append(s)
        for sym in symbols[:20]:
            av_sym = f"{sym}.KS"
            try:
                url = f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&symbol={av_sym}&horizon=3month&apikey={av_key}"
                req = _ur.Request(url, headers={"User-Agent": "MONE/1.0"})
                with _ur.urlopen(req, timeout=8) as r:
                    content = r.read().decode("utf-8")
                for row in _ecsv.DictReader(content.splitlines()):
                    rd = str(row.get("reportDate", "")).strip()
                    if today_s <= rd <= end_s:
                        items.append({
                            "market": "kr", "symbol": sym,
                            "name": str(row.get("name", sym)),
                            "date": rd,
                            "estimate": str(row.get("estimate", "")),
                            "currency": "KRW",
                        })
            except Exception:
                continue

    # ── 미장 (Finnhub → Alpha Vantage 폴백) ──
    if market in ("us", "all"):
        us_items: list[dict] = []

        # 1차: Finnhub
        if fh_key:
            try:
                url = f"https://finnhub.io/api/v1/calendar/earnings?from={today_s}&to={end_s}&token={fh_key}"
                with _ur.urlopen(url, timeout=10) as r:
                    fh_data = __import__("json").loads(r.read())
                for x in (fh_data.get("earningsCalendar") or []):
                    eps = x.get("epsEstimate")
                    if not eps:
                        continue
                    us_items.append({
                        "market": "us", "source": "finnhub",
                        "symbol": x.get("symbol", ""),
                        "name": x.get("symbol", ""),
                        "date": x.get("date", ""),
                        "estimate": str(eps),
                        "hour": x.get("hour", ""),
                        "currency": "USD",
                    })
            except Exception:
                pass

        # 2차: Finnhub 실패 시 Alpha Vantage 폴백
        if not us_items and av_key:
            try:
                url = f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey={av_key}"
                req = _ur.Request(url, headers={"User-Agent": "MONE/1.0"})
                with _ur.urlopen(req, timeout=10) as r:
                    content = r.read().decode("utf-8")
                import io as _io
                for row in __import__("csv").DictReader(_io.StringIO(content)):
                    sym = str(row.get("symbol", ""))
                    rd  = str(row.get("reportDate", "")).strip()
                    if ".KS" in sym or ".KQ" in sym or not rd:
                        continue
                    if today_s <= rd <= end_s and row.get("estimate"):
                        us_items.append({
                            "market": "us", "source": "alpha_vantage",
                            "symbol": sym, "name": sym,
                            "date": rd,
                            "estimate": str(row.get("estimate", "")),
                            "currency": row.get("currency", "USD"),
                        })
            except Exception:
                pass

        items.extend(us_items[:10])

    items.sort(key=lambda x: x["date"])
    return {"status": "OK" if items else "NO_DATA", "count": len(items), "days": days, "items": items[:30]}


# ── 19. journal (투자장부) ────────────────────────────────────────────

def _ensure_journal() -> None:
    _JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _JOURNAL_FILE.exists():
        with _JOURNAL_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            _csv.DictWriter(f, fieldnames=_JOURNAL_COLS).writeheader()


@app.get("/api/journal")
def api_journal_get(market: str = Query("all"), limit: int = Query(200)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        if market != "all":
            rows = [r for r in rows if r.get("market", "").lower() == market.lower()]
        rows = sorted(rows, key=lambda r: r.get("createdAt", ""), reverse=True)
        return {"status": "OK", "count": len(rows[:limit]), "items": rows[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


@app.post("/api/journal/add")
def api_journal_add(payload: dict = Body(...)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        new_row = {
            "id": str(_uuid.uuid4())[:8],
            "date": str(payload.get("date", _dt.now().strftime("%Y-%m-%d"))).strip(),
            "market": str(payload.get("market", "kr")).strip(),
            "symbol": str(payload.get("symbol", "")).strip(),
            "name": str(payload.get("name", "")).strip(),
            "action": str(payload.get("action", "메모")).strip(),
            "price": str(_safe_float_v2(payload.get("price", 0))),
            "qty": str(_safe_float_v2(payload.get("qty", 0))),
            "memo": str(payload.get("memo", "")).strip(),
            "review": str(payload.get("review", "")).strip(),
            "result": str(payload.get("result", "PENDING")).strip(),
            "returnPct": str(_safe_float_v2(payload.get("returnPct", 0))),
            "tags": _json.dumps(payload.get("tags", []), ensure_ascii=False),
            "createdAt": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        rows.append(new_row)
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "item": new_row}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.patch("/api/journal/{entry_id}")
def api_journal_update(entry_id: str, payload: dict = Body(...)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        updated = False
        for r in rows:
            if r.get("id") == entry_id:
                for k in ("memo", "review", "result", "returnPct", "tags"):
                    if k in payload:
                        r[k] = _json.dumps(payload[k], ensure_ascii=False) if k == "tags" else str(payload[k])
                updated = True
        if not updated:
            return {"status": "NOT_FOUND", "error": f"id={entry_id} not found"}
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "id": entry_id}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.delete("/api/journal/{entry_id}")
def api_journal_delete(entry_id: str) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        before = len(rows)
        rows = [r for r in rows if r.get("id") != entry_id]
        if len(rows) == before:
            return {"status": "NOT_FOUND", "error": f"id={entry_id} not found"}
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "deleted": entry_id}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 20. health/github ─────────────────────────────────────────────────

@app.get("/api/health/github")
def api_health_github() -> dict:
    try:
        from app.engine.auto_sync import get_sync_status
        return _ensure_status(get_sync_status())
    except Exception:
        pass
    try:
        status = data.runner_status("kr")
        return {"status": "OK", "kr": status, "source": "runner_status"}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 21. data/audit ───────────────────────────────────────────────────

@app.get("/api/data/audit")
def api_data_audit() -> dict:
    try:
        result: dict = {"status": "OK", "files": [], "summary": {}}
        report_files = list(_REPORTS.glob("*.csv")) if _REPORTS.exists() else []
        ohlcv_files = list(_OHLCV_DIR.glob("*.csv")) if _OHLCV_DIR.exists() else []
        holdings_files = [_REPO / f"holdings_{m}.csv" for m in ["kr", "us"]]
        watchlist_files = [_REPO / f"watchlist_{m}.csv" for m in ["kr", "us"]]
        audit_items = []
        for path in report_files[:20] + ohlcv_files[:10] + holdings_files + watchlist_files:
            if path.exists():
                stat = path.stat()
                audit_items.append({
                    "file": path.name,
                    "path": str(path.relative_to(_REPO)) if _REPO in path.parents else path.name,
                    "size": stat.st_size,
                    "mtime": _dt.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": len(_read_csv_safe(path)),
                })
        result["files"] = audit_items
        result["summary"] = {
            "reportFiles": len(report_files),
            "ohlcvFiles": len(ohlcv_files),
            "totalAuditFiles": len(audit_items),
        }
        return result
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "files": []}


# ── 22-A. exchange-rate ───────────────────────────────────────────────
# 1순위: 한국수출입은행 API (KOREAEXIM_API_KEY)
# 2순위: open.er-api.com (무료, 키 불필요)
# 3순위: api.exchangerate-api.com (무료, 키 불필요)

_EXRATE_CACHE: dict = {}
_EXRATE_TTL = 4 * 3600  # 4시간 캐시

def _try_koreaexim(base: str, api_key: str) -> float | None:
    try:
        import requests as _req
        from datetime import date as _date, timedelta as _td
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.koreaexim.go.kr/site/main/index006",
        }
        for delta in range(5):
            search_date = (_date.today() - _td(days=delta)).strftime("%Y%m%d")
            try:
                resp = _req.get(
                    "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON",
                    params={"authkey": api_key, "searchdate": search_date, "data": "AP01"},
                    headers=headers, timeout=8,
                )
                items = resp.json()
                if isinstance(items, list):
                    for item in items:
                        if item.get("cur_unit") == base:
                            rate_str = str(item.get("deal_bas_r", "")).replace(",", "")
                            rate = float(rate_str)
                            if rate > 0:
                                return rate
            except Exception:
                continue
    except Exception:
        pass
    return None

def _try_open_er_api(base: str) -> float | None:
    try:
        import requests as _req
        resp = _req.get(f"https://open.er-api.com/v6/latest/{base}", timeout=8)
        data = resp.json()
        if data.get("result") == "success":
            return float(data["rates"].get("KRW", 0)) or None
    except Exception:
        pass
    return None

def _try_exchangerate_api(base: str) -> float | None:
    try:
        import os as _os, requests as _req
        key = _os.getenv("EXCHANGERATE_API_KEY", "")
        if key:
            # 인증 엔드포인트 (더 정확, 더 높은 한도)
            resp = _req.get(f"https://v6.exchangerate-api.com/v6/{key}/latest/{base}", timeout=8)
            data = resp.json()
            if data.get("result") == "success":
                return float(data["conversion_rates"].get("KRW", 0)) or None
        # 무료 폴백
        resp = _req.get(f"https://api.exchangerate-api.com/v4/latest/{base}", timeout=8)
        data = resp.json()
        return float(data["rates"].get("KRW", 0)) or None
    except Exception:
        pass
    return None

@app.get("/api/exchange-rate")
def api_exchange_rate(base: str = Query("USD"), target: str = Query("KRW")) -> dict:
    import os as _os, time as _time

    cache_key = f"{base}_{target}"
    now_ts = _time.time()
    cached = _EXRATE_CACHE.get(cache_key, {})
    if cached and now_ts - cached.get("ts", 0) < _EXRATE_TTL:
        return {k: v for k, v in cached.items() if k != "ts"}

    api_key = _os.getenv("KOREAEXIM_API_KEY", "")

    # 1순위: 한국수출입은행
    if api_key:
        rate = _try_koreaexim(base, api_key)
        if rate:
            result = {"status": "OK", "rate": rate, "base": base, "target": target,
                      "source": "koreaexim"}
            _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
            return result

    # 2순위: open.er-api.com
    rate = _try_open_er_api(base)
    if rate:
        result = {"status": "OK", "rate": rate, "base": base, "target": target,
                  "source": "open.er-api.com"}
        _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
        return result

    # 3순위: exchangerate-api.com
    rate = _try_exchangerate_api(base)
    if rate:
        result = {"status": "OK", "rate": rate, "base": base, "target": target,
                  "source": "exchangerate-api.com"}
        _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
        return result

    msg = "KOREAEXIM_API_KEY 미설정 — .env에 추가하세요" if not api_key else "모든 환율 소스 응답 없음"
    return {"status": "NO_DATA", "rate": None, "base": base, "target": target, "message": msg}


# ── 22. position/size ─────────────────────────────────────────────────

@app.get("/api/position/size")
def api_position_size(
    entry: float = Query(...),
    cash: float = Query(...),
    strategy: str = Query("balanced"),
    market: str = Query("kr"),
) -> dict:
    try:
        # Kelly 기반 포지션 계산
        kelly_map = {"conservative": 0.10, "balanced": 0.15, "aggressive": 0.20}
        kelly_f = kelly_map.get(strategy, 0.15)
        position_value = cash * kelly_f
        shares = int(position_value / entry) if entry > 0 else 0
        actual_value = shares * entry
        return {
            "status": "OK",
            "entry": entry,
            "cash": cash,
            "strategy": strategy,
            "kellyFraction": kelly_f,
            "positionValue": round(actual_value),
            "shares": shares,
            "pctOfCash": round(actual_value / cash * 100, 1) if cash > 0 else 0,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 23. kis/token/status ──────────────────────────────────────────────

@app.get("/api/kis/token/status")
def api_kis_token_status() -> dict:
    kis_key = _os.environ.get("KIS_APP_KEY", "")
    kis_secret = _os.environ.get("KIS_APP_SECRET", "")
    kis_account = _os.environ.get("KIS_ACCOUNT_NO", "")
    configured = bool(kis_key and kis_secret and kis_account)
    return {
        "status": "OK" if configured else "NO_KEY",
        "hasKey": bool(kis_key),
        "hasSecret": bool(kis_secret),
        "hasAccount": bool(kis_account),
        "configured": configured,
        "message": "KIS API 설정 완료" if configured else "KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 환경변수 미설정",
    }


# ── 24. EV 필터 추천 (priority 5) ─────────────────────────────────────

@app.get("/api/final/recommendations-ev-filtered")
def api_recommendations_ev_filtered(
    market: str = Query("kr", pattern="^(kr|us|all)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(20),
) -> dict:
    """EV(기댓값) 양수인 종목만 반환하는 필터드 추천 엔드포인트"""
    try:
        mk_list = ["kr", "us"] if market == "all" else [_market(market)]
        all_items = []
        for mk in mk_list:
            rec = final_engine.final_recommendations(mk, mode, horizon)
            for item in rec.get("items", []):
                ev = _safe_float_v2(item.get("expectedValue", 0))
                if ev > 0:
                    all_items.append(item)
        all_items.sort(key=lambda x: _safe_float_v2(x.get("expectedValue", 0)), reverse=True)
        return {"status": "OK" if all_items else "NO_DATA", "count": len(all_items[:limit]), "items": all_items[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


print("[MONE v10.2] 누락 API 엔드포인트 24종 등록 완료")
def _install_mone_virtual_report_routes_v1():
    from fastapi import Query as _MoneVirtualQuery

    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/virtual/summary", "/api/virtual/trades"}
    ]

    @app.get("/api/virtual/summary")
    def mone_virtual_summary(
        market: str = _MoneVirtualQuery("kr", pattern="^(kr|us|all)$"),
        mode: str = _MoneVirtualQuery("all"),
        horizon: str = _MoneVirtualQuery("all"),
    ) -> dict:
        if str(market).lower() == "all":
            kr = _virtual_summary_from_reports("kr", mode, horizon)
            us = _virtual_summary_from_reports("us", mode, horizon)
            total = int(kr.get("totalRecommendations") or 0) + int(us.get("totalRecommendations") or 0)
            executed = int(kr.get("executedTrades") or 0) + int(us.get("executedTrades") or 0)
            unexecuted = int(kr.get("unexecutedCount") or 0) + int(us.get("unexecutedCount") or 0)
            combined_items = (kr.get("items") or []) + (us.get("items") or [])
            combined_returns = [
                value for value in (_safe_pct(row.get("returnPct")) for row in combined_items if isinstance(row, dict))
                if value is not None
            ]
            cumulative = _portfolio_return_pct(combined_returns)
            raw_sum = sum(combined_returns)
            avg_return = raw_sum / len(combined_returns) if combined_returns else 0.0
            rate = round((executed / (executed + unexecuted)) * 100, 2) if executed + unexecuted else 0
            return {
                **us,
                "market": "all",
                "status": "OK" if total else "NO_DATA",
                "totalRecommendations": total,
                "latestRecommendations": int(kr.get("latestRecommendations") or 0) + int(us.get("latestRecommendations") or 0),
                "executedTrades": executed,
                "latestExecutedTrades": executed,
                "unexecutedCount": unexecuted,
                "latestUnexecutedCount": unexecuted,
                "executionRate": rate,
                "latestExecutionRate": rate,
                "executedReturnPct": round(avg_return, 3),
                "cumulativeReturnPct": round(cumulative, 3),
                "latestCumulativeReturnPct": round(cumulative, 3),
                "rawReturnSumPct": round(raw_sum, 3),
                "returnBasis": "executed rows; cumulativeReturnPct is a 10% equal-slot virtual portfolio compound return, not raw return sum",
                "items": combined_items,
                "count": int(kr.get("count") or 0) + int(us.get("count") or 0),
                "source": "virtual_validation_results.csv + virtual_prediction_ledger.csv",
            }
        return _virtual_summary_from_reports(_market(market), mode, horizon)

    @app.get("/api/virtual/trades")
    def mone_virtual_trades(
        market: str = _MoneVirtualQuery("kr", pattern="^(kr|us|all)$"),
        mode: str = _MoneVirtualQuery("all"),
        horizon: str = _MoneVirtualQuery("all"),
        limit: int = _MoneVirtualQuery(300, ge=1, le=1000),
    ) -> dict:
        payload = mone_virtual_summary(market, mode, horizon)
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return {**payload, "items": items[:limit], "count": min(len(items), limit)}


try:
    _install_mone_virtual_report_routes_v1()
except Exception as _mone_virtual_report_error:
    print("[MONE] virtual report route patch failed:", _mone_virtual_report_error)

# ═══════════════════════════════════════════════════════════
# Phase 3 — Signal Ledger & 호라이즌별 자동 결과 검증
# ═══════════════════════════════════════════════════════════

@app.post("/api/signals/record")
def api_signals_record(payload: dict = Body(...)) -> dict:
    """신호를 원장에 기록 (당일 동일 symbol+mode+horizon 중복 제거)."""
    from app.services import signal_ledger as sl
    return sl.record(
        market=str(payload.get("market", "kr")),
        symbol=str(payload.get("symbol", "")),
        name=str(payload.get("name", "")),
        mode=str(payload.get("mode", "balanced")),
        horizon=str(payload.get("horizon", "swing")),
        entry=float(payload.get("entry", 0) or 0),
        stop=float(payload.get("stop", 0) or 0),
        target=float(payload.get("target", 0) or 0),
        ev=float(payload.get("ev", 0) or 0),
        probability=float(payload.get("probability", 0) or 0),
        score=float(payload.get("score", 0) or 0),
        decision_bucket=str(payload.get("decisionBucket", "")),
        sector=str(payload.get("sector", "")),
    )


@app.get("/api/signals/ledger")
def api_signals_ledger(
    market: str = Query("all"),
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    """신호 원장 조회 (검증 결과 포함)."""
    from app.services import signal_ledger as sl
    return sl.ledger_list(market=market, limit=limit)


@app.post("/api/signals/verify")
def api_signals_verify() -> dict:
    """대기 중인 신호에 대해 OHLCV 기반 호라이즌별 결과 검증 실행."""
    from app.services import signal_ledger as sl
    return sl.verify()


@app.get("/api/signals/badge")
def api_signals_badge(
    symbol: str = Query(...),
    horizon: str = Query("all"),
    mode: str = Query("all"),
) -> dict:
    """종목별 백테스트 뱃지 통계 (승률·평균수익·샘플 수)."""
    from app.services import signal_ledger as sl
    return sl.badge(symbol=symbol, horizon=horizon, mode=mode)


# ═══════════════════════════════════════════════════════════
# Phase 4 — Portfolio Conflict
# ═══════════════════════════════════════════════════════════

@app.get("/api/portfolio/conflict")
def api_portfolio_conflict(
    symbol: str = Query(...),
    market: str = Query("kr"),
    sector: str = Query(""),
) -> dict:
    """신규 후보와 보유종목의 섹터 충돌 검사."""
    from app.services import signal_ledger as sl
    return sl.portfolio_conflict(symbol=symbol, market=market, sector=sector)


# ── 데이터 소스 상태 API ───────────────────────────────────────────────────

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")


@app.get("/api/health/data-sources")
def api_data_sources() -> dict:
    """데이터 수집 소스 상태 (GitHub Actions vs 로컬 수집기) 및 추천 CSV 신선도"""
    sources: dict = {}

    # GitHub Actions 마지막 실행 상태
    for f in ("reports/kis_live_refresh_status.json", "reports/auto_sync_status.json"):
        p = data.REPO_ROOT / f
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                sources["github_actions"] = {
                    "lastUpdate": d.get("updatedAt") or d.get("timestamp", ""),
                    "status": d.get("status", "UNKNOWN"),
                    "file": f,
                }
                break
            except Exception:
                pass

    # 로컬 수집기 상태
    p2 = data.REPO_ROOT / "reports" / "local_collector_status.json"
    if p2.exists():
        try:
            d2 = json.loads(p2.read_text(encoding="utf-8"))
            sources["local_collector"] = {
                "lastUpdate": d2.get("completedAt", ""),
                "source": d2.get("source", "local_task_scheduler"),
                "pushed": d2.get("pushed", False),
            }
        except Exception:
            pass

    # 추천 CSV 신선도 (3×3 매트릭스)
    rec_freshness: dict = {}
    for mode in MODES:
        for horizon in HORIZONS:
            p3 = data.REPORT_DIR / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
            if p3.exists():
                age_h = (time.time() - p3.stat().st_mtime) / 3600
                rec_freshness[f"{mode}_{horizon}"] = {
                    "ageHours": round(age_h, 1),
                    "fresh": age_h < 24,
                }

    return {"status": "OK", "sources": sources, "recommendationFreshness": rec_freshness}


@app.post("/api/cache/refresh")
def api_cache_refresh(market: str = "kr", secret: str = "") -> dict:
    """
    작업스케줄러 push 완료 후 추천 CSV 즉시 강제 갱신.
    GitHub raw에서 최신 파일을 즉시(동기) 다운로드.
    secret: 환경변수 CACHE_REFRESH_SECRET 또는 기본값 'mone-refresh'
    """
    import os as _os
    expected = _os.getenv("CACHE_REFRESH_SECRET", "mone-refresh")
    if secret and secret != expected:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="invalid secret")

    refreshed, failed = 0, 0
    markets = ["kr", "us"] if market == "all" else [market]
    for mk in markets:
        for mode_ in MODES:
            for horizon_ in HORIZONS:
                rel = f"reports/mone_v36_final_recommendations_{mk}_{mode_}_{horizon_}.csv"
                ok = data._refresh_from_github(rel)
                if ok:
                    refreshed += 1
                else:
                    failed += 1
    # 패턴 성과 / 지지저항도 갱신
    for extra in ("reports/pattern_performance.json", "reports/support_resistance_zones.json",
                  "reports/local_collector_status.json"):
        data._refresh_from_github(extra)

    # 파일 갱신 후 lru_cache 강제 삭제 — 5분 버킷 내 재호출 시도 구 데이터 반환 방지
    from app.engine.auto_sync import _clear_all_caches
    caches_cleared = _clear_all_caches()

    return {
        "status": "OK",
        "market": market,
        "refreshed": refreshed,
        "failed": failed,
        "cachesCleared": caches_cleared,
        "timestamp": datetime.now().isoformat(),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 데이터 커버리지 상태 (경량 메타데이터 기반)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@app.get("/api/data/coverage")
def api_data_coverage(market: str = "kr") -> dict:
    """파일 메타데이터 기반 데이터 수집 현황 반환 (경량)."""
    result: dict = {"status": "OK", "market": market, "sources": {}}

    # OHLCV
    ohlcv_dir = data.REPO_ROOT / "data" / "market" / "ohlcv"
    if ohlcv_dir.exists():
        prefix = f"{market}_"
        files = [f for f in ohlcv_dir.glob(f"{market}_*_daily.csv") if f.is_file()]
        count = len(files)
        newest = max((f.stat().st_mtime for f in files), default=0)
        age_h = (time.time() - newest) / 3600 if newest else 9999
        result["sources"]["ohlcv"] = {
            "label": "OHLCV",
            "count": count,
            "unit": "종목",
            "ageHours": round(age_h, 1),
            "status": "NORMAL" if count > 0 and age_h < 48 else ("STALE" if count > 0 else "EMPTY"),
        }
    else:
        result["sources"]["ohlcv"] = {"label": "OHLCV", "count": 0, "status": "EMPTY"}

    # 추천선
    reco_files = list((data.REPO_ROOT / "reports").glob(f"mone_v36_final_recommendations_{market}_*.csv"))
    if reco_files:
        reco_newest = max(f.stat().st_mtime for f in reco_files)
        reco_age_h = (time.time() - reco_newest) / 3600
        total_rows = 0
        for f in reco_files:
            try:
                import pandas as _pd
                total_rows += max(0, len(_pd.read_csv(f)) - 1)
            except Exception:
                pass
        result["sources"]["recommendations"] = {
            "label": "추천선",
            "count": total_rows,
            "unit": "후보",
            "ageHours": round(reco_age_h, 1),
            "status": "NORMAL" if total_rows > 0 and reco_age_h < 48 else ("STALE" if total_rows > 0 else "EMPTY"),
        }
    else:
        result["sources"]["recommendations"] = {"label": "추천선", "count": 0, "status": "EMPTY"}

    # 뉴스
    news_file = data.REPO_ROOT / f"data/news/news_{market}.json"
    if news_file.exists():
        age_h = (time.time() - news_file.stat().st_mtime) / 3600
        try:
            import json as _json
            items = _json.loads(news_file.read_text(encoding="utf-8"))
            count = len(items) if isinstance(items, list) else 0
        except Exception:
            count = 0
        result["sources"]["news"] = {
            "label": "뉴스",
            "count": count,
            "unit": "건",
            "ageHours": round(age_h, 1),
            "status": "NORMAL" if count > 0 and age_h < 24 else ("STALE" if count > 0 else "PENDING"),
        }
    else:
        result["sources"]["news"] = {"label": "뉴스", "count": 0, "status": "PENDING"}

    # 기업분석
    dart_dir = data.REPO_ROOT / "data" / "company"
    if dart_dir.exists():
        dart_files = list(dart_dir.glob("*.json")) + list(dart_dir.glob("*.csv"))
        count = len(dart_files)
        newest = max((f.stat().st_mtime for f in dart_files), default=0)
        age_d = (time.time() - newest) / 86400 if newest else 9999
        result["sources"]["company"] = {
            "label": "기업분석",
            "count": count,
            "unit": "종목",
            "ageDays": round(age_d, 1),
            "status": "NORMAL" if count > 0 and age_d < 14 else ("STALE" if count > 0 else "PENDING"),
        }
    else:
        result["sources"]["company"] = {"label": "기업분석", "count": 0, "status": "PENDING"}

    return result


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Broker 계좌연동 (로그인 필수)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

from app.services import broker_service as _broker


def _require_user(authorization: str | None) -> dict:
    """Bearer 토큰 검증 후 payload 반환. 인증 실패 시 JSONResponse 예외 raise."""
    token = _extract_bearer_token(authorization)
    payload = _verify_user_token(token)
    if not payload:
        raise ValueError("로그인이 필요합니다.")
    return payload


@app.get("/api/broker/connections")
def api_broker_connections(authorization: str | None = Header(default=None)) -> dict:
    """현재 사용자의 broker 연결 목록 반환 (로그인 필수)."""
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    user_id = payload.get("userId", "")
    return {"ok": True, "connections": _broker.get_all_connections(user_id)}


@app.post("/api/broker/connect")
def api_broker_connect(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    """broker 연결 테스트 후 암호화 저장 (로그인 필수)."""
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    user_id = payload.get("userId", "")

    broker = str(body.get("broker", "")).lower().strip()
    app_key = str(body.get("appKey", "")).strip()
    app_secret = str(body.get("appSecret", "")).strip()
    account_no = str(body.get("accountNo", "")).strip()

    if broker not in ("toss", "kis"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker는 toss 또는 kis만 지원합니다."})
    if not app_key or not app_secret:
        return JSONResponse(status_code=400, content={"ok": False, "error": "appKey와 appSecret이 필요합니다."})

    # 연결 테스트
    if broker == "toss":
        test = _broker.test_toss_connection(app_key, app_secret)
    else:
        test = _broker.test_kis_connection(app_key, app_secret)

    if not test.get("ok"):
        msg = test.get("message", "연결 실패")
        return {
            "ok": False,
            "testPassed": False,
            "code": test.get("code", "BROKER_CONNECT_FAILED"),
            "message": msg,
            "error": msg,
        }

    # 저장
    _broker.save_connection(user_id, broker, app_key, app_secret, account_no)
    return {"ok": True, "testPassed": True, "code": test.get("code", "BROKER_CONNECTED"),
            "message": test.get("message", "연결됨"),
            "status": _broker.get_connection_status(user_id, broker)}


@app.post("/api/broker/test")
def api_broker_test(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    """broker 토큰 발급 테스트만 수행한다. 인증정보는 저장하지 않는다."""
    try:
        _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})

    broker = str(body.get("broker", "")).lower().strip()
    app_key = str(body.get("appKey", "")).strip()
    app_secret = str(body.get("appSecret", "")).strip()

    if broker not in ("toss", "kis"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker는 toss 또는 kis만 지원합니다."})
    if not app_key or not app_secret:
        return JSONResponse(status_code=400, content={"ok": False, "error": "App Key와 App Secret이 필요합니다."})

    test = _broker.test_toss_connection(app_key, app_secret) if broker == "toss" else _broker.test_kis_connection(app_key, app_secret)
    if not test.get("ok"):
        msg = test.get("message", "토큰 발급 실패")
        return {
            "ok": False,
            "testPassed": False,
            "code": test.get("code", "BROKER_TEST_FAILED"),
            "message": msg,
            "error": msg,
        }
    return {
        "ok": True,
        "testPassed": True,
        "code": test.get("code", "BROKER_TOKEN_OK"),
        "message": test.get("message", "토큰 발급 성공"),
        "elapsedMs": test.get("elapsedMs"),
    }


@app.post("/api/broker/sync-holdings")
def api_broker_sync_holdings(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    """broker 보유종목 동기화 (로그인 필수)."""
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    user_id = payload.get("userId", "")
    broker = str(body.get("broker", "")).lower().strip()

    if broker == "toss":
        return _broker.sync_toss_holdings(user_id)
    elif broker == "kis":
        return JSONResponse(status_code=501, content={"ok": False, "error": "KIS 동기화는 준비 중입니다."})
    return JSONResponse(status_code=400, content={"ok": False, "error": "지원하지 않는 broker입니다."})


@app.delete("/api/broker/disconnect")
def api_broker_disconnect(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    """broker 연결 해제 및 저장된 키 삭제 (로그인 필수)."""
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    user_id = payload.get("userId", "")
    broker = str(body.get("broker", "")).lower().strip()
    if not broker:
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker 필드가 필요합니다."})
    _broker.disconnect(user_id, broker)
    return {"ok": True, "message": f"{broker} 연결이 해제되었습니다."}


# Local broker bridge override.
# The legacy broker routes above used to test tokens and sync holdings from the
# server process. Cloud IPs are blocked by some brokers, so the active routes
# below accept only sanitized holdings uploaded from the user's PC.
_BROKER_ROUTE_PATHS = {
    "/api/broker/connections",
    "/api/broker/connect",
    "/api/broker/test",
    "/api/broker/sync-holdings",
    "/api/broker/disconnect",
}
for _route in list(app.router.routes):
    if isinstance(_route, APIRoute) and getattr(_route, "path", "") in _BROKER_ROUTE_PATHS:
        try:
            app.router.routes.remove(_route)
        except ValueError:
            pass


def _bridge_num(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "nan"):
            return default
        return float(str(value).replace(",", "").strip())
    except Exception:
        return default


def _bridge_decode_str(value) -> str:
    """CP949/EUC-KR로 잘못 디코딩된 문자열을 복구 시도 후 strip."""
    text = str(value or "").strip()
    if not text:
        return ""
    # latin-1로 인코딩 후 cp949로 재디코딩하면 깨진 한글 복구 가능
    try:
        recovered = text.encode("latin-1").decode("cp949")
        if any("가" <= c <= "힣" for c in recovered):
            return recovered
    except Exception:
        pass
    return text


def _bridge_market(value) -> str:
    return "us" if str(value or "kr").lower().strip() == "us" else "kr"


def _bridge_symbol(value, market: str) -> str:
    raw = str(value or "").strip()
    if market == "kr":
        digits = "".join(ch for ch in raw if ch.isdigit())
        return digits.zfill(6)[-6:] if digits else raw
    return raw.upper()


def _normalize_bridge_holding(item: dict, broker: str) -> dict | None:
    market = _bridge_market(item.get("market"))
    symbol = _bridge_symbol(item.get("symbol") or item.get("code") or item.get("ticker"), market)
    if not symbol:
        return None
    quantity = _bridge_num(item.get("quantity") or item.get("qty"))
    avg_price = _bridge_num(item.get("avgPrice") or item.get("averagePrice") or item.get("avg_price"))
    current_price = _bridge_num(item.get("currentPrice") or item.get("price") or item.get("current_price"))
    eval_amount = _bridge_num(item.get("evalAmount") or item.get("valuation") or item.get("marketValue"))
    if not eval_amount and quantity and current_price:
        eval_amount = quantity * current_price
    profit_loss = _bridge_num(item.get("profitLoss") or item.get("pnl") or item.get("profit_loss"))
    profit_loss_rate = _bridge_num(item.get("profitLossRate") or item.get("pnlRate") or item.get("profit_loss_rate"))
    return {
        "broker": broker,
        "source": broker,
        "market": market,
        "symbol": symbol,
        "name": _bridge_decode_str(item.get("name") or item.get("stockName") or symbol),
        "quantity": str(quantity),
        "avgPrice": str(avg_price),
        "stopPrice": str(item.get("stopPrice") or item.get("stop") or ""),
        "targetPrice": str(item.get("targetPrice") or item.get("target") or ""),
        "currentPrice": current_price,
        "evalAmount": eval_amount,
        "valuation": eval_amount,
        "profitLoss": profit_loss,
        "profitLossRate": profit_loss_rate,
        "syncedAt": int(time.time()),
    }


def _save_bridge_holdings(user_id: str, broker: str, items: list[dict], mode: str = "replace_broker") -> dict:
    normalized = [row for row in (_normalize_bridge_holding(item, broker) for item in items) if row]
    if not normalized:
        return {"ok": False, "code": "NO_HOLDINGS", "message": "No holdings were provided for upload.", "count": 0}
    existing = _db.get_holdings(user_id, "all") if mode != "replace_all" else []
    by_key: dict[tuple[str, str], dict] = {
        (_bridge_market(row.get("market")), str(row.get("symbol") or "").strip()): dict(row)
        for row in existing
        if str(row.get("symbol") or "").strip()
    }
    if mode in ("replace", "replace_broker"):
        by_key = {
            key: row
            for key, row in by_key.items()
            if str(row.get("broker") or row.get("source") or "manual").lower() != broker
        }
    added = 0
    updated = 0
    for row in normalized:
        key = (_bridge_market(row.get("market")), str(row.get("symbol") or "").strip())
        if key in by_key:
            updated += 1
        else:
            added += 1
        by_key[key] = row
    saved = _db.save_holdings(user_id, list(by_key.values()))
    return {"ok": True, "status": "OK", "count": len(normalized), "added": added, "updated": updated, "saved": saved}


@app.get("/api/broker/connections")
def api_broker_connections_bridge(authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    return {"ok": True, "connections": _broker.get_all_connections(payload.get("userId", ""))}


@app.post("/api/broker/test")
def api_broker_test_bridge(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    try:
        _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    broker = str(body.get("broker", "")).lower().strip()
    if broker not in ("toss", "kis"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker must be toss or kis."})
    return _broker.local_bridge_mode_response(broker)


@app.post("/api/broker/connect")
def api_broker_connect_bridge(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    broker = str(body.get("broker", "")).lower().strip()
    if broker not in ("toss", "kis"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker must be toss or kis."})
    return {
        **_broker.local_bridge_mode_response(broker),
        "status": _broker.get_connection_status(payload.get("userId", ""), broker),
    }


@app.post("/api/broker/local-bridge/upload")
def api_broker_local_bridge_upload(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    user_id = payload.get("userId", "")
    broker = str(body.get("broker", "")).lower().strip()
    if broker not in ("toss", "kis", "manual", "file"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker must be toss, kis, manual, or file."})
    items = body.get("items") or body.get("holdings") or []
    if not isinstance(items, list):
        return JSONResponse(status_code=400, content={"ok": False, "error": "items must be an array."})
    result = _save_bridge_holdings(user_id, broker, items, str(body.get("mode", "replace_broker")).lower().strip())
    if not result.get("ok"):
        return JSONResponse(status_code=400, content=result)
    _broker.save_bridge_status(
        user_id,
        broker,
        account_no_hint=str(body.get("accountNoHint") or body.get("accountHint") or ""),
        item_count=int(result.get("count") or 0),
        sync_time=time.time(),
        source=str(body.get("source") or "local_bridge"),
    )
    return {
        **result,
        "broker": broker,
        "connection": _broker.get_connection_status(user_id, broker),
        "message": f"{broker} local bridge snapshot applied: {result.get('count', 0)} holdings.",
    }


@app.post("/api/broker/sync-holdings")
def api_broker_sync_holdings_bridge(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    broker = str(body.get("broker", "")).lower().strip()
    if broker not in ("toss", "kis"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "broker must be toss or kis."})
    status = _broker.get_connection_status(payload.get("userId", ""), broker)
    if status.get("connected"):
        return {
            "ok": True,
            "status": "OK",
            "broker": broker,
            "count": status.get("itemCount", 0),
            "lastSync": status.get("lastSync"),
            "message": "The latest local bridge snapshot is already applied.",
        }
    return JSONResponse(status_code=409, content={
        "ok": False,
        "code": "LOCAL_BRIDGE_UPLOAD_REQUIRED",
        "broker": broker,
        "message": "Run the local bridge upload from your PC first.",
    })


@app.delete("/api/broker/disconnect")
def api_broker_disconnect_bridge(body: dict = Body(...), authorization: str | None = Header(default=None)) -> dict:
    try:
        payload = _require_user(authorization)
    except ValueError as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    broker = str(body.get("broker", "")).lower().strip()
    if broker not in ("toss", "kis", "manual", "file"):
        return JSONResponse(status_code=400, content={"ok": False, "error": "Invalid broker value."})
    _broker.disconnect(payload.get("userId", ""), broker)
    return {"ok": True, "message": f"{broker} local bridge status disconnected."}
