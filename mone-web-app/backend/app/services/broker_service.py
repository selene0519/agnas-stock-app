"""Broker connection state for the local bridge model.

MONE must not call broker APIs from Render because some broker APIs reject
cloud-hosted IPs and because App Secrets should stay on the user's PC. This
module stores only sanitized local-bridge sync status. It intentionally does
not persist App Key, App Secret, account password, or access tokens.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from app.services import data_loader as data
from app import db as _db

_LEGACY_BROKER_DIR = data.APP_DIR / "backend" / "broker_credentials"
_BRIDGE_DIR = data.APP_DIR / "backend" / "broker_bridge_status"
_BROKERS = ("toss", "kis", "manual")


def _safe_part(value: str) -> str:
    return "".join(c if c.isalnum() or c in "-_:" else "_" for c in str(value or ""))[:80]


def _bridge_path(user_id: str, broker: str) -> Path:
    return _BRIDGE_DIR / f"{_safe_part(user_id)}_{broker.lower().strip()}.json"


def _legacy_path(user_id: str, broker: str) -> Path:
    return _LEGACY_BROKER_DIR / f"{_safe_part(user_id)}_{broker.lower().strip()}.json"


def _ensure_dir() -> None:
    _BRIDGE_DIR.mkdir(parents=True, exist_ok=True)


def save_bridge_status(
    user_id: str,
    broker: str,
    *,
    account_no_hint: str = "",
    item_count: int = 0,
    sync_time: float | None = None,
    source: str = "local_bridge",
) -> None:
    """Persist sanitized local bridge status — DB primary, file fallback."""
    broker = broker.lower().strip()
    if broker not in ("toss", "kis", "manual", "file"):
        broker = "manual"
    now = float(sync_time or time.time())
    record = {
        "broker": broker,
        "connected": True,
        "connection_mode": "local_bridge",
        "sync_status": "OK",
        "last_sync": now,
        "connected_at": now,
        "account_no_hint": str(account_no_hint or ""),
        "item_count": int(item_count or 0),
        "source": source,
    }
    # DB (Supabase/SQLite) — survives Render restarts
    try:
        _db.save_broker_connection(user_id, broker, record)
    except Exception as e:
        print(f"[broker] db save error: {type(e).__name__}")
    # File fallback (for local dev / backward compat)
    try:
        _ensure_dir()
        _bridge_path(user_id, broker).write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def get_bridge_status(user_id: str, broker: str) -> dict[str, Any] | None:
    # Try DB first (persistent across restarts)
    try:
        db_result = _db.get_broker_connection(user_id, broker)
        if db_result:
            return db_result
    except Exception as e:
        print(f"[broker] db get error: {type(e).__name__}")
    # Fall back to file
    path = _bridge_path(user_id, broker)
    if not path.exists():
        return None
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {
            "broker": broker,
            "connected": False,
            "status": "LOAD_ERROR",
            "connectionMode": "local_bridge",
        }
    return {
        "broker": broker,
        "connected": bool(rec.get("connected", True)),
        "status": rec.get("sync_status", "OK"),
        "connectionMode": rec.get("connection_mode", "local_bridge"),
        "lastSync": rec.get("last_sync"),
        "connectedAt": rec.get("connected_at"),
        "accountNoHint": rec.get("account_no_hint", ""),
        "itemCount": rec.get("item_count", 0),
        "source": rec.get("source", "local_bridge"),
    }


def get_connection_status(user_id: str, broker: str) -> dict[str, Any]:
    """Return broker status without exposing or using credentials."""
    broker = broker.lower().strip()
    bridge = get_bridge_status(user_id, broker)
    if bridge:
        return bridge
    if _legacy_path(user_id, broker).exists():
        return {
            "broker": broker,
            "connected": False,
            "status": "LOCAL_BRIDGE_REQUIRED",
            "connectionMode": "local_bridge",
            "legacyCredential": True,
        }
    return {
        "broker": broker,
        "connected": False,
        "status": "NOT_CONNECTED",
        "connectionMode": "local_bridge",
    }


def get_all_connections(user_id: str) -> list[dict[str, Any]]:
    return [get_connection_status(user_id, broker) for broker in _BROKERS]


def disconnect(user_id: str, broker: str) -> None:
    broker = broker.lower().strip()
    for path in (_bridge_path(user_id, broker), _legacy_path(user_id, broker)):
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def local_bridge_mode_response(broker: str) -> dict[str, Any]:
    return {
        "ok": True,
        "testPassed": True,
        "code": "LOCAL_BRIDGE_MODE",
        "broker": broker,
        "message": (
            "증권사 API 호출은 Render가 아니라 로컬 PC 브릿지에서 실행합니다. "
            "앱에는 App Secret 없이 정제된 보유종목 스냅샷만 업로드됩니다."
        ),
    }


# Legacy compatibility: old routes/components may still import these names.
def save_connection(*_: Any, **__: Any) -> None:
    raise RuntimeError("Cloud broker credential storage is disabled. Use the local bridge upload endpoint.")


def get_decrypted_credentials(*_: Any, **__: Any) -> None:
    return None


def update_sync_status(user_id: str, broker: str, status: str, sync_time: float | None = None) -> None:
    bridge = get_bridge_status(user_id, broker)
    if not bridge:
        return
    save_bridge_status(
        user_id,
        broker,
        account_no_hint=str(bridge.get("accountNoHint") or ""),
        item_count=int(bridge.get("itemCount") or 0),
        sync_time=sync_time or bridge.get("lastSync") or time.time(),
    )


def test_toss_connection(*_: Any, **__: Any) -> dict[str, Any]:
    return local_bridge_mode_response("toss")


def test_kis_connection(*_: Any, **__: Any) -> dict[str, Any]:
    return local_bridge_mode_response("kis")


def sync_toss_holdings(*_: Any, **__: Any) -> dict[str, Any]:
    return {
        "ok": False,
        "code": "LOCAL_BRIDGE_UPLOAD_REQUIRED",
        "message": "토스증권 보유종목은 로컬 브릿지에서 조회한 뒤 업로드해야 합니다.",
    }
