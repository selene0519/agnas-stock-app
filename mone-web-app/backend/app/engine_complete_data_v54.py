from __future__ import annotations

import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from fastapi import Query
from fastapi.routing import APIRoute


SYMBOL_FALLBACK = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "207940": "삼성바이오로직스", "006400": "삼성SDI", "005380": "현대차",
    "000270": "기아", "035420": "NAVER", "035720": "카카오", "068270": "셀트리온",
    "028260": "삼성물산", "012330": "현대모비스", "096770": "SK이노베이션",
    "051910": "LG화학", "055550": "신한지주", "105560": "KB금융",
    "032830": "삼성생명", "086790": "하나금융지주", "000810": "삼성화재",
    "033780": "KT&G", "034020": "두산에너빌리티", "042660": "한화오션",
    "010140": "삼성중공업", "009540": "HD한국조선해양", "010130": "고려아연",
    "003670": "포스코퓨처엠", "005490": "POSCO홀딩스", "066570": "LG전자",
    "058470": "리노공업", "196170": "알테오젠", "402340": "SK스퀘어",
    "375500": "DL이앤씨", "214150": "클래시스", "001440": "대한전선",
    "000720": "현대건설", "NVDA": "NVIDIA", "AAPL": "Apple", "MSFT": "Microsoft",
    "GOOGL": "Alphabet", "GOOG": "Alphabet", "AMZN": "Amazon", "TSLA": "Tesla",
    "META": "Meta", "AMD": "AMD", "AVGO": "Broadcom", "PLTR": "Palantir",
}


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "candidate_universe_kr.csv").exists() or (parent / "data").exists() and (parent / "mone-web-app").exists():
            return parent
    return here.parents[3]


def read_csv(path: Path, hard_limit: int = 2000) -> List[Dict[str, Any]]:
    if not path.exists() or not path.is_file() or path.stat().st_size == 0:
        return []
    last = None
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            rows: List[Dict[str, Any]] = []
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for idx, row in enumerate(reader):
                    rows.append(row)
                    if idx + 1 >= hard_limit:
                        break
            return rows
        except Exception as exc:
            last = exc
    print(f"[MONE v5.4] failed to read {path}: {last}")
    return []


def read_json(path: Path) -> Any:
    if not path.exists() or path.stat().st_size == 0:
        return None
    for enc in ["utf-8-sig", "utf-8", "cp949"]:
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            pass
    return None


def text(row: Dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


def to_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = str(value or "").strip().replace(",", "").replace("원", "").replace("$", "").replace("%", "")
        if raw == "" or raw.lower() in {"nan", "none", "null", "-"}:
            return default
        out = float(raw)
        return default if math.isnan(out) else out
    except Exception:
        return default


def symbol_from(row: Dict[str, Any]) -> str:
    sym = text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "Symbol", "Ticker"], "").strip().upper()
    if sym.endswith(".0"):
        sym = sym[:-2]
    sym = re.sub(r"[^0-9A-Z.\-]", "", sym)
    if sym.isdigit() and len(sym) < 6:
        sym = sym.zfill(6)
    return sym


def market_of_symbol(sym: str) -> str:
    return "kr" if re.fullmatch(r"\d{6}", sym or "") else "us"


def name_from(row: Dict[str, Any], sym: str) -> str:
    name = text(row, ["name", "stock_name", "company_name", "종목명", "Name", "Company", "corp_name"], "")
    return name if name and name != sym else SYMBOL_FALLBACK.get(sym, sym)


def price_text(value: Any, market: str) -> str:
    n = to_float(value, 0)
    if n <= 0:
        return "-"
    return f"${n:,.2f}" if market == "us" else f"{n:,.0f}원"


def pct_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith("%"):
        return raw
    n = to_float(raw, 0)
    if 0 < n <= 1:
        n *= 100
    return f"{n:.1f}%" if n > 0 else "-"


def load_price_map(market: str) -> Dict[str, Dict[str, Any]]:
    root = repo_root()
    paths = [
        root / "data" / "stockapp" / f"kis_current_price_{market}.csv",
        root / "reports" / f"kis_current_price_{market}.csv",
        root / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
        root / "reports" / f"intraday_quote_snapshot_{market}.csv",
    ]
    out: Dict[str, Dict[str, Any]] = {}
    for path in paths:
        for row in read_csv(path, hard_limit=3000):
            sym = symbol_from(row)
            if sym and sym not in out:
                out[sym] = row | {"_source_file": str(path.relative_to(root))}
    return out


def candidate_rows(market: str) -> List[Dict[str, Any]]:
    root = repo_root()
    rows = read_csv(root / f"candidate_universe_{market}.csv", hard_limit=5000)
    if not rows:
        rows = read_csv(root / "predictions.csv", hard_limit=2000)
    prices = load_price_map(market)
    watch = daily_watch_symbols(market)
    order = {s: i for i, s in enumerate(watch)}
    filtered = []
    for row in rows:
        sym = symbol_from(row)
        if not sym or market_of_symbol(sym) != market:
            continue
        if sym in prices:
            merged = row.copy()
            # price row has higher priority only for current quote fields.
            p = prices[sym]
            for k in ["currentPrice", "current_price", "last_price", "priceTime", "priceSource", "priceSourceType", "priceSourceDate"]:
                if p.get(k):
                    merged[k] = p.get(k)
            merged["priceSource"] = p.get("priceSource") or p.get("quote_source_label") or p.get("_source_file") or merged.get("priceSource", "")
            row = merged
        filtered.append(row)
    filtered.sort(key=lambda r: order.get(symbol_from(r), 999999))
    return filtered


def daily_watch_symbols(market: str) -> List[str]:
    data = read_json(repo_root() / "daily_watch_selection.json") or {}
    key = "KR" if market == "kr" else "US"
    values = data.get(key, {}).get("symbols", []) if isinstance(data, dict) else []
    return [str(v).zfill(6) if str(v).isdigit() else str(v).upper() for v in values]


def compact_candidate(row: Dict[str, Any], market: str, mode: str, horizon: str, cash: float) -> Dict[str, Any]:
    sym = symbol_from(row)
    current = to_float(text(row, ["currentPrice", "current_price", "last_price", "현재가", "실시간현재가", "quote_fallback_price", "prev_close"], "0"))
    entry = to_float(text(row, ["entry", "entry_price", "preferred_entry", "technical_entry", "support1", "current_price", "currentPrice"], "0")) or current
    stop = to_float(text(row, ["stop", "stop_loss", "stopLoss"], "0")) or (entry * 0.97 if entry else 0)
    target = to_float(text(row, ["target", "target_price", "take_profit1", "resistance1"], "0")) or (entry * 1.07 if entry else 0)
    allocation = 0.12 if mode in {"conservative", "보수"} else 0.25 if mode in {"aggressive", "공격"} else 0.18
    shares = int((cash * allocation) // entry) if cash and entry else 0
    risk_level = text(row, ["risk_level", "riskLevel"], "")
    data_status = text(row, ["price_data_status", "data_status", "dataStatus", "priceDataStatus"], "NORMAL")
    warn = ""
    if str(data_status).upper() in {"STALE", "NO_DATA", "ERROR"}:
        warn = f"데이터 상태 확인 필요: {data_status}"
    if risk_level in {"상", "높음", "위험"}:
        warn = (warn + " · " if warn else "") + "리스크 레벨 높음"
    rr = ((target - entry) / max(entry - stop, 1e-9)) if entry and stop and target and entry > stop else None
    return {
        "id": f"{market}-{sym}",
        "symbol": sym,
        "name": name_from(row, sym),
        "market": market,
        "currentPrice": current or None,
        "currentPriceText": price_text(current, market),
        "basePrice": current or None,
        "entry": entry or None,
        "entryPrice": entry or None,
        "entryText": price_text(entry, market),
        "stop": stop or None,
        "stopLoss": stop or None,
        "stopText": price_text(stop, market),
        "target": target or None,
        "targetPrice": target or None,
        "targetText": price_text(target, market),
        "rrRatio": round(rr, 2) if rr else None,
        "probabilityText": pct_text(text(row, ["probability", "win_probability", "probSwing", "prob5d"], "58")),
        "probShort": to_float(text(row, ["probShort", "prob1d"], "58")),
        "probSwing": to_float(text(row, ["probSwing", "prob5d", "probability"], "58")),
        "probMid": to_float(text(row, ["probMid", "prob20d"], "58")),
        "expectedPrice": target or current or None,
        "expectedPriceText": price_text(target or current, market),
        "mode": mode,
        "horizon": horizon,
        "period": "스윙" if horizon == "swing" else "단기" if horizon == "short" else "중기",
        "priceSession": f"{market}_after_close",
        "priceDataStatus": "NORMAL" if str(data_status).lower() in {"success", "normal", "api 현재가 수신"} else "PARTIAL",
        "dataStatus": "NORMAL" if str(data_status).lower() in {"success", "normal", "api 현재가 수신"} else "PARTIAL",
        "priceSource": text(row, ["priceSource", "price_source", "quote_source_label", "quote_source", "current_price_source"], "candidate_universe"),
        "priceSourceDate": text(row, ["priceSourceDate", "priceTime", "updated_at"], datetime.now().strftime("%Y-%m-%d")),
        "decisionBucket": "진입 가능" if entry else "대기",
        "buyTiming": "조건부 지정가",
        "warning_reason": warn,
        "warnings": [w for w in [warn] if w],
        "isBanned": bool(warn and "ERROR" in warn),
        "banReason": warn or None,
        "eventBadgesText": text(row, ["theme", "sector_proxy", "sector", "event_label"], ""),
        "sector": text(row, ["theme", "sector_proxy", "sector"], ""),
        "change": to_float(text(row, ["change", "change_pct", "등락률"], "0")),
        "volume": to_float(text(row, ["volume", "거래량"], "0")) or None,
        "recommendedShares": shares,
        "allocationWeight": allocation,
    }


def path_candidates(*parts: str) -> List[Path]:
    root = repo_root()
    return [root.joinpath(*p.split("/")) for p in parts]


def news_items(market: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in path_candidates(f"reports/v81_news_cards_{market}.csv", f"reports/news_cards_{market}.csv", f"reports/v81_news_summary_{market}.csv", f"reports/news_summary_{market}.csv"):
        rows.extend(read_csv(p, hard_limit=500))
    out = []
    for i, r in enumerate(rows[:80]):
        out.append({
            "id": f"news-{market}-{i}",
            "title": text(r, ["title", "제목", "headline"], "뉴스 제목 없음"),
            "summary": text(r, ["summary", "3줄요약", "description"], ""),
            "source": text(r, ["source", "출처"], "MONE"),
            "publishedAt": text(r, ["publishedAt", "date", "날짜"], datetime.now().isoformat()),
            "tags": [t for t in re.split(r"[,/· ]+", text(r, ["tags", "태그", "다음행동"], "")) if t][:4],
            "symbol": symbol_from(r) or None,
            "url": text(r, ["url", "link"], "#"),
            "isWarning": "주의" in text(r, ["다음행동", "tags", "title", "제목"], ""),
        })
    return out


def disclosure_items(market: str) -> List[Dict[str, Any]]:
    rows = []
    for p in path_candidates(f"data/disclosures/disclosures_{market}.csv", f"reports/disclosures_{market}.csv"):
        rows.extend(read_csv(p, hard_limit=500))
    return [{
        "id": text(r, ["rcept_no", "id"], f"disc-{market}-{i}"),
        "company": text(r, ["name", "company", "corp_name"], name_from(r, symbol_from(r))),
        "symbol": symbol_from(r),
        "market": market.upper(),
        "title": text(r, ["title", "report_nm", "form"], "공시 제목 없음"),
        "disclosedAt": text(r, ["date", "rcept_dt", "disclosedAt"], ""),
        "source": text(r, ["source"], "DART" if market == "kr" else "SEC"),
        "url": text(r, ["url"], "#"),
        "isWarning": "정정" in text(r, ["title"], "") or "소송" in text(r, ["title"], ""),
    } for i, r in enumerate(rows[:150])]


def company_items(market: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in path_candidates(f"reports/v81_company_summary_cards_{market}.csv", f"reports/v80_company_cards_{market}.csv", f"reports/v81_financial_statement_{market}.csv", f"reports/v80_financial_statement_{market}.csv"):
        rows.extend(read_csv(p, hard_limit=1000))
    out = []
    for i, r in enumerate(rows[:300]):
        sym = symbol_from(r) or text(r, ["종목코드"], "")
        if sym.isdigit():
            sym = sym.zfill(6)
        out.append({
            "id": f"fund-{market}-{sym or i}",
            "symbol": sym,
            "name": text(r, ["종목명", "name", "company_name"], SYMBOL_FALLBACK.get(sym, sym or "기업")),
            "market": market.upper(),
            "per": to_float(text(r, ["PER", "per"], "0")) or None,
            "pbr": to_float(text(r, ["PBR", "pbr"], "0")) or None,
            "roe": to_float(text(r, ["ROE", "roe"], "0")) or None,
            "eps": to_float(text(r, ["EPS", "eps"], "0")) or None,
            "revenue": to_float(text(r, ["매출", "revenue"], "0")) or None,
            "operatingProfit": to_float(text(r, ["영업이익", "operating_profit"], "0")) or None,
            "netIncome": to_float(text(r, ["순이익", "net_income"], "0")) or None,
            "debtRatio": to_float(text(r, ["부채비율", "debt_ratio"], "0")) or None,
            "growthScore": to_float(text(r, ["성장점수", "growth_score"], "0")) or None,
            "valueScore": to_float(text(r, ["가치점수", "value_score"], "0")) or None,
            "stabilityScore": to_float(text(r, ["안정성점수", "stability_score"], "0")) or None,
            "dataStatus": text(r, ["데이터상태", "data_status"], "NORMAL"),
            "source": text(r, ["데이터출처", "source"], "company_summary"),
        })
    return out


def holding_items(market: str) -> List[Dict[str, Any]]:
    rows = []
    for p in path_candidates(f"data/holdings_{market}.csv", f"holdings_{market}.csv"):
        rows.extend(read_csv(p, hard_limit=500))
    return rows


def virtual_items(market: str) -> List[Dict[str, Any]]:
    root = repo_root()
    rows = read_csv(root / "data/history/virtual_operation_evaluation.csv", hard_limit=1000)
    out = []
    for i, r in enumerate(rows):
        if text(r, ["market"], market).lower() != market:
            continue
        out.append({
            "id": f"virt-{market}-{i}",
            "date": text(r, ["created_at", "evaluated_at", "date"], ""),
            "symbol": symbol_from(r),
            "name": name_from(r, symbol_from(r)),
            "market": market.upper(),
            "entryPrice": to_float(text(r, ["entry_price"], "0")),
            "actualHigh": to_float(text(r, ["actual_high", "high"], "0")) or None,
            "actualLow": to_float(text(r, ["actual_low", "low"], "0")) or None,
            "actualClose": to_float(text(r, ["actual_close", "close"], "0")) or None,
            "entryReached": "체결" in text(r, ["execution_status"], ""),
            "virtualFilled": "체결" in text(r, ["execution_status"], ""),
            "stopLossHit": "손절" in text(r, ["outcome_result"], ""),
            "targetHit": "익절" in text(r, ["outcome_result"], ""),
            "virtualPnlPct": to_float(text(r, ["realized_return_pct"], "0")),
            "failReason": text(r, ["failure_reason", "outcome_result"], "") or None,
            "mode": text(r, ["mode_label", "mode"], "균형"),
        })
    return out[:300]


def chart_items(symbol: str, market: str) -> List[Dict[str, Any]]:
    sym = symbol.upper().zfill(6) if market == "kr" and symbol.isdigit() else symbol.upper()
    path = repo_root() / "data/market/ohlcv" / f"{market}_{sym}_daily.csv"
    rows = read_csv(path, hard_limit=400)
    out = []
    for r in rows[-240:]:
        out.append({
            "date": text(r, ["date", "Date", "날짜"], ""),
            "open": to_float(text(r, ["open", "Open", "시가"], "0")),
            "high": to_float(text(r, ["high", "High", "고가"], "0")),
            "low": to_float(text(r, ["low", "Low", "저가"], "0")),
            "close": to_float(text(r, ["close", "Close", "종가"], "0")),
            "volume": to_float(text(r, ["volume", "Volume", "거래량"], "0")),
        })
    return out


def status_counts() -> Dict[str, Any]:
    root = repo_root()
    return {
        "candidateKR": len(read_csv(root / "candidate_universe_kr.csv", hard_limit=10000)),
        "candidateUS": len(read_csv(root / "candidate_universe_us.csv", hard_limit=10000)),
        "newsKR": len(news_items("kr")),
        "newsUS": len(news_items("us")),
        "disclosuresKR": len(disclosure_items("kr")),
        "disclosuresUS": len(disclosure_items("us")),
        "companyKR": len(company_items("kr")),
        "companyUS": len(company_items("us")),
        "ohlcvFiles": len(list((root / "data/market/ohlcv").glob("*.csv"))) if (root / "data/market/ohlcv").exists() else 0,
        "virtualRows": len(read_csv(root / "data/history/virtual_operation_evaluation.csv", hard_limit=10000)),
    }


def remove_routes(app, paths: Iterable[str]) -> None:
    target = set(paths)
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in target)]


def register_complete_data_api_v54(app):
    remove_routes(app, [
        "/api/v1/candidates", "/api/final/recommendations", "/api/final/trade-validation",
        "/api/final/prediction-validation", "/api/news", "/api/disclosures", "/api/company-analysis",
        "/api/holdings", "/api/status/data-sources", "/api/status/github-actions", "/api/watchlist",
        "/api/chart/{symbol}", "/api/session", "/api/final/data-quality", "/api/backtest/summary",
    ])

    @app.get("/api/session")
    def session(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        return {"market": mk, "priceSession": f"{mk}_after_close", "sessionDescription": "장마감 후 · 로컬 데이터 복기 모드", "isOpen": False, "isHoliday": True, "reviewMode": True, "kstNow": datetime.now().strftime("%Y-%m-%d %H:%M:%S KST")}

    @app.get("/api/v1/candidates")
    def candidates(market: str = Query("kr"), strategy: str = Query("balanced"), term: str = Query("swing"), mode: Optional[str] = Query(None), horizon: Optional[str] = Query(None), cash: float = Query(0), limit: int = Query(30)):
        mk = "us" if str(market).lower() == "us" else "kr"
        md = (mode or strategy or "balanced").lower()
        hz = (horizon or term or "swing").lower()
        mode_kr = "보수" if md == "conservative" else "공격" if md == "aggressive" else "균형"
        safe = max(1, min(int(limit or 30), 80))
        rows = candidate_rows(mk)
        items = [compact_candidate(r, mk, mode_kr, hz, cash) for r in rows[:safe]]
        return {"status": "OK", "market": mk, "mode": md, "horizon": hz, "strategy": md, "term": hz, "count": len(items), "hiddenCount": 0, "items": items, "hidden": [], "dataQuality": {"status": "NORMAL" if items else "NO_DATA", "market": mk, "killSwitch": False, "reviewMode": True, "priceSession": f"{mk}_closed", "counts": status_counts()}, "rule": "v5.4 merged complete data API"}

    @app.get("/api/final/recommendations")
    def recommendations(market: str = Query("kr"), mode: str = Query("balanced"), horizon: str = Query("swing"), limit: int = Query(30)):
        return candidates(market=market, strategy=mode, term=horizon, mode=mode, horizon=horizon, cash=0, limit=limit)

    @app.get("/api/news")
    def news(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = news_items(mk)
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/disclosures")
    def disclosures(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = disclosure_items(mk)
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/company-analysis")
    def company(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = company_items(mk)
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/holdings")
    def holdings(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = holding_items(mk)
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/final/trade-validation")
    def trade_validation(market: str = Query("kr"), mode: str = Query("balanced"), horizon: str = Query("swing")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = virtual_items(mk)
        return {"status": "OK", "market": mk, "mode": mode, "horizon": horizon, "count": len(rows), "items": rows, "trades": rows}

    @app.get("/api/final/prediction-validation")
    def prediction_validation(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = virtual_items(mk)
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/chart/{symbol}")
    def chart(symbol: str, market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = chart_items(symbol, mk)
        return {"status": "OK" if rows else "NO_DATA", "market": mk, "symbol": symbol, "count": len(rows), "items": rows}

    @app.get("/api/status/data-sources")
    def sources():
        counts = status_counts()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        items = [{"name": k, "type": "local csv/json", "status": "NORMAL" if v else "NO_DATA", "latestUpdatedAt": now, "rows": v, "message": "merged v5.4"} for k, v in counts.items()]
        return {"status": "OK", "items": items, "counts": counts}

    @app.get("/api/status/github-actions")
    def github_actions():
        root = repo_root()
        workflows = list((root / ".github/workflows").glob("*.yml")) if (root / ".github/workflows").exists() else []
        return {"status": "NORMAL" if workflows else "PARTIAL", "workflowCount": len(workflows), "updatedAt": datetime.now().isoformat()}

    @app.get("/api/watchlist")
    def watchlist(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = [compact_candidate(r, mk, "균형", "swing", 0) for r in candidate_rows(mk)[:30]]
        return {"status": "OK", "market": mk, "count": len(rows), "items": rows}

    @app.get("/api/final/data-quality")
    def data_quality(market: str = Query("kr")):
        mk = "us" if str(market).lower() == "us" else "kr"
        counts = status_counts()
        return {"status": "NORMAL", "market": mk, "killSwitch": False, "reviewMode": True, "priceSession": f"{mk}_closed", "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "counts": counts}

    @app.get("/api/backtest/summary")
    def backtest_summary(market: str = Query("kr"), mode: str = Query("balanced"), horizon: str = Query("swing")):
        mk = "us" if str(market).lower() == "us" else "kr"
        rows = virtual_items(mk)
        filled = [r for r in rows if r.get("virtualFilled")]
        wins = [r for r in filled if (r.get("virtualPnlPct") or 0) > 0]
        return {"status": "OK", "market": mk, "mode": mode, "horizon": horizon, "totalRecommendations": len(rows), "executedTrades": len(filled), "executionRate": round(len(filled) / len(rows) * 100, 2) if rows else 0, "winRate": round(len(wins) / len(filled) * 100, 2) if filled else 0, "averagePnlPct": round(sum((r.get("virtualPnlPct") or 0) for r in filled) / len(filled), 2) if filled else 0, "failureTop3": []}
