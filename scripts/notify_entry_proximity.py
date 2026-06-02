"""
진입가 근접 / 손절 근접 알림 스크립트.

조건:
  - 추천 종목: 현재가가 진입가 ±2% 이내  → "진입 임박" 알림
  - 보유 종목: 현재가가 손절가 ±2% 이내  → "손절 근접" 경고
  - 보유 종목: 현재가가 목표가 ±2% 이내  → "목표 도달" 알림

환경변수:
  TELEGRAM_BOT_TOKEN  텔레그램 봇 토큰
  TELEGRAM_CHAT_ID    수신 Chat ID
  ENTRY_PROXIMITY_PCT 진입 근접 임계값 (기본 2.0)
  NOTIFY_DRY_RUN      "1" 이면 실제 전송 없이 로그만 출력
"""
from __future__ import annotations

import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
REPORTS     = ROOT / "reports"
DATA        = ROOT / "data" / "stockapp"
HOLDINGS_CSV = ROOT / "holdings_kr.csv"

MODES    = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

ENTRY_PROXIMITY_PCT = float(os.environ.get("ENTRY_PROXIMITY_PCT", "2.0"))
DRY_RUN             = os.environ.get("NOTIFY_DRY_RUN", "0") == "1"
BOT_TOKEN           = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID             = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── 유틸 ──────────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _num(val: Any) -> float:
    try:
        return float(str(val).replace(",", "").strip())
    except Exception:
        return 0.0


def _pct(current: float, level: float) -> float | None:
    if current <= 0 or level <= 0:
        return None
    return (level - current) / current * 100.0


def _current_price(symbol: str, market: str = "kr") -> float | None:
    """KIS 현재가 CSV에서 종목 현재가 조회."""
    for p in [
        DATA / f"kis_current_price_{market}.csv",
        REPORTS / f"kis_current_price_{market}.csv",
    ]:
        for row in _read_csv(p):
            sym = str(row.get("symbol") or row.get("code") or "").strip()
            if sym.lstrip("0") == symbol.lstrip("0") or sym == symbol:
                price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price") or 0)
                if price > 0:
                    return price
    return None


def _send_telegram(text: str) -> bool:
    if DRY_RUN:
        print("[DRY RUN] Telegram:", text[:120])
        return True
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 미설정 — 전송 생략")
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()
    try:
        with urllib.request.urlopen(url, data, timeout=10) as resp:
            result = json.loads(resp.read())
            return bool(result.get("ok"))
    except Exception as e:
        print(f"[ERROR] Telegram 전송 실패: {e}")
        return False


# ── 추천 종목 진입가 근접 체크 ──────────────────────────────────────────────

def check_entry_proximity() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for mode in MODES:
        for horizon in HORIZONS:
            path = REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
            for row in _read_csv(path):
                symbol = str(row.get("symbol") or row.get("code") or "").strip().lstrip("0").zfill(6)
                if not symbol or symbol in seen:
                    continue

                entry  = _num(row.get("entry") or row.get("entryPrice") or 0)
                stop   = _num(row.get("stop")  or row.get("stopPrice")  or 0)
                target = _num(row.get("target") or row.get("targetPrice") or 0)
                name   = str(row.get("name") or row.get("stockName") or symbol)

                current = _current_price(symbol, "kr")
                if not current or entry <= 0:
                    continue

                gap = _pct(current, entry)
                if gap is None:
                    continue

                if abs(gap) <= ENTRY_PROXIMITY_PCT:
                    seen.add(symbol)
                    alerts.append({
                        "type": "ENTRY",
                        "symbol": symbol,
                        "name": name,
                        "mode": mode,
                        "horizon": horizon,
                        "current": current,
                        "entry": entry,
                        "stop": stop,
                        "target": target,
                        "gap_pct": gap,
                    })

    return alerts


# ── 보유종목 손절/목표 근접 체크 ────────────────────────────────────────────

def check_holdings_risk() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    for row in _read_csv(HOLDINGS_CSV):
        symbol   = str(row.get("symbol") or row.get("code") or "").strip().lstrip("0").zfill(6)
        market   = str(row.get("market") or "kr").lower()
        name     = str(row.get("name") or symbol)
        avg_price = _num(row.get("avgPrice") or row.get("avg_price") or 0)
        qty      = _num(row.get("quantity") or row.get("qty") or 0)

        if not symbol or market != "kr" or avg_price <= 0:
            continue

        current = _current_price(symbol, "kr")
        if not current:
            continue

        pnl_pct = (current - avg_price) / avg_price * 100.0

        # 손절 근접: -7% 이하 (스윙 기준 손절폭 -5~-8%)
        if pnl_pct <= -6.0:
            alerts.append({
                "type": "STOP_RISK",
                "symbol": symbol,
                "name": name,
                "current": current,
                "avg_price": avg_price,
                "qty": qty,
                "pnl_pct": pnl_pct,
            })
        # 목표 근접: +8% 이상 (스윙 기준 목표 +8~+18%)
        elif pnl_pct >= 8.0:
            alerts.append({
                "type": "TARGET_NEAR",
                "symbol": symbol,
                "name": name,
                "current": current,
                "avg_price": avg_price,
                "qty": qty,
                "pnl_pct": pnl_pct,
            })

    return alerts


# ── 메시지 포맷 ──────────────────────────────────────────────────────────────

MODE_KR    = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_KR = {"short": "단기", "swing": "스윙", "mid": "중기"}


def _fmt_entry_alert(a: dict) -> str:
    gap_sign = "▲" if a["gap_pct"] > 0 else "▼"
    return (
        f"🎯 <b>진입 임박</b> — {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원  진입가 {a['entry']:,.0f}원 ({gap_sign}{abs(a['gap_pct']):.1f}%)\n"
        f"전략: {MODE_KR.get(a['mode'], a['mode'])} × {HORIZON_KR.get(a['horizon'], a['horizon'])}\n"
        f"손절 {a['stop']:,.0f} | 목표 {a['target']:,.0f}"
    )


def _fmt_stop_alert(a: dict) -> str:
    return (
        f"⚠️ <b>손절 근접</b> — {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원  평단 {a['avg_price']:,.0f}원\n"
        f"손익 <b>{a['pnl_pct']:+.1f}%</b>  수량 {int(a['qty'])}주"
    )


def _fmt_target_alert(a: dict) -> str:
    return (
        f"✅ <b>목표 도달</b> — {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원  평단 {a['avg_price']:,.0f}원\n"
        f"수익 <b>{a['pnl_pct']:+.1f}%</b>  수량 {int(a['qty'])}주"
    )


# ── 알림 상태 저장 (중복 전송 방지) ─────────────────────────────────────────

ALERT_STATE_PATH = REPORTS / "notification_alert_state.json"


def _load_state() -> dict[str, str]:
    try:
        if ALERT_STATE_PATH.exists():
            return json.loads(ALERT_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state: dict[str, str]) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        ALERT_STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _alert_key(a: dict) -> str:
    if a["type"] == "ENTRY":
        return f"entry_{a['symbol']}_{a['mode']}_{a['horizon']}"
    return f"{a['type']}_{a['symbol']}"


def _should_send(key: str, state: dict[str, str], cooldown_hours: float = 2.0) -> bool:
    last = state.get(key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        elapsed = (datetime.now() - last_dt).total_seconds() / 3600
        return elapsed >= cooldown_hours
    except Exception:
        return True


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main() -> None:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    print(f"[{now_kst}] 알림 체크 시작 (진입임박 ±{ENTRY_PROXIMITY_PCT}%, 손절 -6%, 목표 +8%)")

    entry_alerts   = check_entry_proximity()
    holdings_alerts = check_holdings_risk()
    all_alerts = entry_alerts + holdings_alerts

    print(f"  진입 임박: {len(entry_alerts)}건  |  보유 위험/목표: {len(holdings_alerts)}건")

    if not all_alerts:
        print("  알림 없음.")
        return

    state = _load_state()
    sent_count = 0

    for a in all_alerts:
        key = _alert_key(a)
        if not _should_send(key, state):
            print(f"  [{key}] 쿨다운 중 — 생략")
            continue

        if a["type"] == "ENTRY":
            msg = _fmt_entry_alert(a)
        elif a["type"] == "STOP_RISK":
            msg = _fmt_stop_alert(a)
        else:
            msg = _fmt_target_alert(a)

        print(f"  전송: {key}")
        ok = _send_telegram(msg)
        if ok:
            state[key] = datetime.now().isoformat()
            sent_count += 1

    _save_state(state)
    print(f"  완료: {sent_count}건 전송")


if __name__ == "__main__":
    main()
