
from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Query
from fastapi.routing import APIRoute


def _root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "candidate_universe_kr.csv").exists() or (parent / "reports").exists() or (parent / "data").exists():
            return parent
    return here.parents[4]


def _read_csv(path: Path, limit: int = 1000) -> List[Dict[str, Any]]:
    if not path.exists() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            rows: List[Dict[str, Any]] = []
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i + 1 >= limit:
                        break
            return rows
        except Exception:
            continue
    return []


def _text(row: Dict[str, Any], keys: List[str], default: str = "") -> str:
    for k in keys:
        v = row.get(k)
        if v is not None and str(v).strip() != "":
            return str(v).strip()
    return default


def _num(v: Any, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        s = str(v).replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        if s == "" or s.lower() in {"nan", "none", "null", "-"}:
            return default
        n = float(s)
        return default if math.isnan(n) else n
    except Exception:
        return default


def _symbol(row: Dict[str, Any]) -> str:
    s = _text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "Symbol", "Ticker"], "")
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"[^0-9A-Za-z.\-]", "", s)
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스",
    "006400": "삼성SDI",
    "005380": "현대차",
    "000270": "기아",
    "035420": "NAVER",
    "035720": "카카오",
    "068270": "셀트리온",
    "NVDA": "NVIDIA",
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "GOOGL": "Alphabet",
    "AMZN": "Amazon",
    "TSLA": "Tesla",
    "META": "Meta",
    "AMD": "AMD",
}


def _name(row: Dict[str, Any], symbol: str) -> str:
    v = _text(row, ["name", "stock_name", "company_name", "종목명", "Name", "Company"], "")
    return v if v else _NAMES.get(symbol, symbol)


def _price_text(v: Any, market: str) -> str:
    n = _num(v)
    if n <= 0:
        return "-"
    return f"${n:,.2f}" if market == "us" else f"{n:,.0f}원"


def _percent_text(v: Any) -> str:
    s = str(v or "").strip()
    if s.endswith("%"):
        return s
    n = _num(s)
    if 0 < n <= 1:
        n *= 100
    return f"{n:.1f}%" if n > 0 else "-"


def _candidate_file(market: str) -> Optional[Path]:
    root = _root()
    candidates = [
        root / f"candidate_universe_{market}.csv",
        root / "reports" / f"mone_v36_final_recommendations_{market}_balanced_swing.csv",
        root / "reports" / f"mone_v36_action_cards_{market}.csv",
        root / "predictions.csv",
    ]
    for p in candidates:
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _load_candidates(market: str, mode: str, horizon: str, cash: float, limit: int) -> Dict[str, Any]:
    market = "us" if str(market).lower() == "us" else "kr"
    mode = (mode or "balanced").lower()
    horizon = (horizon or "swing").lower()
    safe_limit = max(1, min(int(limit or 20), 100))
    path = _candidate_file(market)

    if path is None:
        return {
            "status": "NO_DATA",
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "strategy": mode,
            "term": horizon,
            "count": 0,
            "hiddenCount": 0,
            "items": [],
            "hidden": [],
            "dataQuality": {"status": "NO_DATA", "market": market, "killSwitch": True, "reviewMode": False},
        }

    rows = _read_csv(path, limit=1000)
    items: List[Dict[str, Any]] = []

    for row in rows:
        sym = _symbol(row)
        if not sym:
            continue
        if market == "kr" and not re.fullmatch(r"\d{6}", sym):
            continue
        if market == "us" and not re.fullmatch(r"[A-Za-z.\-]{1,8}", sym):
            continue

        current = _num(_text(row, ["current_price", "currentPrice", "last_price", "현재가", "실시간현재가", "quote_fallback_price", "prev_close"], "0"))
        entry = _num(_text(row, ["entry", "entry_price", "preferred_entry", "technical_entry", "support1", "current_price"], "0"))
        if entry <= 0:
            entry = current
        stop = _num(_text(row, ["stop", "stop_loss", "stopLoss"], "0"))
        if stop <= 0 and entry > 0:
            stop = entry * 0.97
        target = _num(_text(row, ["target", "target_price", "take_profit1", "resistance1"], "0"))
        if target <= 0 and entry > 0:
            target = entry * 1.07

        allocation = 0.18
        if mode in {"conservative", "보수"}:
            allocation = 0.12
        elif mode in {"aggressive", "공격"}:
            allocation = 0.25

        risk = _text(row, ["risk_level", "riskLevel"], "")
        data_status = _text(row, ["price_data_status", "data_status", "dataStatus", "priceDataStatus"], "NORMAL")
        warning = ""
        if str(data_status).lower() not in {"success", "api 현재가 수신", "normal", "정상"}:
            warning = f"데이터 상태 확인 필요: {data_status}"
        if risk in {"상", "높음", "위험"}:
            warning = (warning + " · " if warning else "") + "리스크 레벨 높음"

        items.append({
            "symbol": sym,
            "name": _name(row, sym),
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "currentPrice": current,
            "currentPriceText": _price_text(current, market),
            "entry": entry,
            "entryText": _price_text(entry, market),
            "stop": stop,
            "stopText": _price_text(stop, market),
            "target": target,
            "targetText": _price_text(target, market),
            "expectedPriceText": _price_text(target, market),
            "probabilityText": _percent_text(_text(row, ["probability", "win_probability", "probSwing"], "58")),
            "priceSession": "kr_after_close" if market == "kr" else "us_after_close",
            "priceDataStatus": "NORMAL" if not warning else "PARTIAL",
            "priceSource": _text(row, ["quote_source_label", "quote_source", "current_price_source", "priceSource"], "candidate_universe"),
            "decisionBucket": "진입 가능" if entry > 0 else "대기",
            "buyTiming": "조건부 지정가",
            "warning_reason": warning,
            "eventBadgesText": _text(row, ["theme", "sector_proxy", "sector"], ""),
            "recommendedShares": int((cash * allocation) // entry) if cash > 0 and entry > 0 else 0,
            "allocationWeight": allocation,
        })
        if len(items) >= safe_limit:
            break

    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "strategy": mode,
        "term": horizon,
        "count": len(items),
        "hiddenCount": 0,
        "items": items,
        "hidden": [],
        "dataQuality": {
            "status": "NORMAL" if items else "NO_DATA",
            "market": market,
            "killSwitch": False,
            "reviewMode": True,
            "priceSession": "kr_closed" if market == "kr" else "us_closed",
            "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "counts": {"recommendations": len(rows), "returned": len(items)},
            "sourceFile": path.name,
        },
    }


def _market_file(market: str, candidates: List[str]) -> Optional[Path]:
    root = _root()
    market = "us" if str(market).lower() == "us" else "kr"
    for pattern in candidates:
        p = root / pattern.format(market=market)
        if p.exists() and p.stat().st_size > 0:
            return p
    return None


def _news(market: str, limit: int) -> Dict[str, Any]:
    p = _market_file(market, [
        "reports/v81_news_cards_{market}.csv",
        "reports/news_cards_{market}.csv",
        "reports/v81_news_summary_{market}.csv",
        "reports/news_summary_{market}.csv",
    ])
    rows = _read_csv(p, limit=limit) if p else []
    items = []
    for i, r in enumerate(rows):
        items.append({
            "id": _text(r, ["id"], f"news-{i}"),
            "title": _text(r, ["제목", "title", "headline"], "뉴스 제목 없음"),
            "summary": _text(r, ["3줄요약", "summary", "description"], ""),
            "source": _text(r, ["출처", "source"], "MONE"),
            "publishedAt": _text(r, ["publishedAt", "date", "날짜"], datetime.now().isoformat()),
            "tags": [x for x in _text(r, ["tags", "태그", "다음행동"], "").split(",") if x],
            "symbol": _text(r, ["symbol", "종목코드", "ticker"], None),
            "url": _text(r, ["url", "URL"], "#"),
            "isWarning": False,
        })
    return {"status": "OK" if rows else "NO_DATA", "market": market, "count": len(items), "items": items}


def _disclosures(market: str, limit: int) -> Dict[str, Any]:
    p = _market_file(market, ["data/disclosures/disclosures_{market}.csv"])
    rows = _read_csv(p, limit=limit) if p else []
    items = []
    for i, r in enumerate(rows):
        items.append({
            "id": _text(r, ["rcept_no", "id"], f"disc-{i}"),
            "company": _text(r, ["name", "company", "corp_name"], "-"),
            "symbol": _text(r, ["symbol", "stock_code", "종목코드"], ""),
            "market": "US" if str(market).lower() == "us" else "KR",
            "title": _text(r, ["title", "report_nm", "공시제목"], "공시 제목 없음"),
            "disclosedAt": _text(r, ["date", "disclosedAt", "rcept_dt"], datetime.now().isoformat()),
            "source": _text(r, ["source"], "DART/SEC"),
            "url": _text(r, ["url"], "#"),
            "isWarning": False,
        })
    return {"status": "OK" if rows else "NO_DATA", "market": market, "count": len(items), "items": items}


def _company(market: str, limit: int) -> Dict[str, Any]:
    p = _market_file(market, [
        "reports/v81_company_summary_cards_{market}.csv",
        "reports/v80_company_cards_{market}.csv",
        "reports/v81_financial_statement_{market}.csv",
        "reports/v80_financial_statement_{market}.csv",
    ])
    rows = _read_csv(p, limit=limit) if p else []
    items = []
    for i, r in enumerate(rows):
        sym = _text(r, ["종목코드", "symbol", "ticker"], "")
        items.append({
            "id": sym or f"company-{i}",
            "symbol": sym,
            "name": _text(r, ["종목명", "name", "company"], sym),
            "market": "US" if str(market).lower() == "us" else "KR",
            "per": _num(_text(r, ["PER", "per"], "")),
            "pbr": _num(_text(r, ["PBR", "pbr"], "")),
            "roe": _num(_text(r, ["ROE", "roe"], "")),
            "revenue": _num(_text(r, ["매출", "revenue"], "")),
            "operatingProfit": _num(_text(r, ["영업이익", "operating_profit"], "")),
            "netIncome": _num(_text(r, ["순이익", "net_income"], "")),
            "debtRatio": _num(_text(r, ["부채비율", "debt_ratio"], "")),
            "valueScore": _num(_text(r, ["가치점수", "value_score"], "")),
            "growthScore": _num(_text(r, ["성장점수", "growth_score"], "")),
            "stabilityScore": _num(_text(r, ["안정성점수", "stability_score"], "")),
            "dataStatus": _text(r, ["데이터상태", "data_status"], "PARTIAL"),
            "source": _text(r, ["데이터출처", "source"], p.name if p else ""),
        })
    return {"status": "OK" if rows else "NO_DATA", "market": market, "count": len(items), "items": items}


def _holdings(market: str, limit: int) -> Dict[str, Any]:
    paths = [
        _root() / "data/history/virtual_operation_history.csv",
        _root() / "data/history/virtual_operation_evaluation.csv",
        _root() / "paper_trading_log.csv",
    ]
    p = next((x for x in paths if x.exists() and x.stat().st_size > 0), None)
    rows = _read_csv(p, limit=limit) if p else []
    return {"status": "OK" if rows else "NO_DATA", "market": market, "count": len(rows), "items": rows[:limit]}


def _validation(market: str, mode: str, horizon: str) -> Dict[str, Any]:
    p = _root() / "data/history/virtual_operation_evaluation.csv"
    rows = _read_csv(p, limit=2000) if p.exists() else []
    m = "us" if str(market).lower() == "us" else "kr"
    filtered = [r for r in rows if str(_text(r, ["market"], "")).lower() in {m, m.upper()}]
    total = len(filtered)
    executed = [r for r in filtered if _text(r, ["execution_status"], "").lower() in {"executed", "filled", "체결"}]
    wins = [r for r in executed if "익절" in _text(r, ["outcome_result"], "") or _num(_text(r, ["realized_return_pct"], "0")) > 0]
    win_rate = round((len(wins) / len(executed) * 100), 2) if executed else 0
    return {
        "status": "OK" if rows else "NO_DATA",
        "market": m,
        "mode": mode,
        "horizon": horizon,
        "totalRecommendations": total,
        "executedTrades": len(executed),
        "executionRate": round((len(executed) / total * 100), 2) if total else 0,
        "winRate": win_rate,
        "items": filtered[:50],
    }


def register_mone_v55_backend_aliases(app):
    existing = {getattr(r, "path", "") for r in app.router.routes if isinstance(r, APIRoute)}

    def add(path: str):
        def decorator(fn):
            if path not in existing:
                app.get(path)(fn)
            return fn
        return decorator

    @add("/api/final/recommendations")
    def final_recommendations(
        market: str = Query("kr"),
        mode: str = Query("balanced"),
        horizon: str = Query("swing"),
        strategy: Optional[str] = Query(None),
        term: Optional[str] = Query(None),
        cash: float = Query(0),
        limit: int = Query(20),
    ):
        return _load_candidates(market, strategy or mode, term or horizon, cash, limit)

    @add("/api/v1/candidates")
    def candidates(
        market: str = Query("kr"),
        strategy: str = Query("balanced"),
        term: str = Query("swing"),
        cash: float = Query(0),
        limit: int = Query(20),
    ):
        return _load_candidates(market, strategy, term, cash, limit)

    @add("/api/news")
    def news(market: str = Query("kr"), limit: int = Query(50)):
        return _news(market, limit)

    @add("/api/disclosures")
    def disclosures(market: str = Query("kr"), limit: int = Query(50)):
        return _disclosures(market, limit)

    @add("/api/company-analysis")
    def company_analysis(market: str = Query("kr"), limit: int = Query(200)):
        return _company(market, limit)

    @add("/api/holdings")
    def holdings(market: str = Query("kr"), limit: int = Query(100)):
        return _holdings(market, limit)

    @add("/api/final/trade-validation")
    def trade_validation(
        market: str = Query("kr"),
        mode: str = Query("balanced"),
        horizon: str = Query("swing"),
    ):
        return _validation(market, mode, horizon)
