"""
Entry proximity and holdings-risk Telegram notifier.

Environment variables:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  ENTRY_PROXIMITY_PCT  default 2.0
  NOTIFY_DRY_RUN       "1" prints messages without sending
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stockapp"
CURRENT_HOLDINGS_SOURCES = [
    ROOT / "data" / "toss_holdings_kr.csv",
    ROOT / "data" / "kis_2_holdings_kr.csv",
    ROOT / "data" / "kis_holdings_kr.csv",
    ROOT / "data" / "holdings_kr.csv",
    ROOT / "holdings_kr.csv",
]

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

ENTRY_PROXIMITY_PCT = float(os.environ.get("ENTRY_PROXIMITY_PCT", "2.0"))
DRY_RUN = os.environ.get("NOTIFY_DRY_RUN", "0") == "1"
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


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
        return float(str(val).replace(",", "").replace("%", "").strip())
    except Exception:
        return 0.0


def _symbol(row: dict[str, Any]) -> str:
    raw = str(row.get("symbol") or row.get("code") or row.get("ticker") or "").strip()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits.zfill(6)[-6:] if digits else raw.upper()


def _pct(current: float, level: float) -> float | None:
    if current <= 0 or level <= 0:
        return None
    return (level - current) / current * 100.0


def _current_price(symbol: str, market: str = "kr") -> float | None:
    for path in [
        DATA / f"kis_current_price_{market}.csv",
        REPORTS / f"kis_current_price_{market}.csv",
    ]:
        for row in _read_csv(path):
            sym = _symbol(row)
            if sym.lstrip("0") == symbol.lstrip("0") or sym == symbol:
                price = _num(row.get("currentPrice") or row.get("current_price") or row.get("last_price") or 0)
                if price > 0:
                    return price
    return None


def _current_holdings_rows() -> tuple[str, list[dict[str, str]]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    sources: list[str] = []
    for path in CURRENT_HOLDINGS_SOURCES:
        if merged and path.name == "holdings_kr.csv":
            continue
        rows = [
            row for row in _read_csv(path)
            if _symbol(row) and str(row.get("market") or "kr").lower() == "kr" and _num(row.get("quantity") or row.get("qty")) > 0
        ]
        source_rows = []
        for row in rows:
            symbol = _symbol(row)
            if symbol in seen:
                continue
            seen.add(symbol)
            source_rows.append(row)
        if source_rows:
            merged.extend(source_rows)
            sources.append(str(path.relative_to(ROOT)).replace("\\", "/"))
    return "/".join(sources), merged


def _current_holding_symbols() -> set[str]:
    _, rows = _current_holdings_rows()
    return {_symbol(row) for row in rows if _symbol(row)}


def _send_telegram(text: str) -> bool:
    if DRY_RUN:
        print("[DRY RUN] Telegram:", text[:180])
        return True
    if not BOT_TOKEN or not CHAT_ID:
        print("[WARN] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID is missing. Skip send.")
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
    except Exception as exc:
        print(f"[ERROR] Telegram send failed: {exc}")
        return False


def check_entry_proximity() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()
    held_symbols = _current_holding_symbols()

    for mode in MODES:
        for horizon in HORIZONS:
            path = REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"
            for row in _read_csv(path):
                symbol = _symbol(row)
                if not symbol or symbol in seen:
                    continue

                entry = _num(row.get("entry") or row.get("entryPrice") or 0)
                stop = _num(row.get("stop") or row.get("stopPrice") or 0)
                target = _num(row.get("target") or row.get("targetPrice") or 0)
                name = str(row.get("name") or row.get("stockName") or symbol)

                current = _current_price(symbol, "kr")
                if not current or entry <= 0:
                    continue

                gap = _pct(current, entry)
                if gap is None or abs(gap) > ENTRY_PROXIMITY_PCT:
                    continue

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
                    "already_held": symbol in held_symbols,
                })

    return alerts


def check_holdings_risk() -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    source, rows = _current_holdings_rows()
    for row in rows:
        symbol = _symbol(row)
        name = str(row.get("name") or symbol)
        avg_price = _num(row.get("avgPrice") or row.get("avg_price") or 0)
        qty = _num(row.get("quantity") or row.get("qty") or 0)

        if not symbol or avg_price <= 0 or qty <= 0:
            continue

        current = _current_price(symbol, "kr") or _num(row.get("currentPrice") or row.get("current_price") or 0)
        if not current:
            continue

        pnl_pct = (current - avg_price) / avg_price * 100.0
        base = {
            "symbol": symbol,
            "name": name,
            "current": current,
            "avg_price": avg_price,
            "qty": qty,
            "pnl_pct": pnl_pct,
            "source": source,
        }

        if pnl_pct <= -6.0:
            alerts.append({"type": "STOP_RISK", **base})
        elif pnl_pct >= 8.0:
            alerts.append({"type": "TARGET_NEAR", **base})

    return alerts


MODE_KR = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_KR = {"short": "단기", "swing": "스윙", "mid": "중기"}


def _fmt_entry_alert(a: dict[str, Any]) -> str:
    gap_sign = "위" if a["gap_pct"] > 0 else "아래"
    held = "\n현재 보유 스냅샷에도 있는 종목입니다. 추가 진입 여부를 별도로 확인하세요." if a.get("already_held") else ""
    return (
        f"<b>추천 후보 진입 임박</b> - {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원 / 진입가 {a['entry']:,.0f}원 ({gap_sign} {abs(a['gap_pct']):.1f}%)\n"
        f"전략: {MODE_KR.get(a['mode'], a['mode'])} x {HORIZON_KR.get(a['horizon'], a['horizon'])}\n"
        f"손절 {a['stop']:,.0f} | 목표 {a['target']:,.0f}{held}"
    )


def _fmt_stop_alert(a: dict[str, Any]) -> str:
    return (
        f"<b>보유 종목 손절 근접</b> - {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원 / 평단 {a['avg_price']:,.0f}원\n"
        f"수익률 <b>{a['pnl_pct']:+.1f}%</b> / 수량 {int(a['qty'])}주\n"
        f"보유 기준: {a.get('source') or 'holdings csv'}"
    )


def _fmt_target_alert(a: dict[str, Any]) -> str:
    return (
        f"<b>보유 종목 목표 근접</b> - {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원 / 평단 {a['avg_price']:,.0f}원\n"
        f"수익률 <b>{a['pnl_pct']:+.1f}%</b> / 수량 {int(a['qty'])}주\n"
        f"보유 기준: {a.get('source') or 'holdings csv'}"
    )


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


def _alert_key(a: dict[str, Any]) -> str:
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


def main() -> None:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    source_label, current_holdings = _current_holdings_rows()
    source_label = source_label or "none"
    print(f"[{now_kst}] alert check start (entry +/-{ENTRY_PROXIMITY_PCT}%, stop -6%, target +8%)")
    print(f"  holdings source: {source_label} ({len(current_holdings)} rows)")

    entry_alerts = check_entry_proximity()
    holdings_alerts = check_holdings_risk()
    all_alerts = entry_alerts + holdings_alerts

    print(f"  recommendation entry alerts: {len(entry_alerts)} | holdings risk/target: {len(holdings_alerts)}")

    if not all_alerts:
        print("  no alerts.")
        return

    state = _load_state()
    sent_count = 0

    for alert in all_alerts:
        key = _alert_key(alert)
        if not _should_send(key, state):
            print(f"  [{key}] cooldown skip")
            continue

        if alert["type"] == "ENTRY":
            msg = _fmt_entry_alert(alert)
        elif alert["type"] == "STOP_RISK":
            msg = _fmt_stop_alert(alert)
        else:
            msg = _fmt_target_alert(alert)

        print(f"  send: {key}")
        if _send_telegram(msg):
            state[key] = datetime.now().isoformat()
            sent_count += 1

    _save_state(state)
    print(f"  done: {sent_count} sent")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] notify_entry_proximity failed: {exc}")
        sys.exit(1)
