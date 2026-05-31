
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
        if (parent / "data").exists() or (parent / "reports").exists() or (parent / "candidate_universe_kr.csv").exists():
            return parent
    return here.parents[4]


def _read_csv(path: Optional[Path], limit: int = 50000) -> List[Dict[str, Any]]:
    if path is None or not path.exists() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            rows = []
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


def _read_json(path: Optional[Path]) -> Any:
    if path is None or not path.exists() or path.stat().st_size <= 0:
        return None
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def _glob_existing(patterns: List[str]) -> List[Path]:
    root = _root()
    found: List[Path] = []
    for pattern in patterns:
        for p in root.glob(pattern):
            if p.exists() and p.is_file() and p.stat().st_size > 0 and p not in found:
                found.append(p)
    return found


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


def _symbol_value(v: Any) -> str:
    s = str(v or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = re.sub(r"[^0-9A-Za-z.\-]", "", s)
    if s.isdigit() and len(s) < 6:
        s = s.zfill(6)
    return s


def _symbol(row: Dict[str, Any]) -> str:
    return _symbol_value(_text(row, ["symbol", "ticker", "code", "stock_code", "종목코드", "Symbol", "Ticker"], ""))


def _market_norm(market: str) -> str:
    raw = str(market or "").lower()
    if raw in {"us", "usa", "미장"}:
        return "us"
    if raw in {"all", "전체"}:
        return "all"
    return "kr"


def _infer_market(sym: str, explicit: str = "") -> str:
    e = str(explicit or "").lower()
    if e in {"kr", "kospi", "kosdaq", "국장", "korea"}:
        return "kr"
    if e in {"us", "usa", "nasdaq", "nyse", "amex", "미장"}:
        return "us"
    return "kr" if re.fullmatch(r"\d{6}", sym or "") else "us"


_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "373220": "LG에너지솔루션",
    "003490": "대한항공", "047810": "한국항공우주", "015760": "한국전력",
    "005380": "현대차", "009540": "HD한국조선해양", "035420": "NAVER",
    "035720": "카카오", "058470": "리노공업", "001440": "대한전선",
    "NVDA": "NVIDIA", "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet",
    "GOOG": "Alphabet", "TSLA": "Tesla", "PLTR": "Palantir", "INTC": "Intel",
    "AMD": "AMD", "AVGO": "Broadcom", "MU": "Micron",
}


def _name(row: Dict[str, Any], sym: str) -> str:
    return _text(row, ["name", "stock_name", "company_name", "종목명", "Name", "Company"], "") or _NAMES.get(sym, sym)


def _virtual_paths() -> List[Path]:
    return _glob_existing([
        "data/history/virtual_operation_evaluation.csv",
        "data/history/virtual_operation_history.csv",
        "data/history/outcome_history.csv",
        "data/history/prediction_history.csv",
        "data/history/prediction_snapshot_history.csv",
        "data/history/auto_correction_summary.csv",
        "reports/*virtual*.csv",
        "reports/*backtest*.csv",
        "reports/*trade*.csv",
        "paper_trading_log.csv",
        "paper_trading_summary.csv",
        "paper_trading*.csv",
        "*virtual*.csv",
        "*backtest*.csv",
        "*trading*.csv",
    ])


def _summary_json_paths() -> List[Path]:
    return _glob_existing([
        "paper_trading_summary.json",
        "data/history/*summary*.json",
        "reports/*summary*.json",
        "runner_status_kr.json",
        "runner_status_us.json",
    ])


def _load_virtual_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for path in _virtual_paths():
        for r in _read_csv(path, limit=50000):
            row = dict(r)
            row["_source_file"] = path.name
            rows.append(row)
    return rows


def _row_market(row: Dict[str, Any]) -> str:
    sym = _symbol(row)
    explicit = _text(row, ["market", "시장", "Market"], "")
    return _infer_market(sym, explicit)


def _is_executed(row: Dict[str, Any]) -> bool:
    raw = " ".join([
        _text(row, ["execution_status", "virtual_status", "is_executed", "executed", "체결여부", "가상체결"], ""),
        _text(row, ["outcome_result", "actual_result", "result", "결과"], ""),
        _text(row, ["status", "상태"], ""),
    ]).lower()
    if any(x in raw for x in ["not_executed", "미체결", "no_touch", "not touched"]):
        return False
    if any(x in raw for x in ["executed", "filled", "true", "1", "체결", "도달"]):
        return True
    ret = _num(_text(row, ["realized_return_pct", "return_pct", "pnl_pct", "profit_pct", "수익률"], "0"))
    return ret != 0


def _is_win(row: Dict[str, Any]) -> bool:
    raw = " ".join([
        _text(row, ["outcome_result", "actual_result", "result", "결과"], ""),
        _text(row, ["status", "상태"], ""),
    ]).lower()
    ret = _num(_text(row, ["realized_return_pct", "return_pct", "pnl_pct", "profit_pct", "수익률"], "0"))
    return any(x in raw for x in ["take_profit", "target", "익절", "성공", "win"]) or ret > 0


def _is_loss(row: Dict[str, Any]) -> bool:
    raw = " ".join([
        _text(row, ["outcome_result", "actual_result", "result", "결과"], ""),
        _text(row, ["status", "상태"], ""),
    ]).lower()
    ret = _num(_text(row, ["realized_return_pct", "return_pct", "pnl_pct", "profit_pct", "수익률"], "0"))
    return any(x in raw for x in ["stop", "loss", "손절", "실패", "fail"]) or ret < 0


def _return_pct(row: Dict[str, Any]) -> float:
    direct = _num(_text(row, ["realized_return_pct", "return_pct", "pnl_pct", "profit_pct", "수익률"], "0"))
    if direct != 0:
        return direct
    entry = _num(_text(row, ["entry_price", "entry", "진입가"], "0"))
    exit_price = _num(_text(row, ["exit_price", "close_price", "target_price", "target", "청산가", "종가"], "0"))
    if entry > 0 and exit_price > 0:
        return round((exit_price - entry) / entry * 100, 4)
    return 0.0


def _dedupe(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for i, r in enumerate(rows):
        sym = _symbol(r)
        key = (
            _text(r, ["evaluated_at", "created_at", "date", "날짜", "timestamp"], ""),
            sym,
            _text(r, ["mode", "mode_label", "strategy"], ""),
            _text(r, ["horizon", "term", "period"], ""),
            _text(r, ["entry_price", "entry", "진입가"], ""),
            _text(r, ["_source_file"], ""),
            i if not sym else "",
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _virtual_summary(market: str = "all", mode: str = "all", horizon: str = "all", limit: int = 300) -> Dict[str, Any]:
    market = _market_norm(market)
    rows = _dedupe(_load_virtual_rows())

    filtered: List[Dict[str, Any]] = []
    for r in rows:
        m = _row_market(r)
        if market != "all" and m != market:
            continue
        row_mode = _text(r, ["mode", "mode_label", "strategy"], "").lower()
        row_horizon = _text(r, ["horizon", "term", "period"], "").lower()
        if mode not in {"", "all"} and row_mode and mode.lower() not in row_mode:
            continue
        if horizon not in {"", "all"} and row_horizon and horizon.lower() not in row_horizon:
            continue
        filtered.append(r)

    executed = [r for r in filtered if _is_executed(r)]
    wins = [r for r in executed if _is_win(r)]
    losses = [r for r in executed if _is_loss(r)]
    returns = [_return_pct(r) for r in executed]
    total = len(filtered)

    # Read any summary files as supplementary context, but computed CSV rows are primary.
    summary_sources = [p.name for p in _summary_json_paths()] + [p.name for p in _virtual_paths()]

    items = []
    for i, r in enumerate(filtered[: max(1, min(limit, 1000))]):
        sym = _symbol(r)
        items.append({
            "id": f"{_row_market(r)}-{sym or i}-{i}",
            "date": _text(r, ["evaluated_at", "created_at", "date", "날짜", "timestamp"], ""),
            "symbol": sym,
            "name": _name(r, sym),
            "market": _row_market(r),
            "mode": _text(r, ["mode", "mode_label", "strategy"], ""),
            "horizon": _text(r, ["horizon", "term", "period"], ""),
            "entryPrice": _num(_text(r, ["entry_price", "entry", "진입가"], "0")),
            "stopLoss": _num(_text(r, ["stop_loss", "stop", "손절가"], "0")),
            "targetPrice": _num(_text(r, ["target_price", "target", "목표가"], "0")),
            "executionStatus": _text(r, ["execution_status", "virtual_status", "is_executed", "가상체결"], ""),
            "outcomeResult": _text(r, ["outcome_result", "actual_result", "result", "결과"], ""),
            "realizedReturnPct": _return_pct(r),
            "sourceFile": _text(r, ["_source_file"], ""),
        })

    win_rate = round(len(wins) / len(executed) * 100, 2) if executed else 0
    avg_return = round(sum(returns) / len(returns), 2) if returns else 0
    cumulative = round(sum(returns), 2) if returns else 0

    return {
        "status": "OK" if filtered else "NO_DATA",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "totalRecommendations": total,
        "totalTrades": total,
        "executedTrades": len(executed),
        "executedCount": len(executed),
        "executionRate": round(len(executed) / total * 100, 2) if total else 0,
        "winRate": win_rate,
        "successRate": win_rate,
        "avgReturnPct": avg_return,
        "averageReturnPct": avg_return,
        "cumulativeReturnPct": cumulative,
        "profitLossRatio": cumulative,
        "lossCount": len(losses),
        "sourceFiles": summary_sources,
        "items": items,
    }


def register_mone_v61_virtual_summary(app):
    replace_paths = {
        "/api/backtest/summary",
        "/api/backtest/trades",
        "/api/final/trade-validation",
        "/api/reports/closing",
        "/api/virtual/summary",
        "/api/virtual/trades",
        "/api/paper-trading/summary",
    }
    app.router.routes = [
        r for r in app.router.routes
        if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)
    ]

    @app.get("/api/virtual/summary")
    def virtual_summary(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all")):
        return _virtual_summary(market, mode, horizon, 200)

    @app.get("/api/virtual/trades")
    def virtual_trades(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all"), limit: int = Query(300)):
        return _virtual_summary(market, mode, horizon, limit)

    @app.get("/api/paper-trading/summary")
    def paper_trading_summary(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all")):
        return _virtual_summary(market, mode, horizon, 200)

    @app.get("/api/backtest/summary")
    def backtest_summary(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all")):
        return _virtual_summary(market, mode, horizon, 200)

    @app.get("/api/backtest/trades")
    def backtest_trades(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all"), limit: int = Query(300)):
        return _virtual_summary(market, mode, horizon, limit)

    @app.get("/api/final/trade-validation")
    def trade_validation(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all")):
        return _virtual_summary(market, mode, horizon, 300)

    @app.get("/api/reports/closing")
    def closing_report(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all"), limit: int = Query(300)):
        data = _virtual_summary(market, mode, horizon, limit)
        data["reportType"] = "closing"
        return data
