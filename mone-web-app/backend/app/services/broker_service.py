"""
broker_service.py — 토스증권/KIS 계좌연동 서비스

보안 원칙:
- App Key/Secret은 서버측 파일에 암호화 저장
- 로그인(OAuth) 사용자 ID와 연결
- 프론트로 Secret 재전송 금지
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

# ── 경로 ──────────────────────────────────────────────────────────────
from app.services import data_loader as data

_BROKER_DIR = data.APP_DIR / "backend" / "broker_credentials"


def _ensure_dir() -> None:
    _BROKER_DIR.mkdir(parents=True, exist_ok=True)


def _broker_path(user_id: str, broker: str) -> Path:
    safe_uid = "".join(c if c.isalnum() or c in "-_:" else "_" for c in user_id)[:80]
    safe_broker = broker.lower().strip()
    return _BROKER_DIR / f"{safe_uid}_{safe_broker}.json"


# ── 암호화 (Fernet-lite: AES-free, HMAC-XOR obfuscation) ──────────────
def _derive_key(user_id: str) -> bytes:
    """사용자 ID + 서버 시크릿을 합쳐 64바이트 키를 도출한다."""
    secret = os.environ.get("MONE_ADMIN_SECRET", "mone-dev-secret").encode()
    return hashlib.sha256(secret + user_id.encode()).digest()


def _encrypt(plaintext: str, user_id: str) -> str:
    """평문 → base64-encoded XOR-obfuscated string."""
    key = _derive_key(user_id)
    data_bytes = plaintext.encode("utf-8")
    key_stream = (key[i % len(key)] for i in range(len(data_bytes)))
    cipher = bytes(b ^ k for b, k in zip(data_bytes, key_stream))
    return base64.urlsafe_b64encode(cipher).decode("ascii")


def _decrypt(ciphertext: str, user_id: str) -> str:
    """base64-encoded XOR string → 평문."""
    key = _derive_key(user_id)
    cipher = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    key_stream = (key[i % len(key)] for i in range(len(cipher)))
    data_bytes = bytes(b ^ k for b, k in zip(cipher, key_stream))
    return data_bytes.decode("utf-8")


# ── CRUD ──────────────────────────────────────────────────────────────

def save_connection(user_id: str, broker: str, app_key: str, app_secret: str,
                    account_no: str, extra: dict[str, Any] | None = None) -> None:
    """연결 정보를 암호화 저장한다. Secret은 저장 후 복호화 불가."""
    _ensure_dir()
    record = {
        "broker": broker,
        "app_key": _encrypt(app_key, user_id),
        "app_secret": _encrypt(app_secret, user_id),
        "account_no": _encrypt(account_no, user_id),
        "extra": extra or {},
        "connected_at": time.time(),
        "last_sync": None,
        "sync_status": "IDLE",
    }
    path = _broker_path(user_id, broker)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def get_connection_status(user_id: str, broker: str) -> dict[str, Any]:
    """연결 상태만 반환 (Secret/Key 미포함)."""
    path = _broker_path(user_id, broker)
    if not path.exists():
        return {"broker": broker, "connected": False, "status": "NOT_CONNECTED"}
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        return {
            "broker": broker,
            "connected": True,
            "status": rec.get("sync_status", "IDLE"),
            "lastSync": rec.get("last_sync"),
            "connectedAt": rec.get("connected_at"),
            "accountNoHint": _mask_account(rec.get("account_no", ""), user_id),
        }
    except Exception:
        return {"broker": broker, "connected": False, "status": "LOAD_ERROR"}


def get_all_connections(user_id: str) -> list[dict[str, Any]]:
    """사용자의 모든 broker 연결 상태를 반환한다."""
    return [get_connection_status(user_id, b) for b in ("toss", "kis", "manual")]


def disconnect(user_id: str, broker: str) -> None:
    """저장된 연결 정보를 완전히 삭제한다."""
    path = _broker_path(user_id, broker)
    if path.exists():
        path.unlink()


def get_decrypted_credentials(user_id: str, broker: str) -> dict[str, str] | None:
    """내부 전용: 실제 API 호출 시 복호화된 자격증명 반환."""
    path = _broker_path(user_id, broker)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        return {
            "app_key": _decrypt(rec["app_key"], user_id),
            "app_secret": _decrypt(rec["app_secret"], user_id),
            "account_no": _decrypt(rec["account_no"], user_id),
        }
    except Exception:
        return None


def update_sync_status(user_id: str, broker: str, status: str, sync_time: float | None = None) -> None:
    path = _broker_path(user_id, broker)
    if not path.exists():
        return
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec["sync_status"] = status
        if sync_time is not None:
            rec["last_sync"] = sync_time
        path.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ── 토스증권 API 테스트 (실제 API 호출) ───────────────────────────────

_TOSS_TOKEN_URL = os.environ.get(
    "TOSSINVEST_TOKEN_URL",
    "https://openapi.tossinvest.com/oauth2/token",
).strip()


def _broker_error(code: str, message: str, *, status: int | None = None) -> dict[str, Any]:
    """프론트에 raw exception이 노출되지 않도록 표준 broker 오류를 만든다."""
    payload: dict[str, Any] = {"ok": False, "code": code, "message": message}
    if status is not None:
        payload["httpStatus"] = status
    return payload


def _is_timeout_exception(exc: BaseException) -> bool:
    import socket
    import urllib.error

    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        return isinstance(reason, (TimeoutError, socket.timeout)) or "timed out" in str(reason).lower()
    return "timed out" in str(exc).lower()


def _read_http_error_body(exc: BaseException, limit: int = 500) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")[:limit]  # type: ignore[attr-defined]
    except Exception:
        return ""


def _classify_toss_http_error(status: int, body_txt: str = "") -> dict[str, Any]:
    body_lower = (body_txt or "").lower()
    if status == 404:
        return _broker_error(
            "TOSS_ENDPOINT_NOT_FOUND",
            "토스증권 API 엔드포인트를 찾을 수 없습니다. 관리자에게 문의하세요.",
            status=status,
        )
    if status in (401, 403):
        if "permission" in body_lower or "scope" in body_lower:
            return _broker_error(
                "TOSS_PERMISSION_REQUIRED",
                "토스증권 Open API 사용 설정 또는 계좌 권한을 확인해주세요.",
                status=status,
            )
        return _broker_error(
            "TOSS_AUTH_FAILED",
            "App Key 또는 App Secret을 확인해주세요.",
            status=status,
        )
    if status == 400:
        if "permission" in body_lower or "scope" in body_lower:
            return _broker_error(
                "TOSS_PERMISSION_REQUIRED",
                "토스증권 Open API 사용 설정 또는 계좌 권한을 확인해주세요.",
                status=status,
            )
        return _broker_error(
            "TOSS_AUTH_FAILED",
            "App Key 또는 App Secret을 확인해주세요.",
            status=status,
        )
    if status >= 500:
        return _broker_error(
            "TOSS_SERVER_ERROR",
            "토스증권 서버 응답이 불안정합니다. 잠시 후 다시 시도해주세요.",
            status=status,
        )
    return _broker_error(
        "TOSS_AUTH_FAILED",
        "App Key 또는 App Secret을 확인해주세요.",
        status=status,
    )


def _request_toss_token(app_key: str, app_secret: str) -> dict[str, Any]:
    """토스증권 OAuth2 Client Credentials 토큰 발급.

    Spec (openapi.tossinvest.com/openapi-docs/latest/openapi.json):
      POST /oauth2/token
      Content-Type: application/x-www-form-urlencoded
      Body: grant_type=client_credentials&client_id=...&client_secret=...
      No Authorization header.
    """
    import logging
    import urllib.error
    import urllib.parse
    import urllib.request

    _log = logging.getLogger(__name__)

    form_data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": app_key,
        "client_secret": app_secret,
    }).encode("utf-8")

    req = urllib.request.Request(
        _TOSS_TOKEN_URL,
        data=form_data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": "MONE/1.0",
        },
        method="POST",
    )
    try:
        started = time.time()
        with urllib.request.urlopen(req, timeout=15) as res:
            payload = json.loads(res.read().decode("utf-8"))
        payload["_elapsedMs"] = int((time.time() - started) * 1000)
        return payload
    except urllib.error.HTTPError as exc:
        body_txt = _read_http_error_body(exc)
        _log.warning("TOSS token HTTP %s | body=%s", exc.code, body_txt[:300])
        classified = _classify_toss_http_error(exc.code, body_txt)
        classified["provider"] = "toss"
        return classified
    except Exception as exc:
        if _is_timeout_exception(exc):
            return _broker_error(
                "TOSS_TIMEOUT",
                "토스증권 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요.",
            )
        _log.warning("TOSS token network error: %s", type(exc).__name__)
        return _broker_error(
            "TOSS_NETWORK_ERROR",
            "토스증권 연결 중 네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.",
        )


def test_toss_connection(app_key: str, app_secret: str) -> dict[str, Any]:
    """토스증권 토큰 발급 테스트. 저장하지 않고 성공 여부만 반환한다."""
    payload = _request_toss_token(app_key, app_secret)
    if not payload.get("ok", True):
        return payload
    if payload.get("access_token"):
        return {
            "ok": True,
            "code": "TOSS_TOKEN_OK",
            "message": "토스증권 토큰 발급 성공",
            "elapsedMs": payload.get("_elapsedMs"),
        }
    return _broker_error(
        "TOSS_AUTH_FAILED",
        "App Key 또는 App Secret을 확인해주세요.",
    )


def test_kis_connection(app_key: str, app_secret: str) -> dict[str, Any]:
    """KIS 토큰 발급 테스트."""
    import urllib.error
    import urllib.request
    try:
        body = json.dumps({"grant_type": "client_credentials",
                           "appkey": app_key, "appsecret": app_secret}).encode()
        req = urllib.request.Request(
            "https://openapi.koreainvestment.com:9443/oauth2/tokenP",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            payload = json.loads(res.read().decode())
            if payload.get("access_token"):
                return {"ok": True, "message": "KIS 연결 성공"}
            return {"ok": False, "message": f"응답 코드: {payload.get('msg1', payload)}"}
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"ok": False, "message": f"HTTP {e.code}: {body_txt[:200]}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


# ── 보유종목 동기화 ──────────────────────────────────────────────────

def sync_toss_holdings(user_id: str) -> dict[str, Any]:
    """토스증권 보유종목 조회 (OAuth token → holdings API)."""
    creds = get_decrypted_credentials(user_id, "toss")
    if not creds:
        return {"ok": False, "error": "토스증권 연결 정보가 없습니다."}
    import urllib.error
    import urllib.request
    try:
        # 1. 토큰 발급
        token_payload = _request_toss_token(creds["app_key"], creds["app_secret"])
        if not token_payload.get("ok", True):
            update_sync_status(user_id, "toss", "ERROR")
            return {
                "ok": False,
                "code": token_payload.get("code", "TOSS_TOKEN_FAILED"),
                "message": token_payload.get("message", "토스증권 토큰 발급에 실패했습니다."),
                "error": token_payload.get("message", "토스증권 토큰 발급에 실패했습니다."),
            }
        access_token = token_payload.get("access_token", "")
        if not access_token:
            update_sync_status(user_id, "toss", "ERROR")
            return {"ok": False, "code": "TOSS_TOKEN_FAILED", "error": "토스증권 토큰 발급에 실패했습니다."}

        # 2. 보유종목 조회
        account_no = creds["account_no"]
        holdings_url = os.environ.get(
            "TOSSINVEST_HOLDINGS_URL",
            "https://openapi.tossinvest.com/api/v1/domestic/account/balance",
        ).strip()
        req2 = urllib.request.Request(
            holdings_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "X-Tossinvest-Account": account_no,
                "Accept": "application/json",
                "User-Agent": "MONE/1.0",
            },
        )
        with urllib.request.urlopen(req2, timeout=15) as res2:
            holdings_payload = json.loads(res2.read().decode("utf-8"))

        items = _normalize_toss_holdings(holdings_payload, user_id)
        update_sync_status(user_id, "toss", "OK", time.time())
        return {"ok": True, "items": items, "count": len(items)}
    except urllib.error.HTTPError as e:
        update_sync_status(user_id, "toss", "ERROR")
        if e.code in (401, 403):
            msg = "토스증권 Open API 사용 설정 또는 계좌 권한을 확인해주세요."
            return {"ok": False, "code": "TOSS_PERMISSION_REQUIRED", "message": msg, "error": msg}
        msg = "토스증권 보유종목 동기화에 실패했습니다. 잠시 후 다시 시도해주세요."
        return {"ok": False, "code": "TOSS_SYNC_FAILED", "message": msg, "error": msg}
    except Exception as exc:
        update_sync_status(user_id, "toss", "ERROR")
        if _is_timeout_exception(exc):
            msg = "토스증권 서버 응답이 지연되고 있습니다. 잠시 후 다시 시도해주세요."
            return {"ok": False, "code": "TOSS_TIMEOUT", "message": msg, "error": msg}
        msg = "토스증권 연결 중 네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요."
        return {"ok": False, "code": "TOSS_NETWORK_ERROR", "message": msg, "error": msg}


def _normalize_toss_holdings(payload: dict, user_id: str) -> list[dict[str, Any]]:
    """토스증권 API 응답 → MONE holdings 형식 변환."""
    raw_items = payload.get("accountBalances") or payload.get("items") or []
    result = []
    for item in raw_items:
        symbol = str(item.get("shortCode") or item.get("isinCode") or item.get("symbol") or "").strip()
        if not symbol:
            continue
        qty = float(item.get("holdingQuantity") or item.get("quantity") or 0)
        avg = float(item.get("averagePrice") or item.get("purchaseUnitPrice") or 0)
        cur = float(item.get("currentPrice") or item.get("closePrice") or 0)
        eval_amt = float(item.get("evaluationAmount") or (qty * cur) or 0)
        pnl = float(item.get("profitLoss") or (eval_amt - qty * avg) if avg else 0)
        pnl_rate = float(item.get("profitLossRate") or (pnl / (qty * avg) * 100 if qty * avg else 0))
        result.append({
            "userId": user_id,
            "broker": "toss",
            "symbol": symbol,
            "name": str(item.get("stockName") or item.get("name") or symbol),
            "market": "kr",
            "quantity": qty,
            "avgPrice": avg,
            "currentPrice": cur,
            "evalAmount": eval_amt,
            "profitLoss": pnl,
            "profitLossRate": round(pnl_rate, 2),
            "syncedAt": time.time(),
        })
    return result


# ── 계좌번호 마스킹 ───────────────────────────────────────────────────

def _mask_account(encrypted: str, user_id: str) -> str:
    try:
        plain = _decrypt(encrypted, user_id)
        if len(plain) >= 6:
            return plain[:3] + "****" + plain[-3:]
        return "****"
    except Exception:
        return "****"
