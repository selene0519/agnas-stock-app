"""Map legacy predictions.csv rows into decision_system CSVs and summary stats."""

from __future__ import annotations

import json
import math
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import (
    ACTUAL_RESULTS,
    DECISION_DATA,
    ERROR_LOGS,
    LEGACY_PREDICTIONS,
    REPORTS_DIR,
    TRADE_SIMULATIONS,
)


def _safe_float(x: Any, default: float = math.nan) -> float:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        s = str(x).strip().replace(",", "")
        if s == "" or s.lower() in {"nan", "none", "nat"}:
            return default
        return float(s)
    except Exception:
        return default


def _infer_direction_from_prices(prev_close: float, close: float) -> str:
    if math.isnan(prev_close) or math.isnan(close) or prev_close == 0:
        return "flat"
    if close > prev_close * 1.0005:
        return "up"
    if close < prev_close * 0.9995:
        return "down"
    return "flat"


def _append_csv(file_path: Path, new_rows: pd.DataFrame) -> int:
    if new_rows.empty:
        return 0
    file_path.parent.mkdir(parents=True, exist_ok=True)
    if not file_path.exists() or file_path.stat().st_size == 0:
        new_rows.to_csv(file_path, index=False, encoding="utf-8-sig")
        return len(new_rows)
    old = pd.read_csv(file_path, dtype=str).fillna("")
    if old.empty:
        merged = new_rows
    else:
        merged = pd.concat([old, new_rows], ignore_index=True)
    key_cols = [c for c in ["prediction_id", "date", "market", "ticker"] if c in merged.columns]
    if key_cols:
        merged = merged.drop_duplicates(subset=key_cols, keep="last")
    merged.to_csv(file_path, index=False, encoding="utf-8-sig")
    return len(new_rows)


def run_from_legacy_predictions(max_rows: int = 500) -> dict[str, Any]:
    """
    Reads root predictions.csv (legacy), emits:
    - data/decision_system/error_logs.csv rows
    - data/decision_system/actual_results.csv rows
    - data/decision_system/trade_simulations.csv rows (when virtual fields exist)
    - reports/validation_summary_YYYY-MM-DD.json
    """
    DECISION_DATA.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    if not LEGACY_PREDICTIONS.exists():
        return {"ok": False, "error": "predictions.csv missing", "rows_processed": 0}

    df = pd.read_csv(LEGACY_PREDICTIONS, dtype=str, low_memory=False).fillna("")
    need = {"prediction_id", "market", "ticker", "actual_close", "prev_close"}
    if not need.issubset(set(df.columns)):
        return {"ok": False, "error": "legacy predictions missing required columns", "rows_processed": 0}

    sub = df[df["actual_close"].astype(str).str.strip() != ""].copy()
    if sub.empty:
        return {"ok": True, "rows_processed": 0, "note": "no rows with actual_close"}

    sub = sub.tail(int(max_rows))

    now = datetime.now().isoformat(timespec="seconds")
    today = datetime.now().strftime("%Y-%m-%d")

    err_rows: list[dict[str, Any]] = []
    act_rows: list[dict[str, Any]] = []
    sim_rows: list[dict[str, Any]] = []

    hits = 0
    n = 0
    open_hits = 0
    close_hits = 0
    ohi = 0
    chi = 0

    for _, r in sub.iterrows():
        pid = str(r.get("prediction_id", "") or "").strip() or str(uuid.uuid4())[:12]
        market = str(r.get("market", ""))
        ticker = str(r.get("ticker", ""))
        target_date = str(r.get("target_date", "") or r.get("actual_date", "") or "")[:10]
        prev = _safe_float(r.get("prev_close"))
        act_o = _safe_float(r.get("actual_open"))
        act_h = _safe_float(r.get("actual_high"))
        act_l = _safe_float(r.get("actual_low"))
        act_c = _safe_float(r.get("actual_close"))
        vol = _safe_float(r.get("actual_volume"))
        if math.isnan(act_c):
            continue

        mid = _safe_float(r.get("pred_close_mid"))
        pred_close_for_dir = mid if not math.isnan(mid) else act_c
        pred_dir = _infer_direction_from_prices(prev, pred_close_for_dir)
        act_dir = _infer_direction_from_prices(prev, act_c)

        dh = _safe_float(r.get("direction_hit"), math.nan)
        if dh == 1.0:
            hit = "hit"
        elif dh == 0.0:
            hit = "miss"
        else:
            hit = "hit" if pred_dir == act_dir and pred_dir != "flat" else "miss"

        conf = _safe_float(r.get("confidence_score"), math.nan)
        exp_ret = _safe_float(r.get("virtual_return_pct"), math.nan)
        act_ret = (act_c - prev) / prev * 100 if prev and not math.isnan(prev) else math.nan

        oir = _safe_float(r.get("open_in_range"), math.nan)
        cir = _safe_float(r.get("close_in_range"), math.nan)
        if not math.isnan(oir):
            ohi += 1
            if oir == 1.0:
                open_hits += 1
        if not math.isnan(cir):
            chi += 1
            if cir == 1.0:
                close_hits += 1

        n += 1
        if hit == "hit":
            hits += 1

        err_reason = str(r.get("prediction_error_reason", "") or r.get("prediction_cause_summary", ""))[:500]
        if not err_reason and hit == "miss":
            err_reason = "direction_miss"

        err_rows.append(
            {
                "prediction_id": pid,
                "date": target_date,
                "market": market,
                "ticker": ticker,
                "predicted_direction": pred_dir,
                "actual_direction": act_dir,
                "confidence_score": "" if math.isnan(conf) else f"{conf:.4f}",
                "expected_return": "" if math.isnan(exp_ret) else f"{exp_ret:.6f}",
                "actual_return": "" if math.isnan(act_ret) else f"{act_ret:.6f}",
                "hit_or_miss": hit,
                "error_size": ""
                if math.isnan(act_ret) or math.isnan(exp_ret)
                else f"{abs(act_ret - exp_ret):.6f}",
                "simulated_pnl": str(r.get("virtual_net_return_pct", r.get("virtual_return_pct", ""))),
                "max_drawdown": "",
                "error_reason": err_reason[:200],
                "correction_needed": str(r.get("next_prediction_adjustment", ""))[:300],
                "created_at": now,
            }
        )

        chg = (act_c - prev) / prev * 100 if prev and not math.isnan(prev) else ""
        act_rows.append(
            {
                "date": str(r.get("actual_date", target_date))[:10],
                "market": market,
                "ticker": ticker,
                "open": "" if math.isnan(act_o) else act_o,
                "high": "" if math.isnan(act_h) else act_h,
                "low": "" if math.isnan(act_l) else act_l,
                "close": act_c,
                "change_pct": chg,
                "volume": "" if math.isnan(vol) else vol,
                "actual_direction": act_dir,
                "actual_return": "" if math.isnan(act_ret) else act_ret,
                "created_at": now,
            }
        )

        vret = r.get("virtual_return_pct", "")
        vlab = r.get("virtual_result_label", "")
        if str(vret).strip() != "":
            sim_rows.append(
                {
                    "prediction_id": pid,
                    "date": target_date,
                    "market": market,
                    "ticker": ticker,
                    "decision": str(r.get("primary_action", "")),
                    "simulated_entry": str(r.get("preferred_entry", "")),
                    "simulated_exit": str(r.get("virtual_exit_price", "")),
                    "stop_loss": str(r.get("stop_loss", "")),
                    "target_price": str(r.get("take_profit1", "")),
                    "max_profit_pct": "",
                    "max_loss_pct": "",
                    "final_pnl_pct": str(vret),
                    "stop_triggered": str(r.get("stop_touched", "")),
                    "target_triggered": str(r.get("tp1_touched", "")),
                    "hold_or_exit": str(r.get("virtual_rule", "")),
                    "result_label": str(vlab),
                }
            )

    summary = {
        "date": today,
        "rows": n,
        "direction_hit_rate": (hits / n) if n else 0.0,
        "open_in_range_rate": (open_hits / ohi) if ohi else None,
        "close_in_range_rate": (close_hits / chi) if chi else None,
        "source": str(LEGACY_PREDICTIONS),
    }
    rep = REPORTS_DIR / f"validation_summary_{today}.json"
    rep.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    added_err = _append_csv(ERROR_LOGS, pd.DataFrame(err_rows)) if err_rows else 0
    added_act = _append_csv(ACTUAL_RESULTS, pd.DataFrame(act_rows)) if act_rows else 0
    added_sim = _append_csv(TRADE_SIMULATIONS, pd.DataFrame(sim_rows)) if sim_rows else 0

    return {
        "ok": True,
        "rows_processed": n,
        "error_log_rows_appended": added_err,
        "actual_results_rows_appended": added_act,
        "trade_sim_rows_appended": added_sim,
        "summary": summary,
        "report": str(rep.relative_to(LEGACY_PREDICTIONS.parent)),
    }
