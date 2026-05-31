
from __future__ import annotations

import csv, math, re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Query
from fastapi.routing import APIRoute

SYMBOL_FALLBACK = {
    "005930":"삼성전자","000660":"SK하이닉스","373220":"LG에너지솔루션","207940":"삼성바이오로직스",
    "006400":"삼성SDI","005380":"현대차","000270":"기아","035420":"NAVER","035720":"카카오",
    "068270":"셀트리온","028260":"삼성물산","012330":"현대모비스","096770":"SK이노베이션",
    "051910":"LG화학","055550":"신한지주","105560":"KB금융","032830":"삼성생명",
    "086790":"하나금융지주","000810":"삼성화재","033780":"KT&G","034020":"두산에너빌리티",
    "042660":"한화오션","010140":"삼성중공업","009540":"HD한국조선해양","010130":"고려아연",
    "003670":"포스코퓨처엠","005490":"POSCO홀딩스","066570":"LG전자","058470":"리노공업",
    "196170":"알테오젠","402340":"SK스퀘어","375500":"DL이앤씨","214150":"클래시스",
    "001440":"대한전선","000720":"현대건설","NVDA":"NVIDIA","AAPL":"Apple","MSFT":"Microsoft",
    "GOOGL":"Alphabet","GOOG":"Alphabet","AMZN":"Amazon","TSLA":"Tesla","META":"Meta",
    "AMD":"AMD","AVGO":"Broadcom","PLTR":"Palantir"
}

def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if (parent / "reports").exists() or (parent / "predictions.csv").exists():
            return parent
    return here.parents[3]

def text(row: Dict[str, Any], keys: List[str], default: str = "") -> str:
    for key in keys:
        val = row.get(key)
        if val is not None and str(val).strip() != "":
            return str(val).strip()
    return default

def to_float(value: Any, default: float = 0.0) -> float:
    try:
        raw = str(value or "").strip().replace(",", "")
        if raw == "" or raw.lower() in {"nan","none","null"}:
            return default
        n = float(raw)
        return default if math.isnan(n) else n
    except Exception:
        return default

def symbol_from(row: Dict[str, Any]) -> str:
    symbol = text(row, ["symbol","ticker","code","stock_code","종목코드","Symbol","Ticker"])
    if symbol.endswith(".0"):
        symbol = symbol[:-2]
    symbol = re.sub(r"[^0-9A-Za-z.\-]", "", symbol)
    if symbol.isdigit() and len(symbol) < 6:
        symbol = symbol.zfill(6)
    return symbol

def name_from(row: Dict[str, Any], symbol: str) -> str:
    name = text(row, ["name","stock_name","company_name","종목명","Name","Company"])
    return name if name and name != symbol else SYMBOL_FALLBACK.get(symbol, symbol)

def market_match(symbol: str, market: str) -> bool:
    if market == "kr":
        return bool(re.fullmatch(r"\d{6}", symbol))
    if market == "us":
        return bool(re.fullmatch(r"[A-Za-z.\-]{1,8}", symbol))
    return True

def price_text(value: Any, market: str) -> str:
    n = to_float(value)
    if n <= 0:
        return "-"
    return f"${n:,.2f}" if market == "us" else f"{n:,.0f}원"

def percent_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith("%"):
        return raw
    n = to_float(raw)
    if 0 < n <= 1:
        n *= 100
    return f"{n:.1f}%" if n > 0 else "-"

def find_source_file(market: str, mode: str, horizon: str) -> Optional[Path]:
    root = repo_root()
    preferred = [
        root / "reports" / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        root / "reports" / f"mone_v36_final_recommendations_{market}_balanced_swing.csv",
        root / "reports" / f"mone_v36_final_recommendations_{market}.csv",
        root / "predictions.csv",
        root / "reports" / "predictions.csv",
    ]
    for p in preferred:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p
    report_dir = root / "reports"
    if report_dir.exists():
        for pattern in [f"*recommendations*{market}*{mode}*{horizon}*.csv", f"*recommendations*{market}*.csv", f"*prediction*{market}*.csv"]:
            matches = sorted(report_dir.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True)
            if matches:
                return matches[0]
    return None

def read_rows(path: Path, hard_limit: int = 500) -> List[Dict[str, Any]]:
    last = None
    for enc in ["utf-8-sig","utf-8","cp949"]:
        try:
            rows = []
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                for i, row in enumerate(reader):
                    rows.append(row)
                    if i + 1 >= hard_limit:
                        break
            return rows
        except Exception as exc:
            last = exc
    raise RuntimeError(f"failed to read csv {path}: {last}")

def compact_candidate(row: Dict[str, Any], market: str, mode: str, horizon: str, cash: float) -> Dict[str, Any]:
    symbol = symbol_from(row)
    current = to_float(text(row, ["currentPrice","current_price","last_price","current_price_at_prediction","basis_close","actual_close","prev_close"]))
    entry = to_float(text(row, ["entry","entry_price","preferred_entry","technical_entry","conservative_entry","pullback_buy"]))
    stop = to_float(text(row, ["stop","stop_loss","stopLoss"]))
    target = to_float(text(row, ["target","target_price","take_profit1","targetPrice"]))
    allocation = 0.12 if mode in {"conservative","보수"} else 0.25 if mode in {"aggressive","공격"} else 0.18
    shares = int((cash * allocation) // entry) if cash > 0 and entry > 0 else 0
    probability = text(row, ["probabilityText","probSwing","prob5d","win_probability","probability"])
    return {
        "symbol": symbol,
        "name": name_from(row, symbol),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "currentPrice": current,
        "currentPriceText": price_text(current, market),
        "entry": entry,
        "entryText": price_text(entry, market),
        "stop": stop,
        "stopText": price_text(stop, market),
        "target": target,
        "targetText": price_text(target, market),
        "expectedPriceText": text(row, ["expectedPriceText","expectedPriceSwingText","expectedPrice5dText","expected_price","expectedPrice"], "-"),
        "probabilityText": percent_text(probability),
        "priceSession": text(row, ["priceSession","price_session"], ""),
        "priceDataStatus": text(row, ["priceDataStatus","dataStatus","data_status"], "NORMAL"),
        "priceSource": text(row, ["priceSource","price_source","current_price_source","priceSourceFile"], ""),
        "decisionBucket": text(row, ["decisionBucket","newEntryDecision","final_decision_after_no_buy_filter","risk_final_decision"], ""),
        "buyTiming": text(row, ["buyTiming","primary_action","suggested_action"], ""),
        "warning_reason": text(row, ["warning_reason","risk_reason","no_buy_flags","risk_warning_flags"], ""),
        "eventBadgesText": text(row, ["eventBadgesText","event_label","eventContext","sec_risk_keywords","dart_risk_keywords"], ""),
        "recommendedShares": shares,
        "allocationWeight": allocation,
    }

def register_light_candidates_api(app):
    app.router.routes = [
        route for route in app.router.routes
        if not (isinstance(route, APIRoute) and getattr(route, "path", "") == "/api/v1/candidates")
    ]

    @app.get("/api/v1/candidates")
    def light_candidates(
        market: str = Query("kr"),
        strategy: str = Query("balanced"),
        term: str = Query("swing"),
        mode: Optional[str] = Query(None),
        horizon: Optional[str] = Query(None),
        cash: float = Query(0),
        limit: int = Query(20),
    ):
        market_norm = (market or "kr").lower()
        mode_norm = (mode or strategy or "balanced").lower()
        horizon_norm = (horizon or term or "swing").lower()
        safe_limit = max(1, min(int(limit or 20), 50))
        source = find_source_file(market_norm, mode_norm, horizon_norm)
        if source is None:
            return {"status":"NO_DATA","market":market_norm,"mode":mode_norm,"horizon":horizon_norm,"strategy":mode_norm,"term":horizon_norm,"count":0,"hiddenCount":0,"items":[],"hidden":[],"dataQuality":{"status":"NO_DATA","market":market_norm,"killSwitch":True,"reviewMode":False,"priceSession":"","counts":{"recommendations":0,"returned":0}}}
        rows = read_rows(source, hard_limit=500)
        items, hidden = [], []
        for row in rows:
            sym = symbol_from(row)
            if not sym or not market_match(sym, market_norm):
                continue
            fundamental_missing = text(row, ["fundamentalMissing","fundamental_missing"], "False").lower() in {"true","1","yes","y"}
            if fundamental_missing and mode_norm in {"conservative","balanced","보수","균형"}:
                hidden.append({"symbol": sym, "name": name_from(row, sym), "reason": "기업분석 데이터 결손으로 보수/균형 모드 제외"})
                continue
            compact = compact_candidate(row, market_norm, mode_norm, horizon_norm, cash)
            if fundamental_missing and mode_norm in {"aggressive","공격"} and not compact["warning_reason"]:
                compact["warning_reason"] = "데이터 결손 리스크 보유"
            items.append(compact)
            if len(items) >= safe_limit:
                break
        return {
            "status": "OK",
            "market": market_norm,
            "mode": mode_norm,
            "horizon": horizon_norm,
            "strategy": mode_norm,
            "term": horizon_norm,
            "count": len(items),
            "hiddenCount": len(hidden),
            "items": items,
            "hidden": hidden[:20],
            "dataQuality": {
                "status": "PARTIAL" if rows else "NO_DATA",
                "market": market_norm,
                "killSwitch": False,
                "reviewMode": True,
                "priceSession": "kr_closed" if market_norm == "kr" else "us_closed",
                "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "counts": {"recommendations": len(rows), "returned": len(items), "hidden": len(hidden)},
                "sourceFile": source.name,
            },
            "rule": "MONE v5.1 lightweight candidates response. Raw prediction rows are omitted.",
        }
