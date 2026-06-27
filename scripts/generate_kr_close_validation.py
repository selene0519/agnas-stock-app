from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPORTS = REPO / "reports"
OHLCV_DIR = REPO / "data" / "market" / "ohlcv"
DATE = datetime.now().strftime("%Y-%m-%d")
YYYYMMDD = DATE.replace("-", "")
MODES = ["conservative", "balanced", "aggressive"]
HORIZONS = ["short", "swing", "mid"]
MARKETS = ["kr", "us"]

# ── 수수료 + 슬리피지 (현실적 비용 반영)
# KR: 편도 수수료 0.015% × 2 + 슬리피지 0.03% × 2 = 0.09%
# US: 무료 브로커 가정, 슬리피지만 0.03% × 2 = 0.06%
COST_PCT = {"kr": 0.09, "us": 0.06}


def read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in csv.DictReader(f)]
        except Exception:
            continue
    return []


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{k: row.get(k, "") for k in fieldnames} for row in rows])


def norm_symbol(value: object, market: str) -> str:
    if market == "us":
        return str(value or "").strip().upper()
    raw = re.sub(r"\D", "", str(value or ""))
    return raw.zfill(6)[-6:] if raw else ""


def num(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).replace(",", "").replace("원", "").replace("₩", "").replace("$", "").strip()
    if text in {"", "-", "None", "nan", "NaN"}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def text_price(value: float | None, market: str) -> str:
    if value is None:
        return ""
    return f"{round(value):,}원" if market == "kr" else f"${value:,.2f}"


def rec_files(market: str, mode: str, horizon: str) -> list[Path]:
    patterns = [
        f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        f"mone_v36_final_recommendations_{market}_{mode}_{horizon}_*.csv",
        f"*recommendations*{market}*{mode}*{horizon}*.csv",
    ]
    files: list[Path] = []
    for pattern in patterns:
        files.extend(sorted(REPORTS.glob(pattern)))
    return list(dict.fromkeys(files))


def get_price(row: dict, names: list[str]) -> float | None:
    for name in names:
        value = num(row.get(name))
        if value is not None and value > 0:
            return value
    return None


def load_recommendations(market: str, mode: str, horizon: str) -> list[dict]:
    for path in rec_files(market, mode, horizon):
        rows = read_csv(path)
        if rows:
            out = []
            for row in rows:
                sym = norm_symbol(row.get("symbol") or row.get("ticker") or row.get("code"), market)
                if not sym:
                    continue
                out.append({**row, "symbol": sym, "_source": path.name})
            if out:
                return out
    return []


def load_pending_ledger_fallback(market: str, mode: str, horizon: str, known_symbols: set[str]) -> list[dict]:
    """오늘 추천 리스트에 없는, 아직 PENDING인 예측도 계속 추적한다.

    추천 후보가 다음날 스크리닝에서 빠지면(섹터캡, 점수 하락 등) load_recommendations()가
    그 심볼을 더 이상 돌려주지 않아 검증 스냅샷이 끊긴다. 그 결과 마감일이 지나도 영원히
    체결 데이터를 찾을 수 없어 EXPIRED(데이터 없음)로 잘못 분류된다. ledger 자체가 entry/stop/
    target 가격을 들고 있으므로, 추천 리스트와 무관하게 이걸로 계속 검증할 수 있다.
    """
    rows = read_csv(REPORTS / "virtual_prediction_ledger.csv")
    out: list[dict] = []
    for row in rows:
        if str(row.get("status") or "").strip().upper() != "PENDING":
            continue
        if str(row.get("market") or "").lower() != market:
            continue
        if str(row.get("mode") or "").lower() != mode:
            continue
        if str(row.get("horizon") or "").lower() != horizon:
            continue
        sym = norm_symbol(row.get("symbol"), market)
        if not sym or sym in known_symbols:
            continue
        out.append({**row, "symbol": sym, "_source": "virtual_prediction_ledger.csv"})
        known_symbols.add(sym)
    return out


def close_row(market: str, symbol: str) -> dict | None:
    for path in [OHLCV_DIR / f"{market}_{symbol}_daily.csv", REPORTS / f"{market}_{symbol}_daily.csv"]:
        rows = read_csv(path)
        for row in rows:
            date = str(row.get("date") or row.get("Date") or "")[:10]
            if date == DATE:
                return row
    return None


def validate_one(market: str, row: dict, mode: str, horizon: str) -> dict:
    sym = row["symbol"]
    ohlcv = close_row(market, sym)
    name = row.get("name") or row.get("companyName") or sym
    entry = get_price(row, ["entryPrice", "entry", "entry_price", "entryPriceValue", "entryText", "진입가"])
    stop = get_price(row, ["stopPrice", "stop", "stop_price", "stopText", "손절가"])
    target = get_price(row, ["targetPrice", "target", "target_price", "targetText", "목표가"])
    if not ohlcv:
        return {"date": DATE, "symbol": sym, "name": name, "market": market, "mode": mode, "horizon": horizon, "executed": "false", "result": "DATA_PENDING", "dataStatus": "DATA_PENDING", "reason": "today_ohlcv_missing", "source": row.get("_source", "")}
    high = get_price(ohlcv, ["high", "High", "고가"])
    low = get_price(ohlcv, ["low", "Low", "저가"])
    close = get_price(ohlcv, ["close", "Close", "종가"])
    if not all(v is not None and v > 0 for v in (entry, high, low, close)):
        return {"date": DATE, "symbol": sym, "name": name, "market": market, "mode": mode, "horizon": horizon, "executed": "false", "result": "DATA_PENDING", "dataStatus": "DATA_PENDING", "reason": "price_fields_missing", "source": row.get("_source", "")}
    executed = bool(low <= entry <= high)  # type: ignore[operator]
    if not executed:
        return {"date": DATE, "symbol": sym, "name": name, "market": market, "mode": mode, "horizon": horizon, "executed": "false", "entryPrice": entry, "entryText": text_price(entry, market), "exitPrice": "", "returnPct": "", "result": "not_executed", "dataStatus": "NORMAL", "reason": "entry_not_touched", "low": low, "high": high, "close": close, "source": row.get("_source", "")}
    result = "close_exit"
    exit_price = close
    target_hit = bool(target and high and high >= target)
    stop_hit = bool(stop and low and low <= stop)
    # 동시 도달 시 손절 우선 (보수적 가정 — 어느 쪽이 먼저인지 알 수 없음)
    if target_hit and stop_hit:
        target_hit = False  # 손절이 먼저 났다고 가정
    if target_hit:
        result = "target_hit"
        exit_price = target
    elif stop_hit:
        result = "stop_hit"
        exit_price = stop
    ret_gross = ((exit_price - entry) / entry) * 100 if entry else 0
    ret = round(ret_gross - COST_PCT.get(market, COST_PCT["kr"]), 4)
    return {"date": DATE, "symbol": sym, "name": name, "market": market, "mode": mode, "horizon": horizon, "executed": "true", "entryPrice": entry, "entryText": text_price(entry, market), "stopPrice": stop or "", "targetPrice": target or "", "exitPrice": exit_price, "exitText": text_price(exit_price, market), "returnPct": ret, "returnPctText": f"{ret:+.2f}%", "result": result, "dataStatus": "NORMAL", "reason": "", "low": low, "high": high, "close": close, "source": row.get("_source", "")}


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    summary = {"date": DATE, "created": [], "skipped": [], "updatedAt": datetime.now().isoformat(timespec="seconds")}
    fieldnames = ["date", "symbol", "name", "market", "mode", "horizon", "executed", "entryPrice", "entryText", "stopPrice", "targetPrice", "exitPrice", "exitText", "returnPct", "returnPctText", "result", "dataStatus", "reason", "low", "high", "close", "source"]
    for market in MARKETS:
        for mode in MODES:
            for horizon in HORIZONS:
                recs = load_recommendations(market, mode, horizon)
                known_symbols = {row["symbol"] for row in recs}
                recs = recs + load_pending_ledger_fallback(market, mode, horizon, known_symbols)
                rows = [validate_one(market, row, mode, horizon) for row in recs]
                if rows and any(row.get("dataStatus") == "NORMAL" for row in rows):
                    out = REPORTS / f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}_{YYYYMMDD}.csv"
                    write_csv(out, rows, fieldnames)
                    summary["created"].append({"market": market, "mode": mode, "horizon": horizon, "file": out.name, "rows": len(rows), "normalRows": sum(1 for r in rows if r.get("dataStatus") == "NORMAL")})
                else:
                    summary["skipped"].append({"market": market, "mode": mode, "horizon": horizon, "rows": len(rows), "reason": "no_today_ohlcv_or_no_recommendations"})
    (REPORTS / "kr_close_validation_status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
