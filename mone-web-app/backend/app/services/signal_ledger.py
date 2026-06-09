"""Signal ledger — Phase 3/4

호라이즌별 자동 결과 검증:
  short  (단기): D+1, D+3, D+5
  swing  (스윙): D+3, D+5, D+10
  mid    (중기): D+5, D+10, D+20
"""
from __future__ import annotations

import csv
import json
import math
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

# Repo root: signal_ledger.py → services/ → app/ → backend/ → mone-web-app/ → ROOT
ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = ROOT / "data"
LEDGER_CSV = DATA_DIR / "signal_ledger.csv"
OUTCOMES_CSV = DATA_DIR / "signal_outcomes.csv"
RECOMMENDATION_SNAPSHOTS_CSV = DATA_DIR / "recommendation_snapshots.csv"
RECOMMENDATION_VALIDATION_CSV = DATA_DIR / "recommendation_validation_results.csv"
OHLCV_DIR = DATA_DIR / "market" / "ohlcv"
REPORTS_DIR = ROOT / "reports"

HORIZON_WINDOWS: dict[str, list[int]] = {
    "short": [1, 3, 5],
    "swing": [3, 5, 10],
    "mid":   [5, 10, 20],
}
HORIZON_BADGE_WINDOW = {"short": 5, "swing": 10, "mid": 20}

LEDGER_COLS = [
    "id", "market", "symbol", "name", "mode", "horizon",
    "entry", "stop", "target", "ev", "probability", "score",
    "decision_bucket", "sector", "recorded_at", "recorded_date",
]
OUTCOME_COLS = [
    "signal_id", "window_days", "close_price",
    "return_pct", "hit_target", "hit_stop", "verified_at",
]

RECOMMENDATION_SNAPSHOT_COLS = [
    "snapshot_id", "date", "market", "symbol", "name", "mode", "horizon",
    "recommendationScore", "opportunityScore", "entryScore", "riskScore", "eventRiskScore",
    "currentPrice", "entryPrice", "targetPrice", "stopPrice",
    "chartSignalUsed", "trendlineUsed", "supportUsed", "resistanceUsed", "fakeBreakoutRiskUsed",
    "dataSourceType", "chartSignalSummary", "recorded_at", "source",
]

RECOMMENDATION_VALIDATION_COLS = [
    "snapshot_id", "date", "market", "symbol", "mode", "horizon",
    "validation_status", "validationConfidence", "validationDataSourceType", "validationDataSource",
    "return_1d", "return_3d", "return_5d", "return_10d", "return_20d",
    "max_favorable_return", "max_adverse_return",
    "target_touched", "stop_touched", "target_first", "stop_first",
    "days_to_target", "days_to_stop", "mdd", "win_loss_result",
    "primaryWindowDays", "primaryReturn", "qualityFlag", "verified_at",
]


def _ensure() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not LEDGER_CSV.exists():
        with open(LEDGER_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(LEDGER_COLS)
    if not OUTCOMES_CSV.exists():
        with open(OUTCOMES_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(OUTCOME_COLS)
    if not RECOMMENDATION_SNAPSHOTS_CSV.exists():
        with open(RECOMMENDATION_SNAPSHOTS_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(RECOMMENDATION_SNAPSHOT_COLS)
    if not RECOMMENDATION_VALIDATION_CSV.exists():
        with open(RECOMMENDATION_VALIDATION_CSV, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(RECOMMENDATION_VALIDATION_COLS)


def _read_ledger() -> pd.DataFrame:
    try:
        df = pd.read_csv(LEDGER_CSV, dtype=str)
        return df
    except Exception:
        return pd.DataFrame(columns=LEDGER_COLS)


def _read_outcomes() -> pd.DataFrame:
    try:
        df = pd.read_csv(OUTCOMES_CSV, dtype={"window_days": int, "return_pct": float,
                                               "hit_target": str, "hit_stop": str})
        return df
    except Exception:
        return pd.DataFrame(columns=OUTCOME_COLS)


def _read_recommendation_snapshots() -> pd.DataFrame:
    try:
        return pd.read_csv(RECOMMENDATION_SNAPSHOTS_CSV, dtype=str)
    except Exception:
        return pd.DataFrame(columns=RECOMMENDATION_SNAPSHOT_COLS)


def _read_recommendation_validations() -> pd.DataFrame:
    try:
        return pd.read_csv(RECOMMENDATION_VALIDATION_CSV, dtype=str)
    except Exception:
        return pd.DataFrame(columns=RECOMMENDATION_VALIDATION_COLS)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        raw = str(value).replace(",", "").replace("$", "").replace("%", "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "-"}:
            return None
        out = float(raw)
        return out if math.isfinite(out) else None
    except Exception:
        return None


def _safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"true", "1", "yes", "y", "추천 반영", "used"}


def _json_text(value: Any) -> str:
    try:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)
    except Exception:
        return "{}"


def _json_value(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        text = str(value or "").strip()
        return json.loads(text) if text else {}
    except Exception:
        return {}


def _clean_record(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            out[key] = None
            continue
        if isinstance(value, float) and math.isnan(value):
            out[key] = None
            continue
        if str(value) == "nan":
            out[key] = None
            continue
        out[key] = value
    if isinstance(out.get("chartSignalSummary"), str):
        out["chartSignalSummary"] = _json_value(out.get("chartSignalSummary"))
    for key in ("chartSignalUsed", "trendlineUsed", "supportUsed", "resistanceUsed", "fakeBreakoutRiskUsed",
                "target_touched", "stop_touched", "target_first", "stop_first"):
        if key in out and out[key] is not None:
            out[key] = _safe_bool(out[key])
    return out


def _write_frame(path: Path, rows: list[dict[str, Any]], cols: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _recommendation_snapshot_id(snapshot_date: str, market: str, symbol: str, mode: str, horizon: str) -> str:
    return f"{snapshot_date}|{market}|{symbol}|{mode}|{horizon}"


def _pick_number(item: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _safe_float(item.get(key))
        if value is not None:
            return value
    return None


def _snapshot_from_item(item: dict[str, Any], snapshot_date: str, source: str) -> dict[str, Any] | None:
    market = str(item.get("market") or "").strip().lower()
    if market not in {"kr", "us"}:
        market = "us" if str(item.get("symbol") or "").isalpha() else "kr"
    symbol = str(item.get("symbol") or "").strip().upper()
    mode = str(item.get("mode") or "balanced").strip().lower()
    horizon = str(item.get("horizon") or "swing").strip().lower()
    if not symbol:
        return None
    summary = item.get("chartSignalSummary") or {}
    return {
        "snapshot_id": _recommendation_snapshot_id(snapshot_date, market, symbol, mode, horizon),
        "date": snapshot_date,
        "market": market,
        "symbol": symbol,
        "name": str(item.get("name") or symbol).strip(),
        "mode": mode,
        "horizon": horizon,
        "recommendationScore": _pick_number(item, ["finalRankScore", "finalScore", "recommendationScore", "score"]),
        "opportunityScore": _pick_number(item, ["opportunityScore", "upsideScore"]),
        "entryScore": _pick_number(item, ["entryScore"]),
        "riskScore": _pick_number(item, ["riskScore"]),
        "eventRiskScore": _pick_number(item, ["eventRiskScore", "newsRiskPenalty"]),
        "currentPrice": _pick_number(item, ["currentPrice", "price", "lastPrice"]),
        "entryPrice": _pick_number(item, ["entryPrice", "entry"]),
        "targetPrice": _pick_number(item, ["targetPrice", "target"]),
        "stopPrice": _pick_number(item, ["stopPrice", "stop", "stopLoss"]),
        "chartSignalUsed": bool(item.get("chartSignalUsed")),
        "trendlineUsed": bool(item.get("trendlineUsed")),
        "supportUsed": bool(item.get("supportUsed")),
        "resistanceUsed": bool(item.get("resistanceUsed")),
        "fakeBreakoutRiskUsed": bool(item.get("fakeBreakoutRiskUsed")),
        "dataSourceType": str(item.get("dataSourceType") or "unavailable"),
        "chartSignalSummary": _json_text(summary),
        "recorded_at": datetime.now().isoformat(timespec="seconds"),
        "source": source,
    }


def record_recommendation_snapshots(items: list[dict[str, Any]], snapshot_date: str | None = None, source: str = "api/final/recommendations") -> dict:
    """Persist final recommendation rows for later OHLCV validation."""
    _ensure()
    snapshot_date = (snapshot_date or date.today().isoformat())[:10]
    existing = _read_recommendation_snapshots()
    existing_rows = existing.to_dict("records") if not existing.empty else []
    seen = {str(row.get("snapshot_id")) for row in existing_rows}
    added: list[dict[str, Any]] = []
    duplicates = 0
    for item in items:
        snap = _snapshot_from_item(item, snapshot_date, source)
        if not snap:
            continue
        if str(snap["snapshot_id"]) in seen:
            duplicates += 1
            continue
        seen.add(str(snap["snapshot_id"]))
        added.append(snap)
    if added:
        _write_frame(RECOMMENDATION_SNAPSHOTS_CSV, existing_rows + added, RECOMMENDATION_SNAPSHOT_COLS)
    return {
        "status": "OK",
        "snapshotDate": snapshot_date,
        "added": len(added),
        "duplicates": duplicates,
        "total": len(existing_rows) + len(added),
        "path": str(RECOMMENDATION_SNAPSHOTS_CSV),
        "items": [_clean_record(row) for row in added],
    }


def _load_validation_ohlcv(market: str, symbol: str) -> tuple[pd.DataFrame, str, str]:
    try:
        from app.services import data_loader as data

        df, source = data._load_ohlcv(symbol, market)  # type: ignore[attr-defined]
    except Exception:
        path = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
        if not path.exists():
            return pd.DataFrame(), "", "unavailable"
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
            source = str(path)
        except Exception:
            return pd.DataFrame(), "", "unavailable"
    if df.empty:
        return df, source, "unavailable"
    source_lower = str(source or "").lower()
    source_type = "close_history_fallback" if "close-history fallback" in source_lower else "actual_ohlcv"
    work = df.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in work:
            work[col] = pd.to_numeric(work[col], errors="coerce")
    if "date" not in work:
        return pd.DataFrame(), source, "unavailable"
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    work = work.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    return work, str(source or ""), source_type


def _return_from(base: float | None, price: float | None) -> float | None:
    if base is None or price is None or base <= 0:
        return None
    return round((price - base) / base * 100, 3)


def _mdd_from_prices(prices: list[float]) -> float | None:
    peak: float | None = None
    worst = 0.0
    for price in prices:
        if price <= 0:
            continue
        peak = price if peak is None else max(peak, price)
        if peak and peak > 0:
            worst = min(worst, (price - peak) / peak * 100)
    return round(worst, 3)


def _primary_window(horizon: str) -> int:
    return {"short": 5, "swing": 20, "mid": 20}.get(str(horizon), 20)


def _quality_flag(entry: float | None, target: float | None, stop: float | None, max_adverse: float | None) -> str:
    flags: list[str] = []
    if entry and target and stop:
        reward = target - entry
        risk = entry - stop
        if reward <= 0 or risk <= 0:
            flags.append("BAD_LEVELS")
        elif reward / risk < 1.0:
            flags.append("LOW_RR")
    if max_adverse is not None and max_adverse <= -12:
        flags.append("HIGH_DRAWDOWN")
    return ",".join(flags) if flags else "OK"


def _validate_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(row.get("snapshot_id") or "")
    market = str(row.get("market") or "kr")
    symbol = str(row.get("symbol") or "")
    horizon = str(row.get("horizon") or "swing")
    snapshot_date = str(row.get("date") or "")[:10]
    current = _safe_float(row.get("currentPrice"))
    entry = _safe_float(row.get("entryPrice"))
    target = _safe_float(row.get("targetPrice"))
    stop = _safe_float(row.get("stopPrice"))
    base = current or entry
    df, source, validation_source_type = _load_validation_ohlcv(market, symbol)
    confidence = "HIGH" if str(row.get("dataSourceType")) == "actual_ohlcv" and validation_source_type == "actual_ohlcv" else "LOW"
    result = {
        "snapshot_id": snapshot_id,
        "date": snapshot_date,
        "market": market,
        "symbol": symbol,
        "mode": str(row.get("mode") or ""),
        "horizon": horizon,
        "validation_status": "DATA_PENDING",
        "validationConfidence": confidence,
        "validationDataSourceType": validation_source_type,
        "validationDataSource": source,
        "return_1d": None,
        "return_3d": None,
        "return_5d": None,
        "return_10d": None,
        "return_20d": None,
        "max_favorable_return": None,
        "max_adverse_return": None,
        "target_touched": False,
        "stop_touched": False,
        "target_first": False,
        "stop_first": False,
        "days_to_target": None,
        "days_to_stop": None,
        "mdd": None,
        "win_loss_result": "DATA_PENDING",
        "primaryWindowDays": _primary_window(horizon),
        "primaryReturn": None,
        "qualityFlag": "DATA_PENDING",
        "verified_at": datetime.now().isoformat(timespec="seconds"),
    }
    if not snapshot_id or not snapshot_date or df.empty or base is None or base <= 0:
        return result
    rec_dt = pd.to_datetime(snapshot_date, errors="coerce")
    if pd.isna(rec_dt):
        return result
    future = df[df["date"] > rec_dt].reset_index(drop=True)
    if future.empty:
        return result
    result["validation_status"] = "PARTIAL" if len(future) < 20 else "COMPLETED"
    for days in (1, 3, 5, 10, 20):
        if len(future) >= days:
            result[f"return_{days}d"] = _return_from(base, _safe_float(future.iloc[days - 1].get("close")))
    max_window = min(20, len(future))
    window = future.iloc[:max_window].copy()
    highs = pd.to_numeric(window.get("high", window["close"]), errors="coerce")
    lows = pd.to_numeric(window.get("low", window["close"]), errors="coerce")
    closes = pd.to_numeric(window["close"], errors="coerce").dropna().astype(float).tolist()
    high_max = float(highs.max()) if not highs.dropna().empty else None
    low_min = float(lows.min()) if not lows.dropna().empty else None
    result["max_favorable_return"] = _return_from(base, high_max)
    result["max_adverse_return"] = _return_from(base, low_min)
    result["mdd"] = _mdd_from_prices([base] + closes)
    first_event = ""
    for idx, candle in future.iloc[:max_window].iterrows():
        day = int(idx) + 1
        high = _safe_float(candle.get("high")) or _safe_float(candle.get("close"))
        low = _safe_float(candle.get("low")) or _safe_float(candle.get("close"))
        target_hit = bool(target and high and high >= target)
        stop_hit = bool(stop and low and low <= stop)
        if target_hit and not result["target_touched"]:
            result["target_touched"] = True
            result["days_to_target"] = day
        if stop_hit and not result["stop_touched"]:
            result["stop_touched"] = True
            result["days_to_stop"] = day
        if not first_event and (target_hit or stop_hit):
            if target_hit and stop_hit:
                first_event = "stop"
                result["stop_first"] = True
            elif target_hit:
                first_event = "target"
                result["target_first"] = True
            else:
                first_event = "stop"
                result["stop_first"] = True
    primary = int(result["primaryWindowDays"])
    primary_return = result.get(f"return_{primary}d")
    if primary_return is None:
        for days in (20, 10, 5, 3, 1):
            if result.get(f"return_{days}d") is not None:
                primary_return = result.get(f"return_{days}d")
                result["primaryWindowDays"] = days
                break
    result["primaryReturn"] = primary_return
    if result["target_first"]:
        result["win_loss_result"] = "WIN_TARGET_FIRST"
    elif result["stop_first"]:
        result["win_loss_result"] = "LOSS_STOP_FIRST"
    elif primary_return is None:
        result["win_loss_result"] = "DATA_PENDING"
    elif float(primary_return) > 0:
        result["win_loss_result"] = "WIN_HORIZON_RETURN"
    elif float(primary_return) < 0:
        result["win_loss_result"] = "LOSS_HORIZON_RETURN"
    else:
        result["win_loss_result"] = "FLAT"
    result["qualityFlag"] = _quality_flag(entry, target, stop, result["max_adverse_return"])
    return result


def validate_recommendation_snapshots(market: str = "all", mode: str = "all", horizon: str = "all", limit: int = 500) -> dict:
    _ensure()
    snapshots = _read_recommendation_snapshots()
    if snapshots.empty:
        return {"status": "NO_DATA", "count": 0, "items": [], "message": "No recommendation snapshots recorded"}
    rows = snapshots.to_dict("records")
    filtered: list[dict[str, Any]] = []
    for row in rows:
        if market not in {"", "all"} and str(row.get("market")) != market:
            continue
        if mode not in {"", "all"} and str(row.get("mode")) != mode:
            continue
        if horizon not in {"", "all"} and str(row.get("horizon")) != horizon:
            continue
        filtered.append(row)
    results = [_validate_snapshot(row) for row in filtered]
    existing = _read_recommendation_validations()
    existing_rows = existing.to_dict("records") if not existing.empty else []
    result_map = {str(row.get("snapshot_id")): row for row in existing_rows}
    for result in results:
        result_map[str(result.get("snapshot_id"))] = result
    _write_frame(RECOMMENDATION_VALIDATION_CSV, list(result_map.values()), RECOMMENDATION_VALIDATION_COLS)
    items = [{**_clean_record(snap), **_clean_record(res)} for snap, res in zip(filtered, results)]
    items.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return {
        "status": "OK" if items else "NO_DATA",
        "count": len(items[:limit]),
        "totalCount": len(items),
        "source": str(RECOMMENDATION_VALIDATION_CSV),
        "items": items[:limit],
    }


def _is_completed(row: dict[str, Any]) -> bool:
    return str(row.get("validation_status") or "") in {"COMPLETED", "PARTIAL"} and str(row.get("win_loss_result") or "") != "DATA_PENDING"


def _validation_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if _is_completed(row)]
    wins = [row for row in completed if str(row.get("win_loss_result") or "").startswith("WIN")]
    losses = [row for row in completed if str(row.get("win_loss_result") or "").startswith("LOSS")]
    returns = [_safe_float(row.get("primaryReturn")) for row in completed]
    returns = [r for r in returns if r is not None]
    win_returns = [r for r in returns if r > 0]
    loss_returns = [r for r in returns if r < 0]
    avg_win = sum(win_returns) / len(win_returns) if win_returns else 0.0
    avg_loss = sum(loss_returns) / len(loss_returns) if loss_returns else 0.0
    mdds = [_safe_float(row.get("mdd")) for row in completed]
    mdds = [m for m in mdds if m is not None]
    return {
        "totalRecommendations": len(rows),
        "validatedCount": len(completed),
        "winRate": round(len(wins) / len(completed) * 100, 2) if completed else 0.0,
        "averageReturn": round(sum(returns) / len(returns), 3) if returns else 0.0,
        "averageGain": round(avg_win, 3),
        "averageLoss": round(avg_loss, 3),
        "expectancy": round(sum(returns) / len(returns), 3) if returns else 0.0,
        "profitLossRatio": round(avg_win / abs(avg_loss), 3) if avg_win and avg_loss else 0.0,
        "mdd": round(min(mdds), 3) if mdds else 0.0,
        "targetFirstRate": round(sum(1 for row in completed if _safe_bool(row.get("target_first"))) / len(completed) * 100, 2) if completed else 0.0,
        "stopFirstRate": round(sum(1 for row in completed if _safe_bool(row.get("stop_first"))) / len(completed) * 100, 2) if completed else 0.0,
        "lowConfidenceCount": sum(1 for row in rows if str(row.get("validationConfidence")) == "LOW"),
        "dataPendingCount": sum(1 for row in rows if str(row.get("win_loss_result")) == "DATA_PENDING"),
    }


def _group_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool):
            label = "true" if value else "false"
        else:
            label = str(value if value not in (None, "") else "unknown")
        groups.setdefault(label, []).append(row)
    return {label: _validation_summary_from_rows(group_rows) for label, group_rows in sorted(groups.items())}


def recommendation_validation_summary(market: str = "all", mode: str = "all", horizon: str = "all") -> dict:
    payload = validate_recommendation_snapshots(market=market, mode=mode, horizon=horizon, limit=100000)
    rows = payload.get("items", [])
    summary = _validation_summary_from_rows(rows)
    return {
        "status": payload.get("status"),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "summary": summary,
        "byHorizon": _group_summary(rows, "horizon"),
        "byMode": _group_summary(rows, "mode"),
        "byChartSignalUsed": _group_summary(rows, "chartSignalUsed"),
        "byTrendlineUsed": _group_summary(rows, "trendlineUsed"),
        "bySupportUsed": _group_summary(rows, "supportUsed"),
        "byResistanceUsed": _group_summary(rows, "resistanceUsed"),
        "byFakeBreakoutRiskUsed": _group_summary(rows, "fakeBreakoutRiskUsed"),
        "byDataSourceType": _group_summary(rows, "dataSourceType"),
        "count": len(rows),
    }


def recommendation_validation_by_signal(market: str = "all", mode: str = "all", horizon: str = "all") -> dict:
    payload = validate_recommendation_snapshots(market=market, mode=mode, horizon=horizon, limit=100000)
    rows = payload.get("items", [])
    signal_keys = [
        "chartSignalUsed", "trendlineUsed", "supportUsed", "resistanceUsed",
        "fakeBreakoutRiskUsed", "dataSourceType", "validationConfidence",
    ]
    return {
        "status": payload.get("status"),
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "signals": {key: _group_summary(rows, key) for key in signal_keys},
        "count": len(rows),
    }


# ── Record ─────────────────────────────────────────────────────────────────

def record(
    market: str, symbol: str, name: str,
    mode: str, horizon: str,
    entry: float, stop: float, target: float,
    ev: float, probability: float, score: float,
    decision_bucket: str, sector: str = "",
) -> dict:
    _ensure()
    today = date.today().isoformat()

    # Dedup: same symbol+mode+horizon already recorded today
    df = _read_ledger()
    if not df.empty:
        dup = df[
            (df["symbol"] == symbol) &
            (df["mode"] == mode) &
            (df["horizon"] == horizon) &
            (df["recorded_date"] == today)
        ]
        if not dup.empty:
            return {"ok": True, "duplicate": True, "id": str(dup.iloc[0]["id"])}

    sid = str(uuid.uuid4())[:12]
    with open(LEDGER_CSV, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([
            sid, market, symbol, name, mode, horizon,
            entry, stop, target, ev, probability, score,
            decision_bucket, sector,
            datetime.now().isoformat(), today,
        ])
    return {"ok": True, "duplicate": False, "id": sid}


# ── Verify ─────────────────────────────────────────────────────────────────

def verify() -> dict:
    """호라이즌별 OHLCV 기반 결과 검증."""
    _ensure()
    ledger = _read_ledger()
    outcomes = _read_outcomes()

    verified = skipped = 0

    for _, row in ledger.iterrows():
        sid = str(row["id"])
        horizon = str(row.get("horizon", "swing"))
        windows = HORIZON_WINDOWS.get(horizon, [3, 5, 10])
        entry = float(row.get("entry", 0) or 0)
        stop  = float(row.get("stop", 0) or 0)
        target = float(row.get("target", 0) or 0)
        recorded_date = str(row.get("recorded_date", ""))
        market = str(row.get("market", "kr"))
        symbol = str(row.get("symbol", ""))

        if not recorded_date or entry <= 0:
            continue

        ohlcv_path = OHLCV_DIR / f"{market}_{symbol}_daily.csv"
        if not ohlcv_path.exists():
            skipped += 1
            continue

        try:
            ohlcv = pd.read_csv(ohlcv_path, encoding="utf-8-sig")
            ohlcv.columns = [c.lstrip("﻿").strip() for c in ohlcv.columns]
            ohlcv["date"] = pd.to_datetime(ohlcv["date"])
            ohlcv = ohlcv.sort_values("date").reset_index(drop=True)

            rec_dt = pd.to_datetime(recorded_date)
            future = ohlcv[ohlcv["date"] > rec_dt].reset_index(drop=True)

            for w in windows:
                already = outcomes[
                    (outcomes["signal_id"] == sid) &
                    (outcomes["window_days"] == w)
                ]
                if not already.empty:
                    continue
                if len(future) < w:
                    continue  # 아직 데이터 없음

                w_row = future.iloc[w - 1]
                close_p = float(w_row.get("close", 0) or 0)
                slc = future.iloc[:w]
                high_max = float(slc["high"].max() or 0)
                low_min  = float(slc["low"].min() or 0)

                ret = round((close_p - entry) / entry * 100, 2) if entry > 0 and close_p > 0 else 0.0
                hit_t = bool(target > 0 and high_max >= target)
                hit_s = bool(stop > 0 and low_min <= stop)

                with open(OUTCOMES_CSV, "a", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow([
                        sid, w, close_p, ret,
                        str(hit_t), str(hit_s),
                        datetime.now().isoformat(),
                    ])
                verified += 1

        except Exception:
            skipped += 1

    return {"ok": True, "verified": verified, "skipped": skipped}


# ── Badge ──────────────────────────────────────────────────────────────────

def badge(symbol: str, horizon: str = "all", mode: str = "all") -> dict:
    """백테스트 뱃지 통계 — 호라이즌에 맞는 검증 윈도우 사용."""
    _ensure()
    ledger   = _read_ledger()
    outcomes = _read_outcomes()

    mask = ledger["symbol"] == symbol
    if horizon not in ("all", ""):
        mask &= ledger["horizon"] == horizon
    if mode not in ("all", ""):
        mask &= ledger["mode"] == mode

    matched = ledger[mask]
    if matched.empty:
        return {"sample": 0, "winRate": None, "avgReturn": None}

    target_window = HORIZON_BADGE_WINDOW.get(horizon, 10)
    sids = matched["id"].astype(str).tolist()

    try:
        outs = outcomes[
            (outcomes["signal_id"].astype(str).isin(sids)) &
            (outcomes["window_days"].astype(int) == target_window)
        ]
    except Exception:
        outs = pd.DataFrame()

    if outs.empty:
        return {
            "sample": len(matched),
            "winRate": None, "avgReturn": None,
            "windowDays": target_window, "pending": True,
        }

    returns = outs["return_pct"].astype(float)
    wins = (returns > 0).sum()

    return {
        "sample": len(outs),
        "totalRecorded": len(matched),
        "winRate": round(float(wins / len(outs) * 100), 1),
        "avgReturn": round(float(returns.mean()), 2),
        "windowDays": target_window,
        "pending": False,
    }


# ── Ledger list ────────────────────────────────────────────────────────────

def ledger_list(market: str = "all", limit: int = 100) -> dict:
    _ensure()
    ledger   = _read_ledger()
    outcomes = _read_outcomes()

    if market not in ("all", ""):
        ledger = ledger[ledger["market"] == market]

    ledger = ledger.sort_values("recorded_at", ascending=False).head(limit)

    items = []
    for _, row in ledger.iterrows():
        sid = str(row["id"])
        outs = outcomes[outcomes["signal_id"].astype(str) == sid]
        items.append({
            **{k: (None if (str(v) in ("nan", "")) else v) for k, v in row.to_dict().items()},
            "outcomes": outs.to_dict("records") if not outs.empty else [],
        })

    return {"items": items, "count": len(items)}


# ── Portfolio conflict ─────────────────────────────────────────────────────

def portfolio_conflict(symbol: str, market: str, sector: str = "") -> dict:
    """보유종목과의 섹터 충돌 검사."""
    holdings_path = ROOT / f"holdings_{market}.csv"
    if not holdings_path.exists():
        return {"ok": True, "conflicts": [], "score": 0, "message": "보유종목 없음"}

    try:
        holdings = pd.read_csv(holdings_path, encoding="utf-8-sig", dtype=str)
        holdings.columns = [c.lstrip("﻿").strip() for c in holdings.columns]
    except Exception as e:
        return {"ok": False, "error": str(e), "conflicts": [], "score": 0}

    # 추천 파일에서 섹터 정보 수집
    holding_sectors: dict[str, str] = {}
    for csv_file in REPORTS_DIR.glob("mone_v36_final_recommendations_*.csv"):
        try:
            df = pd.read_csv(csv_file, encoding="utf-8-sig", usecols=["symbol", "sector"], dtype=str)
            for _, r in df.iterrows():
                s = str(r.get("symbol", "")).strip()
                sec = str(r.get("sector", "")).strip()
                if s and sec and s not in holding_sectors:
                    holding_sectors[s] = sec
        except Exception:
            continue

    target_sector = sector.strip()
    conflicts = []

    for _, h in holdings.iterrows():
        h_sym = str(h.get("symbol", "")).strip()
        if h_sym == symbol:
            continue
        h_sector = holding_sectors.get(h_sym, "")
        if target_sector and h_sector and target_sector == h_sector:
            conflicts.append({
                "symbol": h_sym,
                "name": str(h.get("name", "")),
                "sector": h_sector,
                "type": "섹터 동일",
            })

    score = min(100, len(conflicts) * 35)
    msg = "충돌 없음" if not conflicts else f"{len(conflicts)}개 보유종목과 섹터({target_sector}) 겹침"

    return {
        "ok": True, "symbol": symbol,
        "sector": target_sector,
        "conflicts": conflicts,
        "score": score,
        "message": msg,
    }
