"""Post-prediction adjustment engine based on accumulated error profiles."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import PROJECT_ROOT
from core.prediction_error_analysis import (
    MARKET_CONDITION_ERROR_SUMMARY,
    PREDICTION_ERROR_REPORT,
    TICKER_ERROR_PROFILE,
)


PREDICTION_ADJUSTMENTS = PROJECT_ROOT / "data" / "prediction_adjustments.csv"
FINAL_DECISION_STEPS = ["손절 우선", "비중 축소 우선", "관망 우위", "눌림목 매수 가능", "돌파 확인 후 접근"]

ADJUSTMENT_COLUMNS = [
    "ticker",
    "market",
    "total_cases",
    "direction_hit_rate",
    "avg_open_error_pct",
    "avg_close_error_pct",
    "entry_touch_rate",
    "stop_touch_rate",
    "tp1_touch_rate",
    "avg_final_pnl_pct",
    "open_bias_adjustment_pct",
    "close_bias_adjustment_pct",
    "atr_multiplier_adjustment",
    "entry_adjustment_pct",
    "stop_adjustment_pct",
    "tp_adjustment_pct",
    "confidence_penalty",
    "decision_downgrade",
    "adjustment_reason",
    "updated_at",
]


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() and path.parent.name == "data":
        fallback = PROJECT_ROOT / path.name
        if fallback.exists():
            path = fallback
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        return pd.DataFrame()


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        text = str(value).strip().replace(",", "").replace("%", "")
        if text == "" or text.lower() in {"nan", "none", "nat", "n/a", "na"}:
            return default
        return float(text)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    val = _safe_float(value, math.nan)
    if math.isnan(val):
        return default
    return int(round(val))


def _clip(value: float, lo: float, hi: float) -> float:
    if math.isnan(value):
        return 0.0
    return max(lo, min(hi, value))


def _ticker_key(ticker: Any) -> str:
    text = str(ticker or "").strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit() and len(text) < 6:
        return text.zfill(6)
    return text


def _rename_first(df: pd.DataFrame, target: str, candidates: list[str]) -> pd.DataFrame:
    if df.empty or target in df.columns:
        return df
    for name in candidates:
        if name in df.columns:
            return df.rename(columns={name: target})
    return df


def _canonicalize_profile(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for target, candidates in {
        "ticker": ["symbol", "종목", "종목코드", "티커"],
        "market": ["시장", "market_name"],
        "total_cases": ["cases", "count", "n", "총건수"],
        "direction_hit_rate": ["hit_rate", "direction_rate", "방향적중률"],
        "avg_open_error_pct": ["open_error_pct", "평균시초가오차"],
        "avg_close_error_pct": ["close_error_pct", "평균종가오차"],
        "entry_touch_rate": ["entry_rate", "진입터치율"],
        "stop_touch_rate": ["stop_rate", "손절터치율"],
        "tp1_touch_rate": ["tp_rate", "target_touch_rate", "익절터치율"],
        "avg_final_pnl_pct": ["avg_pnl", "final_pnl_pct", "평균손익"],
    }.items():
        out = _rename_first(out, target, candidates)
    return out


def _canonicalize_report(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for target, candidates in {
        "ticker": ["symbol", "종목", "종목코드", "티커"],
        "market": ["시장", "market_name"],
        "open_error_pct": ["시초가오차", "open_error"],
        "close_error_pct": ["종가오차", "close_error"],
    }.items():
        out = _rename_first(out, target, candidates)
    return out


def _canonicalize_market_summary(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for target, candidates in {
        "market_condition": ["condition", "시장상태"],
        "direction_hit_rate": ["hit_rate", "방향적중률"],
        "stop_touch_rate": ["stop_rate", "손절터치율"],
    }.items():
        out = _rename_first(out, target, candidates)
    return out


def _mean_signed_error(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty or not {"market", "ticker"}.issubset(report.columns):
        return pd.DataFrame(columns=["market", "ticker", "signed_open_error_pct", "signed_close_error_pct"])
    work = report.copy()
    work["_ticker_key"] = work["ticker"].map(_ticker_key)
    for col in ["open_error_pct", "close_error_pct"]:
        if col not in work.columns:
            work[col] = ""
        work[col] = pd.to_numeric(work[col], errors="coerce")
    grouped = (
        work.groupby(["market", "_ticker_key"], dropna=False)[["open_error_pct", "close_error_pct"]]
        .mean()
        .reset_index()
        .rename(
            columns={
                "_ticker_key": "ticker",
                "open_error_pct": "signed_open_error_pct",
                "close_error_pct": "signed_close_error_pct",
            }
        )
    )
    return grouped


def _market_summary_flags(summary: pd.DataFrame) -> tuple[int, str]:
    if summary.empty:
        return 0, ""
    penalty = 0
    reasons: list[str] = []
    for _, row in summary.iterrows():
        condition = str(row.get("market_condition", ""))
        hit = _safe_float(row.get("direction_hit_rate"), math.nan)
        stop = _safe_float(row.get("stop_touch_rate"), math.nan)
        if ("event_high" in condition or "negative" in condition) and not math.isnan(hit) and hit < 45:
            penalty = max(penalty, 3)
            reasons.append(f"{condition}: 방향 적중률 낮음")
        if not math.isnan(stop) and stop >= 45:
            penalty = max(penalty, 5)
            reasons.append(f"{condition}: 손절 터치율 높음")
    return penalty, " / ".join(dict.fromkeys(reasons))


def build_prediction_adjustments(
    ticker_profile_path: Path = TICKER_ERROR_PROFILE,
    market_summary_path: Path = MARKET_CONDITION_ERROR_SUMMARY,
    prediction_error_path: Path = PREDICTION_ERROR_REPORT,
    output_path: Path = PREDICTION_ADJUSTMENTS,
) -> dict[str, Any]:
    profile = _canonicalize_profile(_read_csv(ticker_profile_path))
    market_summary = _canonicalize_market_summary(_read_csv(market_summary_path))
    report = _canonicalize_report(_read_csv(prediction_error_path))
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if profile.empty:
        empty = pd.DataFrame(columns=ADJUSTMENT_COLUMNS)
        empty.to_csv(output_path, index=False, encoding="utf-8-sig")
        return {"ok": True, "rows": 0, "generated_file": str(output_path.relative_to(PROJECT_ROOT))}

    signed = _mean_signed_error(report)
    if not signed.empty:
        signed = signed.set_index(["market", "ticker"])

    market_penalty, market_reason = _market_summary_flags(market_summary)
    now = datetime.now().isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []

    for _, row in profile.iterrows():
        market = str(row.get("market", "")).strip()
        ticker = str(row.get("ticker", "")).strip()
        ticker_key = _ticker_key(ticker)
        total_cases = _safe_int(row.get("total_cases"), 0)
        direction_hit_rate = _safe_float(row.get("direction_hit_rate"), math.nan)
        entry_touch_rate = _safe_float(row.get("entry_touch_rate"), math.nan)
        stop_touch_rate = _safe_float(row.get("stop_touch_rate"), math.nan)
        tp1_touch_rate = _safe_float(row.get("tp1_touch_rate"), math.nan)
        avg_final_pnl = _safe_float(row.get("avg_final_pnl_pct"), math.nan)
        avg_open_abs = _safe_float(row.get("avg_open_error_pct"), math.nan)
        avg_close_abs = _safe_float(row.get("avg_close_error_pct"), math.nan)

        core_missing = (
            total_cases <= 0
            or not ticker
            or not market
            or math.isnan(direction_hit_rate)
            or math.isnan(stop_touch_rate)
            or math.isnan(tp1_touch_rate)
        )
        if core_missing:
            rows.append(
                {
                    "ticker": ticker,
                    "market": market,
                    "total_cases": total_cases,
                    "direction_hit_rate": "" if math.isnan(direction_hit_rate) else f"{direction_hit_rate:.4f}",
                    "avg_open_error_pct": "" if math.isnan(avg_open_abs) else f"{avg_open_abs:.4f}",
                    "avg_close_error_pct": "" if math.isnan(avg_close_abs) else f"{avg_close_abs:.4f}",
                    "entry_touch_rate": "" if math.isnan(entry_touch_rate) else f"{entry_touch_rate:.4f}",
                    "stop_touch_rate": "" if math.isnan(stop_touch_rate) else f"{stop_touch_rate:.4f}",
                    "tp1_touch_rate": "" if math.isnan(tp1_touch_rate) else f"{tp1_touch_rate:.4f}",
                    "avg_final_pnl_pct": "" if math.isnan(avg_final_pnl) else f"{avg_final_pnl:.4f}",
                    "open_bias_adjustment_pct": "0.0000",
                    "close_bias_adjustment_pct": "0.0000",
                    "atr_multiplier_adjustment": "0.0000",
                    "entry_adjustment_pct": "0.0000",
                    "stop_adjustment_pct": "0.0000",
                    "tp_adjustment_pct": "0.0000",
                    "confidence_penalty": 0,
                    "decision_downgrade": 0,
                    "adjustment_reason": "누적 데이터 부족",
                    "updated_at": now,
                }
            )
            continue

        signed_open = math.nan
        signed_close = math.nan
        if not signed.empty and (market, ticker_key) in signed.index:
            srow = signed.loc[(market, ticker_key)]
            signed_open = _safe_float(srow.get("signed_open_error_pct"), math.nan)
            signed_close = _safe_float(srow.get("signed_close_error_pct"), math.nan)

        if math.isnan(signed_open):
            signed_open = avg_open_abs if not math.isnan(avg_open_abs) else 0.0
        if math.isnan(signed_close):
            signed_close = avg_close_abs if not math.isnan(avg_close_abs) else 0.0

        if total_cases < 3:
            strength = 0.25
        elif total_cases < 5:
            strength = 0.55
        else:
            strength = 1.0

        reasons: list[str] = []
        confidence_penalty = market_penalty
        decision_downgrade = 0

        if not math.isnan(direction_hit_rate) and direction_hit_rate < 45:
            confidence_penalty = max(confidence_penalty, 10)
            reasons.append("방향 적중률 45% 미만")
        if not math.isnan(direction_hit_rate) and direction_hit_rate < 35:
            decision_downgrade = max(decision_downgrade, 1)
            reasons.append("방향 적중률 35% 미만")

        entry_adj = 0.0
        stop_adj = 0.0
        if not math.isnan(stop_touch_rate) and stop_touch_rate >= 60:
            level = min(1.0, (stop_touch_rate - 60) / 40)
            entry_adj = -0.3 - 0.5 * level
            stop_adj = -0.2 - 0.3 * level
            reasons.append("손절 터치율 60% 이상")

        tp_adj = 0.0
        if not math.isnan(tp1_touch_rate) and tp1_touch_rate < 25:
            level = min(1.0, (25 - tp1_touch_rate) / 25)
            tp_adj = -0.5 - 0.5 * level
            reasons.append("TP1 터치율 25% 미만")

        if not math.isnan(avg_final_pnl) and avg_final_pnl < 0 and not math.isnan(stop_touch_rate) and stop_touch_rate >= 45:
            decision_downgrade = max(decision_downgrade, 1)
            confidence_penalty = max(confidence_penalty, 12)
            reasons.append("평균 손익 음수 + 손절 터치율 높음")

        if total_cases < 3:
            entry_adj = 0.0
            stop_adj = 0.0
            tp_adj = 0.0
            decision_downgrade = 0
            confidence_penalty = min(max(confidence_penalty, 3 if confidence_penalty else 0), 5)
            reasons.append("누적 데이터 3건 미만: 약한 보정만 적용")

        open_bias = _clip(signed_open * 0.35 * strength, -1.5, 1.5)
        close_bias = _clip(signed_close * 0.35 * strength, -1.5, 1.5)
        if abs(open_bias) >= 0.05:
            reasons.append("시초가 평균 오차 반영")
        if abs(close_bias) >= 0.05:
            reasons.append("종가 평균 오차 반영")

        atr_adj = 0.0
        if (not math.isnan(avg_open_abs) and avg_open_abs >= 2.5) or (not math.isnan(avg_close_abs) and avg_close_abs >= 3.0):
            atr_adj = min(0.35, max(0.10, ((avg_open_abs if not math.isnan(avg_open_abs) else 0) + (avg_close_abs if not math.isnan(avg_close_abs) else 0)) / 25))
            reasons.append("평균 오차 커서 예측 범위 확대")

        if market_reason:
            reasons.append(market_reason)

        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "total_cases": total_cases,
                "direction_hit_rate": "" if math.isnan(direction_hit_rate) else f"{direction_hit_rate:.4f}",
                "avg_open_error_pct": "" if math.isnan(signed_open) else f"{signed_open:.4f}",
                "avg_close_error_pct": "" if math.isnan(signed_close) else f"{signed_close:.4f}",
                "entry_touch_rate": "" if math.isnan(entry_touch_rate) else f"{entry_touch_rate:.4f}",
                "stop_touch_rate": "" if math.isnan(stop_touch_rate) else f"{stop_touch_rate:.4f}",
                "tp1_touch_rate": "" if math.isnan(tp1_touch_rate) else f"{tp1_touch_rate:.4f}",
                "avg_final_pnl_pct": "" if math.isnan(avg_final_pnl) else f"{avg_final_pnl:.4f}",
                "open_bias_adjustment_pct": f"{_clip(open_bias, -1.5, 1.5):.4f}",
                "close_bias_adjustment_pct": f"{_clip(close_bias, -1.5, 1.5):.4f}",
                "atr_multiplier_adjustment": f"{_clip(atr_adj, -0.30, 0.50):.4f}",
                "entry_adjustment_pct": f"{_clip(entry_adj * strength, -1.2, 0.5):.4f}",
                "stop_adjustment_pct": f"{_clip(stop_adj * strength, -1.0, 0.5):.4f}",
                "tp_adjustment_pct": f"{_clip(tp_adj * strength, -1.5, 0.5):.4f}",
                "confidence_penalty": int(_clip(confidence_penalty * strength if total_cases >= 3 else confidence_penalty, 0, 25)),
                "decision_downgrade": int(_clip(decision_downgrade, 0, 2)),
                "adjustment_reason": " / ".join(dict.fromkeys(reasons)) if reasons else "보정 없음",
                "updated_at": now,
            }
        )

    out = pd.DataFrame(rows, columns=ADJUSTMENT_COLUMNS)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")
    return {"ok": True, "rows": int(len(out)), "generated_file": str(output_path.relative_to(PROJECT_ROOT))}


def load_prediction_adjustments(path: Path = PREDICTION_ADJUSTMENTS) -> pd.DataFrame:
    return _read_csv(path)


def find_adjustment(ticker: str, market: str, adjustments: pd.DataFrame | None = None) -> dict[str, Any] | None:
    df = load_prediction_adjustments() if adjustments is None else adjustments
    if df is None or df.empty:
        return None
    if not {"ticker", "market"}.issubset(df.columns):
        return None
    key = _ticker_key(ticker)
    work = df.copy()
    work["_ticker_key"] = work["ticker"].map(_ticker_key)
    hit = work[(work["market"].astype(str) == str(market)) & (work["_ticker_key"] == key)]
    if hit.empty:
        return None
    return hit.iloc[0].to_dict()


def _adj_float(adj: dict[str, Any], name: str) -> float:
    return _safe_float(adj.get(name), 0.0)


def _apply_pct(value: Any, pct: float) -> Any:
    val = _safe_float(value, math.nan)
    if math.isnan(val):
        return value
    return val * (1 + pct / 100)


def _widen_range(pred: dict[str, Any], low_key: str, mid_key: str, high_key: str, multiplier_adjustment: float) -> None:
    low = _safe_float(pred.get(low_key), math.nan)
    mid = _safe_float(pred.get(mid_key), math.nan)
    high = _safe_float(pred.get(high_key), math.nan)
    if any(math.isnan(x) for x in [low, mid, high]):
        return
    factor = max(0.75, min(1.50, 1 + multiplier_adjustment))
    pred[low_key] = mid - (mid - low) * factor
    pred[high_key] = mid + (high - mid) * factor


def _infer_final_decision(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return "관망 우위"
    for step in FINAL_DECISION_STEPS:
        if step in raw:
            return step
    lowered = raw.lower()
    if "손절" in raw:
        return "손절 우선"
    if "비중" in raw or "축소" in raw:
        return "비중 축소 우선"
    if "돌파" in raw:
        return "돌파 확인 후 접근"
    if "눌림" in raw or "지지선 근처" in raw or "반등 확인" in raw or "매수" in raw or "진입" in raw:
        return "눌림목 매수 가능"
    if "금지" in raw or "관망" in raw or "중립" in raw or "확인" in raw or "보류" in raw or "avoid" in lowered:
        return "관망 우위"
    return "관망 우위"


def _downgrade_decision(text: str, level: int) -> tuple[str, str]:
    before = _infer_final_decision(text)
    idx = FINAL_DECISION_STEPS.index(before)
    after_idx = max(0, idx - max(0, int(level)))
    return before, FINAL_DECISION_STEPS[after_idx]


def apply_prediction_adjustment(
    prediction: dict[str, Any],
    ticker: str,
    market: str,
    adjustments: pd.DataFrame | None = None,
) -> dict[str, Any]:
    out = dict(prediction or {})
    adj = find_adjustment(ticker, market, adjustments)
    before_decision = str(out.get("primary_action", "") or "")
    before_final_decision = _infer_final_decision(before_decision)
    before_conf = _safe_float(out.get("confidence_score"), math.nan)

    base_meta = {
        "adjustment_applied": 0,
        "adjustment_reason": "누적 데이터 부족",
        "open_bias_adjustment_pct": 0.0,
        "close_bias_adjustment_pct": 0.0,
        "atr_multiplier_adjustment": 0.0,
        "entry_adjustment_pct": 0.0,
        "stop_adjustment_pct": 0.0,
        "tp_adjustment_pct": 0.0,
        "confidence_penalty": 0,
        "decision_downgrade": 0,
        "final_decision_before_adjustment": before_final_decision,
        "final_decision_after_adjustment": before_final_decision,
        "confidence_score_before_adjustment": "" if math.isnan(before_conf) else before_conf,
        "confidence_score_after_adjustment": "" if math.isnan(before_conf) else before_conf,
    }
    if not adj:
        out.update(base_meta)
        return out

    total_cases = _safe_int(adj.get("total_cases"), 0)
    if total_cases <= 0:
        out.update(base_meta)
        return out

    open_bias = _clip(_adj_float(adj, "open_bias_adjustment_pct"), -1.5, 1.5)
    close_bias = _clip(_adj_float(adj, "close_bias_adjustment_pct"), -1.5, 1.5)
    atr_adj = _clip(_adj_float(adj, "atr_multiplier_adjustment"), -0.30, 0.50)
    entry_adj = _clip(_adj_float(adj, "entry_adjustment_pct"), -1.2, 0.5)
    stop_adj = _clip(_adj_float(adj, "stop_adjustment_pct"), -1.0, 0.5)
    tp_adj = _clip(_adj_float(adj, "tp_adjustment_pct"), -1.5, 0.5)
    penalty = int(_clip(_safe_int(adj.get("confidence_penalty"), 0), 0, 25))
    downgrade = int(_clip(_safe_int(adj.get("decision_downgrade"), 0), 0, 2))

    for key in ["pred_open_low", "pred_open_mid", "pred_open_high"]:
        out[key] = _apply_pct(out.get(key), open_bias)
    for key in ["pred_close_low", "pred_close_mid", "pred_close_high"]:
        out[key] = _apply_pct(out.get(key), close_bias)

    _widen_range(out, "pred_open_low", "pred_open_mid", "pred_open_high", atr_adj)
    _widen_range(out, "pred_close_low", "pred_close_mid", "pred_close_high", atr_adj)

    out["preferred_entry"] = _apply_pct(out.get("preferred_entry"), entry_adj)
    out["conservative_entry"] = _apply_pct(out.get("conservative_entry"), entry_adj)
    out["stop_loss"] = _apply_pct(out.get("stop_loss"), stop_adj)
    out["take_profit1"] = _apply_pct(out.get("take_profit1"), tp_adj)
    out["take_profit2"] = _apply_pct(out.get("take_profit2"), tp_adj)

    conf = _safe_float(out.get("confidence_score"), math.nan)
    if not math.isnan(conf):
        out["confidence_score"] = int(_clip(conf - penalty, 0, 100))
    after_conf = _safe_float(out.get("confidence_score"), math.nan)

    before_final_decision, after_decision = _downgrade_decision(before_decision, downgrade)
    out["primary_action"] = after_decision

    risk = _safe_float(out.get("preferred_entry"), math.nan) - _safe_float(out.get("stop_loss"), math.nan)
    if not math.isnan(risk) and risk > 0:
        out["rr1"] = (_safe_float(out.get("take_profit1"), math.nan) - _safe_float(out.get("preferred_entry"), math.nan)) / risk

    applied = any(abs(x) >= 0.0001 for x in [open_bias, close_bias, entry_adj, stop_adj, tp_adj, atr_adj]) or penalty > 0 or downgrade > 0
    out.update(
        {
            "adjustment_applied": int(applied),
            "adjustment_reason": str(adj.get("adjustment_reason", "")) or "보정 없음",
            "open_bias_adjustment_pct": open_bias,
            "close_bias_adjustment_pct": close_bias,
            "atr_multiplier_adjustment": atr_adj,
            "entry_adjustment_pct": entry_adj,
            "stop_adjustment_pct": stop_adj,
            "tp_adjustment_pct": tp_adj,
            "confidence_penalty": penalty,
            "decision_downgrade": downgrade,
            "final_decision_before_adjustment": before_final_decision,
            "final_decision_after_adjustment": after_decision,
            "confidence_score_before_adjustment": "" if math.isnan(before_conf) else before_conf,
            "confidence_score_after_adjustment": "" if math.isnan(after_conf) else after_conf,
        }
    )
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(build_prediction_adjustments(), ensure_ascii=False, indent=2))
