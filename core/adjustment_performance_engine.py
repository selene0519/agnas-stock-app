"""Performance comparison for raw, adjusted, and market-filtered predictions."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import PROJECT_ROOT


DATA_DIR = PROJECT_ROOT / "data"
REPORT_FILE = DATA_DIR / "adjustment_performance_report.csv"
SUMMARY_FILE = DATA_DIR / "adjustment_performance_summary.csv"
BY_TICKER_FILE = DATA_DIR / "adjustment_performance_by_ticker.csv"
BY_REGIME_FILE = DATA_DIR / "adjustment_performance_by_market_regime.csv"

REPORT_COLUMNS = [
    "ticker", "market", "prediction_date", "target_date", "actual_direction",
    "raw_predicted_direction", "adjusted_predicted_direction", "market_filtered_direction",
    "raw_direction_hit", "adjusted_direction_hit", "market_filtered_direction_hit",
    "raw_open_mid", "adjusted_open_mid", "actual_open", "raw_open_error_pct", "adjusted_open_error_pct",
    "raw_close_mid", "adjusted_close_mid", "actual_close", "raw_close_error_pct", "adjusted_close_error_pct",
    "raw_final_decision", "adjusted_final_decision", "market_filtered_decision",
    "raw_confidence_score", "adjusted_confidence_score", "market_filtered_confidence_score",
    "preferred_entry", "stop_loss", "take_profit1", "entry_touched", "stop_touched", "tp1_touched",
    "raw_pnl_pct", "adjusted_pnl_pct", "market_filtered_pnl_pct",
    "market_regime", "market_risk_score", "adjustment_applied", "market_filter_applied",
    "improvement_label", "improvement_reason", "created_at",
]

SUMMARY_COLUMNS = [
    "total_cases", "raw_direction_hit_rate", "adjusted_direction_hit_rate", "market_filtered_direction_hit_rate",
    "raw_avg_open_error_pct", "adjusted_avg_open_error_pct", "raw_avg_close_error_pct", "adjusted_avg_close_error_pct",
    "raw_avg_pnl_pct", "adjusted_avg_pnl_pct", "market_filtered_avg_pnl_pct",
    "raw_stop_touch_rate", "adjusted_stop_touch_rate", "raw_tp1_touch_rate", "adjusted_tp1_touch_rate",
    "improved_cases", "worsened_cases", "neutral_cases", "loss_avoided_cases", "missed_opportunity_cases",
    "summary_judgment", "updated_at",
]

BY_TICKER_COLUMNS = [
    "ticker", "market", "total_cases", "raw_direction_hit_rate", "adjusted_direction_hit_rate",
    "direction_hit_rate_change", "raw_avg_open_error_pct", "adjusted_avg_open_error_pct",
    "open_error_improvement", "raw_avg_close_error_pct", "adjusted_avg_close_error_pct",
    "close_error_improvement", "raw_avg_pnl_pct", "adjusted_avg_pnl_pct", "pnl_improvement",
    "stop_touch_rate", "tp1_touch_rate", "improvement_label", "main_improvement_reason", "recommended_action",
]

BY_REGIME_COLUMNS = [
    "market_regime", "total_cases", "raw_direction_hit_rate", "adjusted_direction_hit_rate",
    "market_filtered_direction_hit_rate", "raw_avg_pnl_pct", "adjusted_avg_pnl_pct",
    "market_filtered_avg_pnl_pct", "stop_touch_rate", "tp1_touch_rate",
    "loss_avoided_cases", "missed_opportunity_cases", "recommended_rule_change",
]


def _candidate_path(*parts: str) -> Path:
    data_path = DATA_DIR.joinpath(*parts)
    if data_path.exists():
        return data_path
    root_path = PROJECT_ROOT.joinpath(*parts)
    if root_path.exists():
        return root_path
    decision_path = DATA_DIR.joinpath("decision_system", *parts)
    if decision_path.exists():
        return decision_path
    return root_path


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        return pd.DataFrame()


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        text = str(value if value is not None else "").strip().replace(",", "").replace("%", "")
        if text == "" or text.lower() in {"nan", "none", "nat", "n/a", "na"}:
            return default
        return float(text)
    except Exception:
        return default


def _safe_str(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _normalize_date(value: Any) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    try:
        return str(pd.to_datetime(text).date())
    except Exception:
        return text[:10]


def _normalize_market(value: Any) -> str:
    text = _safe_str(value)
    if text in {"KR", "Korea", "KOSPI", "KOSDAQ", "국장"}:
        return "한국주식"
    if text in {"US", "USA", "미장"}:
        return "미국주식"
    return text


def _normalize_ticker(value: Any, market: Any = "") -> str:
    text = _safe_str(value).upper().replace(".KS", "").replace(".KQ", "")
    if not text:
        return ""
    if _normalize_market(market) == "한국주식" and text.isdigit():
        return text.zfill(6)
    return text


def _first(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index and _safe_str(row.get(name)) != "":
            return row.get(name)
    return default


def _boolish(value: Any) -> bool | None:
    text = _safe_str(value).lower()
    if text in {"1", "1.0", "true", "yes", "y", "hit"}:
        return True
    if text in {"0", "0.0", "false", "no", "n", "miss"}:
        return False
    return None


def _fmt(value: float) -> str:
    return "" if math.isnan(value) else f"{value:.4f}"


def _direction(ref: float, price: float) -> str:
    if math.isnan(ref) or math.isnan(price) or ref == 0:
        return ""
    if price > ref * 1.0005:
        return "up"
    if price < ref * 0.9995:
        return "down"
    return "flat"


def _pct_error(actual: float, pred: float) -> float:
    if math.isnan(actual) or math.isnan(pred) or pred == 0:
        return math.nan
    return (actual / pred - 1) * 100


def _reverse_pct(value: float, pct: float) -> float:
    if math.isnan(value):
        return math.nan
    denom = 1 + pct / 100
    if denom == 0:
        return value
    return value / denom


def _decision_rank(decision: str) -> int:
    text = _safe_str(decision)
    steps = ["손절 우선", "비중 축소 우선", "관망 우위", "눌림목 매수 가능", "돌파 확인 후 접근"]
    for i, step in enumerate(steps):
        if step in text:
            return i
    if "돌파" in text:
        return 4
    if "눌림" in text or "매수" in text or "진입" in text:
        return 3
    if "비중" in text or "축소" in text:
        return 1
    if "손절" in text:
        return 0
    return 2


def _is_buyable(decision: str) -> bool:
    return _decision_rank(decision) >= 3


def _is_watch_or_lower(decision: str) -> bool:
    return _decision_rank(decision) <= 2


def _trade_pnl(decision: str, entry: float, stop: float, tp1: float, actual_close: float, entry_touched: bool | None, stop_touched: bool | None, tp1_touched: bool | None) -> float:
    if not _is_buyable(decision):
        return 0.0
    if math.isnan(entry) or entry <= 0 or math.isnan(actual_close):
        return math.nan
    if entry_touched is False:
        return 0.0
    if stop_touched is True and not math.isnan(stop):
        return (stop / entry - 1) * 100
    if tp1_touched is True and not math.isnan(tp1):
        return (tp1 / entry - 1) * 100
    return (actual_close / entry - 1) * 100


def _hit_rate(series: pd.Series) -> float:
    vals = series.astype(str).str.lower()
    known = vals[vals.isin(["true", "false"])]
    if known.empty:
        return math.nan
    return float((known == "true").mean() * 100)


def _mean_abs(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return math.nan
    return float(vals.abs().mean())


def _mean(series: pd.Series) -> float:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if vals.empty:
        return math.nan
    return float(vals.mean())


def _actual_lookup(actual: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, Any]]:
    if actual.empty:
        return {}
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    for _, row in actual.iterrows():
        market = _normalize_market(_first(row, ["market", "시장"]))
        ticker = _normalize_ticker(_first(row, ["ticker", "symbol", "종목"]), market)
        actual_date = _normalize_date(_first(row, ["date", "actual_date", "target_date", "목표일"]))
        if not actual_date or not ticker:
            continue
        lookup[(actual_date, market, ticker)] = {
            "actual_date": actual_date,
            "actual_open": _first(row, ["open", "actual_open", "실제시초가"]),
            "actual_high": _first(row, ["high", "actual_high", "실제고가"]),
            "actual_low": _first(row, ["low", "actual_low", "실제저가"]),
            "actual_close": _first(row, ["close", "actual_close", "실제종가"]),
            "actual_volume": _first(row, ["volume", "actual_volume"]),
            "actual_direction": _first(row, ["actual_direction"]),
            "actual_source": "data/decision_system/actual_results.csv",
        }
    return lookup


def _merge_actual_results(pred: pd.DataFrame, actual: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if pred.empty:
        return pred, 0
    lookup = _actual_lookup(actual)
    if not lookup:
        return pred.copy(), 0
    out = pred.copy()
    for col in ["actual_date", "actual_open", "actual_high", "actual_low", "actual_close", "actual_volume", "actual_direction", "actual_source"]:
        if col not in out.columns:
            out[col] = ""
    matched = 0
    for idx, row in out.iterrows():
        market = _normalize_market(_first(row, ["market", "시장"]))
        ticker = _normalize_ticker(_first(row, ["ticker", "symbol", "종목"]), market)
        target = _normalize_date(_first(row, ["target_date", "actual_date", "date", "목표일"]))
        if not target or not ticker:
            continue
        actual_row = lookup.get((target, market, ticker))
        if not actual_row:
            continue
        matched += 1
        for col, value in actual_row.items():
            if col == "actual_source" and _safe_str(row.get(col)):
                continue
            if col == "actual_date" or _safe_str(row.get(col)) == "":
                out.loc[idx, col] = value
    return out, matched


def _report_row(row: pd.Series) -> dict[str, Any]:
    market = _normalize_market(_first(row, ["market", "시장"]))
    ticker = _normalize_ticker(_first(row, ["ticker", "symbol", "종목"]), market)
    created = _safe_str(_first(row, ["created_at", "prediction_date", "생성일"]))
    target = _normalize_date(_first(row, ["target_date", "actual_date", "목표일"]))
    prev = _safe_float(_first(row, ["prev_close", "previous_close"]))
    actual_open = _safe_float(_first(row, ["actual_open", "실제시초가"]))
    actual_close = _safe_float(_first(row, ["actual_close", "실제종가"]))
    actual_high = _safe_float(_first(row, ["actual_high", "실제고가"]))
    actual_low = _safe_float(_first(row, ["actual_low", "실제저가"]))

    adjusted_open = _safe_float(_first(row, ["pred_open_mid", "predicted_open_mid", "predicted_open"]))
    adjusted_close = _safe_float(_first(row, ["pred_close_mid", "predicted_close_mid", "predicted_close"]))
    open_adj = _safe_float(_first(row, ["open_bias_adjustment_pct"]), 0.0)
    close_adj = _safe_float(_first(row, ["close_bias_adjustment_pct"]), 0.0)
    raw_open = _reverse_pct(adjusted_open, open_adj)
    raw_close = _reverse_pct(adjusted_close, close_adj)

    actual_dir = _safe_str(_first(row, ["actual_direction"]))
    if not actual_dir:
        actual_dir = _direction(prev, actual_close) or _direction(actual_open, actual_close)
    raw_dir = _direction(prev, raw_close) or _direction(raw_open, raw_close)
    adjusted_dir = _direction(prev, adjusted_close) or _direction(adjusted_open, adjusted_close)
    market_dir = adjusted_dir

    raw_hit = bool(raw_dir == actual_dir) if raw_dir and actual_dir else None
    adjusted_hit = bool(adjusted_dir == actual_dir) if adjusted_dir and actual_dir else None
    market_hit = adjusted_hit

    raw_open_err = _pct_error(actual_open, raw_open)
    adjusted_open_err = _pct_error(actual_open, adjusted_open)
    raw_close_err = _pct_error(actual_close, raw_close)
    adjusted_close_err = _pct_error(actual_close, adjusted_close)

    raw_decision = _safe_str(_first(row, ["final_decision_before_adjustment", "raw_final_decision", "final_decision", "primary_action"]))
    adjusted_decision = _safe_str(_first(row, ["final_decision_before_market_filter", "final_decision_after_adjustment", "primary_action"]))
    market_decision = _safe_str(_first(row, ["final_decision_after_market_filter", "primary_action"]))

    raw_conf = _safe_float(_first(row, ["confidence_score_before_adjustment", "raw_confidence_score", "confidence_score"]))
    adjusted_conf = _safe_float(_first(row, ["confidence_score_before_market_filter", "confidence_score_after_adjustment", "confidence_score"]))
    market_conf = _safe_float(_first(row, ["confidence_score_after_market_filter", "confidence_score"]))

    entry = _safe_float(_first(row, ["preferred_entry", "entry_price", "우선진입가"]))
    stop = _safe_float(_first(row, ["stop_loss", "손절가"]))
    tp1 = _safe_float(_first(row, ["take_profit1", "target_price", "1차익절가"]))
    entry_t = _boolish(_first(row, ["entry_touched"]))
    stop_t = _boolish(_first(row, ["stop_touched"]))
    tp1_t = _boolish(_first(row, ["tp1_touched"]))

    raw_pnl = _trade_pnl(raw_decision, entry, stop, tp1, actual_close, entry_t, stop_t, tp1_t)
    adj_pnl = _trade_pnl(adjusted_decision, entry, stop, tp1, actual_close, entry_t, stop_t, tp1_t)
    mkt_pnl = _trade_pnl(market_decision, entry, stop, tp1, actual_close, entry_t, stop_t, tp1_t)

    market_filter_applied = _boolish(_first(row, ["market_filter_applied"]))
    adjustment_applied = _boolish(_first(row, ["adjustment_applied"]))
    regime = _safe_str(_first(row, ["market_regime"])) or "미분류"
    risk = _safe_float(_first(row, ["market_risk_score"]), 50)

    label, reason = _improvement_label(
        raw_hit, adjusted_hit, raw_open_err, adjusted_open_err, raw_close_err, adjusted_close_err,
        raw_pnl, adj_pnl, mkt_pnl, raw_decision, market_decision, market_filter_applied,
        actual_close, prev, stop_t, tp1_t,
    )

    return {
        "ticker": ticker, "market": market, "prediction_date": created[:10], "target_date": target,
        "actual_direction": actual_dir, "raw_predicted_direction": raw_dir,
        "adjusted_predicted_direction": adjusted_dir, "market_filtered_direction": market_dir,
        "raw_direction_hit": "" if raw_hit is None else str(raw_hit),
        "adjusted_direction_hit": "" if adjusted_hit is None else str(adjusted_hit),
        "market_filtered_direction_hit": "" if market_hit is None else str(market_hit),
        "raw_open_mid": _fmt(raw_open), "adjusted_open_mid": _fmt(adjusted_open), "actual_open": _fmt(actual_open),
        "raw_open_error_pct": _fmt(raw_open_err), "adjusted_open_error_pct": _fmt(adjusted_open_err),
        "raw_close_mid": _fmt(raw_close), "adjusted_close_mid": _fmt(adjusted_close), "actual_close": _fmt(actual_close),
        "raw_close_error_pct": _fmt(raw_close_err), "adjusted_close_error_pct": _fmt(adjusted_close_err),
        "raw_final_decision": raw_decision, "adjusted_final_decision": adjusted_decision, "market_filtered_decision": market_decision,
        "raw_confidence_score": _fmt(raw_conf), "adjusted_confidence_score": _fmt(adjusted_conf), "market_filtered_confidence_score": _fmt(market_conf),
        "preferred_entry": _fmt(entry), "stop_loss": _fmt(stop), "take_profit1": _fmt(tp1),
        "entry_touched": "" if entry_t is None else str(entry_t), "stop_touched": "" if stop_t is None else str(stop_t), "tp1_touched": "" if tp1_t is None else str(tp1_t),
        "raw_pnl_pct": _fmt(raw_pnl), "adjusted_pnl_pct": _fmt(adj_pnl), "market_filtered_pnl_pct": _fmt(mkt_pnl),
        "market_regime": regime, "market_risk_score": _fmt(risk),
        "adjustment_applied": "" if adjustment_applied is None else str(adjustment_applied),
        "market_filter_applied": "" if market_filter_applied is None else str(market_filter_applied),
        "improvement_label": label, "improvement_reason": reason,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _improvement_label(raw_hit, adjusted_hit, raw_open_err, adj_open_err, raw_close_err, adj_close_err, raw_pnl, adj_pnl, mkt_pnl, raw_decision, market_decision, market_filter_applied, actual_close, prev, stop_t, tp1_t) -> tuple[str, str]:
    if math.isnan(actual_close):
        return "실제 결과 대기", "실제 OHLC 데이터 부족 또는 아직 미반영"
    reasons: list[str] = []
    score = 0
    if raw_hit is False and adjusted_hit is True:
        score += 2; reasons.append("보정 후 방향 적중 개선")
    elif raw_hit is True and adjusted_hit is False:
        score -= 2; reasons.append("보정 후 방향 적중 악화")
    if not math.isnan(raw_open_err) and not math.isnan(adj_open_err):
        if abs(adj_open_err) + 0.05 < abs(raw_open_err):
            score += 1; reasons.append("보정 후 시초가 오차 감소")
        elif abs(adj_open_err) > abs(raw_open_err) + 0.2:
            score -= 1; reasons.append("보정 후 시초가 오차 증가")
    if not math.isnan(raw_close_err) and not math.isnan(adj_close_err):
        if abs(adj_close_err) + 0.05 < abs(raw_close_err):
            score += 1; reasons.append("보정 후 종가 오차 감소")
        elif abs(adj_close_err) > abs(raw_close_err) + 0.2:
            score -= 1; reasons.append("보정 후 종가 오차 증가")
    if not math.isnan(raw_pnl) and not math.isnan(adj_pnl):
        if adj_pnl > raw_pnl + 0.1:
            score += 1; reasons.append("보정 후 손익 개선")
        elif adj_pnl < raw_pnl - 0.1:
            score -= 1; reasons.append("보정 후 손익 악화")
    loss_avoided = _loss_avoided(raw_decision, market_decision, market_filter_applied, adj_pnl, stop_t)
    missed = _missed_opportunity(raw_decision, market_decision, market_filter_applied, actual_close, prev, tp1_t)
    if loss_avoided:
        return "손실 회피", "시장 필터로 급락장/이벤트장 매수 회피"
    if missed:
        return "기회 손실", "시장 필터가 상승 기회를 과도하게 차단"
    if score > 0:
        return "개선", " / ".join(reasons)
    if score < 0:
        return "악화", " / ".join(reasons)
    return "중립", "변화 미미"


def _loss_avoided(before: str, after: str, applied: bool | None, pnl: float, stop_t: bool | None) -> bool:
    return bool(applied is True and _is_buyable(before) and _is_watch_or_lower(after) and ((not math.isnan(pnl) and pnl < 0) or stop_t is True))


def _missed_opportunity(before: str, after: str, applied: bool | None, actual_close: float, prev: float, tp1_t: bool | None) -> bool:
    close_up = (not math.isnan(actual_close) and not math.isnan(prev) and prev > 0 and actual_close > prev * 1.01)
    return bool(applied is True and _is_buyable(before) and _is_watch_or_lower(after) and (tp1_t is True or close_up))


def _build_report(pred: pd.DataFrame, actual: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if pred.empty:
        return pd.DataFrame(columns=REPORT_COLUMNS), 0
    pred, matched = _merge_actual_results(pred, actual)
    rows = []
    for _, row in pred.iterrows():
        rows.append(_report_row(row))
    return pd.DataFrame(rows, columns=REPORT_COLUMNS), matched


def _summary_judgment(row: dict[str, Any]) -> str:
    total = int(_safe_float(row.get("total_cases"), 0))
    if total < 5:
        return "데이터 부족"
    improved = int(_safe_float(row.get("improved_cases"), 0)) + int(_safe_float(row.get("loss_avoided_cases"), 0))
    worsened = int(_safe_float(row.get("worsened_cases"), 0)) + int(_safe_float(row.get("missed_opportunity_cases"), 0))
    raw_pnl = _safe_float(row.get("raw_avg_pnl_pct"), math.nan)
    adj_pnl = _safe_float(row.get("adjusted_avg_pnl_pct"), math.nan)
    if worsened > improved and not math.isnan(adj_pnl) and not math.isnan(raw_pnl) and adj_pnl < raw_pnl:
        return "보정 후 성과 악화"
    if improved > worsened:
        return "보정 효과 양호"
    return "보정 효과 제한적"


def _build_summary(report: pd.DataFrame) -> pd.DataFrame:
    completed = report[pd.to_numeric(report.get("actual_close", ""), errors="coerce").notna()].copy() if not report.empty else report
    if completed.empty:
        row = {c: "" for c in SUMMARY_COLUMNS}
        row.update({"total_cases": 0, "summary_judgment": "데이터 부족", "updated_at": datetime.now().isoformat(timespec="seconds")})
        return pd.DataFrame([row], columns=SUMMARY_COLUMNS)
    report = completed
    row = {
        "total_cases": len(report),
        "raw_direction_hit_rate": _fmt(_hit_rate(report["raw_direction_hit"])),
        "adjusted_direction_hit_rate": _fmt(_hit_rate(report["adjusted_direction_hit"])),
        "market_filtered_direction_hit_rate": _fmt(_hit_rate(report["market_filtered_direction_hit"])),
        "raw_avg_open_error_pct": _fmt(_mean_abs(report["raw_open_error_pct"])),
        "adjusted_avg_open_error_pct": _fmt(_mean_abs(report["adjusted_open_error_pct"])),
        "raw_avg_close_error_pct": _fmt(_mean_abs(report["raw_close_error_pct"])),
        "adjusted_avg_close_error_pct": _fmt(_mean_abs(report["adjusted_close_error_pct"])),
        "raw_avg_pnl_pct": _fmt(_mean(report["raw_pnl_pct"])),
        "adjusted_avg_pnl_pct": _fmt(_mean(report["adjusted_pnl_pct"])),
        "market_filtered_avg_pnl_pct": _fmt(_mean(report["market_filtered_pnl_pct"])),
        "raw_stop_touch_rate": _fmt(_hit_rate(report["stop_touched"])),
        "adjusted_stop_touch_rate": _fmt(_hit_rate(report["stop_touched"])),
        "raw_tp1_touch_rate": _fmt(_hit_rate(report["tp1_touched"])),
        "adjusted_tp1_touch_rate": _fmt(_hit_rate(report["tp1_touched"])),
        "improved_cases": int(report["improvement_label"].isin(["개선", "손실 회피"]).sum()),
        "worsened_cases": int(report["improvement_label"].isin(["악화", "기회 손실"]).sum()),
        "neutral_cases": int(report["improvement_label"].eq("중립").sum()),
        "loss_avoided_cases": int(report["improvement_label"].eq("손실 회피").sum()),
        "missed_opportunity_cases": int(report["improvement_label"].eq("기회 손실").sum()),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    row["summary_judgment"] = _summary_judgment(row)
    return pd.DataFrame([row], columns=SUMMARY_COLUMNS)


def _build_by_ticker(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return pd.DataFrame(columns=BY_TICKER_COLUMNS)
    report = report[pd.to_numeric(report.get("actual_close", ""), errors="coerce").notna()].copy()
    if report.empty:
        return pd.DataFrame(columns=BY_TICKER_COLUMNS)
    rows = []
    for (ticker, market), g in report.groupby(["ticker", "market"], dropna=False):
        raw_hit = _hit_rate(g["raw_direction_hit"])
        adj_hit = _hit_rate(g["adjusted_direction_hit"])
        raw_open = _mean_abs(g["raw_open_error_pct"])
        adj_open = _mean_abs(g["adjusted_open_error_pct"])
        raw_close = _mean_abs(g["raw_close_error_pct"])
        adj_close = _mean_abs(g["adjusted_close_error_pct"])
        raw_pnl = _mean(g["raw_pnl_pct"])
        adj_pnl = _mean(g["adjusted_pnl_pct"])
        pnl_imp = adj_pnl - raw_pnl if not math.isnan(adj_pnl) and not math.isnan(raw_pnl) else math.nan
        label_counts = g["improvement_label"].value_counts()
        main_label = str(label_counts.index[0]) if not label_counts.empty else "데이터 부족"
        if len(g) < 3:
            action = "데이터 부족"
        elif not math.isnan(pnl_imp) and pnl_imp > 0.2:
            action = "보정 유지"
        elif not math.isnan(pnl_imp) and pnl_imp < -0.2:
            action = "보정 약화 필요"
        elif _hit_rate(g["stop_touched"]) >= 50:
            action = "매수금지 조건 검토"
        else:
            action = "보정 강화 필요"
        rows.append({
            "ticker": ticker, "market": market, "total_cases": len(g),
            "raw_direction_hit_rate": _fmt(raw_hit), "adjusted_direction_hit_rate": _fmt(adj_hit),
            "direction_hit_rate_change": _fmt(adj_hit - raw_hit if not math.isnan(adj_hit) and not math.isnan(raw_hit) else math.nan),
            "raw_avg_open_error_pct": _fmt(raw_open), "adjusted_avg_open_error_pct": _fmt(adj_open),
            "open_error_improvement": _fmt(raw_open - adj_open if not math.isnan(raw_open) and not math.isnan(adj_open) else math.nan),
            "raw_avg_close_error_pct": _fmt(raw_close), "adjusted_avg_close_error_pct": _fmt(adj_close),
            "close_error_improvement": _fmt(raw_close - adj_close if not math.isnan(raw_close) and not math.isnan(adj_close) else math.nan),
            "raw_avg_pnl_pct": _fmt(raw_pnl), "adjusted_avg_pnl_pct": _fmt(adj_pnl),
            "pnl_improvement": _fmt(pnl_imp), "stop_touch_rate": _fmt(_hit_rate(g["stop_touched"])),
            "tp1_touch_rate": _fmt(_hit_rate(g["tp1_touched"])), "improvement_label": main_label,
            "main_improvement_reason": str(g["improvement_reason"].mode().iloc[0]) if not g["improvement_reason"].mode().empty else "",
            "recommended_action": action,
        })
    return pd.DataFrame(rows, columns=BY_TICKER_COLUMNS)


def _build_by_regime(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return pd.DataFrame(columns=BY_REGIME_COLUMNS)
    report = report[pd.to_numeric(report.get("actual_close", ""), errors="coerce").notna()].copy()
    if report.empty:
        return pd.DataFrame(columns=BY_REGIME_COLUMNS)
    rows = []
    for regime, g in report.groupby("market_regime", dropna=False):
        raw_pnl = _mean(g["raw_pnl_pct"])
        adj_pnl = _mean(g["adjusted_pnl_pct"])
        mkt_pnl = _mean(g["market_filtered_pnl_pct"])
        loss = int(g["improvement_label"].eq("손실 회피").sum())
        missed = int(g["improvement_label"].eq("기회 손실").sum())
        if len(g) < 3:
            rec = "데이터 부족"
        elif "급락" in str(regime) and loss >= missed:
            rec = "급락장 필터 유지"
        elif "급락" in str(regime):
            rec = "급락장 필터 강화"
        elif "이벤트" in str(regime) and missed > loss:
            rec = "이벤트장 신뢰도 차감 완화"
        elif "이벤트" in str(regime):
            rec = "이벤트장 신뢰도 차감 강화"
        elif "상승" in str(regime):
            rec = "상승장 필터 완화"
        else:
            rec = "현행 유지"
        rows.append({
            "market_regime": regime or "미분류", "total_cases": len(g),
            "raw_direction_hit_rate": _fmt(_hit_rate(g["raw_direction_hit"])),
            "adjusted_direction_hit_rate": _fmt(_hit_rate(g["adjusted_direction_hit"])),
            "market_filtered_direction_hit_rate": _fmt(_hit_rate(g["market_filtered_direction_hit"])),
            "raw_avg_pnl_pct": _fmt(raw_pnl), "adjusted_avg_pnl_pct": _fmt(adj_pnl),
            "market_filtered_avg_pnl_pct": _fmt(mkt_pnl),
            "stop_touch_rate": _fmt(_hit_rate(g["stop_touched"])), "tp1_touch_rate": _fmt(_hit_rate(g["tp1_touched"])),
            "loss_avoided_cases": loss, "missed_opportunity_cases": missed, "recommended_rule_change": rec,
        })
    return pd.DataFrame(rows, columns=BY_REGIME_COLUMNS)


def run_adjustment_performance() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    pred = _read_csv(_candidate_path("predictions.csv"))
    actual = _read_csv(_candidate_path("actual_results.csv"))
    trades = _read_csv(_candidate_path("trade_simulations.csv"))
    error_report = _read_csv(_candidate_path("prediction_error_report.csv"))
    adjustments = _read_csv(_candidate_path("prediction_adjustments.csv"))
    regime_history = _read_csv(_candidate_path("market_regime_history.csv"))
    report, matched_actual_rows = _build_report(pred, actual)
    summary = _build_summary(report)
    by_ticker = _build_by_ticker(report)
    by_regime = _build_by_regime(report)

    report.to_csv(REPORT_FILE, index=False, encoding="utf-8-sig")
    summary.to_csv(SUMMARY_FILE, index=False, encoding="utf-8-sig")
    by_ticker.to_csv(BY_TICKER_FILE, index=False, encoding="utf-8-sig")
    by_regime.to_csv(BY_REGIME_FILE, index=False, encoding="utf-8-sig")
    return {
        "ok": True,
        "report_rows": int(len(report)),
        "summary_rows": int(len(summary)),
        "by_ticker_rows": int(len(by_ticker)),
        "by_regime_rows": int(len(by_regime)),
        "input_rows": {
            "predictions": int(len(pred)),
            "actual_results": int(len(actual)),
            "trade_simulations": int(len(trades)),
            "prediction_error_report": int(len(error_report)),
            "prediction_adjustments": int(len(adjustments)),
            "market_regime_history": int(len(regime_history)),
            "matched_actual_rows": int(matched_actual_rows),
        },
        "files": {
            "report": str(REPORT_FILE.relative_to(PROJECT_ROOT)),
            "summary": str(SUMMARY_FILE.relative_to(PROJECT_ROOT)),
            "by_ticker": str(BY_TICKER_FILE.relative_to(PROJECT_ROOT)),
            "by_regime": str(BY_REGIME_FILE.relative_to(PROJECT_ROOT)),
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_adjustment_performance(), ensure_ascii=False, indent=2))
