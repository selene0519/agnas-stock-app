
from __future__ import annotations

import csv
import json
import math
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from zoneinfo import ZoneInfo

from fastapi import Query
from fastapi.routing import APIRoute

KST = ZoneInfo("Asia/Seoul")
NY = ZoneInfo("America/New_York")

KR_FIXED = {(1, 1), (3, 1), (5, 5), (6, 6), (8, 15), (10, 3), (10, 9), (12, 25)}
US_FIXED = {(1, 1), (6, 19), (7, 4), (12, 25)}

def _app_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if parent.name == "mone-web-app" and (parent / "backend").exists():
            return parent
    for parent in [here.parent, *here.parents]:
        if (parent / "backend").exists() and (parent / "frontend").exists():
            return parent
    return here.parents[3]

def _roots() -> List[Path]:
    app = _app_root()
    roots = [app, app / "data", app / "reports", app.parent, app.parent / "data", app.parent / "reports"]
    out: List[Path] = []
    for p in roots:
        try:
            if p.exists() and p not in out:
                out.append(p)
        except Exception:
            pass
    return out

def _find(patterns: Iterable[str], max_files: int = 500) -> List[Path]:
    found: List[Path] = []
    for root in _roots():
        for pattern in patterns:
            try:
                for p in root.glob(pattern):
                    if p.is_file() and p.stat().st_size > 0 and p not in found:
                        found.append(p)
                        if len(found) >= max_files:
                            return found
            except Exception:
                continue
    return sorted(found, key=lambda x: x.stat().st_mtime, reverse=True)

def _safe_rel(path: Optional[Path]) -> str:
    if not path:
        return ""
    for root in _roots():
        try:
            return str(path.relative_to(root))
        except Exception:
            pass
    return str(path)

def _observed_fixed(d: date, fixed: set[Tuple[int, int]]) -> bool:
    if (d.month, d.day) in fixed:
        return True
    prev_day = d - timedelta(days=1)
    next_day = d + timedelta(days=1)
    if d.weekday() == 0 and (prev_day.month, prev_day.day) in fixed:
        return True
    if d.weekday() == 4 and (next_day.month, next_day.day) in fixed:
        return True
    return False

def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))

def _last_weekday(year: int, month: int, weekday: int) -> date:
    cur = date(year, month + 1, 1) - timedelta(days=1) if month < 12 else date(year, 12, 31)
    while cur.weekday() != weekday:
        cur -= timedelta(days=1)
    return cur

def _easter(year: int) -> date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)

def _us_market_holiday(d: date) -> bool:
    if d.weekday() >= 5:
        return True
    y = d.year
    floating = {
        _nth_weekday(y, 1, 0, 3),
        _nth_weekday(y, 2, 0, 3),
        _easter(y) - timedelta(days=2),
        _last_weekday(y, 5, 0),
        _nth_weekday(y, 9, 0, 1),
        _nth_weekday(y, 11, 3, 4),
    }
    return d in floating or _observed_fixed(d, US_FIXED)

def _kr_holiday(d: date) -> bool:
    return d.weekday() >= 5 or _observed_fixed(d, KR_FIXED)

def _session_desc(session: str) -> str:
    return {
        "kr_premarket": "국장 장전 · 전일 OHLCV/장전 리포트 기준",
        "kr_intraday": "국장 장중 · KIS 현재가/장중 스냅샷 우선",
        "kr_after_close": "국장 장마감 후 · 당일 OHLCV 마감 기준",
        "kr_closed_weekend": "국장 휴장일 · 지난 세션 복기 모드",
        "kr_closed_holiday": "국장 공휴일 · 지난 세션 복기 모드",
        "us_premarket": "미장 장전 · 뉴욕 프리마켓 기준",
        "us_intraday": "미장 장중 · 뉴욕 본장 현재가 기준",
        "us_after_close": "미장 장마감 후 · 당일 OHLCV/마감 검증 기준",
        "us_closed_weekend": "미장 휴장일 · 지난 세션 복기 모드",
        "us_closed_holiday": "미장 공휴일 · 지난 세션 복기 모드",
    }.get(session, session)

def session_payload(market: str = "kr") -> Dict[str, Any]:
    market = (market or "kr").lower()
    now_kst = datetime.now(KST)
    if market == "us":
        ny = now_kst.astimezone(NY)
        d, t = ny.date(), ny.time()
        holiday = _us_market_holiday(d)
        if holiday:
            ps = "us_closed_weekend" if d.weekday() >= 5 else "us_closed_holiday"
            is_open = False
        elif time(4, 0) <= t < time(9, 30):
            ps, is_open = "us_premarket", False
        elif time(9, 30) <= t < time(16, 0):
            ps, is_open = "us_intraday", True
        else:
            ps, is_open = "us_after_close", False
        return {
            "status": "OK",
            "market": "us",
            "priceSession": ps,
            "isOpen": is_open,
            "isHoliday": holiday,
            "isWeekend": d.weekday() >= 5,
            "reviewMode": not is_open,
            "timezone": "America/New_York",
            "dst": ny.dst() != timedelta(0),
            "kstNow": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
            "nyNow": ny.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "sessionDescription": _session_desc(ps),
        }

    d = now_kst.date()
    hhmm = now_kst.hour * 100 + now_kst.minute
    holiday = _kr_holiday(d)
    if holiday:
        ps = "kr_closed_weekend" if d.weekday() >= 5 else "kr_closed_holiday"
        is_open = False
    elif hhmm < 900:
        ps, is_open = "kr_premarket", False
    elif hhmm < 1530:
        ps, is_open = "kr_intraday", True
    else:
        ps, is_open = "kr_after_close", False
    return {
        "status": "OK",
        "market": "kr",
        "priceSession": ps,
        "isOpen": is_open,
        "isHoliday": holiday,
        "isWeekend": d.weekday() >= 5,
        "reviewMode": not is_open,
        "timezone": "Asia/Seoul",
        "dst": False,
        "kstNow": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "marketNow": now_kst.strftime("%Y-%m-%d %H:%M:%S KST"),
        "sessionDescription": _session_desc(ps),
    }

def _patterns(market: str) -> Dict[str, List[str]]:
    return {
        "candidates": [f"candidate_universe_{market}.csv", f"reports/*candidate*{market}*.csv", f"reports/*recommend*{market}*.csv", f"reports/*action*{market}*.csv"],
        "ohlcv": [f"data/market/ohlcv/{market}_*_daily.csv", f"data/**/*ohlcv*{market}*.csv", f"reports/**/*ohlcv*{market}*.csv"],
        "quotes": [f"**/kis_current_price_{market}.csv", f"**/intraday_quote_snapshot_{market}.csv", f"data/**/*quote*{market}*.csv", f"reports/**/*price*{market}*.csv"],
        "company": [f"reports/*company*{market}*.csv", f"reports/*financial*{market}*.csv", f"data/**/*financial*{market}*.csv"],
        "predictions": ["predictions.csv", f"reports/*prediction*{market}*.csv", "reports/*prediction*.csv", "data/history/prediction*.csv"],
        "virtual": ["paper_trading*.csv", "data/history/*virtual*.csv", "data/history/*trading*.csv", "reports/*backtest*.csv", "reports/*trade*.csv"],
    }

def _count_records(p: Path) -> int:
    try:
        if p.suffix.lower() == ".json":
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return len(data)
            if isinstance(data, dict):
                for k in ("items", "data", "rows", "records"):
                    if isinstance(data.get(k), list):
                        return len(data[k])
                return 1
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with p.open("r", encoding=enc, newline="") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    return sum(1 for _ in reader)
            except Exception:
                continue
    except Exception:
        return 0
    return 0

def _mtime(p: Path) -> Dict[str, Any]:
    st = p.stat()
    dt = datetime.fromtimestamp(st.st_mtime, tz=KST)
    return {"path": _safe_rel(p), "mtime": dt.strftime("%Y-%m-%d %H:%M:%S KST"), "date": dt.date().isoformat(), "size": st.st_size}

def _expected_date(session: Dict[str, Any]) -> date:
    now = datetime.now(KST)
    if session["market"] == "us":
        ny = now.astimezone(NY)
        if session["priceSession"] in {"us_premarket", "us_after_close"} and ny.time() < time(16, 0):
            return ny.date() - timedelta(days=1)
        return ny.date()
    if session["priceSession"] == "kr_premarket":
        return now.date() - timedelta(days=1)
    return now.date()

def data_quality_payload(market: str = "kr") -> Dict[str, Any]:
    s = session_payload(market)
    m = s["market"]
    expected = _expected_date(s)
    items = []
    stale = partial = nodata = 0
    for source, pats in _patterns(m).items():
        files = _find(pats, max_files=50)
        newest = files[0] if files else None
        if newest is None:
            nodata += 1
            items.append({"source": source, "status": "NO_DATA", "records": 0, "path": "", "mtime": "", "reason": "file not found"})
            continue
        meta = _mtime(newest)
        records = _count_records(newest)
        fdate = date.fromisoformat(meta["date"])
        if s["isHoliday"]:
            status = "NORMAL" if records > 0 else "PARTIAL"
        elif fdate >= expected and records > 0:
            status = "NORMAL"
        elif records > 0:
            status = "STALE"
            stale += 1
        else:
            status = "PARTIAL"
            partial += 1
        items.append({"source": source, "status": status, "records": records, **meta, "expectedFreshDate": expected.isoformat()})

    if nodata == len(items):
        overall = "NO_DATA"
    elif stale and s["isOpen"]:
        overall = "STALE"
    elif any(x["status"] in {"PARTIAL", "NO_DATA"} for x in items):
        overall = "PARTIAL"
    else:
        overall = "NORMAL"
    kill = overall in {"STALE", "NO_DATA", "ERROR"} and not s["isHoliday"]
    return {"status": "OK", "market": m, "dataStatus": overall, "killSwitch": kill, "priceSession": s["priceSession"], "sessionDescription": s["sessionDescription"], "isHoliday": s["isHoliday"], "reviewMode": s["reviewMode"], "items": items, "searchRoots": [str(x) for x in _roots()]}

def position_size_payload(entry: float, cash: float, strategy: str = "balanced", market: str = "kr") -> Dict[str, Any]:
    weights = {"conservative": 0.02, "balanced": 0.05, "aggressive": 0.12, "보수": 0.02, "균형": 0.05, "공격": 0.12}
    key = (strategy or "balanced").lower()
    w = weights.get(key, 0.05)
    entry = float(entry or 0)
    cash = float(cash or 0)
    budget = max(0.0, cash * w)
    qty = int(budget // entry) if entry > 0 else 0
    return {"status": "OK", "market": market, "strategy": strategy, "cash": cash, "allocationPct": round(w * 100, 2), "allocatedBudget": round(budget, 2), "entryPrice": entry, "quantity": qty, "estimatedOrderAmount": round(qty * entry, 2), "cashRemainAfterOrder": round(cash - qty * entry, 2)}

def token_status_payload() -> Dict[str, Any]:
    files = _find(["**/*kis*token*.json", "**/*kis*token*.txt", "**/token_cache.json", "**/kis_access_token*"], max_files=10)
    newest = files[0] if files else None
    out = {"status": "OK" if newest else "NO_DATA", "hasTokenCache": newest is not None, "path": _safe_rel(newest), "mtime": "", "note": "토큰 값은 보안상 반환하지 않습니다. 캐시 파일 존재와 수정시각만 표시합니다."}
    if newest:
        out["mtime"] = _mtime(newest)["mtime"]
    return out

def _read_csv(p: Path) -> List[Dict[str, Any]]:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with p.open("r", encoding=enc, newline="") as f:
                return [{**row, "_source_file": p.name} for row in csv.DictReader(f)]
        except Exception:
            continue
    return []

def _num(v: Any) -> float:
    try:
        s = str(v or "").replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        if not s or s.lower() in {"nan", "none", "null", "-", "na"}:
            return 0.0
        n = float(s)
        return 0.0 if math.isnan(n) else n
    except Exception:
        return 0.0

def _text(row: Dict[str, Any], names: Iterable[str]) -> str:
    low = {str(k).lower(): v for k, v in row.items()}
    for n in names:
        if n in row and str(row[n]).strip():
            return str(row[n]).strip()
        if n.lower() in low and str(low[n.lower()]).strip():
            return str(low[n.lower()]).strip()
    return ""

def _symbol(row: Dict[str, Any]) -> str:
    raw = _text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "종목"]).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = "".join(ch for ch in raw if ch.isalnum() or ch in ".-")
    if raw.isdigit() and len(raw) < 6:
        raw = raw.zfill(6)
    if raw.lower() in {"", "nan", "none", "null"}:
        return ""
    return raw.upper() if not raw.isdigit() else raw

def near_alerts_payload(market: str = "kr", threshold_pct: float = 1.0, limit: int = 20) -> Dict[str, Any]:
    files = _find([f"candidate_universe_{market}.csv", f"reports/*recommend*{market}*.csv", f"reports/*action*{market}*.csv", "predictions.csv", "reports/*prediction*.csv"], max_files=30)
    alerts, seen = [], set()
    for f in files:
        for row in _read_csv(f):
            sym = _symbol(row)
            if not sym or sym in seen:
                continue
            current = _num(_text(row, ["currentPrice", "current_price", "last_price", "현재가", "close", "prev_close"]))
            entry = _num(_text(row, ["entry", "entry_price", "preferred_entry", "technical_entry", "진입가", "base_price", "기준가"]))
            stop = _num(_text(row, ["stop", "stop_loss", "stopLoss", "손절가"]))
            name = _text(row, ["name", "stock_name", "company_name", "종목명"]) or sym
            if current <= 0:
                continue
            checks = []
            if entry > 0:
                checks.append(("ENTRY_NEAR", entry, abs(current - entry) / entry * 100))
            if stop > 0:
                checks.append(("STOP_NEAR", stop, abs(current - stop) / stop * 100))
            checks.sort(key=lambda x: x[2])
            if checks and checks[0][2] <= threshold_pct:
                kind, ref, dist = checks[0]
                alerts.append({"symbol": sym, "name": name, "market": market, "type": kind, "currentPrice": current, "referencePrice": ref, "distancePct": round(dist, 2), "message": "진입가 임박" if kind == "ENTRY_NEAR" else "손절가 임박", "source": f.name})
                seen.add(sym)
            if len(alerts) >= limit:
                return {"status": "OK", "market": market, "thresholdPct": threshold_pct, "count": len(alerts), "items": alerts}
    return {"status": "OK" if alerts else "NO_ALERT", "market": market, "thresholdPct": threshold_pct, "count": len(alerts), "items": alerts}

def register_mone_v75_session_guard_routes(app):
    replace_paths = {"/api/session", "/api/data/quality", "/api/position/size", "/api/risk/near-alerts", "/api/kis/token/status"}
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)]

    @app.get("/api/session")
    def session(market: str = Query("kr")):
        if market == "all":
            return {"status": "OK", "kr": session_payload("kr"), "us": session_payload("us")}
        return session_payload(market)

    @app.get("/api/data/quality")
    def data_quality(market: str = Query("kr")):
        if market == "all":
            return {"status": "OK", "kr": data_quality_payload("kr"), "us": data_quality_payload("us")}
        return data_quality_payload(market)

    @app.get("/api/position/size")
    def position_size(entry: float = Query(...), cash: float = Query(...), strategy: str = Query("balanced"), market: str = Query("kr")):
        return position_size_payload(entry=entry, cash=cash, strategy=strategy, market=market)

    @app.get("/api/risk/near-alerts")
    def near_alerts(market: str = Query("kr"), thresholdPct: float = Query(1.0), limit: int = Query(20)):
        return near_alerts_payload(market=market, threshold_pct=thresholdPct, limit=limit)

    @app.get("/api/kis/token/status")
    def kis_token_status():
        return token_status_payload()
