"""Prediction failure review reports for the stock app.

This module is intentionally read-only with respect to prediction logic. It
compares saved predictions, actual OHLC results, and trade simulations, then
emits review CSVs that can be used to tune later rules.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import ACTUAL_RESULTS, LEGACY_PREDICTIONS, TRADE_SIMULATIONS, PROJECT_ROOT


REPORT_DIR = PROJECT_ROOT / "data"
PREDICTION_ERROR_REPORT = REPORT_DIR / "prediction_error_report.csv"
TICKER_ERROR_PROFILE = REPORT_DIR / "ticker_error_profile.csv"
MARKET_CONDITION_ERROR_SUMMARY = REPORT_DIR / "market_condition_error_summary.csv"


REPORT_COLUMNS = [
    "ticker",
    "market",
    "prediction_date",
    "target_date",
    "market_condition",
    "predicted_direction",
    "actual_direction",
    "direction_hit",
    "predicted_open_mid",
    "actual_open",
    "open_error_pct",
    "predicted_close_mid",
    "predicted_close_range",
    "actual_close",
    "close_error_pct",
    "actual_high",
    "actual_low",
    "preferred_entry",
    "stop_loss",
    "take_profit1",
    "entry_touched",
    "stop_touched",
    "tp1_touched",
    "final_decision",
    "decision_result",
    "failure_reason",
    "suggested_adjustment",
    "final_pnl_pct",
]


PROFILE_COLUMNS = [
    "market",
    "ticker",
    "total_cases",
    "direction_hit_rate",
    "avg_open_error_pct",
    "avg_close_error_pct",
    "entry_touch_rate",
    "stop_touch_rate",
    "tp1_touch_rate",
    "avg_final_pnl_pct",
    "main_failure_reason",
    "recommended_atr_adjustment",
    "recommended_entry_adjustment",
    "recommended_tp_adjustment",
    "recommended_confidence_penalty",
]


MARKET_COLUMNS = [
    "market_condition",
    "total_cases",
    "direction_hit_rate",
    "avg_open_error_pct",
    "avg_close_error_pct",
    "stop_touch_rate",
    "tp1_touch_rate",
    "avg_pnl",
    "recommended_rule_change",
]


def _read_csv(path: Path) -> pd.DataFrame:
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
        text = str(value).strip().replace(",", "")
        if text == "" or text.lower() in {"nan", "none", "nat", "n/a", "na"}:
            return default
        return float(text)
    except Exception:
        return default


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "nat"}:
        return ""
    return text


def _first(row: pd.Series, names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in row.index:
            val = row.get(name)
            if _safe_str(val) != "":
                return val
    return default


def _date10(value: Any) -> str:
    text = _safe_str(value)
    return text[:10] if len(text) >= 10 else text


def _ticker_key(ticker: Any) -> str:
    text = _safe_str(ticker).upper()
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit() and len(text) < 6:
        return text.zfill(6)
    return text


def _truthy(value: Any) -> bool | None:
    text = _safe_str(value).lower()
    if text in {"true", "1", "yes", "y", "hit", "성공", "도달"}:
        return True
    if text in {"false", "0", "no", "n", "miss", "실패", "미도달"}:
        return False
    return None


def _direction(prev_close: float, price: float) -> str:
    if math.isnan(prev_close) or math.isnan(price) or prev_close == 0:
        return ""
    if price > prev_close * 1.0005:
        return "up"
    if price < prev_close * 0.9995:
        return "down"
    return "flat"


def _pct_error(actual: float, predicted: float) -> float:
    if math.isnan(actual) or math.isnan(predicted) or predicted == 0:
        return math.nan
    return (actual - predicted) / predicted * 100


def _pct_out(value: float) -> str:
    if math.isnan(value):
        return ""
    return f"{value:.4f}"


def _bool_out(value: bool | None) -> str:
    if value is True:
        return "True"
    if value is False:
        return "False"
    return ""


def _build_actual_lookup(actual_df: pd.DataFrame) -> dict[tuple[str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str], dict[str, Any]] = {}
    if actual_df.empty:
        return lookup
    for _, row in actual_df.iterrows():
        market = _safe_str(row.get("market"))
        ticker = _ticker_key(row.get("ticker"))
        date = _date10(row.get("date") or row.get("actual_date"))
        if market and ticker and date:
            lookup[(market, ticker, date)] = row.to_dict()
    return lookup


def _build_trade_lookup(trade_df: pd.DataFrame) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    by_pid: dict[str, dict[str, Any]] = {}
    by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    if trade_df.empty:
        return by_pid, by_key
    for _, row in trade_df.iterrows():
        pid = _safe_str(row.get("prediction_id"))
        if pid:
            by_pid[pid] = row.to_dict()
        market = _safe_str(row.get("market"))
        ticker = _ticker_key(row.get("ticker"))
        date = _date10(row.get("date") or row.get("target_date"))
        if market and ticker and date:
            by_key[(market, ticker, date)] = row.to_dict()
    return by_pid, by_key


def _market_condition(row: pd.Series) -> str:
    raw = _safe_str(_first(row, ["market_condition", "session_label", "range_quality_label", "confidence_label"]))
    market_score = _safe_float(_first(row, ["market_score", "auto_market_score"]))
    risk_mult = _safe_float(_first(row, ["event_risk_mult", "earnings_risk_mult"]))
    event_label = _safe_str(_first(row, ["event_label", "news_impact_label", "earnings_event_phase"]))
    if not math.isnan(market_score):
        if market_score <= -0.5:
            base = "market_score_negative"
        elif market_score >= 0.5:
            base = "market_score_positive"
        else:
            base = "market_score_neutral"
    else:
        base = raw or "unknown"
    if not math.isnan(risk_mult) and risk_mult >= 1.5:
        return f"{base}|event_high"
    if event_label:
        return f"{base}|{event_label[:30]}"
    return base


def _decision_is_buyish(text: str) -> bool:
    return any(x in text for x in ["매수", "진입", "돌파", "눌림", "우선", "buy", "entry"])


def _decision_is_watch(text: str) -> bool:
    return any(x in text for x in ["관망", "제외", "금지", "보류", "watch", "hold", "avoid"])


def _failure_reasons(
    row: pd.Series,
    pred_open_low: float,
    pred_open_high: float,
    actual_open: float,
    actual_high: float,
    actual_low: float,
    preferred_entry: float,
    stop_loss: float,
    take_profit1: float,
    direction_hit: bool | None,
    entry_touched: bool | None,
    stop_touched: bool | None,
    tp1_touched: bool | None,
    final_decision: str,
) -> str:
    if any(math.isnan(x) for x in [actual_open, actual_high, actual_low]) or (
        math.isnan(_safe_float(_first(row, ["pred_open_mid"])))
        and math.isnan(_safe_float(_first(row, ["pred_close_mid"])))
    ):
        return "데이터 부족"

    reasons: list[str] = []
    market_score = _safe_float(_first(row, ["market_score", "auto_market_score"]))
    risk_mult = _safe_float(_first(row, ["event_risk_mult", "earnings_risk_mult"]))
    event_text = " ".join(
        _safe_str(_first(row, [name]))
        for name in ["event_label", "news_impact_label", "post_prediction_event_policy", "no_buy_flags"]
    )
    buyish = _decision_is_buyish(final_decision.lower())

    if not math.isnan(market_score) and market_score < 0 and buyish:
        reasons.append("시장 급락 미반영")
    if not math.isnan(pred_open_low) and actual_open < pred_open_low * 0.995:
        reasons.append("갭하락 과소평가")
    if not math.isnan(pred_open_high) and actual_open > pred_open_high * 1.005:
        reasons.append("갭상승 과소평가")
    if stop_touched is True and tp1_touched is not True:
        reasons.append("손절선 과다 터치")
    if buyish and tp1_touched is False:
        reasons.append("익절 목표 과도")
    if entry_touched is False and not math.isnan(preferred_entry):
        reasons.append("진입가 비현실적")
    if direction_hit is False:
        reasons.append("방향 예측 실패")
    if (not math.isnan(risk_mult) and risk_mult >= 1.5) or any(x in event_text.lower() for x in ["event", "earnings", "fomc", "cpi", "실적", "이벤트"]):
        if stop_touched is True or direction_hit is False or tp1_touched is False:
            reasons.append("이벤트 변동성 미반영")

    existing = _safe_str(_first(row, ["prediction_error_reason", "auto_failure_tags", "failure_tags"]))
    if existing and not reasons:
        reasons.append(existing[:120])
    if not reasons:
        reasons.append("정상 범위")
    return " / ".join(dict.fromkeys(reasons))


def _suggest_adjustment(reason: str) -> str:
    if reason == "정상 범위":
        return "현행 규칙 유지"
    rules = []
    if "시장 급락" in reason:
        rules.append("market_score 음수 구간은 매수 판단을 한 단계 낮추기")
    if "갭하락" in reason or "갭상승" in reason:
        rules.append("시초가 예측 범위와 ATR 배수를 확대하고 장전 이벤트 가중치 상향")
    if "손절선 과다" in reason:
        rules.append("손절선을 ATR/지지선 기준으로 재보정하거나 진입가를 낮추기")
    if "익절 목표 과도" in reason:
        rules.append("1차 목표가를 보수화하고 분할익절 기준을 낮추기")
    if "진입가 비현실적" in reason:
        rules.append("preferred_entry를 실제 지지권/최근 저가 범위 안으로 제한")
    if "방향 예측 실패" in reason:
        rules.append("시장·섹터·뉴스 점수의 방향 가중치를 재점검")
    if "이벤트 변동성" in reason:
        rules.append("고위험 이벤트 날은 신뢰도 감점과 관망 필터 강화")
    if "데이터 부족" in reason:
        rules.append("누락 컬럼은 N/A 처리하고 실제 OHLC 업데이트 완료 후 재분석")
    return " / ".join(dict.fromkeys(rules)) if rules else "실패 유형별 표본 추가 수집"


def _decision_result(final_decision: str, entry_touched: bool | None, stop_touched: bool | None, tp1_touched: bool | None, final_pnl: float, direction_hit: bool | None) -> str:
    text = final_decision.lower()
    buyish = _decision_is_buyish(text)
    watch = _decision_is_watch(text)
    if entry_touched is None and stop_touched is None and tp1_touched is None and math.isnan(final_pnl):
        return "DATA_MISSING"
    if buyish:
        if entry_touched is False:
            return "미체결"
        if stop_touched is True and tp1_touched is not True:
            return "손절 실패"
        if tp1_touched is True:
            return "익절 유효"
        if not math.isnan(final_pnl) and final_pnl > 0:
            return "수익 유효"
        if not math.isnan(final_pnl) and final_pnl < 0:
            return "손실"
        return "보유/추적"
    if watch:
        if tp1_touched is True or (not math.isnan(final_pnl) and final_pnl > 1):
            return "기회 손실"
        if stop_touched is True or direction_hit is False:
            return "관망 유효"
        return "관망 유지"
    if stop_touched is True:
        return "위험 확인"
    if tp1_touched is True:
        return "상승 확인"
    return "평가 보류"


def _analysis_rows(pred_df: pd.DataFrame, actual_df: pd.DataFrame, trade_df: pd.DataFrame) -> pd.DataFrame:
    actual_lookup = _build_actual_lookup(actual_df)
    trade_by_pid, trade_by_key = _build_trade_lookup(trade_df)
    rows: list[dict[str, Any]] = []

    for _, src in pred_df.iterrows():
        pid = _safe_str(src.get("prediction_id"))
        market = _safe_str(src.get("market"))
        ticker = _safe_str(src.get("ticker") or src.get("symbol"))
        target_date = _date10(src.get("target_date") or src.get("actual_date") or src.get("date"))
        key = (market, _ticker_key(ticker), target_date)
        actual = actual_lookup.get(key, {})
        trade = trade_by_pid.get(pid, {}) if pid else {}
        if not trade:
            trade = trade_by_key.get(key, {})

        prev_close = _safe_float(_first(src, ["prev_close", "close_prev"]))
        pred_open_low = _safe_float(_first(src, ["pred_open_low", "predicted_open_low"]))
        pred_open_mid = _safe_float(_first(src, ["pred_open_mid", "predicted_open_mid", "predicted_open"]))
        pred_open_high = _safe_float(_first(src, ["pred_open_high", "predicted_open_high"]))
        pred_close_low = _safe_float(_first(src, ["pred_close_low", "predicted_close_low"]))
        pred_close_mid = _safe_float(_first(src, ["pred_close_mid", "predicted_close_mid", "predicted_close"]))
        pred_close_high = _safe_float(_first(src, ["pred_close_high", "predicted_close_high"]))

        actual_open = _safe_float(_first(src, ["actual_open"], actual.get("open", "")))
        actual_high = _safe_float(_first(src, ["actual_high"], actual.get("high", "")))
        actual_low = _safe_float(_first(src, ["actual_low"], actual.get("low", "")))
        actual_close = _safe_float(_first(src, ["actual_close"], actual.get("close", "")))
        actual_direction = _safe_str(actual.get("actual_direction")) or _direction(prev_close, actual_close)
        if not actual_direction:
            actual_direction = _direction(actual_open, actual_close)
        predicted_direction = _direction(prev_close, pred_close_mid)
        if not predicted_direction:
            predicted_direction = _direction(pred_open_mid, pred_close_mid)

        direction_hit = _truthy(src.get("direction_hit"))
        if direction_hit is None and predicted_direction and actual_direction:
            direction_hit = predicted_direction == actual_direction

        open_error = _safe_float(src.get("open_error_pct"))
        if math.isnan(open_error):
            open_error = _pct_error(actual_open, pred_open_mid)
        close_error = _safe_float(src.get("close_error_pct"))
        if math.isnan(close_error):
            close_error = _pct_error(actual_close, pred_close_mid)

        preferred_entry = _safe_float(_first(src, ["preferred_entry", "priority_entry"], trade.get("simulated_entry", "")))
        stop_loss = _safe_float(_first(src, ["stop_loss"], trade.get("stop_loss", "")))
        take_profit1 = _safe_float(_first(src, ["take_profit1", "target_price"], trade.get("target_price", "")))

        entry_touched = _truthy(_first(src, ["entry_touched"], ""))
        if entry_touched is None and not any(math.isnan(x) for x in [preferred_entry, actual_low, actual_high]):
            entry_touched = actual_low <= preferred_entry <= actual_high
        stop_touched = _truthy(_first(src, ["stop_touched"], trade.get("stop_triggered", "")))
        if stop_touched is None and not any(math.isnan(x) for x in [stop_loss, actual_low]):
            stop_touched = actual_low <= stop_loss
        tp1_touched = _truthy(_first(src, ["tp1_touched"], trade.get("target_triggered", "")))
        if tp1_touched is None and not any(math.isnan(x) for x in [take_profit1, actual_high]):
            tp1_touched = actual_high >= take_profit1

        final_decision = _safe_str(
            _first(src, ["final_decision", "primary_action", "technical_verdict"], trade.get("decision", ""))
        )
        final_pnl = _safe_float(_first(src, ["virtual_net_return_pct", "virtual_return_pct"], trade.get("final_pnl_pct", "")))
        reason = _failure_reasons(
            src,
            pred_open_low,
            pred_open_high,
            actual_open,
            actual_high,
            actual_low,
            preferred_entry,
            stop_loss,
            take_profit1,
            direction_hit,
            entry_touched,
            stop_touched,
            tp1_touched,
            final_decision,
        )

        if not math.isnan(pred_close_low) and not math.isnan(pred_close_high):
            close_range = f"{pred_close_low:.4f}~{pred_close_high:.4f}"
        else:
            close_range = ""

        rows.append(
            {
                "ticker": ticker,
                "market": market,
                "prediction_date": _date10(src.get("created_at") or src.get("prediction_date")),
                "target_date": target_date,
                "market_condition": _market_condition(src),
                "predicted_direction": predicted_direction,
                "actual_direction": actual_direction,
                "direction_hit": _bool_out(direction_hit),
                "predicted_open_mid": "" if math.isnan(pred_open_mid) else pred_open_mid,
                "actual_open": "" if math.isnan(actual_open) else actual_open,
                "open_error_pct": _pct_out(open_error),
                "predicted_close_mid": "" if math.isnan(pred_close_mid) else pred_close_mid,
                "predicted_close_range": close_range,
                "actual_close": "" if math.isnan(actual_close) else actual_close,
                "close_error_pct": _pct_out(close_error),
                "actual_high": "" if math.isnan(actual_high) else actual_high,
                "actual_low": "" if math.isnan(actual_low) else actual_low,
                "preferred_entry": "" if math.isnan(preferred_entry) else preferred_entry,
                "stop_loss": "" if math.isnan(stop_loss) else stop_loss,
                "take_profit1": "" if math.isnan(take_profit1) else take_profit1,
                "entry_touched": _bool_out(entry_touched),
                "stop_touched": _bool_out(stop_touched),
                "tp1_touched": _bool_out(tp1_touched),
                "final_decision": final_decision,
                "decision_result": _decision_result(final_decision, entry_touched, stop_touched, tp1_touched, final_pnl, direction_hit),
                "failure_reason": reason,
                "suggested_adjustment": _suggest_adjustment(reason),
                "final_pnl_pct": _pct_out(final_pnl),
            }
        )

    return pd.DataFrame(rows, columns=REPORT_COLUMNS)


def _rate(series: pd.Series) -> float:
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


def _main_failure(series: pd.Series) -> str:
    parts: list[str] = []
    for value in series.astype(str):
        for item in value.split("/"):
            text = item.strip()
            if text and text != "정상 범위":
                parts.append(text)
    if not parts:
        return "정상 범위"
    return Counter(parts).most_common(1)[0][0]


def _profile_recommendations(row: dict[str, Any]) -> tuple[str, str, str, int]:
    hit_rate = _safe_float(row.get("direction_hit_rate"))
    open_err = _safe_float(row.get("avg_open_error_pct"))
    close_err = _safe_float(row.get("avg_close_error_pct"))
    entry_rate = _safe_float(row.get("entry_touch_rate"))
    stop_rate = _safe_float(row.get("stop_touch_rate"))
    tp_rate = _safe_float(row.get("tp1_touch_rate"))
    main_reason = _safe_str(row.get("main_failure_reason"))

    atr = "keep"
    if open_err >= 2.5 or close_err >= 3.0 or "갭" in main_reason or "이벤트" in main_reason:
        atr = "increase_atr_range"

    entry = "keep"
    if entry_rate < 35:
        entry = "move_entry_closer_to_tradeable_range"
    if stop_rate >= 45:
        entry = "lower_entry_or_widen_stop"

    tp = "keep"
    if tp_rate < 25 or "익절 목표 과도" in main_reason:
        tp = "lower_tp1_target"

    penalty = 0
    if hit_rate < 45:
        penalty += 10
    if stop_rate >= 45:
        penalty += 5
    if open_err >= 3 or close_err >= 4:
        penalty += 5
    return atr, entry, tp, min(penalty, 20)


def _build_ticker_profile(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return pd.DataFrame(columns=PROFILE_COLUMNS)
    rows: list[dict[str, Any]] = []
    for (market, ticker), group in report.groupby(["market", "ticker"], dropna=False):
        row = {
            "market": market,
            "ticker": ticker,
            "total_cases": int(len(group)),
            "direction_hit_rate": _pct_out(_rate(group["direction_hit"])),
            "avg_open_error_pct": _pct_out(_mean_abs(group["open_error_pct"])),
            "avg_close_error_pct": _pct_out(_mean_abs(group["close_error_pct"])),
            "entry_touch_rate": _pct_out(_rate(group["entry_touched"])),
            "stop_touch_rate": _pct_out(_rate(group["stop_touched"])),
            "tp1_touch_rate": _pct_out(_rate(group["tp1_touched"])),
            "avg_final_pnl_pct": _pct_out(_mean(group["final_pnl_pct"])),
            "main_failure_reason": _main_failure(group["failure_reason"]),
        }
        atr, entry, tp, penalty = _profile_recommendations(row)
        row["recommended_atr_adjustment"] = atr
        row["recommended_entry_adjustment"] = entry
        row["recommended_tp_adjustment"] = tp
        row["recommended_confidence_penalty"] = penalty
        rows.append(row)
    return pd.DataFrame(rows, columns=PROFILE_COLUMNS).sort_values(["total_cases", "ticker"], ascending=[False, True])


def _market_rule_change(row: dict[str, Any]) -> str:
    hit_rate = _safe_float(row.get("direction_hit_rate"))
    stop_rate = _safe_float(row.get("stop_touch_rate"))
    tp_rate = _safe_float(row.get("tp1_touch_rate"))
    open_err = _safe_float(row.get("avg_open_error_pct"))
    condition = _safe_str(row.get("market_condition"))
    changes: list[str] = []
    if "negative" in condition:
        changes.append("market_score_negative 구간 매수 신뢰도 하향")
    if "event_high" in condition:
        changes.append("고위험 이벤트 구간 ATR 확대 및 관망 필터 강화")
    if hit_rate < 45:
        changes.append("방향 예측 가중치 재학습")
    if stop_rate >= 45:
        changes.append("손절선/진입가 보수화")
    if tp_rate < 25:
        changes.append("TP1 목표 낮추기")
    if open_err >= 3:
        changes.append("시초가 갭 보정 강화")
    return " / ".join(dict.fromkeys(changes)) if changes else "현행 규칙 유지"


def _build_market_summary(report: pd.DataFrame) -> pd.DataFrame:
    if report.empty:
        return pd.DataFrame(columns=MARKET_COLUMNS)
    rows: list[dict[str, Any]] = []
    for condition, group in report.groupby("market_condition", dropna=False):
        row = {
            "market_condition": condition or "unknown",
            "total_cases": int(len(group)),
            "direction_hit_rate": _pct_out(_rate(group["direction_hit"])),
            "avg_open_error_pct": _pct_out(_mean_abs(group["open_error_pct"])),
            "avg_close_error_pct": _pct_out(_mean_abs(group["close_error_pct"])),
            "stop_touch_rate": _pct_out(_rate(group["stop_touched"])),
            "tp1_touch_rate": _pct_out(_rate(group["tp1_touched"])),
            "avg_pnl": _pct_out(_mean(group["final_pnl_pct"])),
        }
        row["recommended_rule_change"] = _market_rule_change(row)
        rows.append(row)
    return pd.DataFrame(rows, columns=MARKET_COLUMNS).sort_values("total_cases", ascending=False)


def run_error_analysis(
    predictions_path: Path = LEGACY_PREDICTIONS,
    actual_path: Path = ACTUAL_RESULTS,
    trade_path: Path = TRADE_SIMULATIONS,
) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pred_df = _read_csv(predictions_path)
    actual_df = _read_csv(actual_path)
    trade_df = _read_csv(trade_path)

    if pred_df.empty:
        empty_report = pd.DataFrame(columns=REPORT_COLUMNS)
        empty_profile = pd.DataFrame(columns=PROFILE_COLUMNS)
        empty_market = pd.DataFrame(columns=MARKET_COLUMNS)
    else:
        empty_report = _analysis_rows(pred_df, actual_df, trade_df)
        empty_profile = _build_ticker_profile(empty_report)
        empty_market = _build_market_summary(empty_report)

    empty_report.to_csv(PREDICTION_ERROR_REPORT, index=False, encoding="utf-8-sig")
    empty_profile.to_csv(TICKER_ERROR_PROFILE, index=False, encoding="utf-8-sig")
    empty_market.to_csv(MARKET_CONDITION_ERROR_SUMMARY, index=False, encoding="utf-8-sig")

    now = datetime.now().isoformat(timespec="seconds")
    return {
        "ok": True,
        "generated_at": now,
        "prediction_rows": int(len(pred_df)),
        "actual_rows": int(len(actual_df)),
        "trade_rows": int(len(trade_df)),
        "report_rows": int(len(empty_report)),
        "ticker_profile_rows": int(len(empty_profile)),
        "market_summary_rows": int(len(empty_market)),
        "files": {
            "prediction_error_report": str(PREDICTION_ERROR_REPORT.relative_to(PROJECT_ROOT)),
            "ticker_error_profile": str(TICKER_ERROR_PROFILE.relative_to(PROJECT_ROOT)),
            "market_condition_error_summary": str(MARKET_CONDITION_ERROR_SUMMARY.relative_to(PROJECT_ROOT)),
        },
    }


if __name__ == "__main__":
    import json

    print(json.dumps(run_error_analysis(), ensure_ascii=False, indent=2))
