"""
이벤트 캘린더 수집 스크립트
────────────────────────────
출력:
  data/calendar/macro_calendar.csv    — 매크로 경제지표 일정
  data/calendar/earnings_calendar.csv — 실적발표 일정

데이터 소스:
  US 매크로 : Finnhub economic calendar API
  KR 매크로 : BOK(한국은행) 금리결정 + 통계청 주요지표 (하드코딩/추정)
  US 실적   : Finnhub earnings calendar API (추적 종목 필터)
  KR 실적   : yfinance .KS/.KQ (실패 시 skip)

실행:
  cd <repo_root>
  python scripts/generate_event_calendar.py
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

# .env 로드
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
CALENDAR_DIR = ROOT / "data" / "calendar"
OHLCV_DIR   = ROOT / "data" / "market" / "ohlcv"

# ── ETF / 지수 / 암호화폐 제외 심볼 ─────────────────────────────────────
_ETF_EXCLUDE = {
    "SPY", "QQQ", "IWM", "DIA", "SMH", "SOXX", "XLE", "XLF",
    "GLD", "TLT", "IBIT", "BTC-USD", "SP500", "NAN",
}

# ── BOK 2026 기준금리 결정일 (추정) ─────────────────────────────────────
# BOK는 매년 8회 (1, 2, 4, 5, 7, 8, 10, 11월) 개최
BOK_2026 = [
    "2026-01-15", "2026-02-26", "2026-04-16", "2026-05-28",
    "2026-07-16", "2026-08-27", "2026-10-15", "2026-11-26",
]

# ── 한국 주요 경제지표 (매월 추정 발표일) ────────────────────────────────
# 통계청 소비자물가지수(CPI): 매월 초 (~2~4일)
# 수출입 통계: 매월 1일 (당월 기준)
# 산업생산지수: 매월 말 (~30~31일)
def _kr_monthly_events(start: datetime, end: datetime) -> list[dict]:
    rows: list[dict] = []
    cur = start.replace(day=1)
    while cur <= end:
        y, m = cur.year, cur.month
        # CPI: 전월 발표 (예: 5월 발표 = 4월 CPI)
        cpi_date = _nth_workday(y, m, 3)
        if start <= cpi_date <= end:
            prev_m = m - 1 if m > 1 else 12
            prev_y = y if m > 1 else y - 1
            rows.append({
                "date": cpi_date.strftime("%Y-%m-%d"),
                "market": "kr", "country": "KR",
                "event": f"한국 소비자물가지수 CPI ({prev_y}-{prev_m:02d})",
                "impact": "high", "actual": "", "forecast": "", "previous": "",
                "unit": "%YoY", "source": "kosis_estimated",
            })
        # 수출입: 매월 1일 발표
        trade_date = datetime(y, m, 1)
        if start <= trade_date <= end:
            rows.append({
                "date": trade_date.strftime("%Y-%m-%d"),
                "market": "kr", "country": "KR",
                "event": f"한국 수출입 통계 ({y}-{m:02d})",
                "impact": "medium", "actual": "", "forecast": "", "previous": "",
                "unit": "억달러", "source": "customs_estimated",
            })
        # 산업생산: 매월 말
        import calendar as _cal
        last_day = _cal.monthrange(y, m)[1]
        prod_date = datetime(y, m, last_day)
        if start <= prod_date <= end:
            rows.append({
                "date": prod_date.strftime("%Y-%m-%d"),
                "market": "kr", "country": "KR",
                "event": f"한국 산업생산지수 ({y}-{m:02d})",
                "impact": "medium", "actual": "", "forecast": "", "previous": "",
                "unit": "%MoM", "source": "kosis_estimated",
            })
        # 다음 달
        if m == 12:
            cur = datetime(y + 1, 1, 1)
        else:
            cur = datetime(y, m + 1, 1)
    return rows


def _nth_workday(year: int, month: int, n: int) -> datetime:
    """월의 n번째 영업일"""
    import calendar as _cal
    d = datetime(year, month, 1)
    count = 0
    while True:
        if d.weekday() < 5:  # 월~금
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)
        if d.month != month:
            return datetime(year, month, 1)  # 폴백


# ── CSV 읽기/쓰기 ────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc) as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  [OK] {path.name}: {len(rows)}rows saved")


def _fetch_json(url: str, timeout: int = 10) -> Any:
    import urllib.request as _ur
    try:
        with _ur.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"  [WARN] fetch 실패: {url[:80]}... → {e}")
        return None


# ── 미장 매크로: Finnhub economic calendar ──────────────────────────────
def fetch_us_macro(days_ahead: int = 90) -> list[dict]:
    if not FINNHUB_KEY:
        print("  [SKIP] FINNHUB_API_KEY 미설정")
        return []

    today = datetime.now()
    end   = today + timedelta(days=days_ahead)
    from_s = today.strftime("%Y-%m-%d")
    to_s   = end.strftime("%Y-%m-%d")

    url = f"https://finnhub.io/api/v1/calendar/economic?from={from_s}&to={to_s}&token={FINNHUB_KEY}"
    data = _fetch_json(url)
    if not data:
        return []

    rows = []
    for item in data.get("economicCalendar") or []:
        country = str(item.get("country", "")).upper()
        if country != "US":
            continue
        # 날짜 파싱: time 필드가 ISO 형식
        raw_time = str(item.get("time") or item.get("date") or "")
        date_str = raw_time[:10] if raw_time else ""
        if not date_str or date_str < from_s or date_str > to_s:
            continue
        impact = str(item.get("impact") or "low").lower()
        event  = str(item.get("event") or "")
        if not event:
            continue
        rows.append({
            "date": date_str,
            "market": "us",
            "country": country,
            "event": event,
            "impact": impact,   # high / medium / low / na
            "actual": str(item.get("actual") or ""),
            "forecast": str(item.get("estimate") or ""),
            "previous": str(item.get("prev") or ""),
            "unit": str(item.get("unit") or ""),
            "source": "finnhub",
        })

    print(f"  Finnhub 매크로: {len(rows)}건 수신 ({from_s}~{to_s})")
    return rows


# ── 국장 매크로: BOK + 통계청 ───────────────────────────────────────────
def fetch_kr_macro(days_ahead: int = 180) -> list[dict]:
    today = datetime.now()
    end   = today + timedelta(days=days_ahead)
    rows: list[dict] = []

    # BOK 기준금리 결정일
    for d_str in BOK_2026:
        d = datetime.strptime(d_str, "%Y-%m-%d")
        if today.date() <= d.date() <= end.date():
            rows.append({
                "date": d_str,
                "market": "kr", "country": "KR",
                "event": "한국은행 기준금리 결정",
                "impact": "high", "actual": "", "forecast": "", "previous": "",
                "unit": "%", "source": "bok_hardcoded",
            })

    # 통계청 주요지표 (추정)
    rows.extend(_kr_monthly_events(today, end))
    print(f"  KR 매크로 (BOK+통계청): {len(rows)}건")
    return rows


# ── 미장 실적: Finnhub earnings calendar ────────────────────────────────
def fetch_us_earnings(days_ahead: int = 60) -> list[dict]:
    if not FINNHUB_KEY:
        print("  [SKIP] FINNHUB_API_KEY 미설정")
        return []

    today = datetime.now()
    end   = today + timedelta(days=days_ahead)
    from_s = today.strftime("%Y-%m-%d")
    to_s   = end.strftime("%Y-%m-%d")

    # 추적 중인 US 심볼 수집
    tracked = set()
    for f in OHLCV_DIR.glob("us_*.csv"):
        parts = f.stem.split("_")
        if len(parts) >= 2:
            sym = parts[1].upper()
            if sym and sym not in _ETF_EXCLUDE:
                tracked.add(sym)

    url = f"https://finnhub.io/api/v1/calendar/earnings?from={from_s}&to={to_s}&token={FINNHUB_KEY}"
    data = _fetch_json(url)
    if not data:
        return []

    rows = []
    for item in data.get("earningsCalendar") or []:
        sym = str(item.get("symbol") or "").upper()
        d   = str(item.get("date") or "")
        if not d or not sym:
            continue
        if sym in _ETF_EXCLUDE:
            continue
        # 전체 수집 (추적 종목 필터 없이 — 이후 filtering은 API 쪽에서)
        # 단, 추적 종목이면 우선 표시용 플래그
        tracked_flag = sym in tracked
        rows.append({
            "date": d,
            "market": "us",
            "symbol": sym,
            "name": str(item.get("symbol") or sym),
            "epsEstimate": str(item.get("epsEstimate") or ""),
            "revenueEstimate": str(item.get("revenueEstimate") or ""),
            "quarter": str(item.get("quarter") or ""),
            "year": str(item.get("year") or ""),
            "hour": str(item.get("hour") or ""),
            "tracked": "Y" if tracked_flag else "N",
            "source": "finnhub",
        })

    # 추적 종목 우선 정렬, 날짜 순
    rows.sort(key=lambda r: (r["date"], r["tracked"] != "Y"))
    print(f"  Finnhub US 실적: {len(rows)}건 (추적종목 {sum(1 for r in rows if r['tracked']=='Y')}건)")
    return rows


# ── 국장 실적: yfinance .KS ──────────────────────────────────────────────
def fetch_kr_earnings(days_ahead: int = 60) -> list[dict]:
    try:
        import yfinance as yf
    except ImportError:
        print("  [SKIP] yfinance 미설치")
        return []

    # 추적 KR 심볼
    symbols = []
    for f in sorted(OHLCV_DIR.glob("kr_*.csv")):
        parts = f.stem.split("_")
        if len(parts) >= 2:
            sym = parts[1]
            if sym and sym not in {"NAN", "NULL"}:
                symbols.append(sym)

    today = datetime.now()
    end   = today + timedelta(days=days_ahead)
    rows: list[dict] = []

    print(f"  yfinance KR 실적 조회 중... ({len(symbols)}종목)")
    for sym in symbols[:80]:  # rate limit 고려
        try:
            for suffix in (".KS", ".KQ"):
                ticker = yf.Ticker(f"{sym}{suffix}")
                cal = ticker.calendar
                if not cal:
                    continue
                # yfinance calendar 형식 다양성 처리
                earnings_dates: list[datetime] = []
                if hasattr(cal, 'get'):
                    # dict 형식
                    ed = cal.get("Earnings Date") or cal.get("earningsDate")
                    if ed is not None:
                        if isinstance(ed, (list, tuple)):
                            for e in ed:
                                try:
                                    earnings_dates.append(pd_to_dt(e))
                                except Exception:
                                    pass
                        else:
                            try:
                                earnings_dates.append(pd_to_dt(ed))
                            except Exception:
                                pass
                elif hasattr(cal, '__iter__'):
                    # DataFrame 형식
                    try:
                        import pandas as pd
                        df = pd.DataFrame(cal)
                        if "Earnings Date" in df.columns:
                            for v in df["Earnings Date"]:
                                try:
                                    earnings_dates.append(pd_to_dt(v))
                                except Exception:
                                    pass
                    except Exception:
                        pass

                for dt in earnings_dates:
                    if today.date() <= dt.date() <= end.date():
                        # 종목명 가져오기 (OHLCV 첫 행)
                        name = sym
                        try:
                            ohlcv = OHLCV_DIR / f"kr_{sym}_daily.csv"
                            if ohlcv.exists():
                                with ohlcv.open(encoding="utf-8-sig") as f2:
                                    r2 = next(csv.DictReader(f2), {})
                                    name = r2.get("name", sym) or sym
                        except Exception:
                            pass
                        rows.append({
                            "date": dt.strftime("%Y-%m-%d"),
                            "market": "kr",
                            "symbol": sym,
                            "name": name,
                            "epsEstimate": "",
                            "revenueEstimate": "",
                            "quarter": "",
                            "year": str(dt.year),
                            "hour": "bmo",
                            "tracked": "Y",
                            "source": "yfinance",
                        })
                    break  # 첫 suffix가 성공하면 KQ 생략
                if earnings_dates:
                    break
        except Exception:
            pass
        time.sleep(0.05)  # yfinance rate limit

    print(f"  yfinance KR 실적: {len(rows)}건")
    return rows


def pd_to_dt(v: Any) -> datetime:
    """pandas Timestamp / string / int → datetime"""
    try:
        import pandas as pd
        if hasattr(v, 'to_pydatetime'):
            return v.to_pydatetime().replace(tzinfo=None)
        if isinstance(v, str):
            return datetime.strptime(v[:10], "%Y-%m-%d")
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v)
        return datetime(*list(v.timetuple())[:6])
    except Exception:
        raise ValueError(f"변환 실패: {v}")


# ── 기존 캘린더 병합 (중복 제거) ────────────────────────────────────────
def _merge_macro(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """날짜+이벤트명 기준 중복 제거 후 병합. 새 데이터 우선."""
    seen: dict[str, dict] = {}
    for r in existing + new_rows:
        key = f"{r.get('date','')}__{r.get('event','')}"
        # 나중에 오는 것(new_rows)이 덮어씀
        seen[key] = r
    return sorted(seen.values(), key=lambda x: x.get("date", ""))


def _merge_earnings(existing: list[dict], new_rows: list[dict]) -> list[dict]:
    """날짜+심볼 기준 중복 제거."""
    seen: dict[str, dict] = {}
    for r in existing + new_rows:
        key = f"{r.get('date','')}__{r.get('market','')}__{r.get('symbol','')}"
        seen[key] = r
    return sorted(seen.values(), key=lambda x: x.get("date", ""))


# ── 메인 ─────────────────────────────────────────────────────────────────
MACRO_FIELDS = ["date", "market", "country", "event", "impact", "actual", "forecast", "previous", "unit", "source"]
EARNINGS_FIELDS = ["date", "market", "symbol", "name", "epsEstimate", "revenueEstimate", "quarter", "year", "hour", "tracked", "source"]

MACRO_PATH    = CALENDAR_DIR / "macro_calendar.csv"
EARNINGS_PATH = CALENDAR_DIR / "earnings_calendar.csv"


def run() -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{now}] 이벤트 캘린더 수집 시작")
    print(f"  Finnhub key: {'설정됨' if FINNHUB_KEY else '없음'}")
    CALENDAR_DIR.mkdir(parents=True, exist_ok=True)

    # ── 매크로 캘린더 ──
    print("\n[1/4] US 매크로 (Finnhub economic calendar)")
    us_macro = fetch_us_macro(days_ahead=90)

    print("\n[2/4] KR 매크로 (BOK + 통계청 추정)")
    kr_macro = fetch_kr_macro(days_ahead=180)

    existing_macro = _read_csv(MACRO_PATH)
    all_macro = _merge_macro(existing_macro, us_macro + kr_macro)
    _write_csv(MACRO_PATH, all_macro, MACRO_FIELDS)

    # ── 실적 캘린더 ──
    print("\n[3/4] US 실적 (Finnhub earnings calendar)")
    us_earnings = fetch_us_earnings(days_ahead=60)

    print("\n[4/4] KR 실적 (yfinance)")
    kr_earnings = fetch_kr_earnings(days_ahead=60)

    existing_earn = _read_csv(EARNINGS_PATH)
    all_earn = _merge_earnings(existing_earn, us_earnings + kr_earnings)
    _write_csv(EARNINGS_PATH, all_earn, EARNINGS_FIELDS)

    # ── 요약 ──
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_macro  = [r for r in all_macro  if r.get("date") == today_str]
    today_earn   = [r for r in all_earn   if r.get("date") == today_str]
    high_today   = [r for r in today_macro if r.get("impact", "").lower() in {"high", "critical"}]

    print(f"\n=== 수집 완료 ===")
    print(f"  매크로 캘린더: {len(all_macro)}건 (오늘 {len(today_macro)}건, HIGH {len(high_today)}건)")
    print(f"  실적 캘린더:   {len(all_earn)}건 (오늘 {len(today_earn)}건)")
    if high_today:
        print("\n  [HIGH] today's events:")
        for e in high_today:
            print(f"     {e['event']} [forecast={e.get('forecast','')}]")
    print()


if __name__ == "__main__":
    run()
