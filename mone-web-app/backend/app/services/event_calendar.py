"""
event_calendar.py — 이벤트 캘린더 서비스

data/calendar/macro_calendar.csv      → 매크로 경제지표 일정
data/calendar/earnings_calendar.csv   → 실적발표 일정

주요 함수:
  upcoming_macro(market, days)          → 향후 N일 매크로 이벤트 목록
  upcoming_earnings(market, days, syms) → 향후 N일 실적 목록
  today_high_impact(market)             → 오늘 HIGH 이벤트 요약
  event_risk_boost(market, symbol)      → 추천 엔진용 리스크 가산점 (0~30)
"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import data_loader as data

_CALENDAR_DIR   = Path(data.REPO_ROOT) / "data" / "calendar"
_MACRO_PATH     = _CALENDAR_DIR / "macro_calendar.csv"
_EARNINGS_PATH  = _CALENDAR_DIR / "earnings_calendar.csv"

# 캐시 TTL: 파일 mtime 변경 시 자동 갱신 (아래 _load_* 참조)
_macro_cache:    tuple[float, list[dict]] | None = None
_earnings_cache: tuple[float, list[dict]] | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _file_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except Exception:
        return 0.0


def _load_macro() -> list[dict]:
    global _macro_cache
    mtime = _file_mtime(_MACRO_PATH)
    if _macro_cache and _macro_cache[0] == mtime:
        return _macro_cache[1]
    rows = _read_csv(_MACRO_PATH)
    _macro_cache = (mtime, rows)
    return rows


def _load_earnings() -> list[dict]:
    global _earnings_cache
    mtime = _file_mtime(_EARNINGS_PATH)
    if _earnings_cache and _earnings_cache[0] == mtime:
        return _earnings_cache[1]
    rows = _read_csv(_EARNINGS_PATH)
    _earnings_cache = (mtime, rows)
    return rows


def _norm_impact(impact: str) -> str:
    v = impact.strip().lower()
    if v in {"1", "high", "critical", "high_impact"}:
        return "high"
    if v in {"2", "medium", "moderate"}:
        return "medium"
    return "low"


def _parse_date(s: str) -> str | None:
    """YYYY-MM-DD 형식만 허용, 아니면 None"""
    s = str(s or "").strip()[:10]
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s
    return None


def upcoming_macro(
    market: str = "us",
    days: int = 30,
    impact_min: str = "low",
) -> list[dict[str, Any]]:
    """향후 N일 매크로 이벤트 목록 (impact_min 이상만)"""
    today = datetime.now().strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    mkt   = market.lower()

    _impact_order = {"low": 0, "medium": 1, "high": 2}
    min_level = _impact_order.get(impact_min.lower(), 0)

    rows = []
    for r in _load_macro():
        if r.get("market", "").lower() != mkt:
            continue
        d = _parse_date(r.get("date", ""))
        if not d or not (today <= d <= end):
            continue
        if _impact_order.get(_norm_impact(r.get("impact", "")), 0) < min_level:
            continue
        today_dt = datetime.now().date()
        event_dt = datetime.strptime(d, "%Y-%m-%d").date()
        dday = (event_dt - today_dt).days
        rows.append({
            **r,
            "impact": _norm_impact(r.get("impact", "")),
            "dday": dday,
            "badge": "📣 오늘" if dday == 0 else (f"D-{dday}" if dday > 0 else f"D+{abs(dday)}"),
        })
    return sorted(rows, key=lambda x: (x.get("date", ""), x.get("impact", "") != "high"))


def upcoming_earnings(
    market: str = "us",
    days: int = 14,
    symbols: list[str] | None = None,
    tracked_only: bool = False,
) -> list[dict[str, Any]]:
    """향후 N일 실적 목록"""
    today = datetime.now().strftime("%Y-%m-%d")
    end   = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    mkt   = market.lower()
    sym_filter = {s.upper() for s in symbols} if symbols else None

    rows = []
    for r in _load_earnings():
        if r.get("market", "").lower() != mkt:
            continue
        d = _parse_date(r.get("date", ""))
        if not d or not (today <= d <= end):
            continue
        sym = str(r.get("symbol", "")).upper()
        if sym_filter and sym not in sym_filter:
            continue
        if tracked_only and str(r.get("tracked", "")).upper() != "Y":
            continue
        today_dt = datetime.now().date()
        event_dt = datetime.strptime(d, "%Y-%m-%d").date()
        dday = (event_dt - today_dt).days
        rows.append({
            **r,
            "dday": dday,
        })
    return sorted(rows, key=lambda x: x.get("date", ""))


def today_high_impact(market: str = "us") -> dict[str, Any]:
    """오늘 HIGH impact 이벤트 요약 + 향후 3일 이벤트 포함"""
    today_str  = datetime.now().strftime("%Y-%m-%d")
    tomorrow   = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    day3       = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    mkt = market.lower()

    macro_all  = upcoming_macro(mkt, days=3, impact_min="low")
    earn_all   = upcoming_earnings(mkt, days=3)

    today_macro  = [e for e in macro_all  if e.get("date") == today_str]
    today_earn   = [e for e in earn_all   if e.get("date") == today_str]
    tmrw_macro   = [e for e in macro_all  if e.get("date") == tomorrow]
    tmrw_earn    = [e for e in earn_all   if e.get("date") == tomorrow]

    high_today   = [e for e in today_macro if e.get("impact") == "high"]
    med_today    = [e for e in today_macro if e.get("impact") == "medium"]
    high_tmrw    = [e for e in tmrw_macro  if e.get("impact") == "high"]

    # 종합 위험도
    risk_level = "low"
    if high_today or (len(today_earn) >= 2):
        risk_level = "high"
    elif med_today or today_earn or high_tmrw:
        risk_level = "medium"

    return {
        "market":     mkt,
        "today":      today_str,
        "riskLevel":  risk_level,
        "todayHighMacro":  high_today,
        "todayAllMacro":   today_macro,
        "todayEarnings":   today_earn,
        "tomorrowHighMacro": high_tmrw,
        "tomorrowEarnings":  tmrw_earn,
        "hasHighAlert":  bool(high_today),
        "hasMedAlert":   bool(med_today or today_earn),
        "alertMessage": _build_alert_msg(high_today, today_earn, high_tmrw, mkt),
    }


def _build_alert_msg(
    high_macro: list[dict],
    today_earn: list[dict],
    tmrw_high: list[dict],
    market: str,
) -> str:
    parts: list[str] = []
    if high_macro:
        names = [e.get("event", "") for e in high_macro[:3]]
        parts.append("🔴 오늘 주요 지표: " + " / ".join(n for n in names if n))
    if today_earn:
        syms = [e.get("symbol", e.get("name", "")) for e in today_earn[:3]]
        parts.append("📊 오늘 실적: " + ", ".join(s for s in syms if s))
    if tmrw_high and not high_macro:
        names = [e.get("event", "") for e in tmrw_high[:2]]
        parts.append("⚠️ 내일 예정: " + " / ".join(n for n in names if n))
    return " | ".join(parts) if parts else ""


def event_risk_boost(market: str, symbol: str | None = None) -> int:
    """
    추천 엔진 eventRisk 가산점 (0~30).
    오늘 HIGH macro → +25
    오늘 MEDIUM macro / 오늘 실적 → +12
    내일 HIGH macro → +10
    종목 실적 3일 이내 → +8
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    d3 = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    mkt = market.lower()

    boost = 0

    macro_today = [r for r in _load_macro()
                   if r.get("market") == mkt and r.get("date") == today]
    if any(_norm_impact(r.get("impact", "")) == "high" for r in macro_today):
        boost += 25
    elif macro_today:
        boost += 12

    macro_tmrw = [r for r in _load_macro()
                  if r.get("market") == mkt and r.get("date") == tomorrow
                  and _norm_impact(r.get("impact", "")) == "high"]
    if macro_tmrw:
        boost += 10

    # 종목별 실적 (symbol 지정 시)
    if symbol:
        sym_up = symbol.upper()
        earn_soon = [r for r in _load_earnings()
                     if r.get("market") == mkt
                     and r.get("symbol", "").upper() == sym_up
                     and today <= (r.get("date") or "") <= d3]
        if earn_soon:
            boost += 8

    return min(boost, 30)
