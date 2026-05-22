from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
US_ET = ZoneInfo("America/New_York")


def coerce_kst(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(KST)
    if now.tzinfo is None:
        return now.replace(tzinfo=KST)
    return now.astimezone(KST)


def is_kr_market(market: Any) -> bool:
    text = str(market or "").strip().upper()
    return "한국" in str(market or "") or text in {"KR", "KRX", "KOSPI", "KOSDAQ", "KOREA"}


def is_us_market(market: Any) -> bool:
    text = str(market or "").strip().upper()
    return "미국" in str(market or "") or text in {"US", "USA", "NASDAQ", "NYSE", "AMEX", "NYS", "NAS"}


def market_bucket(market: Any) -> str:
    if is_kr_market(market):
        return "KR"
    if is_us_market(market):
        return "US"
    return "UNKNOWN"


def current_session_for_market(market: Any, now: datetime | None = None) -> dict[str, Any]:
    """Return a display-safe current session context.

    This is intentionally conservative and timezone-aware. Holiday calendars are
    not embedded; weekends are handled and exchange holidays should still be
    treated as API/no-data in downstream diagnostics.
    """
    now_kst = coerce_kst(now)
    bucket = market_bucket(market)
    if bucket == "KR":
        d = now_kst.date()
        t = now_kst.time()
        if now_kst.weekday() >= 5:
            session, status = "closed", "휴장"
        elif time(9, 0) <= t < time(15, 30):
            session, status = "regular", "정규장"
        elif t < time(9, 0):
            session, status = "closed", "장전"
        else:
            session, status = "closed", "장마감"
        return {
            "market": "한국주식",
            "bucket": bucket,
            "session": session,
            "session_status": status,
            "session_label": status,
            "is_regular": session == "regular",
            "quote_should_refresh": session == "regular",
            "orderbook_should_refresh": session == "regular",
            "flow_should_refresh": session == "regular",
            "now_kst": now_kst,
            "now_et": now_kst.astimezone(US_ET),
            "basis": f"KR KST={now_kst.strftime('%Y-%m-%d %H:%M:%S %Z')} regular=09:00-15:30 session={session}",
            "date": d,
        }

    if bucket == "US":
        now_et = now_kst.astimezone(US_ET)
        d = now_et.date()
        t = now_et.time()
        if now_et.weekday() >= 5:
            session, status = "closed", "휴장"
        elif time(4, 0) <= t < time(9, 30):
            session, status = "premarket", "프리마켓"
        elif time(9, 30) <= t < time(16, 0):
            session, status = "regular", "정규장"
        elif time(16, 0) <= t < time(20, 0):
            session, status = "afterhours", "애프터마켓"
        elif t < time(4, 0):
            session, status = "closed", "장전"
        else:
            session, status = "closed", "장마감"
        return {
            "market": "미국주식",
            "bucket": bucket,
            "session": session,
            "session_status": status,
            "session_label": status,
            "is_regular": session == "regular",
            "quote_should_refresh": session in {"premarket", "regular", "afterhours"},
            "orderbook_should_refresh": session == "regular",
            "flow_should_refresh": False,
            "now_kst": now_kst,
            "now_et": now_et,
            "basis": (
                f"US ET={now_et.strftime('%Y-%m-%d %H:%M:%S %Z')} "
                "premarket=04:00-09:30 regular=09:30-16:00 afterhours=16:00-20:00 "
                f"session={session}"
            ),
            "date": d,
        }

    return {
        "market": str(market or ""),
        "bucket": bucket,
        "session": "unknown",
        "session_status": "확인 불가",
        "session_label": "확인 불가",
        "is_regular": False,
        "quote_should_refresh": False,
        "orderbook_should_refresh": False,
        "flow_should_refresh": False,
        "now_kst": now_kst,
        "now_et": now_kst.astimezone(US_ET),
        "basis": f"unknown market={market}",
        "date": now_kst.date(),
    }


def current_session_code(market: Any, now: datetime | None = None) -> str:
    return str(current_session_for_market(market, now).get("session", "unknown"))


def current_session_status(market: Any, now: datetime | None = None) -> str:
    return str(current_session_for_market(market, now).get("session_status", "확인 불가"))


def should_run_intraday_refresh(now: datetime | None = None) -> bool:
    kr = current_session_for_market("한국주식", now)
    us = current_session_for_market("미국주식", now)
    return bool(kr.get("quote_should_refresh") or us.get("quote_should_refresh"))
