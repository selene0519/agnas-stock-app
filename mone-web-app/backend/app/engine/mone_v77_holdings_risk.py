
from __future__ import annotations

import csv
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
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
}

DEFAULT_HOLDINGS = [
    {"symbol": "131970", "name": "두산테스나", "market": "kr", "quantity": 30, "avgPrice": 0, "stopPrice": 151617, "targetPrice": 0},
    {"symbol": "222800", "name": "심텍", "market": "kr", "quantity": 55, "avgPrice": 0, "stopPrice": 93856, "targetPrice": 0},
    {"symbol": "005930", "name": "삼성전자", "market": "kr", "quantity": 0, "avgPrice": 0, "stopPrice": 0, "targetPrice": 0},
    {"symbol": "000660", "name": "SK하이닉스", "market": "kr", "quantity": 0, "avgPrice": 0, "stopPrice": 0, "targetPrice": 0},
]

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

def _find(patterns: Iterable[str], max_files: int = 200) -> List[Path]:
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

def _read_csv(path: Path) -> List[Dict[str, Any]]:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [{**row, "_source_file": path.name, "_source_path": _safe_rel(path)} for row in csv.DictReader(f)]
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
    low = {str(k).lower(): v for k, v in row.items()}
    for k in keys:
        if k in row and str(row[k]).strip():
            return str(row[k]).strip()
        if k.lower() in low and str(low[k.lower()]).strip():
            return str(low[k.lower()]).strip()
    return ""

def _symbol(row: Dict[str, Any]) -> str:
    raw = _text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "종목", "종목번호"]).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    raw = "".join(ch for ch in raw if ch.isalnum() or ch in ".-")
    if raw.isdigit() and len(raw) < 6:
        raw = raw.zfill(6)
    if raw.lower() in {"", "nan", "none", "null"}:
        return ""
    return raw.upper() if not raw.isdigit() else raw

def _market(symbol: str, row: Dict[str, Any]) -> str:
    raw = _text(row, ["market", "시장", "exchange"]).lower()
    if raw in {"kr", "kospi", "kosdaq", "국장", "korea"}:
        return "kr"
    if raw in {"us", "nasdaq", "nyse", "미장", "usa"}:
        return "us"
    return "kr" if symbol.isdigit() else "us"

def _clean_name(symbol: str, name: str) -> str:
    raw = str(name or "").strip()
    sym = str(symbol or "").strip().upper()
    mapped = KR_NAME_MAP.get(sym) if sym.isdigit() else US_NAME_MAP.get(sym)
    if mapped:
        return mapped
    if not raw or raw == sym or "ì" in raw or "ë" in raw or "í" in raw or "ê" in raw or "Â" in raw or "�" in raw:
        return sym
    return raw

def _latest_quote_map(market: str) -> Dict[str, Dict[str, Any]]:
    files = _find([
        f"reports/kis_current_price_{market}.csv",
        f"**/kis_current_price_{market}.csv",
        f"**/*current*price*{market}*.csv",
        f"**/*quote*{market}*.csv",
    ], max_files=20)
    out: Dict[str, Dict[str, Any]] = {}
    for f in files:
        for row in _read_csv(f):
            sym = _symbol(row)
            if not sym:
                continue
            price = _num(_text(row, ["currentPrice", "current_price", "price", "close", "현재가", "stck_prpr", "last"]))
            change = _text(row, ["changePctText", "change_pct", "changeRate", "change", "등락률"]) or "+0.00%"
            if price > 0 and sym not in out:
                out[sym] = {"price": price, "change": change, "source": f.name}
    return out

def _recommendation_map(market: str) -> Dict[str, Dict[str, Any]]:
    files = _find([
        f"reports/*recommend*{market}*.csv",
        f"reports/*action*{market}*.csv",
        "predictions.csv",
        f"reports/*prediction*{market}*.csv",
        "reports/*prediction*.csv",
    ], max_files=30)
    out: Dict[str, Dict[str, Any]] = {}
    for f in files:
        for row in _read_csv(f):
            sym = _symbol(row)
            if not sym or sym in out:
                continue
            entry = _num(_text(row, ["entry", "entryPrice", "entry_price", "preferred_entry", "technical_entry", "진입가", "base_price", "기준가"]))
            stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "stopLoss", "손절가"]))
            target = _num(_text(row, ["target", "targetPrice", "target_price", "목표가", "expectedPrice", "expected_price"]))
            prob = _text(row, ["probabilityText", "probability", "prob", "확률"])
            out[sym] = {"entry": entry, "stop": stop, "target": target, "probabilityText": prob, "source": f.name}
    return out

def _holding_rows() -> List[Dict[str, Any]]:
    files = _find([
        "**/*holdings*.csv", "**/*holding*.csv", "**/*portfolio*.csv", "**/*position*.csv",
        "data/history/*holdings*.csv", "reports/*holdings*.csv", "reports/*portfolio*.csv",
    ], max_files=40)
    rows: List[Dict[str, Any]] = []
    for f in files:
        for row in _read_csv(f):
            sym = _symbol(row)
            qty = _num(_text(row, ["quantity", "qty", "shares", "수량", "보유수량"]))
            # Skip pure watchlist rows unless they have quantity/avg/stop data.
            avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평단", "매입가", "평균단가"]))
            stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]))
            if sym and (qty > 0 or avg > 0 or stop > 0):
                rows.append(row)
    if rows:
        return rows
    return [{**r, "_source_file": "default_holdings_fallback", "_source_path": "built-in fallback"} for r in DEFAULT_HOLDINGS]

def _fmt_price(v: float, market: str) -> str:
    if v <= 0:
        return "-"
    return f"USD {v:,.2f}" if market == "us" else f"KRW {round(v):,}"

def _ohlcv_rows(market: str, symbol: str) -> List[Dict[str, Any]]:
    files = _find([f"market/ohlcv/{market}_{symbol}_daily.csv"], max_files=1)
    if not files:
        return []
    rows = _read_csv(files[0])
    rows.sort(key=lambda r: str(r.get("date") or r.get("Date") or ""))
    return rows

def _stop_loss_delay_info(market: str, symbol: str, stop: float, current: float) -> Dict[str, Any]:
    """현재가가 손절가를 이미 깼는데 며칠째 들고 있는지(추격매수의 반대 패턴, 손절지연) 계산.

    종가 기준으로 최근부터 거슬러 올라가며, 종가가 손절가 이상이었던 마지막 날 다음부터
    오늘까지 며칠 연속 손절가 밑인지 센다. OHLCV가 없으면 '오늘 손절가 밑'이라는 사실만으로
    WATCH를 준다(완전히 모르는 척 하지 않되, 과장하지 않는다).
    """
    if stop <= 0 or current <= 0 or current >= stop:
        return {"breached": False, "daysSinceBreach": 0, "delayRisk": "NONE"}

    rows = _ohlcv_rows(market, symbol)
    if not rows:
        return {"breached": True, "daysSinceBreach": 0, "delayRisk": "WATCH"}

    days_since = 0
    for row in reversed(rows):
        close = _num(row.get("close") or row.get("Close"))
        if close <= 0:
            continue
        if close >= stop:
            break
        days_since += 1

    if days_since >= 3:
        delay_risk = "HIGH"
    elif days_since >= 1:
        delay_risk = "WATCH"
    else:
        delay_risk = "WATCH"  # 오늘 처음 깼어도 watch — HIGH는 "지연"이 누적된 경우로 한정
    return {"breached": True, "daysSinceBreach": days_since, "delayRisk": delay_risk}

def holdings_payload(market: str = "all", limit: int = 200) -> Dict[str, Any]:
    market = (market or "all").lower()
    quote_kr = _latest_quote_map("kr")
    quote_us = _latest_quote_map("us")
    rec_kr = _recommendation_map("kr")
    rec_us = _recommendation_map("us")
    seen = set()
    items = []

    for row in _holding_rows():
        sym = _symbol(row)
        if not sym:
            continue
        m = _market(sym, row)
        if market != "all" and m != market:
            continue
        key = f"{m}-{sym}"
        if key in seen:
            continue
        seen.add(key)

        quote = (quote_kr if m == "kr" else quote_us).get(sym, {})
        rec = (rec_kr if m == "kr" else rec_us).get(sym, {})
        qty = _num(_text(row, ["quantity", "qty", "shares", "수량", "보유수량"]))
        avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평단", "매입가", "평균단가"]))
        current = _num(_text(row, ["currentPrice", "current_price", "price", "현재가"]), quote.get("price", 0))
        stop = _num(_text(row, ["stop", "stopPrice", "stop_loss", "손절가"]), rec.get("stop", 0))
        target = _num(_text(row, ["target", "targetPrice", "목표가"]), rec.get("target", 0))
        entry = _num(_text(row, ["entry", "entryPrice", "진입가"]), rec.get("entry", avg))
        name = _clean_name(sym, _text(row, ["name", "stock_name", "company_name", "종목명"]))

        valuation = qty * current if qty > 0 and current > 0 else 0
        cost = qty * avg if qty > 0 and avg > 0 else 0
        pnl = valuation - cost if valuation > 0 and cost > 0 else 0
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        stop_gap_pct = ((current - stop) / current * 100) if current > 0 and stop > 0 else None
        target_gap_pct = ((target - current) / current * 100) if current > 0 and target > 0 else None

        if stop_gap_pct is not None and stop_gap_pct <= 0.5:
            risk = "HIGH"
        elif stop_gap_pct is not None and stop_gap_pct <= 3:
            risk = "WATCH"
        else:
            risk = "NORMAL"

        delay = _stop_loss_delay_info(m, sym, stop, current)
        if delay["delayRisk"] == "HIGH":
            risk = "STOP_LOSS_DELAY"

        items.append({
            "id": key,
            "symbol": sym,
            "name": name,
            "market": m,
            "quantity": qty,
            "avgPrice": avg,
            "currentPrice": current,
            "entryPrice": entry,
            "stopPrice": stop,
            "targetPrice": target,
            "valuation": valuation,
            "cost": cost,
            "pnl": pnl,
            "pnlPct": pnl_pct,
            "stopGapPct": stop_gap_pct,
            "targetGapPct": target_gap_pct,
            "riskStatus": risk,
            "stopLossBreached": delay["breached"],
            "stopLossDelayDays": delay["daysSinceBreach"],
            "stopLossDelayRisk": delay["delayRisk"],
            "currentPriceText": _fmt_price(current, m),
            "avgPriceText": _fmt_price(avg, m),
            "valuationText": _fmt_price(valuation, m),
            "pnlText": _fmt_price(pnl, m) if pnl != 0 else "0",
            "pnlPctText": f"{pnl_pct:+.2f}%" if cost > 0 else "-",
            "stopText": _fmt_price(stop, m),
            "targetText": _fmt_price(target, m),
            "currency": "KRW" if m == "kr" else "USD",
            "currentPriceDisplay": _fmt_price(current, m),
            "valuationDisplay": _fmt_price(valuation, m),
            "stopDisplay": _fmt_price(stop, m),
            "targetDisplay": _fmt_price(target, m),
            "changePctText": quote.get("change", "+0.00%"),
            "source": row.get("_source_file", ""),
            "quoteSource": quote.get("source", ""),
            "recommendationSource": rec.get("source", ""),
        })

    total_value = sum(_num(x["valuation"]) for x in items)
    total_cost = sum(_num(x["cost"]) for x in items)
    total_pnl = total_value - total_cost if total_cost > 0 and total_value > 0 else 0
    risk_count = sum(1 for x in items if x["riskStatus"] in {"HIGH", "WATCH", "STOP_LOSS_DELAY"})
    stop_loss_delay_count = sum(1 for x in items if x["riskStatus"] == "STOP_LOSS_DELAY")
    return {
        "status": "OK",
        "market": market,
        "count": len(items[:limit]),
        "items": items[:limit],
        "summary": {
            "totalValue": total_value,
            "totalCost": total_cost,
            "totalPnl": total_pnl,
            "totalPnlPct": (total_pnl / total_cost * 100) if total_cost > 0 else 0,
            "holdingCount": len(items),
            "riskCount": risk_count,
            "stopLossDelayCount": stop_loss_delay_count,
            "totalValueText": _fmt_price(total_value, "kr") if market != "us" else _fmt_price(total_value, "us"),
            "totalPnlText": _fmt_price(total_pnl, "kr") if total_pnl != 0 else "0",
            "totalPnlPctText": f"{(total_pnl / total_cost * 100):+.2f}%" if total_cost > 0 else "-",
        },
        "updatedAt": datetime.now(KST).isoformat(),
    }

def register_mone_v77_holdings_routes(app):
    replace_paths = {"/api/holdings", "/api/holdings/summary", "/api/holdings/risk"}
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)]

    @app.get("/api/holdings")
    def holdings(market: str = Query("all"), limit: int = Query(200)):
        return holdings_payload(market=market, limit=limit)

    @app.get("/api/holdings/summary")
    def holdings_summary(market: str = Query("all")):
        payload = holdings_payload(market=market, limit=1000)
        return {"status": "OK", "market": market, **payload["summary"], "updatedAt": payload["updatedAt"]}

    @app.get("/api/holdings/risk")
    def holdings_risk(market: str = Query("all")):
        payload = holdings_payload(market=market, limit=1000)
        risky = [x for x in payload["items"] if x.get("riskStatus") in {"HIGH", "WATCH", "STOP_LOSS_DELAY"}]
        return {"status": "OK", "market": market, "count": len(risky), "items": risky, "updatedAt": payload["updatedAt"]}
