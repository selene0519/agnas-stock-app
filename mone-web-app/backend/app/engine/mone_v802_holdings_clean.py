
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from functools import lru_cache
from zoneinfo import ZoneInfo

from fastapi import Query
from fastapi.routing import APIRoute

KST = ZoneInfo("Asia/Seoul")

KR_NAME_MAP = {
    "005930": "삼성전자", "000660": "SK하이닉스", "005380": "현대차", "035420": "NAVER",
    "131970": "두산테스나", "222800": "심텍", "003490": "대한항공", "373220": "LG에너지솔루션",
    "375500": "DL이앤씨", "058470": "리노공업", "403870": "HPSP", "034020": "두산에너빌리티",
    "047810": "한국항공우주", "015760": "한국전력", "009540": "HD한국조선해양", "010120": "LS ELECTRIC",
    "298040": "효성중공업", "006260": "LS", "001440": "대한전선", "012450": "한화에어로스페이스",
    "079550": "LIG넥스원", "064350": "현대로템", "272210": "한화시스템", "247540": "에코프로비엠",
    "090360": "로보스타", "196170": "알테오젠", "086520": "에코프로", "214150": "클래시스",
}
US_NAME_MAP = {
    "SNDK": "SanDisk", "NBIS": "Nebius", "CRCL": "Circle", "BMNR": "BMNR", "ASTS": "AST SpaceMobile",
    "CAT": "Caterpillar", "INTC": "Intel", "LITE": "Lumentum", "RKLB": "Rocket Lab", "NVDA": "NVIDIA",
    "GOOGL": "Alphabet", "TSLA": "Tesla", "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon",
    "PLTR": "Palantir", "AMD": "AMD", "AVGO": "Broadcom", "MU": "Micron", "MRVL": "Marvell",
}

def _app_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if parent.name == "mone-web-app" and (parent / "backend").exists():
            return parent
    for parent in [here.parent, *here.parents]:
        if (parent / "backend").exists() and (parent / "frontend").exists():
            return parent
    return here.parents[3]

@lru_cache(maxsize=1)
def _roots_cached() -> tuple:
    app = _app_root()

    # v8.2 fast fix:
    # ?? ?? app.parent ?? ??? ????.
    # OneDrive/dev ?? ?? ??? ** glob? ??? holdings-clean API? 10? ?? ?? ? ??.
    roots = [
        app,
        app / "data",
        app / "reports",
        app / "backend" / "data",
        app / "backend" / "reports",
        app / "frontend" / "data",
        app / "frontend" / "reports",

        # v8.2.1:
        # ?? holdings_kr.csv / holdings_us.csv ??
        app.parent,
        app.parent / "data",
        app.parent / "reports",
    ]

    out = []
    for p in roots:
        try:
            if p.exists() and p not in out:
                out.append(p)
        except Exception:
            pass
    return tuple(out)

def _roots() -> List[Path]:
    return list(_roots_cached())

@lru_cache(maxsize=512)
def _find_cached(patterns_key: tuple, max_files: int = 200) -> tuple:
    found: List[Path] = []

    for root in _roots_cached():
        for pattern in patterns_key:
            try:
                # emergency fix:
                # app.parent is C:\dev\agnas-stock-app and contains many backups.
                # Never run recursive ** glob on app.parent.
                try:
                    if root == _app_root().parent and str(pattern).startswith("**/"):
                        continue
                except Exception:
                    pass

                for item in root.glob(pattern):
                    try:
                        if item.is_file() and item.stat().st_size > 0 and item not in found:
                            found.append(item)
                            if len(found) >= max_files:
                                return tuple(sorted(found, key=lambda x: x.stat().st_mtime, reverse=True))
                    except Exception:
                        continue
            except Exception:
                continue

    return tuple(sorted(found, key=lambda x: x.stat().st_mtime, reverse=True))

def _find(patterns: Iterable[str], max_files: int = 200) -> List[Path]:
    return list(_find_cached(tuple(patterns), max_files))

def _rel(path: Path) -> str:
    for root in _roots():
        try:
            return str(path.relative_to(root))
        except Exception:
            pass
    return str(path)

def _read_csv(path: Path) -> List[Dict[str, Any]]:
    # cp949 우선: KR 보유/회사 파일이 cp949인 경우 PowerShell과 화면 모두에서 깨짐 방지
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [{**row, "_source_file": path.name, "_source_path": _rel(path)} for row in csv.DictReader(f)]
        except Exception:
            continue
    return []

def _text(row: Dict[str, Any], keys: Iterable[str]) -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
        lk = k.lower()
        if lk in lower and str(lower[lk]).strip():
            return str(lower[lk]).strip()
    return ""

def _num(v: Any, default: float = 0.0) -> float:
    try:
        s = str(v if v is not None else "").replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        if not s or s.lower() in {"nan", "none", "null", "na", "-"}:
            return default
        n = float(s)
        if math.isnan(n):
            return default
        return n
    except Exception:
        return default

def _symbol(row: Dict[str, Any]) -> str:
    raw = _text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "종목", "종목번호"]).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = "".join(ch for ch in raw if ch.isalnum() or ch in ".-")
    if raw.isdigit() and len(raw) < 6:
        raw = raw.zfill(6)
    return raw.upper() if raw and not raw.isdigit() else raw

def _market(symbol: str, row: Dict[str, Any]) -> str:
    raw = _text(row, ["market", "시장", "exchange", "marketType"]).lower()
    if raw in {"kr", "kospi", "kosdaq", "국장", "한국", "korea"}:
        return "kr"
    if raw in {"us", "nasdaq", "nyse", "amex", "미장", "미국", "usa"}:
        return "us"
    return "kr" if symbol.isdigit() else "us"

def _bad_name(raw: str, symbol: str) -> bool:
    if not raw or raw.strip() == "" or raw.upper() == symbol.upper():
        return True
    return any(x in raw for x in ["ì", "ë", "í", "ê", "Â", "ã"])

def _name(symbol: str, market: str, raw: str = "") -> str:
    sym = str(symbol or "").upper()
    if sym.isdigit() and len(sym) < 6:
        sym = sym.zfill(6)
    mapped = KR_NAME_MAP.get(sym) if market == "kr" else US_NAME_MAP.get(sym)
    if mapped:
        return mapped
    raw = str(raw or "").strip()
    if _bad_name(raw, sym):
        return sym
    return raw

def _fmt_price(v: float, market: str) -> str:
    if v <= 0:
        return "-"
    return f"${v:,.2f}" if market == "us" else f"{round(v):,}원"

def _fmt_pct(v: float) -> str:
    if not isinstance(v, (int, float)) or math.isnan(v):
        return "+0.00%"
    return f"{v:+.2f}%"

@lru_cache(maxsize=1)
def _holding_files_cached() -> tuple:
    # 루트 원장만 단일 소스로 사용. data/ 폴더의 holdings는 제외해
    # 삭제 후 되살아남 버그 방지 (user_data.py도 루트 파일만 씀).
    return tuple(_find([
        "holdings_kr.csv",
        "holdings_us.csv",
    ], max_files=2))

def _holding_files() -> List[Path]:
    return list(_holding_files_cached())

@lru_cache(maxsize=16)
def _price_files_cached(market: str) -> tuple:
    return tuple(_find([
        f"reports/kis_current_price_{market}.csv",
        f"data/kis_current_price_{market}.csv",
        f"backend/reports/kis_current_price_{market}.csv",
        f"backend/data/kis_current_price_{market}.csv",
        f"**/kis_current_price_{market}.csv",
        f"**/*current*price*{market}*.csv",
        f"**/*quote*{market}*.csv",
        f"**/candidate_universe_{market}.csv",
        f"**/*recommend*{market}*.csv",
        f"**/*action*{market}*.csv",
        "predictions.csv",
        "**/*prediction*.csv",
    ], max_files=40))

def _price_files(market: str) -> List[Path]:
    return list(_price_files_cached((market or "all").lower()))

def _price_ref(symbol: str, market: str) -> Dict[str, Any]:
    sym = symbol.upper()
    for f in _price_files(market):
        for row in _read_csv(f):
            if _symbol(row) != sym:
                continue
            current = _num(_text(row, ["currentPrice", "current_price", "price", "현재가", "stck_prpr", "last", "base_price", "기준가", "close"]))
            entry = _num(_text(row, ["entry", "entryPrice", "entry_price", "진입가", "technical_entry"]))
            stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]))
            target = _num(_text(row, ["target", "targetPrice", "target_price", "목표가", "expectedPrice", "expected_price"]))
            if current > 0 or entry > 0 or stop > 0 or target > 0:
                return {"current": current, "entry": entry, "stop": stop, "target": target, "source": f.name}
    return {"current": 0.0, "entry": 0.0, "stop": 0.0, "target": 0.0, "source": ""}

@lru_cache(maxsize=2048)
def _ohlcv_files_cached(symbol: str, market: str) -> tuple:
    sym = symbol.upper()
    return tuple(_find([
        f"data/market/ohlcv/{market}_{sym}_daily.csv",
        f"backend/data/market/ohlcv/{market}_{sym}_daily.csv",
        f"reports/ohlcv/{market}_{sym}_daily.csv",
        f"**/ohlcv/{market}_{sym}_daily.csv",
        f"**/{market}_{sym}_daily.csv",
        f"**/*{sym}*daily*.csv",
        f"**/*{sym}*ohlcv*.csv",
    ], max_files=5))

def _ohlcv_ref(symbol: str, market: str) -> Dict[str, Any]:
    sym = symbol.upper()
    files = list(_ohlcv_files_cached(sym, market))
    if not files:
        return {"latest": 0.0, "prev": 0.0, "source": "", "date": ""}
    rows = []
    for row in _read_csv(files[0]):
        close = _num(_text(row, ["close", "Close", "종가", "stck_clpr", "price"]))
        date = _text(row, ["date", "Date", "날짜", "timestamp", "time", "일자"])
        if close > 0:
            rows.append({"close": close, "date": date})
    if not rows:
        return {"latest": 0.0, "prev": 0.0, "source": files[0].name, "date": ""}
    latest = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else {"close": 0.0, "date": ""}
    return {"latest": latest["close"], "prev": prev["close"], "source": files[0].name, "date": latest["date"]}

def _stop_loss_delay_info(symbol: str, market: str, stop: float, current: float) -> Dict[str, Any]:
    """현재가가 손절가를 이미 깼는데 며칠째 들고 있는지(추격매수의 반대 패턴, 손절지연) 계산.

    종가 기준으로 최근부터 거슬러 올라가며, 종가가 손절가 이상이었던 마지막 날 다음부터
    오늘까지 며칠 연속 손절가 밑인지 센다. OHLCV가 없으면 '지금 손절가 밑'이라는 사실만으로
    주의를 주되, 며칠째인지 모르니 위험까지는 올리지 않는다.
    """
    if stop <= 0 or current <= 0 or current >= stop:
        return {"breached": False, "daysSinceBreach": 0, "delayRisk": "정상"}

    sym = symbol.upper()
    files = list(_ohlcv_files_cached(sym, market))
    if not files:
        return {"breached": True, "daysSinceBreach": 0, "delayRisk": "주의"}

    rows = []
    for row in _read_csv(files[0]):
        close = _num(_text(row, ["close", "Close", "종가", "stck_clpr", "price"]))
        date = _text(row, ["date", "Date", "날짜", "timestamp", "time", "일자"])
        if close > 0:
            rows.append({"close": close, "date": date})
    rows.sort(key=lambda r: str(r.get("date") or ""))
    if not rows:
        return {"breached": True, "daysSinceBreach": 0, "delayRisk": "주의"}

    days_since = 0
    for row in reversed(rows):
        if row["close"] >= stop:
            break
        days_since += 1

    delay_risk = "손절지연" if days_since >= 3 else "주의"
    return {"breached": True, "daysSinceBreach": days_since, "delayRisk": delay_risk}

def _candidate_score(row: Dict[str, Any]) -> int:
    score = 0
    for keys in [
        ["currentPrice", "current_price", "price", "현재가"],
        ["avgPrice", "avg_price", "평단", "매입가", "평균단가"],
        ["stop", "stopPrice", "손절가"],
        ["target", "targetPrice", "목표가"],
        ["quantity", "qty", "shares", "수량"],
    ]:
        if _num(_text(row, keys)) > 0:
            score += 1
    return score

def _raw_holdings() -> List[Dict[str, Any]]:
    rows = []
    for f in _holding_files():
        for row in _read_csv(f):
            sym = _symbol(row)
            if not sym:
                continue
            qty = _num(_text(row, ["quantity", "qty", "shares", "수량", "보유수량"]))
            avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평단", "매입가", "평균단가"]))
            stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]))
            target = _num(_text(row, ["target", "targetPrice", "목표가"]))
            if qty > 0 or avg > 0 or stop > 0 or target > 0:
                rows.append(row)
    return rows

def holdings_clean_payload(market: str = "all", limit: int = 500) -> Dict[str, Any]:
    market = (market or "all").lower()
    best: Dict[str, Dict[str, Any]] = {}

    for row in _raw_holdings():
        sym = _symbol(row)
        m = _market(sym, row)
        if market != "all" and m != market:
            continue
        key = f"{m}-{sym}"
        current_score = _candidate_score(row)
        old = best.get(key)
        if old is None or current_score > old["_score"]:
            best[key] = {**row, "_score": current_score}

    items = []
    for key, row in best.items():
        sym = _symbol(row)
        m = _market(sym, row)
        ref = _price_ref(sym, m)
        oh = _ohlcv_ref(sym, m)

        qty = _num(_text(row, ["quantity", "qty", "shares", "수량", "보유수량"]))
        avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평단", "매입가", "평균단가"]))
        current = _num(_text(row, ["currentPrice", "current_price", "price", "현재가"]), ref["current"])
        if current <= 0:
            current = oh["latest"]
        stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]), ref["stop"])
        target = _num(_text(row, ["target", "targetPrice", "목표가"]), ref["target"])
        prev = _num(_text(row, ["prevClose", "previousClose", "prev_close", "전일종가"]), oh["prev"])

        has_change_base = current > 0 and prev > 0
        change = ((current - prev) / prev * 100) if has_change_base else None
        valuation = qty * current if qty > 0 and current > 0 else 0.0
        cost = qty * avg if qty > 0 and avg > 0 else 0.0
        pnl = valuation - cost if valuation > 0 and cost > 0 else 0.0
        pnl_pct = pnl / cost * 100 if cost > 0 else 0.0
        stop_gap = (current - stop) / current * 100 if current > 0 and stop > 0 else None

        missing = []
        if current <= 0: missing.append("현재가")
        if avg <= 0: missing.append("평단")
        if stop <= 0: missing.append("손절가")
        if target <= 0: missing.append("목표가")
        if prev <= 0: missing.append("전일종가")

        risk = "위험" if stop_gap is not None and stop_gap <= 0.5 else "주의" if stop_gap is not None and stop_gap <= 3 else "정상"

        delay = _stop_loss_delay_info(sym, m, stop, current)
        if delay["delayRisk"] == "손절지연":
            risk = "손절지연"

        items.append({
            "id": key,
            "symbol": sym,
            "name": _name(sym, m, _text(row, ["name", "stock_name", "company_name", "종목명"])),
            "market": m,
            "quantity": qty,
            "avgPrice": avg,
            "currentPrice": current,
            "stopPrice": stop,
            "targetPrice": target,
            "prevClose": prev,
            "changePct": change,
            "valuation": valuation,
            "cost": cost,
            "pnl": pnl,
            "pnlPct": pnl_pct,
            "stopGapPct": stop_gap,
            "riskStatus": risk,
            "stopLossBreached": delay["breached"],
            "stopLossDelayDays": delay["daysSinceBreach"],
            "stopLossDelayRisk": delay["delayRisk"],
            "missingFields": missing,
            "dataStatus": "PARTIAL" if missing else "OK",
            "currentPriceText": _fmt_price(current, m),
            "avgPriceText": _fmt_price(avg, m),
            "valuationText": _fmt_price(valuation, m),
            "pnlText": _fmt_price(pnl, m) if pnl else "0",
            "pnlPctText": _fmt_pct(pnl_pct) if cost > 0 else "-",
            "stopText": _fmt_price(stop, m),
            "targetText": _fmt_price(target, m),
            "prevCloseText": _fmt_price(prev, m),
            "changePctText": _fmt_pct(change) if has_change_base else "-",
            "source": row.get("_source_file", ""),
            "quoteSource": ref["source"],
            "ohlcvSource": oh["source"],
            "changeSource": oh["source"],
            "changeDate": oh["date"],
        })

    items.sort(key=lambda x: (x["market"], x["symbol"]))

    total_value = sum(_num(x.get("valuation")) for x in items)
    total_cost = sum(_num(x.get("cost")) for x in items)
    total_pnl = total_value - total_cost if total_value and total_cost else 0.0
    risk_count = sum(1 for x in items if x["riskStatus"] in {"위험", "주의", "손절지연"})

    return {
        "status": "OK",
        "routeVersion": "v80.2-clean",
        "market": market,
        "count": len(items[:limit]),
        "uniqueCount": len(items),
        "items": items[:limit],
        "summary": {
            "holdingCount": len(items),
            "riskCount": risk_count,
            "missingCount": sum(1 for x in items if x["missingFields"]),
            "totalValue": total_value,
            "totalCost": total_cost,
            "totalPnl": total_pnl,
            "totalPnlPct": total_pnl / total_cost * 100 if total_cost > 0 else 0,
            "totalValueText": _fmt_price(total_value, "kr" if market != "us" else "us"),
            "totalPnlText": _fmt_price(total_pnl, "kr" if market != "us" else "us") if total_pnl else "0",
        },
        "updatedAt": datetime.now(KST).isoformat(),
    }

import re as _re_uid

def _sanitize_user_id(raw: str) -> str:
    clean = _re_uid.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))
    return clean[:64]

def _raw_holdings_for_user(user_id: str) -> List[Dict[str, Any]]:
    app_root = _app_root()
    user_dir = app_root / "data" / "users" / user_id
    rows = []
    for mk in ("kr", "us"):
        path = user_dir / f"holdings_{mk}.csv"
        if path.exists() and path.stat().st_size > 0:
            for row in _read_csv(path):
                sym = _symbol(row)
                if not sym:
                    continue
                rows.append(row)
    return rows

def holdings_clean_payload_for_user(user_id: str, market: str = "all", limit: int = 500) -> Dict[str, Any]:
    uid = _sanitize_user_id(user_id)
    if not uid:
        return holdings_clean_payload(market=market, limit=limit)

    # SQLite 우선 조회
    try:
        import sys
        # db 모듈 경로 동적 검색
        for p in sys.path:
            db_path = __import__('pathlib').Path(p) / "app" / "db.py"
            if db_path.exists():
                break
        from app import db as _db_mod
        sqlite_items = _db_mod.get_holdings(uid, market)
        if sqlite_items:
            raw_rows = [{
                "symbol": it["symbol"], "market": it["market"], "name": it["name"],
                "quantity": it["quantity"], "avgPrice": it["avgPrice"],
                "stopPrice": it["stopPrice"], "targetPrice": it["targetPrice"],
                # 브로커 동기화 시 저장된 실제 현재가/평가손익을 전달해야
                # holdings_clean_payload()가 ETF 등 스캔 유니버스 밖 종목까지
                # 0으로 떨어지지 않고 브로커 보고값을 그대로 사용한다.
                "currentPrice": it.get("currentPrice"),
                "evalAmount": it.get("evalAmount"),
                "profitLoss": it.get("profitLoss"),
                "profitLossRate": it.get("profitLossRate"),
            } for it in sqlite_items]
            return _holdings_payload_from_rows(raw_rows, market=market, limit=limit)
    except Exception:
        pass

    # SQLite에 없으면 파일 폴백
    user_rows = _raw_holdings_for_user(uid)
    if user_rows:
        return _holdings_payload_from_rows(user_rows, market=market, limit=limit)
    return holdings_clean_payload(market=market, limit=limit)

def _holdings_payload_from_rows(raw_rows: List[Dict[str, Any]], market: str = "all", limit: int = 500) -> Dict[str, Any]:
    """Same logic as holdings_clean_payload but from provided rows instead of _raw_holdings()."""
    market = (market or "all").lower()
    best: Dict[str, Dict[str, Any]] = {}
    for row in raw_rows:
        sym = _symbol(row)
        if not sym:
            continue
        m = _market(sym, row)
        if market != "all" and m != market:
            continue
        key = f"{m}-{sym}"
        current_score = _candidate_score(row)
        old = best.get(key)
        if old is None or current_score > old["_score"]:
            best[key] = {**row, "_score": current_score}
    # Reuse holdings_clean_payload's item assembly by temporarily monkey-patching _raw_holdings
    # Instead, call the full payload function after writing to a temp context
    # Simpler: just call holdings_clean_payload with the same rows via the existing logic
    import sys
    mod = sys.modules[__name__]
    original_fn = mod._raw_holdings
    mod._raw_holdings = lambda: raw_rows
    try:
        result = holdings_clean_payload(market=market, limit=limit)
    finally:
        mod._raw_holdings = original_fn
    return result

def register_mone_v802_holdings_clean_routes(app):
    from fastapi import Header
    # NOTE: "/api/holdings" 경로는 삭제하지 않는다 — POST/PATCH/DELETE CRUD가 등록되어 있음
    # GET /api/holdings 만 교체 (v80.2 clean 버전으로)
    replace_paths = {
        "/api/holdings-clean",
        "/api/final/holdings-clean",
        "/api/holdings/summary",
        "/api/holdings/risk",
    }
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)]
    # GET /api/holdings 만 선택적으로 교체
    app.router.routes = [
        r for r in app.router.routes
        if not (isinstance(r, APIRoute) and getattr(r, "path", "") == "/api/holdings" and "GET" in getattr(r, "methods", set()))
    ]

    @app.get("/api/holdings-clean")
    def holdings_clean(
        market: str = Query("all"),
        limit: int = Query(500),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ):
        uid = _sanitize_user_id(x_mone_user)
        if uid:
            return holdings_clean_payload_for_user(uid, market=market, limit=limit)
        return holdings_clean_payload(market=market, limit=limit)

    @app.get("/api/final/holdings-clean")
    def final_holdings_clean(
        market: str = Query("all"),
        limit: int = Query(500),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ):
        uid = _sanitize_user_id(x_mone_user)
        if uid:
            return holdings_clean_payload_for_user(uid, market=market, limit=limit)
        return holdings_clean_payload(market=market, limit=limit)

    @app.get("/api/holdings")
    def holdings(
        market: str = Query("all"),
        limit: int = Query(500),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ):
        uid = _sanitize_user_id(x_mone_user)
        if uid:
            return holdings_clean_payload_for_user(uid, market=market, limit=limit)
        return holdings_clean_payload(market=market, limit=limit)

    @app.get("/api/holdings/summary")
    def holdings_summary(
        market: str = Query("all"),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ):
        uid = _sanitize_user_id(x_mone_user)
        payload = (holdings_clean_payload_for_user(uid, market=market, limit=1000)
                   if uid else holdings_clean_payload(market=market, limit=1000))
        return {"status": "OK", "routeVersion": "v80.2-clean", "market": market, **payload["summary"], "updatedAt": payload["updatedAt"]}

    @app.get("/api/holdings/risk")
    def holdings_risk(
        market: str = Query("all"),
        x_mone_user: str = Header(default="", alias="x-mone-user"),
    ):
        uid = _sanitize_user_id(x_mone_user)
        payload = (holdings_clean_payload_for_user(uid, market=market, limit=1000)
                   if uid else holdings_clean_payload(market=market, limit=1000))
        items = [x for x in payload["items"] if x["riskStatus"] in {"위험", "주의", "손절지연"}]
        return {"status": "OK", "routeVersion": "v80.2-clean", "market": market, "count": len(items), "items": items, "updatedAt": payload["updatedAt"]}


# ---------------------------------------------------------------------
# emergency override: exact holdings file lookup only
# Prevents slow recursive glob over project backup folders.
# ---------------------------------------------------------------------
def _project_root_exact() -> Path:
    # app/engine/mone_v802_holdings_clean.py
    # parents: engine -> app -> backend -> mone-web-app -> agnas-stock-app
    return Path(__file__).resolve().parents[4]

def _holding_files() -> List[Path]:
    # 루트 원장만 단일 소스로 사용. data/ 폴더는 제외해 삭제 후 되살아남 방지.
    root = _project_root_exact()
    candidates = [
        root / "holdings_kr.csv",
        root / "holdings_us.csv",
    ]

    out = []
    for path in candidates:
        try:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                out.append(path)
        except Exception:
            pass

    return out

def _price_files(market: str) -> List[Path]:
    root = _project_root_exact()
    market = (market or "").lower()

    candidates = [
        root / "candidate_universe_kr.csv",
        root / "candidate_universe_us.csv",
        root / "predictions.csv",
        root / "data" / "candidate_universe_kr.csv",
        root / "data" / "candidate_universe_us.csv",
        root / "data" / "predictions.csv",
        root / "reports" / f"kis_current_price_{market}.csv",
        root / "data" / f"kis_current_price_{market}.csv",
    ]

    out = []
    for path in candidates:
        try:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                out.append(path)
        except Exception:
            pass

    return out


# ---------------------------------------------------------------------
# emergency override: fast price file lookup only
# Avoid reading large prediction files during holdings-clean.
# ---------------------------------------------------------------------
def _price_files(market: str) -> List[Path]:
    root = _project_root_exact()
    market = (market or "").lower()

    candidates = [
        root / "reports" / f"kis_current_price_{market}.csv",
        root / "data" / f"kis_current_price_{market}.csv",
        root / "data" / "quotes" / f"{market}_quotes.csv",
        root / "reports" / f"quotes_{market}.csv",
        root / f"candidate_universe_{market}.csv",
        root / "data" / f"candidate_universe_{market}.csv",
    ]

    out = []
    for path in candidates:
        try:
            if path.exists() and path.is_file() and path.stat().st_size > 0:
                out.append(path)
        except Exception:
            pass

    return out

def _ohlcv_ref(symbol: str, market: str) -> Dict[str, Any]:
    # holdings-clean should not scan OHLCV folders for every holding.
    # Chart page can use the dedicated OHLCV API instead.
    return {"latest": 0.0, "prev": 0.0, "source": "", "date": ""}
