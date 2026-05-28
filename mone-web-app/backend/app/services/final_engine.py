from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from functools import lru_cache
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from app.services import data_loader as data

MARKETS = ("kr", "us")
MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}
HORIZON_DAYS = {"short": 1, "swing": 5, "mid": 20}
HORIZON_PROB_FIELD = {"short": "prob1d", "swing": "prob5d", "mid": "prob20d"}
HORIZON_PRICE_FIELD = {"short": "expectedPrice1dText", "swing": "expectedPrice5dText", "mid": "expectedPrice20dText"}

MODE_RULES = {
    "conservative": {"min_opportunity": 68, "min_entry": 64, "max_risk": 38, "max_gap": 0.035, "max_items": 5, "risk_mult": 0.82},
    "balanced": {"min_opportunity": 58, "min_entry": 54, "max_risk": 56, "max_gap": 0.075, "max_items": 8, "risk_mult": 1.0},
    "aggressive": {"min_opportunity": 48, "min_entry": 42, "max_risk": 74, "max_gap": 0.13, "max_items": 12, "risk_mult": 1.25},
}

EVENT_KEYWORDS = {
    "macro": ("FOMC", "CPI", "PPI", "PCE", "고용", "금리", "파월", "환율", "국채", "yield"),
    "earnings": ("실적", "earnings", "분기", "컨센서스", "EPS", "guidance", "가이던스"),
    "disclosure_good": ("수주", "공급계약", "계약", "자사주", "배당", "흑자", "승인", "FDA", "임상 성공"),
    "disclosure_risk": ("증자", "CB", "전환사채", "BW", "관리종목", "상장폐지", "감사의견", "소송", "유상증자"),
    "theme": ("테마", "급등", "상한가", "IPO", "상장", "보호예수", "락업", "신규상장"),
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any) -> float | None:
    return data._safe_float(value)  # type: ignore[attr-defined]


def _pct(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.replace("%", "").replace(",", "").strip()
    n = _num(value)
    if n is None:
        return None
    if 0 <= n <= 1:
        return n * 100
    return n


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    return str(value).strip()


def _has(text: str, words: Iterable[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def _symbol(item: dict[str, Any], market: str) -> str:
    return data.normalize_symbol(item.get("symbol") or data.first_value(item.get("raw", item), data.SYMBOL_ALIASES, ""), market)


def _raw(item: dict[str, Any]) -> dict[str, Any]:
    raw = item.get("raw")
    return dict(raw) if isinstance(raw, dict) else dict(item)


def _latest_ohlcv(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    try:
        return data._load_ohlcv(symbol, market)  # type: ignore[attr-defined]
    except Exception:
        return pd.DataFrame(), ""


OPERATIONAL_VERSION = "v3.6.1-operational-stable"


def _to_ts(value: Any) -> pd.Timestamp | None:
    """Parse a date/time value safely. Returns None if parsing fails."""
    text = _as_text(value)
    if not text:
        return None
    # Common KST strings contain extra labels; keep the date/time-looking prefix.
    text = text.replace("KST", "").replace("kst", "").strip()
    ts = pd.to_datetime(text, errors="coerce")
    if pd.isna(ts):
        # Try YYYYMMDD embedded in filenames/fields.
        m = re.search(r"(20\d{6})", text)
        if m:
            ts = pd.to_datetime(m.group(1), format="%Y%m%d", errors="coerce")
    if pd.isna(ts):
        return None
    return ts.normalize()


def _prediction_date(row: dict[str, Any]) -> pd.Timestamp | None:
    for key in ("prediction_date", "created_at", "run_time_kst", "prediction_at", "target_date", "actual_date", "date", "날짜"):
        ts = _to_ts(row.get(key))
        if ts is not None:
            return ts
    return None


def _ohlcv_with_dates(symbol: str, market: str) -> tuple[pd.DataFrame, str]:
    df, source = _latest_ohlcv(symbol, market)
    if df.empty:
        return df, source
    work = df.copy()
    work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").reset_index(drop=True)
    return work, source


def _actual_close_after(symbol: str, market: str, base_date: pd.Timestamp | None, trading_day_offset: int) -> tuple[float | None, str, str]:
    """Return close at Nth trading day after base_date from stored OHLCV."""
    if base_date is None:
        return None, "", "예측일 부족"
    df, source = _ohlcv_with_dates(symbol, market)
    if df.empty:
        return None, source, "OHLCV 없음"
    future = df[df["_date_ts"] > base_date]
    if len(future) < trading_day_offset:
        return None, source, f"D+{trading_day_offset} 거래일 미도래"
    row = future.iloc[trading_day_offset - 1]
    close = _num(row.get("close"))
    date_text = _as_text(row.get("date"))
    return close, source, date_text


@lru_cache(maxsize=256)
def _evaluation_window(symbol: str, market: str, horizon: str) -> tuple[pd.DataFrame, str]:
    df, source = _ohlcv_with_dates(symbol, market)
    if df.empty:
        return df, source
    # Use enough bars to evaluate fill and exit. Keep the window deterministic.
    days = max(1, HORIZON_DAYS.get(horizon, 5))
    return df.tail(days).reset_index(drop=True), source


def _row_date_text(row: pd.Series) -> str:
    return _as_text(row.get("date")) or _as_text(row.get("_date_ts"))


def _calendar_files() -> list[Path]:
    candidates: list[Path] = []
    for base in (data.DATA_DIR, data.REPORT_DIR, data.REPO_ROOT):
        for rel in (
            "calendar/macro_calendar.csv",
            "calendar/earnings_calendar.csv",
            "calendar/ipo_lockup_calendar.csv",
            "calendar/event_calendar.csv",
            "macro_calendar.csv",
            "earnings_calendar.csv",
            "ipo_lockup_calendar.csv",
            "event_calendar.csv",
        ):
            path = base / rel
            if path.exists():
                candidates.append(path)
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        key = path.resolve().as_posix().lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _calendar_events(market: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    today = pd.Timestamp.today().normalize()
    for path in _calendar_files():
        df = data.read_csv(path)
        if df.empty:
            continue
        for raw in data.dataframe_records(df):
            row_market = _as_text(raw.get("market") or raw.get("시장") or raw.get("country"))
            if row_market and market == "kr" and row_market.lower() not in {"kr", "korea", "국장", "한국", "한국주식"}:
                continue
            if row_market and market == "us" and row_market.lower() not in {"us", "usa", "미장", "미국", "미국주식"}:
                continue
            date_ts = _to_ts(raw.get("date") or raw.get("event_date") or raw.get("발표일") or raw.get("일자"))
            dday = None if date_ts is None else int((date_ts - today).days)
            title = _as_text(raw.get("title") or raw.get("event") or raw.get("name") or raw.get("이벤트") or raw.get("지표"))
            if not title:
                continue
            risk = 12
            text = title + " " + _as_text(raw.get("description") or raw.get("memo") or raw.get("설명"))
            if _has(text, EVENT_KEYWORDS["macro"]):
                risk += 22
            if _has(text, EVENT_KEYWORDS["earnings"]):
                risk += 18
            if _has(text, EVENT_KEYWORDS["theme"]):
                risk += 12
            if dday is not None:
                if -1 <= dday <= 1:
                    risk += 28
                elif 2 <= dday <= 5:
                    risk += 15
                elif dday < -3:
                    risk = max(4, risk - 10)
            badge = "매크로 주의" if _has(text, EVENT_KEYWORDS["macro"]) else "이벤트 주의"
            rows.append({
                "market": market,
                "sourceType": "일정",
                "symbol": _as_text(raw.get("symbol") or raw.get("ticker") or raw.get("종목코드")),
                "name": _as_text(raw.get("name") or raw.get("종목명") or title),
                "date": date_ts.strftime("%Y-%m-%d") if date_ts is not None else _as_text(raw.get("date") or raw.get("event_date")),
                "dday": "" if dday is None else dday,
                "title": title,
                "badges": [badge],
                "badgeText": f"{badge}" + (f" D{dday:+d}" if dday is not None else ""),
                "riskScore": int(data._clamp(risk, 0, 100)),  # type: ignore[attr-defined]
                "action": "신규 진입 기준 강화" if risk >= 35 else "근거 확인 후 유지",
                "source": data.source_label(path),
            })
    return rows


def _mtime_age_hours(path: Path) -> float | None:
    try:
        if not path.exists():
            return None
        return max(0.0, (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600)
    except Exception:
        return None


def _critical_file_status(path: Path, max_age_hours: float | None = None) -> dict[str, Any]:
    exists = path.exists()
    age = _mtime_age_hours(path)
    status = "OK" if exists else "MISSING"
    if exists and max_age_hours is not None and age is not None and age > max_age_hours:
        status = "STALE"
    return {
        "path": data.source_label(path),
        "exists": exists,
        "status": status,
        "ageHours": round(age, 2) if age is not None else "",
        "updatedAt": data.file_mtime(path) if exists else "",
    }


@lru_cache(maxsize=256)
def _news_context(market: str) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        rows = data.news_rows(market).get("items", [])
    except Exception:
        rows = []
    for row in rows:
        sym = data.normalize_symbol(row.get("symbol", ""), market)
        if sym:
            by_symbol[sym].append(row)
    return by_symbol


@lru_cache(maxsize=256)
def _disclosure_context(market: str) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        rows = data.disclosure_rows(market).get("items", [])
    except Exception:
        rows = []
    for row in rows:
        sym = data.normalize_symbol(row.get("symbol", ""), market)
        if sym:
            by_symbol[sym].append(row)
    return by_symbol


@lru_cache(maxsize=256)
def _candidate_universe(market: str) -> tuple[list[dict[str, Any]], list[str]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    sources: list[str] = []
    prediction_rows, prediction_source, _ = data.read_primary_predictions(market)
    if prediction_rows:
        sources.append(prediction_source)
        for row in prediction_rows:
            sym = _symbol(row, market)
            if not sym:
                continue
            key = f"{market}|{sym}"
            enriched = dict(row)
            enriched["baseBucket"] = "github_predictions"
            enriched.setdefault("sourceType", "github")
            enriched.setdefault("sourceFile", prediction_source)
            enriched.setdefault("isFallback", False)
            seen.add(key)
            items.append(enriched)
    for kind in ("action", "pullback", "flow", "risk"):
        payload = data.candidate_rows(market, kind)
        src = payload.get("source", "")
        if src and src not in sources:
            sources.append(src)
        for item in payload.get("items", []):
            sym = _symbol(item, market)
            if not sym:
                continue
            key = f"{market}|{sym}"
            enriched = dict(item)
            enriched["baseBucket"] = kind
            if key in seen:
                continue
            seen.add(key)
            items.append(enriched)
    # Add broader symbol snapshot as discovery fallback so the app is not limited to current watch/action cards.
    try:
        symbol_payload = data.symbols(market)
        if symbol_payload.get("source") and symbol_payload.get("source") not in sources:
            sources.append(symbol_payload.get("source"))
        for item in symbol_payload.get("items", [])[:250]:
            sym = _symbol(item, market)
            key = f"{market}|{sym}"
            if sym and key not in seen:
                seen.add(key)
                enriched = dict(item)
                enriched["baseBucket"] = "discovery"
                items.append(enriched)
    except Exception:
        pass
    return items, sources


def _event_badges(item: dict[str, Any], news_rows: list[dict[str, Any]], disclosure_rows: list[dict[str, Any]]) -> tuple[list[str], int, int, str]:
    texts = [
        _as_text(item.get("reason")),
        _as_text(item.get("warning")),
        _as_text(item.get("nextAction")),
        _as_text(item.get("dataStatus")),
        _as_text(_raw(item).get("event_label")),
        _as_text(_raw(item).get("earnings_event_timing")),
        _as_text(_raw(item).get("risk_warning_flags")),
        _as_text(_raw(item).get("disclosure_summary")),
        _as_text(_raw(item).get("sec_title")),
        _as_text(_raw(item).get("dart_report_nm")),
    ]
    texts.extend(_as_text(n.get("title")) + " " + _as_text(n.get("summary")) for n in news_rows[:5])
    texts.extend(_as_text(d.get("title")) for d in disclosure_rows[:5])
    joined = " | ".join(t for t in texts if t)

    badges: list[str] = []
    event_risk = 0
    news_reliability = 50
    if _has(joined, EVENT_KEYWORDS["macro"]):
        badges.append("매크로 주의")
        event_risk += 16
    if _has(joined, EVENT_KEYWORDS["earnings"]):
        badges.append("실적 이벤트")
        event_risk += 12
    if _has(joined, EVENT_KEYWORDS["disclosure_good"]):
        badges.append("신뢰도 높은 공시")
        news_reliability += 16
        event_risk = max(0, event_risk - 4)
    if _has(joined, EVENT_KEYWORDS["disclosure_risk"]):
        badges.append("공시 리스크")
        event_risk += 22
    if _has(joined, EVENT_KEYWORDS["theme"]):
        badges.append("재료 소멸 주의")
        event_risk += 14
    if news_rows:
        news_reliability += min(18, len(news_rows) * 3)
    if disclosure_rows:
        news_reliability += min(18, len(disclosure_rows) * 4)
    if not badges:
        badges.append("이벤트 특이사항 낮음")
    return badges[:4], int(data._clamp(event_risk, 0, 100)), int(data._clamp(news_reliability, 0, 100)), joined


def _surge_label(item: dict[str, Any], df: pd.DataFrame) -> tuple[str, str]:
    if df.empty or len(df) < 5:
        return "판단 대기", "차트/OHLCV 부족"
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 5:
        return "판단 대기", "종가 데이터 부족"
    last = float(close.iloc[-1])
    prev5 = float(close.iloc[-5]) if close.iloc[-5] else last
    ret5 = (last / prev5 - 1) * 100 if prev5 else 0
    high20 = float(close.tail(20).max()) if len(close) >= 20 else float(close.max())
    near_high = high20 > 0 and last >= high20 * 0.97
    if ret5 >= 12 and near_high:
        return "과열 주의", f"5일 {ret5:.1f}% 상승 · 20일 고점권"
    if ret5 >= 6 and not near_high:
        return "추세 지속 후보", f"5일 {ret5:.1f}% 상승 · 고점 돌파 전"
    if ret5 < -4:
        return "눌림 대기 후보", f"5일 {ret5:.1f}% 조정"
    return "보유 유지 후보", f"5일 {ret5:.1f}% 흐름"


def _entry_gap(current: float | None, entry: float | None) -> float | None:
    if current is None or entry is None or entry <= 0:
        return None
    return (current - entry) / entry


def _mode_allowed(mode: str, horizon: str, scores: dict[str, Any], event_risk: int) -> bool:
    rule = MODE_RULES.get(mode, MODE_RULES["balanced"])
    opp = float(scores.get("opportunityScore") or 0)
    entry = float(scores.get("entryScore") or 0)
    risk = float(scores.get("riskScore") or 0) + event_risk * 0.35
    gap = scores.get("gap")
    if mode == "aggressive" and horizon == "short":
        return opp >= 45 and entry >= 38 and risk <= 82 and (gap is None or gap <= 0.16)
    if horizon == "mid":
        return opp >= rule["min_opportunity"] - 3 and risk <= rule["max_risk"] + 10
    return opp >= rule["min_opportunity"] and entry >= rule["min_entry"] and risk <= rule["max_risk"] and (gap is None or gap <= rule["max_gap"])


def _decision_bucket(mode: str, horizon: str, scores: dict[str, Any], event_risk: int, surge_label: str) -> tuple[str, str, str]:
    opp = float(scores.get("opportunityScore") or 0)
    entry = float(scores.get("entryScore") or 0)
    risk = float(scores.get("riskScore") or 0) + event_risk * 0.35
    gap = scores.get("gap")
    gap_text = "기준가 거리 없음" if gap is None else f"기준가 대비 {gap * 100:+.1f}%"
    if risk >= 70 or surge_label == "과열 주의":
        return "주의", "신규 진입 제한", f"위험 {risk:.1f} · {surge_label} · {gap_text}"
    if _mode_allowed(mode, horizon, scores, event_risk) and entry >= 66:
        return "오늘 진입", "조건부 매수 등록", f"기회 {opp:.1f} / 진입 {entry:.1f} / 위험 {risk:.1f} · {gap_text}"
    if opp >= 58 and risk < 62:
        return "기다림", "기준가 도달 대기", f"좋은 후보이나 {gap_text} · 체결 조건 확인 필요"
    if opp >= 50 and risk < 70:
        return "다음 진입", "다음 장전 재검토", f"기회는 있으나 진입점수 {entry:.1f}로 보수적 확인 필요"
    return "주의", "관망/제외", f"기회 {opp:.1f} / 위험 {risk:.1f}"


def _conditional_execution(item: dict[str, Any], mode: str, horizon: str, df: pd.DataFrame, source: str) -> dict[str, Any]:
    """Operational conditional trade validation.

    Recommended != bought. A trade is filled only when entry_price is touched by
    OHLCV low/high inside the evaluation window. Returns are calculated only for
    filled orders. If both target and stop are touched in the same daily bar, the
    mode setting decides whether to use the conservative stop-first rule.
    """
    settings = data.TRADE_MODE_SETTINGS.get(mode, data.TRADE_MODE_SETTINGS["balanced"])
    entry = _num(item.get("entry"))
    stop = _num(item.get("stop"))
    target = _num(item.get("target"))
    market = item.get("market", "kr")
    hold_days = HORIZON_DAYS[horizon]
    if entry is None or stop is None or target is None:
        return {
            "executionStatus": "검증 대기",
            "executionReason": "진입가/손절가/목표가 부족",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "수익률 제외",
            "ohlcvSource": source,
        }
    if df.empty:
        status = data._execution_status_for_plan(item.get("currentPrice"), entry, mode)  # type: ignore[attr-defined]
        return {
            "executionStatus": status if status != "체결 가능" else "체결 가능(현재가 기준)",
            "executionReason": "OHLCV 부족: 현재가와 기준가 거리만 표시",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "실제 체결 검증 대기",
            "ohlcvSource": source,
        }

    # If caller passed a raw dataframe, normalize dates/window again.
    work = df.copy()
    if "_date_ts" not in work.columns:
        work["_date_ts"] = pd.to_datetime(work.get("date"), errors="coerce").dt.normalize()
    work = work.dropna(subset=["_date_ts"]).sort_values("_date_ts").tail(max(1, hold_days)).reset_index(drop=True)
    if work.empty:
        return {
            "executionStatus": "검증 대기",
            "executionReason": "평가 구간 OHLCV 부족",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "수익률 제외",
            "ohlcvSource": source,
        }

    fill_idx: int | None = None
    fill_row: pd.Series | None = None
    for idx, row in work.iterrows():
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low")) or _num(row.get("close"))
        if hi is None or lo is None:
            continue
        if lo <= entry <= hi:
            fill_idx = int(idx)
            fill_row = row
            break

    latest = work.iloc[-1]
    day_high = _num(latest.get("high")) or _num(latest.get("close"))
    day_low = _num(latest.get("low")) or _num(latest.get("close"))
    if fill_idx is None or fill_row is None:
        return {
            "executionStatus": "미체결",
            "executionReason": f"평가 구간 {hold_days}거래일 내 진입가 미도달",
            "filled": False,
            "excludedFromReturn": True,
            "pnlPct": "",
            "pnlText": "미체결 · 수익률 제외",
            "dayHigh": data.format_price(day_high, market) if day_high is not None else "",
            "dayLow": data.format_price(day_low, market) if day_low is not None else "",
            "ohlcvDate": _row_date_text(latest),
            "ohlcvSource": source,
            "evaluationDays": hold_days,
        }

    exit_price = None
    outcome = "보유중"
    exit_date = ""
    target_first = bool(settings.get("target_first"))
    for idx in range(fill_idx, len(work)):
        row = work.iloc[idx]
        hi = _num(row.get("high")) or _num(row.get("close"))
        lo = _num(row.get("low")) or _num(row.get("close"))
        close = _num(row.get("close"))
        if hi is None or lo is None:
            continue
        target_hit = hi >= target
        stop_hit = lo <= stop
        if target_hit and stop_hit:
            exit_price = target if target_first else stop
            outcome = "목표/손절 동시 · 목표 우선" if target_first else "목표/손절 동시 · 보수적 손절 우선"
            exit_date = _row_date_text(row)
            break
        if target_hit:
            exit_price = target
            outcome = "목표 도달"
            exit_date = _row_date_text(row)
            break
        if stop_hit:
            exit_price = stop
            outcome = "손절 도달"
            exit_date = _row_date_text(row)
            break
        if idx == len(work) - 1:
            exit_price = close if close is not None else entry
            outcome = "기간종료" if len(work) >= hold_days else "보유중"
            exit_date = _row_date_text(row)

    if exit_price is None:
        exit_price = entry
    pnl = ((exit_price - entry) / entry) * 100 if entry else None
    return {
        "executionStatus": "체결",
        "executionReason": f"{_row_date_text(fill_row)} 진입가 도달 · {exit_date or _row_date_text(latest)} {outcome}",
        "filled": True,
        "excludedFromReturn": False,
        "entryFilledPrice": data.format_price(entry, market),
        "entryFilledDate": _row_date_text(fill_row),
        "exitStatus": outcome,
        "exitDate": exit_date,
        "exitPrice": data.format_price(exit_price, market),
        "pnlPct": round(pnl, 3) if pnl is not None else "",
        "pnlText": data.format_percent(pnl) if pnl is not None else "수익률 산출 대기",
        "dayHigh": data.format_price(day_high, market) if day_high is not None else "",
        "dayLow": data.format_price(day_low, market) if day_low is not None else "",
        "ohlcvDate": _row_date_text(latest),
        "ohlcvSource": source,
        "evaluationDays": hold_days,
        "rule": "진입가 도달 종목만 체결 · 체결 이후 목표/손절/기간종료 판정 · 미체결 수익률 제외",
    }


@lru_cache(maxsize=256)
def final_recommendations(market: str = "kr", mode: str = "balanced", horizon: str = "swing", limit: int | None = None) -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    mode = mode if mode in MODES else "balanced"
    horizon = horizon if horizon in HORIZONS else "swing"
    news_map = _news_context(market)
    disc_map = _disclosure_context(market)
    universe, sources = _candidate_universe(market)
    rows: list[dict[str, Any]] = []
    for item in universe:
        sym = _symbol(item, market)
        if not sym:
            continue
        raw = _raw(item)
        merged = dict(raw)
        for key, value in item.items():
            if key not in merged and key != "raw":
                merged[key] = value
        scores = data._mone_classifier_scores(merged, market)  # type: ignore[attr-defined]
        normalized = data.normalize_security_row(merged, market)
        for key, value in item.items():
            normalized.setdefault(key, value)
        normalized.update({
            "symbol": sym,
            "market": market,
            "mode": mode,
            "modeLabel": MODE_LABELS[mode],
            "horizon": horizon,
            "horizonLabel": HORIZON_LABELS[horizon],
            "opportunityScore": scores["opportunityScore"],
            "entryScore": scores["entryScore"],
            "riskScore": scores["riskScore"],
            "rr": round(float(scores.get("rr") or 0), 3),
            "riskReward": f"1:{float(scores.get('rr') or 0):.2f}" if scores.get("rr") else "손익비 없음",
        })
        n_rows = news_map.get(sym, [])
        d_rows = disc_map.get(sym, [])
        badges, event_risk, news_reliability, event_text = _event_badges(normalized, n_rows, d_rows)
        df, ohlcv_source = _evaluation_window(sym, market, horizon)
        surge, surge_reason = _surge_label(normalized, df)
        bucket, buy_timing, decision_reason = _decision_bucket(mode, horizon, scores, event_risk, surge)
        allowed = _mode_allowed(mode, horizon, scores, event_risk)
        execution = _conditional_execution(normalized, mode, horizon, df, ohlcv_source)
        holding_decision = "보유 유지" if surge in {"추세 지속 후보", "보유 유지 후보"} and event_risk < 55 else "비중 축소/손절선 확인" if event_risk >= 55 else "보유자는 목표가·손절가 대응"
        sell_timing = "목표가 도달 시 분할익절 / 손절가 이탈 시 종료 / 보유기간 종료 시 재검토"
        rank_score = float(scores["opportunityScore"]) * 0.45 + float(scores["entryScore"]) * 0.35 - (float(scores["riskScore"]) + event_risk * 0.4) * 0.25 + news_reliability * 0.08
        if bucket == "오늘 진입":
            rank_score += 8
        if execution.get("executionStatus") == "체결":
            rank_score += 4
        row = {
            **normalized,
            "decisionBucket": bucket,
            "buyTiming": buy_timing,
            "sellTiming": sell_timing,
            "newEntryDecision": "조건부 진입" if bucket == "오늘 진입" else "대기" if bucket in {"기다림", "다음 진입"} else "신규 진입 제한",
            "holderDecision": holding_decision,
            "decisionReason": decision_reason,
            "eventBadges": badges,
            "eventBadgesText": " · ".join(badges),
            "eventRiskScore": event_risk,
            "newsReliabilityScore": news_reliability,
            "surgeLabel": surge,
            "surgeReason": surge_reason,
            "finalRankScore": round(data._clamp(rank_score, 0, 100), 1),  # type: ignore[attr-defined]
            "recommended": bool(allowed and bucket != "주의"),
            "probabilityText": normalized.get(HORIZON_PROB_FIELD[horizon], "확률 산출 필요"),
            "expectedPriceText": normalized.get(HORIZON_PRICE_FIELD[horizon], "예상가 산출 필요"),
            "execution": execution,
            "executionStatus": execution.get("executionStatus", "검증 대기"),
            "exitStatus": execution.get("exitStatus", ""),
            "pnlText": execution.get("pnlText", ""),
            "sourceBucket": item.get("baseBucket", item.get("category", "")),
            "newsCount": len(n_rows),
            "disclosureCount": len(d_rows),
            "eventContext": event_text[:300],
        }
        rows.append(row)
    rows.sort(key=lambda r: (bool(r.get("recommended")), float(r.get("finalRankScore") or 0)), reverse=True)
    max_items = limit or int(MODE_RULES[mode]["max_items"])
    selected = rows[:max_items]
    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "modeLabel": MODE_LABELS[mode],
        "horizon": horizon,
        "horizonLabel": HORIZON_LABELS[horizon],
        "count": len(selected),
        "universeCount": len(rows),
        "sources": sources[:12],
        "rule": "국장/미장 후보군을 StockApp raw·MONE reports·CSV/OHLCV·뉴스·공시로 합친 뒤 MONE 점수로 재분류",
        "items": selected,
        "generatedAt": _now(),
    }


def conditional_execution_summary(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    payload = final_recommendations(market, mode, horizon, limit=int(MODE_RULES.get(mode, MODE_RULES["balanced"])["max_items"]))
    items = payload.get("items", [])
    filled = [r for r in items if r.get("execution", {}).get("filled")]
    unfilled = [r for r in items if not r.get("execution", {}).get("filled")]
    pnl_values = [_num(r.get("execution", {}).get("pnlPct")) for r in filled]
    pnl_values = [v for v in pnl_values if v is not None]
    avg = sum(pnl_values) / len(pnl_values) if pnl_values else None
    return {
        "status": "OK",
        "market": payload["market"],
        "mode": payload["mode"],
        "modeLabel": payload["modeLabel"],
        "horizon": payload["horizon"],
        "horizonLabel": payload["horizonLabel"],
        "conditionalOrders": len(items),
        "filledCount": len(filled),
        "unfilledCount": len(unfilled),
        "filledReturnAvgPct": round(avg, 3) if avg is not None else "",
        "filledReturnAvgText": data.format_percent(avg) if avg is not None else "체결 종목 수익률 없음",
        "rule": "추천됨 ≠ 매수됨 · 진입가가 당일 고가/저가 범위에 들어온 종목만 체결 · 미체결은 수익률 계산 제외",
        "items": items,
        "generatedAt": _now(),
    }


def _prediction_rows(market: str) -> list[dict[str, Any]]:
    rows, _, _ = data.read_primary_predictions(market)
    if rows:
        return rows
    rows = data.read_predictions_csv(market)
    if rows:
        return rows
    return data.dataframe_records(data.read_csv(data.REPO_ROOT / "predictions.csv"))


def prediction_validation(market: str = "kr", limit: int = 250) -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    rows = []
    for row in _prediction_rows(market):
        if not data._market_matches(row, market):  # type: ignore[attr-defined]
            continue
        sym = data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES + ["ticker", "stock_code"], ""), market)
        if not sym:
            continue
        pred_date = _prediction_date(row)
        prev_close = data.first_number(row, ["prev_close", "basis_close", "current_price_at_prediction", "close_at_prediction"])
        if prev_close is None:
            df_for_prev, _ = _ohlcv_with_dates(sym, market)
            if pred_date is not None and not df_for_prev.empty:
                before = df_for_prev[df_for_prev["_date_ts"] <= pred_date]
                if not before.empty:
                    prev_close = _num(before.iloc[-1].get("close"))
        pred = {
            "D+1": data.first_number(row, ["pred_close_mid", "expected_price_1d", "predicted_price_1d", "target_price_1d", "1일예상가"]),
            "D+5": data.first_number(row, ["expected_price_5d", "predicted_price_5d", "target_price_5d", "take_profit1", "5일예상가"]),
            "D+20": data.first_number(row, ["expected_price_20d", "predicted_price_20d", "midterm_expected_price", "take_profit2", "20일예상가"]),
        }
        actual = {
            "D+1": data.first_number(row, ["actual_close", "actual_1d_close"]),
            "D+5": data.first_number(row, ["actual_5d_close"]),
            "D+20": data.first_number(row, ["actual_20d_close"]),
        }
        offsets = {"D+1": 1, "D+5": 5, "D+20": 20}
        actual_dates: dict[str, str] = {"D+1": "", "D+5": "", "D+20": ""}
        actual_sources: dict[str, str] = {"D+1": "", "D+5": "", "D+20": ""}
        for key, offset in offsets.items():
            if actual[key] is None:
                close, source, date_or_reason = _actual_close_after(sym, market, pred_date, offset)
                actual[key] = close
                actual_sources[key] = source
                actual_dates[key] = date_or_reason
            else:
                actual_sources[key] = "predictions.csv actual column"
                actual_dates[key] = data.first_value(row, ["actual_date", "target_date"], "")
        validations = {}
        for key in ("D+1", "D+5", "D+20"):
            pval = pred[key]
            aval = actual[key]
            error = ((aval - pval) / pval * 100) if pval and aval else None
            direction_hit = "검증 대기"
            if prev_close and pval and aval:
                direction_hit = "적중" if (pval - prev_close) * (aval - prev_close) >= 0 else "불일치"
            range_hit = "검증 대기"
            if error is not None:
                tolerance = 2.5 if key == "D+1" else 5.0 if key == "D+5" else 9.0
                range_hit = "허용범위 적중" if abs(error) <= tolerance else "허용범위 이탈"
            validations[key] = {
                "expectedPrice": data.format_price(pval, market) if pval else "예상가 없음",
                "actualClose": data.format_price(aval, market) if aval else "실제 종가 대기",
                "actualDate": actual_dates.get(key, ""),
                "actualSource": actual_sources.get(key, ""),
                "errorPct": round(error, 3) if error is not None else "",
                "errorText": data.format_percent(error) if error is not None else "오차율 대기",
                "directionHit": direction_hit,
                "rangeHit": range_hit,
            }
        rows.append({
            "market": market,
            "symbol": sym,
            "name": data.first_value(row, data.NAME_ALIASES + ["stock_name"], sym),
            "predictionDate": pred_date.strftime("%Y-%m-%d") if pred_date is not None else data.first_value(row, ["created_at", "run_time_kst", "prediction_at"], ""),
            "targetDate": data.first_value(row, ["target_date", "actual_date"], ""),
            "sessionLabel": data.first_value(row, ["session_label", "session_type"], ""),
            "D+1": validations["D+1"],
            "D+5": validations["D+5"],
            "D+20": validations["D+20"],
            "openErrorPct": data.first_value(row, ["open_error_pct"], ""),
            "closeErrorPct": data.first_value(row, ["close_error_pct"], ""),
            "predictionResult": data.first_value(row, ["prediction_result", "direction_hit"], "검증 대기"),
        })
    rows = sorted(rows, key=lambda r: str(r.get("predictionDate", "")), reverse=True)[:limit]
    ready = sum(1 for r in rows if r.get("D+1", {}).get("actualClose") != "실제 종가 대기")
    return {
        "status": "OK",
        "version": OPERATIONAL_VERSION,
        "market": market,
        "count": len(rows),
        "validatedD1Count": ready,
        "source": "predictions.csv + OHLCV 자동 매칭",
        "rule": "예측 검증은 예측일 이후 거래일 기준 D+1/D+5/D+20 종가를 OHLCV에서 자동 매칭해 오차·방향성을 검증",
        "items": rows,
    }


def trade_validation(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    summary = conditional_execution_summary(market, mode, horizon)
    items = []
    for row in summary.get("items", []):
        ex = row.get("execution", {})
        items.append({
            "market": row.get("market"),
            "symbol": row.get("symbol"),
            "name": row.get("name"),
            "mode": row.get("mode"),
            "horizon": row.get("horizon"),
            "entry": row.get("entryText"),
            "stop": row.get("stopText"),
            "target": row.get("targetText"),
            "executionStatus": ex.get("executionStatus", row.get("executionStatus")),
            "executionReason": ex.get("executionReason", ""),
            "exitStatus": ex.get("exitStatus", ""),
            "pnlText": ex.get("pnlText", ""),
            "excludedFromReturn": ex.get("excludedFromReturn", True),
            "ohlcvDate": ex.get("ohlcvDate", ""),
            "ohlcvSource": ex.get("ohlcvSource", ""),
        })
    return {**summary, "items": items, "rule": "가상운용 검증은 진입가 도달/체결/손절/목표/기간종료만 검증하며 예측 정확도와 분리"}


def macro_event_risk(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    events: list[dict[str, Any]] = _calendar_events(market)
    for payload_name, getter in (("뉴스", data.news_rows), ("공시", data.disclosure_rows)):
        try:
            payload = getter(market)
            source = payload.get("source") or " · ".join(payload.get("sources", []))
            for row in payload.get("items", [])[:200]:
                text = f"{row.get('title','')} {row.get('summary','')} {row.get('status','')}"
                badges = []
                risk = 0
                if _has(text, EVENT_KEYWORDS["macro"]):
                    badges.append("매크로 주의")
                    risk += 20
                if _has(text, EVENT_KEYWORDS["earnings"]):
                    badges.append("실적 이벤트")
                    risk += 15
                if _has(text, EVENT_KEYWORDS["disclosure_risk"]):
                    badges.append("공시 리스크")
                    risk += 25
                if _has(text, EVENT_KEYWORDS["disclosure_good"]):
                    badges.append("신뢰도 높은 공시")
                    risk = max(0, risk - 8)
                if _has(text, EVENT_KEYWORDS["theme"]):
                    badges.append("재료 소멸 주의")
                    risk += 16
                if badges:
                    events.append({
                        "market": market,
                        "sourceType": payload_name,
                        "symbol": row.get("symbol", ""),
                        "name": row.get("name", ""),
                        "date": row.get("publishedAt") or row.get("date") or "",
                        "title": row.get("title", ""),
                        "badges": badges,
                        "badgeText": " · ".join(badges),
                        "riskScore": int(data._clamp(risk, 0, 100)),  # type: ignore[attr-defined]
                        "action": "신규 진입 기준 강화" if risk >= 20 else "근거 확인 후 유지",
                        "source": source,
                    })
        except Exception:
            continue
    if not events:
        events.append({
            "market": market,
            "sourceType": "시스템",
            "symbol": "",
            "name": "시장 이벤트",
            "date": "",
            "title": "저장된 뉴스/공시에서 FOMC·CPI·실적·IPO 등 이벤트 키워드가 감지되지 않음",
            "badges": ["일정 데이터 연결 대기"],
            "badgeText": "일정 데이터 연결 대기",
            "riskScore": 0,
            "action": "외부 일정 CSV/API 연결 시 자동 반영",
            "source": "news/disclosures fallback",
        })
    return {"status": "OK", "market": market, "version": OPERATIONAL_VERSION, "calendarFiles": [data.source_label(p) for p in _calendar_files()], "count": len(events), "items": sorted(events, key=lambda e: int(e.get("riskScore", 0)), reverse=True)[:80]}


def portfolio_risk(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    rec = final_recommendations(market, mode, horizon, limit=20)
    items = rec.get("items", [])
    sectors = Counter(_as_text(_raw(r).get("sector") or r.get("sector") or "섹터 미분류") or "섹터 미분류" for r in items)
    filled = [r for r in items if r.get("execution", {}).get("filled")]
    risk_scores = [_num(r.get("riskScore")) or 0 for r in items]
    event_scores = [_num(r.get("eventRiskScore")) or 0 for r in items]
    warnings = []
    if sectors:
        top_sector, top_count = sectors.most_common(1)[0]
        if len(items) and top_count / len(items) >= 0.45:
            warnings.append(f"{top_sector} 비중 과다: {top_count}/{len(items)}")
    if sum(1 for r in items if r.get("market") == "kr") and sum(1 for r in items if r.get("market") == "us"):
        market_mix = "국장/미장 혼합"
    else:
        market_mix = "국장 단일" if rec.get("market") == "kr" else "미장 단일"
    avg_risk = sum(risk_scores) / len(risk_scores) if risk_scores else 0
    avg_event = sum(event_scores) / len(event_scores) if event_scores else 0
    if avg_risk >= 55:
        warnings.append("후보 평균 위험 점수 높음")
    if avg_event >= 25:
        warnings.append("이벤트/매크로 리스크 확인 필요")
    if not warnings:
        warnings.append("쏠림 경고 낮음")
    return {
        "status": "OK",
        "market": rec.get("market"),
        "mode": mode,
        "horizon": horizon,
        "candidateCount": len(items),
        "filledCount": len(filled),
        "sectorDistribution": dict(sectors),
        "topSector": sectors.most_common(1)[0][0] if sectors else "섹터 없음",
        "marketMix": market_mix,
        "averageRiskScore": round(avg_risk, 1),
        "averageEventRiskScore": round(avg_event, 1),
        "cashPolicy": "보수 3종목 / 균형 5종목 / 공격 8~12종목 이내, 동일 섹터 과다 시 진입 수 제한",
        "warnings": warnings,
        "items": [{"symbol": r.get("symbol"), "name": r.get("name"), "sector": _raw(r).get("sector", "섹터 미분류"), "riskScore": r.get("riskScore"), "eventRiskScore": r.get("eventRiskScore"), "decision": r.get("decisionBucket")} for r in items],
    }


def data_center(market: str = "kr") -> dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    status = data.data_source_status().get("items", [])
    github = data.github_actions_status()
    bridge = data.stockapp_bridge_status()
    files = data.status_files().get("items", [])
    critical_paths = [
        data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_balanced_swing.csv",
        data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_balanced_swing.csv",
        data.REPORT_DIR / f"mone_v36_final_prediction_validation_{market}.csv",
        data.REPORT_DIR / f"mone_v36_final_macro_events_{market}.csv",
        data.REPORT_DIR / f"mone_v36_final_data_center_{market}.csv",
        data.REPO_ROOT / "predictions.csv",
    ]
    critical = [_critical_file_status(path, max_age_hours=48 if "final" in path.name else 96) for path in critical_paths]
    def find_status(key: str) -> str:
        row = next((x for x in status if x.get("key") == key), {})
        return row.get("status", "MISSING")
    chart_status = find_status("chart")
    disclosure_status = find_status("disclosure")
    missing = [x for x in critical if x["status"] == "MISSING"]
    stale = [x for x in critical if x["status"] == "STALE"]
    prediction_payload = data.predictions(market)
    prediction_items = prediction_payload.get("items", [])
    item_statuses = {str(item.get("dataStatus", "")) for item in prediction_items}
    if not prediction_items:
        data_status = "NO_DATA"
    elif "STALE" in item_statuses:
        data_status = "STALE"
    elif "NORMAL" in item_statuses:
        data_status = "NORMAL"
    else:
        data_status = "PARTIAL"
    ok_points = 0
    ok_points += 20 if github.get("status") in {"OK", "NEED_TOKEN", "ERROR"} else 0
    ok_points += 20 if bridge.get("status") in {"OK", "NOT_FOUND"} else 0
    ok_points += 20 if chart_status == "OK" else 0
    ok_points += 15 if disclosure_status == "OK" else 0
    ok_points += 25 if not missing and not stale else max(0, 25 - len(missing) * 8 - len(stale) * 5)
    readiness = int(data._clamp(ok_points, 0, 100))  # type: ignore[attr-defined]
    if readiness >= 85:
        readiness_label = "운영 가능"
    elif readiness >= 65:
        readiness_label = "부분 운영 가능"
    else:
        readiness_label = "점검 필요"
    warnings = []
    if missing:
        warnings.append(f"핵심 산출물 누락 {len(missing)}개")
    if stale:
        warnings.append(f"오래된 산출물 {len(stale)}개")
    if chart_status != "OK":
        warnings.append("차트/OHLCV 데이터 부족")
    if disclosure_status != "OK":
        warnings.append("공시 데이터 부족")
    if not warnings:
        warnings.append("핵심 데이터 상태 양호")
    return {
        "status": data_status,
        "version": OPERATIONAL_VERSION,
        "market": market,
        "updatedAt": data.latest_updated_at(),
        "readinessScore": readiness,
        "readinessLabel": readiness_label,
        "warnings": warnings,
        "todayDataSource": "GitHub predictions.csv + KIS/GitHub price",
        "githubStatus": github.get("status", "UNKNOWN"),
        "stockAppBridgeStatus": bridge.get("status", "NOT_FOUND"),
        "chartData": chart_status,
        "flowData": find_status("flow"),
        "orderbookData": find_status("orderbook"),
        "disclosureData": disclosure_status,
        "criticalFiles": critical,
        "summary": [
            {"label": "운영 준비도", "value": f"{readiness}점 · {readiness_label}", "note": "핵심 파일/차트/공시/GitHub/StockApp 상태 종합"},
            {"label": "오늘 데이터 출처", "value": "MONE v3.6 final 우선 · StockApp fallback", "note": "StockApp 판단은 원본으로만 보존"},
            {"label": "마지막 업데이트", "value": data.latest_updated_at(), "note": "reports/data 기준"},
            {"label": "차트 데이터", "value": chart_status, "note": "OHLCV/기술지표/체결 검증"},
            {"label": "공시 데이터", "value": disclosure_status, "note": "DART/SEC CSV 감지"},
        ],
        "raw": {"dataSources": status, "github": github, "stockapp": bridge},
    }


def discovery(market: str = "kr", mode: str = "balanced", horizon: str = "swing") -> dict[str, Any]:
    rec = final_recommendations(market, mode, horizon, limit=80)
    buckets = defaultdict(list)
    for r in rec.get("items", []):
        label = "저평가 성장" if "저평가" in _as_text(r.get("eventContext")) or "valuation" in _as_text(r.get("scores")) else None
        if not label and "수급" in _as_text(r.get("sourceBucket")) + _as_text(r.get("decisionReason")):
            label = "수급 포착"
        if not label and r.get("surgeLabel") in {"눌림 대기 후보", "추세 지속 후보"}:
            label = r.get("surgeLabel")
        if not label and r.get("decisionBucket") == "오늘 진입":
            label = "모멘텀 초기"
        if not label:
            label = "중기 관심 후보" if horizon == "mid" else "차트 회복 후보"
        row = {"symbol": r.get("symbol"), "name": r.get("name"), "label": label, "mode": r.get("modeLabel"), "horizon": r.get("horizonLabel"), "score": r.get("finalRankScore"), "decision": r.get("decisionBucket"), "buyTiming": r.get("buyTiming"), "eventBadges": r.get("eventBadgesText")}
        buckets[label].append(row)
    items = [{"bucket": k, "count": len(v), "items": v[:12]} for k, v in sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True)]
    return {"status": "OK", "market": market, "mode": mode, "horizon": horizon, "count": sum(x["count"] for x in items), "items": items}




def operational_readiness() -> dict[str, Any]:
    """Fast operational readiness check for UI/GitHub.

    This intentionally avoids doing a second full market scan when reports already
    exist. It checks every market/mode/horizon output file and only computes a
    lightweight fallback when a file is missing.
    """
    markets = [data_center("kr"), data_center("us")]
    checks: list[dict[str, Any]] = []
    for market in MARKETS:
        for mode in MODES:
            for horizon in HORIZONS:
                rec_path = data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
                trade_path = data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv"
                rec_df = data.read_csv(rec_path) if rec_path.exists() else pd.DataFrame()
                trade_df = data.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()
                if rec_df.empty:
                    rec = final_recommendations(market, mode, horizon, limit=1)
                    rec_count = int(rec.get("count", 0))
                    universe_count = int(rec.get("universeCount", 0))
                else:
                    rec_count = int(len(rec_df))
                    universe_count = rec_count
                filled_count = 0
                avg_return = ""
                if not trade_df.empty:
                    status_col = next((c for c in trade_df.columns if c in {"executionStatus", "execution_status"}), None)
                    if status_col:
                        filled_count = int((trade_df[status_col].astype(str) == "체결").sum())
                    pnl_col = next((c for c in trade_df.columns if c in {"pnlText", "pnl_text"}), None)
                    if pnl_col and filled_count:
                        avg_return = "체결 기준 산출됨"
                checks.append({
                    "market": market,
                    "mode": mode,
                    "horizon": horizon,
                    "recommendations": rec_count,
                    "universeCount": universe_count,
                    "conditionalOrders": rec_count,
                    "filledCount": filled_count,
                    "avgReturn": avg_return,
                    "recommendationReport": data.source_label(rec_path),
                    "tradeValidationReport": data.source_label(trade_path),
                    "status": "OK" if rec_count > 0 else "NO_RECOMMENDATION",
                })
    pred = {}
    macro = {}
    for market in MARKETS:
        pred_payload = prediction_validation(market, limit=80)
        pred[market] = pred_payload.get("validatedD1Count", 0)
        macro[market] = macro_event_risk(market).get("count", 0)
    avg_readiness = sum(int(m.get("readinessScore", 0)) for m in markets) / len(markets)
    no_rec = [c for c in checks if c["status"] != "OK"]
    blocking = []
    if no_rec:
        blocking.append(f"추천 없음 조합 {len(no_rec)}개")
    if avg_readiness < 65:
        blocking.append("데이터 센터 준비도 낮음")
    label = "운영 안정" if not blocking and avg_readiness >= 75 else "부분 운영" if avg_readiness >= 55 else "운영 전 점검"
    return {
        "status": "OK" if label != "운영 전 점검" else "CHECK_REQUIRED",
        "version": OPERATIONAL_VERSION,
        "readinessAverage": round(avg_readiness, 1),
        "readinessLabel": label,
        "blockingIssues": blocking or ["차단 이슈 없음"],
        "markets": markets,
        "matrix": checks,
        "predictionValidatedD1Count": pred,
        "macroEventCount": macro,
        "generatedAt": _now(),
    }


def write_final_reports() -> dict[str, Any]:
    data.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[dict[str, Any]] = []
    for market in MARKETS:
        dc = data_center(market)
        pd.DataFrame(dc.get("summary", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_data_center_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_data_center_{market}.csv", "rows": len(dc.get("summary", []))})
        macro = macro_event_risk(market)
        pd.DataFrame(macro.get("items", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_macro_events_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_macro_events_{market}.csv", "rows": len(macro.get("items", []))})
        pred = prediction_validation(market)
        flat_pred = []
        for row in pred.get("items", []):
            base = {k: v for k, v in row.items() if k not in {"D+1", "D+5", "D+20"}}
            for h in ("D+1", "D+5", "D+20"):
                for kk, vv in row.get(h, {}).items():
                    base[f"{h}_{kk}"] = vv
            flat_pred.append(base)
        pd.DataFrame(flat_pred).to_csv(data.REPORT_DIR / f"mone_v36_final_prediction_validation_{market}.csv", index=False, encoding="utf-8-sig")
        written.append({"path": f"reports/mone_v36_final_prediction_validation_{market}.csv", "rows": len(flat_pred)})
        for mode in MODES:
            for horizon in HORIZONS:
                rec = final_recommendations(market, mode, horizon)
                flat = []
                for r in rec.get("items", []):
                    ex = r.get("execution", {})
                    flat.append({
                        "market": market,
                        "mode": mode,
                        "modeLabel": MODE_LABELS[mode],
                        "horizon": horizon,
                        "horizonLabel": HORIZON_LABELS[horizon],
                        "symbol": r.get("symbol"),
                        "name": r.get("name"),
                        "decisionBucket": r.get("decisionBucket"),
                        "newEntryDecision": r.get("newEntryDecision"),
                        "holderDecision": r.get("holderDecision"),
                        "buyTiming": r.get("buyTiming"),
                        "sellTiming": r.get("sellTiming"),
                        "entry": r.get("entryText"),
                        "stop": r.get("stopText"),
                        "target": r.get("targetText"),
                        "probability": r.get("probabilityText"),
                        "expectedPrice": r.get("expectedPriceText"),
                        "opportunityScore": r.get("opportunityScore"),
                        "entryScore": r.get("entryScore"),
                        "riskScore": r.get("riskScore"),
                        "eventRiskScore": r.get("eventRiskScore"),
                        "newsReliabilityScore": r.get("newsReliabilityScore"),
                        "finalRankScore": r.get("finalRankScore"),
                        "surgeLabel": r.get("surgeLabel"),
                        "eventBadges": r.get("eventBadgesText"),
                        "executionStatus": ex.get("executionStatus"),
                        "exitStatus": ex.get("exitStatus"),
                        "pnlText": ex.get("pnlText"),
                        "excludedFromReturn": ex.get("excludedFromReturn"),
                        "sourceBucket": r.get("sourceBucket"),
                    })
                path = data.REPORT_DIR / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
                pd.DataFrame(flat).to_csv(path, index=False, encoding="utf-8-sig")
                written.append({"path": f"reports/{path.name}", "rows": len(flat)})
                trade = trade_validation(market, mode, horizon)
                pd.DataFrame(trade.get("items", [])).to_csv(data.REPORT_DIR / f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv", index=False, encoding="utf-8-sig")
                written.append({"path": f"reports/mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv", "rows": len(trade.get("items", []))})
    readiness = operational_readiness()
    pd.DataFrame(readiness.get("matrix", [])).to_csv(data.REPORT_DIR / "mone_v36_operational_readiness_matrix.csv", index=False, encoding="utf-8-sig")
    written.append({"path": "reports/mone_v36_operational_readiness_matrix.csv", "rows": len(readiness.get("matrix", []))})
    data.write_json(data.REPORT_DIR / "mone_v36_operational_readiness.json", readiness)
    written.append({"path": "reports/mone_v36_operational_readiness.json", "rows": len(readiness.get("matrix", []))})
    manifest = {"version": OPERATIONAL_VERSION, "generatedAt": _now(), "readiness": readiness, "written": written}
    data.write_json(data.REPORT_DIR / "mone_v36_final_manifest.json", manifest)
    return manifest
