from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")

DATA_STATUS_VALUES = {
    "NORMAL",
    "PARTIAL",
    "STALE",
    "NO_DATA",
    "ERROR",
    "PREVIOUS_CLOSE_BASIS",
    "INTRADAY_OBSERVE",
}
KILL_STATUSES = {"STALE", "NO_DATA", "ERROR"}
KR_SESSIONS = {"kr_premarket", "kr_intraday", "kr_after_close", "kr_closed"}
US_SESSIONS = {"us_premarket", "us_intraday", "us_after_close", "us_closed"}


@dataclass(frozen=True)
class SessionState:
    market: str
    priceSession: str
    sessionLabel: str
    priceBasis: str
    nowKst: str
    nowLocal: str
    isHoliday: bool
    isReviewMode: bool
    isUsDst: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _market(value: Any = "kr") -> str:
    return "us" if str(value or "").strip().lower() in {"us", "usa", "미장"} else "kr"


def _coerce_datetime(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now(KST)
    if value.tzinfo is None:
        return value.replace(tzinfo=KST)
    return value.astimezone(KST)


def _nth_weekday(year: int, month: int, weekday: int, nth: int) -> date:
    cursor = date(year, month, 1)
    shift = (weekday - cursor.weekday()) % 7
    return cursor + timedelta(days=shift + (nth - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        cursor = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        cursor = date(year, month + 1, 1) - timedelta(days=1)
    return cursor - timedelta(days=(cursor.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _us_holidays(year: int) -> set[date]:
    return {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _last_weekday(year, 5, 0),
        _observed(date(year, 6, 19)),
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(date(year, 12, 25)),
    }


def _kr_holidays(year: int) -> set[date]:
    return {
        date(year, 1, 1),
        date(year, 3, 1),
        date(year, 5, 5),
        date(year, 6, 6),
        date(year, 8, 15),
        date(year, 10, 3),
        date(year, 10, 9),
        date(year, 12, 25),
    }


def is_market_holiday(market: str = "kr", value: datetime | date | None = None) -> bool:
    normalized_market = _market(market)
    if isinstance(value, datetime):
        kst_now = _coerce_datetime(value)
        local_day = kst_now.astimezone(NY).date() if normalized_market == "us" else kst_now.date()
    elif isinstance(value, date):
        local_day = value
    else:
        now = datetime.now(KST)
        local_day = now.astimezone(NY).date() if normalized_market == "us" else now.date()

    if local_day.weekday() >= 5:
        return True
    holidays = _us_holidays(local_day.year) if normalized_market == "us" else _kr_holidays(local_day.year)
    return local_day in holidays


def get_price_session(market: str = "kr", now: datetime | None = None) -> dict[str, Any]:
    normalized_market = _market(market)
    kst_now = _coerce_datetime(now)

    if normalized_market == "kr":
        is_holiday = is_market_holiday("kr", kst_now)
        t = kst_now.time()
        if is_holiday:
            state = SessionState(
                market="kr",
                priceSession="kr_closed",
                sessionLabel="국장 휴장",
                priceBasis="시장 휴장일 · 지난 운용 복기 모드",
                nowKst=kst_now.isoformat(),
                nowLocal=kst_now.isoformat(),
                isHoliday=True,
                isReviewMode=True,
                isUsDst=False,
            )
        elif time(0, 0) <= t < time(9, 0):
            state = SessionState("kr", "kr_premarket", "국장 장전", "국장 장전 · 전일 OHLCV 종가 기준", kst_now.isoformat(), kst_now.isoformat(), False, False, False)
        elif time(9, 0) <= t < time(15, 30):
            state = SessionState("kr", "kr_intraday", "국장 장중", "국장 장중 · KIS 현재가 기준", kst_now.isoformat(), kst_now.isoformat(), False, False, False)
        else:
            state = SessionState("kr", "kr_after_close", "국장 장마감 후", "국장 장마감 후 · 당일 OHLCV 기준", kst_now.isoformat(), kst_now.isoformat(), False, False, False)
        return state.to_dict()

    ny_now = kst_now.astimezone(NY)
    is_holiday = is_market_holiday("us", kst_now)
    t = ny_now.time()
    is_dst = bool(ny_now.dst())

    if is_holiday:
        state = SessionState("us", "us_closed", "미장 휴장", "시장 휴장일 · 지난 운용 복기 모드", kst_now.isoformat(), ny_now.isoformat(), True, True, is_dst)
    elif time(4, 0) <= t < time(9, 30):
        state = SessionState("us", "us_premarket", "미장 장전", "미장 장전 · 프리마켓 업데이트 기준", kst_now.isoformat(), ny_now.isoformat(), False, False, is_dst)
    elif time(9, 30) <= t < time(16, 0):
        state = SessionState("us", "us_intraday", "미장 장중", "미장 장중 · KIS 현재가 기준", kst_now.isoformat(), ny_now.isoformat(), False, False, is_dst)
    else:
        state = SessionState("us", "us_after_close", "미장 장마감 후", "미장 장마감 후 · 마감 업데이트 기준", kst_now.isoformat(), ny_now.isoformat(), False, False, is_dst)
    return state.to_dict()


def file_mtime_date(path: str | Path) -> date | None:
    file_path = Path(path)
    if not file_path.exists():
        return None
    return datetime.fromtimestamp(file_path.stat().st_mtime, KST).date()


def evaluate_file_status(
    path: str | Path | None,
    market: str = "kr",
    *,
    required_today: bool = True,
    allow_holiday_stale: bool = True,
) -> dict[str, Any]:
    if not path:
        return {"status": "NO_DATA", "reason": "파일 경로 없음", "mtimeDate": None}

    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"status": "NO_DATA", "reason": "파일 없음", "path": str(file_path), "mtimeDate": None}

        mtime_day = file_mtime_date(file_path)
        today_kst = datetime.now(KST)
        today = today_kst.astimezone(NY).date() if _market(market) == "us" else today_kst.date()
        holiday = is_market_holiday(market)

        if required_today and mtime_day and mtime_day < today and not (holiday and allow_holiday_stale):
            return {"status": "STALE", "reason": "거래일 기준 과거 파일", "path": str(file_path), "mtimeDate": mtime_day.isoformat()}

        if file_path.stat().st_size <= 0:
            return {"status": "NO_DATA", "reason": "빈 파일", "path": str(file_path), "mtimeDate": mtime_day.isoformat() if mtime_day else None}

        return {"status": "NORMAL", "reason": "정상", "path": str(file_path), "mtimeDate": mtime_day.isoformat() if mtime_day else None}
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc), "path": str(path), "mtimeDate": None}


def worst_status(statuses: Iterable[str | None]) -> str:
    rank = {
        "NORMAL": 0,
        "PREVIOUS_CLOSE_BASIS": 1,
        "INTRADAY_OBSERVE": 1,
        "PARTIAL": 1,
        "STALE": 2,
        "NO_DATA": 3,
        "ERROR": 4,
    }
    normalized = [str(s or "NO_DATA").upper() for s in statuses]
    if not normalized:
        return "NO_DATA"
    return max(normalized, key=lambda item: rank.get(item, 3))


def is_kill_status(status: str | None) -> bool:
    return str(status or "").upper() in KILL_STATUSES
