"""
Telegram 알림 서비스.

환경변수:
  TELEGRAM_BOT_TOKEN   - BotFather에서 발급받은 봇 토큰
  TELEGRAM_CHAT_ID     - 알림 수신 채팅방/유저 ID
  TELEGRAM_THRESHOLD_PCT   - 근접 알림 임계값 (기본 1.0%)
  TELEGRAM_INTERVAL_MIN    - 체크 주기 (기본 15분)
  TELEGRAM_COOLDOWN_HOURS  - 동일 알림 재발송 유예 시간 (기본 4시간)
"""
from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import requests

BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
THRESHOLD_PCT: float = float(os.getenv("TELEGRAM_THRESHOLD_PCT", "1.0"))
INTERVAL_MIN: float = float(os.getenv("TELEGRAM_INTERVAL_MIN", "15.0"))
COOLDOWN_HOURS: float = float(os.getenv("TELEGRAM_COOLDOWN_HOURS", "4.0"))

_sent_cache: dict[str, datetime] = {}
_lock = threading.Lock()
_last_check: dict[str, Any] = {}


def is_enabled() -> bool:
    return bool(BOT_TOKEN and CHAT_ID)


def send_message(text: str, parse_mode: str = "HTML") -> dict[str, Any]:
    if not BOT_TOKEN or not CHAT_ID:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정"}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        data = r.json()
        return {"ok": r.status_code == 200 and data.get("ok", False), "response": data}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def _alert_key(alert: dict) -> str:
    return f"{alert['type']}:{alert['symbol']}:{alert['market']}"


def _should_send(key: str) -> bool:
    with _lock:
        last = _sent_cache.get(key)
        if last is None:
            return True
        return datetime.now() - last > timedelta(hours=COOLDOWN_HOURS)


def _mark_sent(key: str) -> None:
    with _lock:
        _sent_cache[key] = datetime.now()


def _format_stop(alert: dict) -> str:
    gap = alert["gapPct"]
    urgency = "🚨" if gap <= 0.5 else "🔴"
    return (
        f"{urgency} <b>[MONE] 손절가 근접 경고</b>\n"
        f"종목: <b>{alert['name']}</b> ({alert['symbol']} / {alert['market'].upper()})\n"
        f"현재가: <b>{alert['currentPrice']:,.0f}</b>\n"
        f"손절가: <b>{alert['stopPrice']:,.0f}</b>\n"
        f"남은 거리: <b>{gap:.1f}%</b>\n"
        f"⏰ {datetime.now().strftime('%m/%d %H:%M')}"
    )


def _format_target(alert: dict) -> str:
    gap = alert["gapPct"]
    urgency = "🎉" if gap <= 0.5 else "🎯"
    return (
        f"{urgency} <b>[MONE] 목표가 근접</b>\n"
        f"종목: <b>{alert['name']}</b> ({alert['symbol']} / {alert['market'].upper()})\n"
        f"현재가: <b>{alert['currentPrice']:,.0f}</b>\n"
        f"목표가: <b>{alert['targetPrice']:,.0f}</b>\n"
        f"남은 거리: <b>{gap:.1f}%</b>\n"
        f"⏰ {datetime.now().strftime('%m/%d %H:%M')}"
    )


def _fetch_near_alerts(threshold_pct: float) -> list[dict]:
    from app.engine.mone_v77_holdings_risk import holdings_payload

    alerts: list[dict] = []
    for mk in ["kr", "us"]:
        try:
            hp = holdings_payload(mk, 100)
        except Exception:
            continue
        for h in hp.get("items", []):
            current = float(h.get("currentPrice") or 0)
            stop = float(h.get("stop") or h.get("stopPrice") or 0)
            target = float(h.get("target") or h.get("targetPrice") or 0)
            sym = str(h.get("symbol", "")).strip()
            name = str(h.get("name", sym)).strip()

            if current > 0 and stop > 0:
                gap = (current - stop) / current * 100
                if 0 < gap <= threshold_pct * 5:
                    alerts.append({
                        "type": "STOP",
                        "symbol": sym,
                        "name": name,
                        "market": mk,
                        "currentPrice": current,
                        "stopPrice": stop,
                        "gapPct": round(gap, 2),
                    })

            if current > 0 and target > 0 and current < target:
                gap = (target - current) / current * 100
                if 0 < gap <= threshold_pct * 5:
                    alerts.append({
                        "type": "TARGET",
                        "symbol": sym,
                        "name": name,
                        "market": mk,
                        "currentPrice": current,
                        "targetPrice": target,
                        "gapPct": round(gap, 2),
                    })

    return sorted(alerts, key=lambda x: x["gapPct"])


def check_and_send(threshold_pct: float | None = None, force: bool = False) -> dict[str, Any]:
    """근접 알림 체크 후 Telegram 발송. 결과 dict 반환."""
    thr = threshold_pct if threshold_pct is not None else THRESHOLD_PCT
    alerts = _fetch_near_alerts(thr)

    result: dict[str, Any] = {
        "checkedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "enabled": is_enabled(),
        "thresholdPct": thr,
        "total": len(alerts),
        "sent": 0,
        "skipped": 0,
        "errors": 0,
        "items": alerts,
    }

    if not is_enabled():
        result["message"] = "TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정"
        _last_check.update(result)
        return result

    for alert in alerts:
        key = _alert_key(alert)
        if not force and not _should_send(key):
            result["skipped"] += 1
            continue
        text = _format_stop(alert) if alert["type"] == "STOP" else _format_target(alert)
        r = send_message(text)
        if r.get("ok"):
            _mark_sent(key)
            result["sent"] += 1
        else:
            result["errors"] += 1
        time.sleep(0.3)

    _last_check.update(result)
    return result


def get_status() -> dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "botTokenSet": bool(BOT_TOKEN),
        "chatIdSet": bool(CHAT_ID),
        "thresholdPct": THRESHOLD_PCT,
        "intervalMin": INTERVAL_MIN,
        "cooldownHours": COOLDOWN_HOURS,
        "lastCheck": dict(_last_check),
        "pendingCooldowns": {
            k: v.strftime("%Y-%m-%d %H:%M:%S")
            for k, v in _sent_cache.items()
        },
    }


def _alert_loop(interval_minutes: float) -> None:
    time.sleep(300)  # 시작 후 5분 대기
    while True:
        try:
            result = check_and_send()
            if result.get("sent", 0) > 0:
                print(f"[TelegramAlert] {result['checkedAt']} sent={result['sent']} skipped={result['skipped']}")
        except Exception as exc:
            print(f"[TelegramAlert] error: {exc}")
        time.sleep(interval_minutes * 60)


def start_scheduler() -> None:
    if not is_enabled():
        print("[TelegramAlert] 비활성 (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정)")
        return
    t = threading.Thread(target=_alert_loop, args=(INTERVAL_MIN,), daemon=True)
    t.start()
    print(f"[TelegramAlert] 스케줄러 시작 (임계값={THRESHOLD_PCT}%, 주기={INTERVAL_MIN}분)")
