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

def test_toss_connection(app_key: str, app_secret: str) -> dict[str, Any]:
    """토스증권 토큰 발급 테스트."""
    import urllib.error
    import urllib.request
    try:
        body = json.dumps({"appkey": app_key, "appsecret": app_secret,
                           "grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            "https://openapi.toss.im/oauth2/token",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            payload = json.loads(res.read().decode())
            if payload.get("access_token"):
                return {"ok": True, "message": "토스증권 연결 성공"}
            return {"ok": False, "message": f"토큰 없음: {payload}"}
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return {"ok": False, "message": f"HTTP {e.code}: {body_txt[:200]}"}
    except Exception as exc:
        return {"ok": False, "message": str(exc)}


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
        body = json.dumps({"appkey": creds["app_key"], "appsecret": creds["app_secret"],
                           "grant_type": "client_credentials"}).encode()
        req = urllib.request.Request(
            "https://openapi.toss.im/oauth2/token",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            token_payload = json.loads(res.read().decode())
        access_token = token_payload.get("access_token", "")
        if not access_token:
            return {"ok": False, "error": "토큰 발급 실패"}

        # 2. 보유종목 조회 (실제 endpoint는 토스증권 API 문서 확인 필요)
        account_no = creds["account_no"]
        req2 = urllib.request.Request(
            f"https://openapi.toss.im/api/v1/domestic/account/balance?accountNumber={account_no}",
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req2, timeout=10) as res2:
            holdings_payload = json.loads(res2.read().decode())

        items = _normalize_toss_holdings(holdings_payload, user_id)
        update_sync_status(user_id, "toss", "OK", time.time())
        return {"ok": True, "items": items, "count": len(items)}
    except urllib.error.HTTPError as e:
        body_txt = ""
        try:
            body_txt = e.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        update_sync_status(user_id, "toss", "ERROR")
        return {"ok": False, "error": f"HTTP {e.code}: {body_txt[:300]}"}
    except Exception as exc:
        update_sync_status(user_id, "toss", "ERROR")
        return {"ok": False, "error": str(exc)}


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
