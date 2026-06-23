"""
Entry proximity and holdings-risk Telegram notifier.

Runs once per market, right before that market's open (KR ~08:30 KST,
US ~09:00 ET) — see _is_kr_preopen()/_is_us_preopen(). Outside those
windows (e.g. manual workflow_dispatch), both markets are checked.

Environment variables:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  ENTRY_PROXIMITY_PCT  default 2.0
  NOTIFY_DRY_RUN       "1" prints messages without sending
  NOTIFY_MARKET        "kr" | "us" — force a single market, skip time-window check
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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
DATA = ROOT / "data" / "stockapp"

_BACKEND = str(ROOT / "mone-web-app" / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

HORIZON_TO_RETURN_KEY = {"short": "d1", "swing": "d5", "mid": "d10"}


def _similar_pattern_win_rate(symbol: str, market: str, horizon: str) -> float | None:
    """RSI·볼린저·MACD 상태가 비슷했던 과거 시점들의 승률 (참고용 보조 신호)."""
    try:
        from app.services import data_loader as data
        result = data.similar_pattern_history(symbol, market)
        if result.get("status") != "OK":
            return None
        summary = result.get("summary", {}).get(HORIZON_TO_RETURN_KEY.get(horizon, "d5"))
        if not summary or summary.get("count", 0) < 5:
            return None
        return summary.get("winRate")
    except Exception:
        return None
def _holdings_sources(market: str) -> list[Path]:
    if market == "us":
        return [ROOT / "data" / "holdings_us.csv"]
    return [
        ROOT / "data" / "toss_holdings_kr.csv",
        ROOT / "data" / "kis_2_holdings_kr.csv",
        ROOT / "data" / "kis_holdings_kr.csv",
        ROOT / "data" / "holdings_kr.csv",
        ROOT / "holdings_kr.csv",
    ]


def _is_kr_preopen() -> bool:
    """KR 정규장(09:00 KST) 시작 전 1회만 보내기 위한 시간창 (08:00~08:59 KST)."""
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    return now.weekday() < 5 and now.hour == 8


def _is_us_preopen() -> bool:
    """미장 정규장(09:30 ET) 시작 전 1회만 보내기 위한 시간창 (09:00~09:59 ET).
    워크플로우는 EDT/EST 두 시각 모두 cron을 등록해두고, 실제 발송 여부는
    이 시간창 체크로 걸러서 매일 한 번만 보내도록 한다."""
    now = datetime.now(ZoneInfo("America/New_York"))
    return now.weekday() < 5 and now.hour == 9


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


def _current_holdings_rows(market: str = "kr") -> tuple[str, list[dict[str, str]]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    sources: list[str] = []
    for path in _holdings_sources(market):
        if merged and path.name == f"holdings_{market}.csv" and path.parent.name != "data":
            continue
        rows = [
            row for row in _read_csv(path)
            if _symbol(row) and str(row.get("market") or market).lower() == market and _num(row.get("quantity") or row.get("qty")) > 0
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


def _current_holding_symbols(market: str = "kr") -> set[str]:
    _, rows = _current_holdings_rows(market)
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


def check_entry_proximity(market: str = "kr") -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    seen: set[str] = set()
    held_symbols = _current_holding_symbols(market)

    for mode in MODES:
        for horizon in HORIZONS:
            path = REPORTS / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
            for row in _read_csv(path):
                symbol = _symbol(row)
                if not symbol or symbol in seen:
                    continue

                entry = _num(row.get("entry") or row.get("entryPrice") or 0)
                stop = _num(row.get("stop") or row.get("stopPrice") or 0)
                target = _num(row.get("target") or row.get("targetPrice") or 0)
                name = str(row.get("name") or row.get("stockName") or symbol)

                current = _current_price(symbol, market)
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
                    "similar_win_rate": _similar_pattern_win_rate(symbol, market, horizon),
                })

    return alerts


def check_holdings_risk(market: str = "kr") -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    source, rows = _current_holdings_rows(market)
    for row in rows:
        symbol = _symbol(row)
        name = str(row.get("name") or symbol)
        avg_price = _num(row.get("avgPrice") or row.get("avg_price") or 0)
        qty = _num(row.get("quantity") or row.get("qty") or 0)

        if not symbol or avg_price <= 0 or qty <= 0:
            continue

        current = _current_price(symbol, market) or _num(row.get("currentPrice") or row.get("current_price") or 0)
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
    win_rate = a.get("similar_win_rate")
    similar = f"\n과거 유사 패턴 승률 {win_rate:.0f}% (참고용, 투자 조언 아님)" if win_rate is not None else ""
    return (
        f"<b>추천 후보 진입 임박</b> - {a['name']} ({a['symbol']})\n"
        f"현재가 {a['current']:,.0f}원 / 진입가 {a['entry']:,.0f}원 ({gap_sign} {abs(a['gap_pct']):.1f}%)\n"
        f"전략: {MODE_KR.get(a['mode'], a['mode'])} x {HORIZON_KR.get(a['horizon'], a['horizon'])}\n"
        f"손절 {a['stop']:,.0f} | 목표 {a['target']:,.0f}{similar}{held}"
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


def _alert_key(market: str, a: dict[str, Any]) -> str:
    if a["type"] == "ENTRY":
        return f"{market}_entry_{a['symbol']}_{a['mode']}_{a['horizon']}"
    return f"{market}_{a['type']}_{a['symbol']}"


def _should_send(key: str, state: dict[str, str], cooldown_hours: float = 20.0) -> bool:
    """기본 쿨다운 20시간 — 시장별 장전 1회 발송 기준이라 같은 날 중복 발송만 막으면 된다."""
    last = state.get(key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        elapsed = (datetime.now() - last_dt).total_seconds() / 3600
        return elapsed >= cooldown_hours
    except Exception:
        return True


def _run_market(market: str, state: dict[str, str]) -> int:
    now_kst = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    source_label, current_holdings = _current_holdings_rows(market)
    source_label = source_label or "none"
    print(f"[{now_kst}] [{market}] alert check start (entry +/-{ENTRY_PROXIMITY_PCT}%, stop -6%, target +8%)")
    print(f"  holdings source: {source_label} ({len(current_holdings)} rows)")

    entry_alerts = check_entry_proximity(market)
    holdings_alerts = check_holdings_risk(market)
    all_alerts = entry_alerts + holdings_alerts

    print(f"  recommendation entry alerts: {len(entry_alerts)} | holdings risk/target: {len(holdings_alerts)}")

    if not all_alerts:
        print("  no alerts.")
        return 0

    sent_count = 0
    for alert in all_alerts:
        key = _alert_key(market, alert)
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

    return sent_count


def main() -> None:
    requested = os.environ.get("NOTIFY_MARKET", "").strip().lower()
    if requested in ("kr", "us"):
        markets = [requested]
    else:
        preopen = [m for m, hit in (("kr", _is_kr_preopen()), ("us", _is_us_preopen())) if hit]
        markets = preopen or ["kr", "us"]  # 시간창 밖 수동 실행은 양쪽 다 점검 (테스트용)

    print(f"markets to check: {markets}")
    state = _load_state()
    total_sent = 0
    for market in markets:
        total_sent += _run_market(market, state)
    _save_state(state)
    print(f"done: {total_sent} sent")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] notify_entry_proximity failed: {exc}")
        sys.exit(1)
