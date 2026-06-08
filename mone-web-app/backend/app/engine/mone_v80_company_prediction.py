
from __future__ import annotations

import csv
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
from zoneinfo import ZoneInfo

from fastapi import Query
from fastapi.routing import APIRoute

KST = ZoneInfo("Asia/Seoul")

KR_NAME_MAP = {
    "005930": "삼성전자", "000660": "SK하이닉스", "003490": "대한항공", "373220": "LG에너지솔루션",
    "131970": "두산테스나", "222800": "심텍", "005380": "현대차", "034020": "두산에너빌리티",
    "009540": "HD한국조선해양", "047810": "한국항공우주", "015760": "한국전력", "058470": "리노공업",
    "247540": "에코프로비엠", "090360": "로보스타", "196170": "알테오젠", "375500": "DL이앤씨",
    "403870": "HPSP", "001440": "대한전선",
}
US_NAME_MAP = {
    "NVDA": "NVIDIA", "GOOGL": "Alphabet", "GOOG": "Alphabet", "TSLA": "Tesla", "AAPL": "Apple",
    "MSFT": "Microsoft", "AMZN": "Amazon", "PLTR": "Palantir", "INTC": "Intel", "AMD": "AMD",
    "NBIS": "Nebius", "CRCL": "Circle", "RKLB": "Rocket Lab", "ASTS": "AST SpaceMobile",
    "SNDK": "SanDisk", "CAT": "Caterpillar", "BMNR": "BMNR", "LITE": "Lumentum",
}

TERM_DAYS = {
    "short": 3,
    "day": 3,
    "scalp": 3,
    "단기": 3,
    "swing": 15,
    "스윙": 15,
    "mid": 60,
    "middle": 60,
    "long": 60,
    "중기": 60,
    "중장기": 60,
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

def _roots() -> List[Path]:
    app = _app_root()
    roots = [app, app / "data", app / "reports", app.parent, app.parent / "data", app.parent / "reports"]
    out = []
    for p in roots:
        if p.exists() and p not in out:
            out.append(p)
    return out

def _find(patterns: Iterable[str], max_files: int = 200) -> List[Path]:
    found: List[Path] = []
    app_parent = _app_root().parent
    for root in _roots():
        for pattern in patterns:
            if root == app_parent and str(pattern).startswith("**/"):
                continue
            try:
                for p in root.glob(pattern):
                    if p.is_file() and p.stat().st_size > 0 and p not in found:
                        found.append(p)
                        if len(found) >= max_files:
                            return found
            except Exception:
                pass
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)

def _rel(path: Path) -> str:
    for root in _roots():
        try:
            return str(path.relative_to(root))
        except Exception:
            pass
    return str(path)

def _read_csv(path: Path) -> List[Dict[str, Any]]:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [{**row, "_source_file": path.name, "_source_path": _rel(path)} for row in csv.DictReader(f)]
        except Exception:
            continue
    return []

def _num(v: Any, default: float = 0.0) -> float:
    try:
        s = str(v if v is not None else "").replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        if not s or s.lower() in {"nan", "none", "null", "na", "-"}:
            return default
        n = float(s)
        return default if math.isnan(n) else n
    except Exception:
        return default

def _text(row: Dict[str, Any], keys: Iterable[str]) -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
        if k.lower() in lower and str(lower[k.lower()]).strip():
            return str(lower[k.lower()]).strip()
    return ""

def _symbol(row: Dict[str, Any]) -> str:
    raw = _text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "종목"]).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = "".join(ch for ch in raw if ch.isalnum() or ch in ".-")
    if raw.isdigit() and len(raw) < 6:
        raw = raw.zfill(6)
    return raw.upper() if raw and not raw.isdigit() else raw

def _market(symbol: str, row: Dict[str, Any]) -> str:
    raw = _text(row, ["market", "시장", "exchange"]).lower()
    if raw in {"kr", "kospi", "kosdaq", "국장", "korea"}:
        return "kr"
    if raw in {"us", "nasdaq", "nyse", "미장", "usa"}:
        return "us"
    return "kr" if symbol.isdigit() else "us"

def _name(symbol: str, market: str, raw: str = "") -> str:
    sym = str(symbol or "").upper()
    mapped = KR_NAME_MAP.get(sym) if market == "kr" else US_NAME_MAP.get(sym)
    if mapped:
        return mapped
    raw = str(raw or "").strip()
    if not raw or raw == sym or any(x in raw for x in ["ì", "ë", "í", "ê", "Â", "�"]):
        return sym
    return raw

def _fmt_price(v: float, market: str) -> str:
    if v <= 0:
        return "-"
    return f"USD {v:,.2f}" if market == "us" else f"KRW {round(v):,}"

def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%" if v >= 0 else f"{v:.1f}%"

def _company_files(market: str) -> List[Path]:
    return _find([
        f"reports/v93_company_integrated_{market}.csv",
        f"reports/v92_company_integrated_{market}.csv",
        f"reports/v92_company_summary_cards_{market}.csv",
        f"reports/v92_company_clean_{market}.csv",
        f"reports/v92_company_cards_{market}.csv",
        f"reports/v91_company_integrated_{market}.csv",
        f"reports/v85_company_integrated_{market}.csv",
        f"reports/v84_company_integrated_{market}.csv",
        f"reports/v83_company_integrated_{market}.csv",
        f"reports/v82_company_integrated_{market}.csv",
        f"reports/v81_company_summary_cards_{market}.csv",
        f"reports/v81_company_cards_{market}.csv",
        f"reports/v80_company_cards_{market}.csv",
        f"reports/*company*{market}*.csv",
        f"data/*company*{market}*.csv",
        f"data/*fundamental*{market}*.csv",
    ], max_files=50)

def _prediction_files(market: str) -> List[Path]:
    return _find([
        "predictions.csv",
        f"reports/*prediction*{market}*.csv",
        f"reports/*recommend*{market}*.csv",
        f"reports/*action*{market}*.csv",
        f"**/candidate_universe_{market}.csv",
    ], max_files=80)

def _ohlcv_ref(symbol: str, market: str) -> Dict[str, Any]:
    sym = symbol.upper()
    files = _find([
        f"data/market/ohlcv/{market}_{sym}_daily.csv",
        f"**/ohlcv/{market}_{sym}_daily.csv",
        f"**/{market}_{sym}_daily.csv",
        f"**/*{sym}*daily*.csv",
        f"**/*{sym}*ohlcv*.csv",
    ], max_files=20)
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

def _company_items(market: str, limit: int = 200, q: str = "") -> Dict[str, Any]:
    market = (market or "all").lower()
    markets = ["kr", "us"] if market == "all" else [market]
    seen = set()
    items = []

    for m in markets:
        for f in _company_files(m):
            for row in _read_csv(f):
                sym = _symbol(row)
                if not sym:
                    continue
                mm = _market(sym, row)
                if market != "all" and mm != market:
                    continue
                key = f"{mm}-{sym}"
                if key in seen:
                    continue
                seen.add(key)

                eps = _num(_text(row, ["eps", "EPS", "주당순이익"]))
                per = _num(_text(row, ["per", "PER"]))
                pbr = _num(_text(row, ["pbr", "PBR"]))
                roe = _num(_text(row, ["roe", "ROE"]))
                revenue = _num(_text(row, ["revenue", "sales", "매출", "매출액"]))
                op = _num(_text(row, ["operatingProfit", "operating_profit", "영업이익"]))
                net = _num(_text(row, ["netIncome", "net_income", "순이익"]))
                debt = _num(_text(row, ["debtRatio", "debt_ratio", "부채비율"]))
                flow = _num(_text(row, ["flowScore", "flow_score", "수급점수"]))

                missing = []
                for label, value in [("EPS", eps), ("PER", per), ("PBR", pbr), ("ROE", roe), ("매출", revenue), ("영업이익", op), ("순이익", net)]:
                    if value == 0:
                        missing.append(label)
                status = "OK" if len(missing) <= 2 else "PARTIAL"
                reason = "정상 연결" if status == "OK" else "CSV/API 누락 또는 컬럼 매핑 부족"

                score = 50.0
                if per > 0 and per < 25: score += 8
                if pbr > 0 and pbr < 3: score += 5
                if roe > 0: score += min(15, roe / 2)
                if debt > 0 and debt < 150: score += 5
                if missing: score -= min(25, len(missing) * 3)

                item = {
                    "id": key,
                    "symbol": sym,
                    "name": _name(sym, mm, _text(row, ["name", "company", "company_name", "종목명"])),
                    "market": mm,
                    "eps": eps,
                    "per": per,
                    "pbr": pbr,
                    "roe": roe,
                    "revenue": revenue,
                    "operatingProfit": op,
                    "netIncome": net,
                    "debtRatio": debt,
                    "flowScore": flow,
                    "fundamentalScore": round(max(0, min(100, score)), 1),
                    "missingFields": missing,
                    "dataStatus": status,
                    "missingReason": reason,
                    "source": f.name,
                }
                text = (sym + " " + item["name"]).lower()
                if q and q.lower() not in text:
                    continue
                items.append(item)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break
    return {"status": "OK", "market": market, "count": len(items), "items": items[:limit], "updatedAt": datetime.now(KST).isoformat()}

def _base_probability(row: Dict[str, Any], market: str, term: str, strategy: str) -> float:
    raw = _num(_text(row, ["probability", "prob", "probabilityText", "확률"]), 0)
    if raw > 1 and raw <= 100:
        base = raw
    elif raw > 0 and raw <= 1:
        base = raw * 100
    else:
        base = 52 if market == "us" else 48

    term = (term or "swing").lower()
    strategy = (strategy or "balanced").lower()

    if term in {"short", "day", "단기"}:
        base -= 3
    elif term in {"mid", "long", "중기", "중장기"}:
        base += 4

    if strategy in {"conservative", "보수"}:
        base -= 4
    elif strategy in {"aggressive", "공격"}:
        base += 5

    return max(5, min(88, base))

def _prediction_items(market: str = "all", term: str = "swing", strategy: str = "balanced", limit: int = 300) -> Dict[str, Any]:
    market = (market or "all").lower()
    markets = ["kr", "us"] if market == "all" else [market]
    seen = set()
    items = []
    term_days = TERM_DAYS.get((term or "swing").lower(), 15)

    for m in markets:
        for f in _prediction_files(m):
            for row in _read_csv(f):
                sym = _symbol(row)
                if not sym:
                    continue
                mm = _market(sym, row)
                if market != "all" and mm != market:
                    continue
                key = f"{mm}-{sym}"
                if key in seen:
                    continue
                seen.add(key)

                ohlcv = _ohlcv_ref(sym, mm)
                current = _num(_text(row, ["currentPrice", "current_price", "price", "현재가", "base_price", "기준가"]), ohlcv.get("latest", 0))
                entry = _num(_text(row, ["entry", "entryPrice", "entry_price", "진입가", "technical_entry"]), current)
                stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]), entry * 0.95 if entry > 0 else 0)
                target = _num(_text(row, ["target", "targetPrice", "target_price", "목표가", "expectedPrice", "expected_price"]), entry * 1.08 if entry > 0 else 0)
                prob = _base_probability(row, mm, term, strategy)

                # 기간이 길수록 기대가는 목표가 쪽으로 더 가까워지게 단순 보정.
                weight = 0.35 if term_days <= 3 else 0.65 if term_days <= 20 else 0.9
                expected = entry + (target - entry) * weight if entry > 0 and target > 0 else target

                rr = ((target - entry) / max(1, entry - stop)) if entry > 0 and stop > 0 and target > entry else 0
                missing = []
                if current <= 0: missing.append("현재가")
                if entry <= 0: missing.append("진입가")
                if stop <= 0: missing.append("손절가")
                if target <= 0: missing.append("목표가")

                score = prob
                if rr >= 2: score += 6
                if rr < 1.5: score -= 8
                if missing: score -= len(missing) * 4
                if strategy in {"conservative", "보수"} and missing:
                    score -= 10
                if strategy in {"aggressive", "공격"}:
                    score += 3

                item = {
                    "id": key,
                    "symbol": sym,
                    "name": _name(sym, mm, _text(row, ["name", "company", "종목명"])),
                    "market": mm,
                    "term": term,
                    "strategy": strategy,
                    "termDays": term_days,
                    "currentPrice": current,
                    "entryPrice": entry,
                    "stopPrice": stop,
                    "targetPrice": target,
                    "expectedPrice": expected,
                    "probability": round(prob, 1),
                    "score": round(max(0, min(100, score)), 1),
                    "rr": round(rr, 2),
                    "currentPriceText": _fmt_price(current, mm),
                    "entryText": _fmt_price(entry, mm),
                    "stopText": _fmt_price(stop, mm),
                    "targetText": _fmt_price(target, mm),
                    "expectedPriceText": _fmt_price(expected, mm),
                    "probabilityText": _fmt_pct(prob),
                    "missingFields": missing,
                    "dataStatus": "PARTIAL" if missing else "OK",
                    "source": f.name,
                }
                items.append(item)
                if len(items) >= limit:
                    break
            if len(items) >= limit:
                break

    items.sort(key=lambda x: (x.get("dataStatus") != "OK", -x.get("score", 0)))
    return {
        "status": "OK",
        "market": market,
        "term": term,
        "strategy": strategy,
        "count": len(items[:limit]),
        "items": items[:limit],
        "updatedAt": datetime.now(KST).isoformat(),
    }

def register_mone_v80_company_prediction_routes(app):
    replace_paths = {"/api/company-analysis", "/api/predictions/table", "/api/predictions/matrix"}
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)]

    @app.get("/api/company-analysis")
    def company_analysis(market: str = Query("all"), limit: int = Query(200), q: str = Query("")):
        return _company_items(market=market, limit=limit, q=q)

    @app.get("/api/predictions/table")
    def predictions_table(
        market: str = Query("all"),
        mode: str = Query("balanced"),
        horizon: str = Query("swing"),
        strategy: str = Query(""),
        term: str = Query(""),
        limit: int = Query(300),
    ):
        return _prediction_items(
            market=market,
            term=term or horizon or "swing",
            strategy=strategy or mode or "balanced",
            limit=limit,
        )

    @app.get("/api/predictions/matrix")
    def predictions_matrix(market: str = Query("all"), limit: int = Query(80)):
        strategies = ["conservative", "balanced", "aggressive"]
        terms = ["short", "swing", "mid"]
        matrix = {}
        for strategy in strategies:
            matrix[strategy] = {}
            for term in terms:
                payload = _prediction_items(market=market, term=term, strategy=strategy, limit=limit)
                matrix[strategy][term] = payload["items"][:10]
        return {"status": "OK", "market": market, "matrix": matrix, "updatedAt": datetime.now(KST).isoformat()}
