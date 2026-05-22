"""No-buy / forced-watch post filter for risky candidates."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import PROJECT_ROOT


DATA_DIR = PROJECT_ROOT / "data"
NO_BUY_SUMMARY = DATA_DIR / "no_buy_filter_summary.csv"
NO_BUY_HISTORY = DATA_DIR / "no_buy_filter_history.csv"

FINAL_DECISION_STEPS = ["손절 우선", "비중 축소 우선", "관망 우위", "눌림목 매수 가능", "돌파 확인 후 접근"]

SUMMARY_COLUMNS = [
    "ticker",
    "market",
    "target_date",
    "no_buy_score",
    "no_buy_level",
    "no_buy_reasons",
    "market_regime",
    "market_risk_score",
    "direction_hit_rate",
    "stop_touch_rate",
    "tp1_touch_rate",
    "avg_final_pnl_pct",
    "raw_final_decision",
    "final_decision_before_no_buy_filter",
    "final_decision_after_no_buy_filter",
    "no_buy_filter_applied",
    "updated_at",
    "source_prediction_path",
    "source_adjustment_performance_path",
    "data_status",
]

PREDICTION_CANDIDATES = [
    PROJECT_ROOT / "predictions.csv",
    DATA_DIR / "predictions.csv",
    DATA_DIR / "decision_system" / "predictions.csv",
    PROJECT_ROOT / "stock_ai_app_new" / "data" / "predictions.csv",
]

ACTUAL_CANDIDATES = [
    PROJECT_ROOT / "actual_results.csv",
    DATA_DIR / "actual_results.csv",
    DATA_DIR / "decision_system" / "actual_results.csv",
    PROJECT_ROOT / "stock_ai_app_new" / "data" / "actual_results.csv",
]

_LIVE_INPUT_CACHE: dict[str, Any] | None = None


def _safe_str(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        text = _safe_str(value).replace(",", "").replace("%", "")
        if not text or text.lower() in {"n/a", "na"}:
            return default
        return float(text)
    except Exception:
        return default


def _clip(value: float, lo: float, hi: float) -> float:
    if math.isnan(value):
        return lo
    return max(lo, min(hi, value))


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        return pd.DataFrame()


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _normalize_market(value: Any) -> str:
    text = _safe_str(value)
    if text in {"KR", "Korea", "KOSPI", "KOSDAQ", "국장"}:
        return "한국주식"
    if text in {"US", "USA", "미장"}:
        return "미국주식"
    return text or "한국주식"


def _ticker_key(value: Any, market: Any = "") -> str:
    text = _safe_str(value).upper().replace(".KS", "").replace(".KQ", "")
    if text.endswith(".0"):
        text = text[:-2]
    if _normalize_market(market) == "한국주식" and text.isdigit():
        return text.zfill(6)
    return text


def _date_text(value: Any) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    try:
        return str(pd.to_datetime(text).date())
    except Exception:
        return text[:10]


def _rename_first(df: pd.DataFrame, target: str, candidates: list[str]) -> pd.DataFrame:
    if df.empty or target in df.columns:
        return df
    for col in candidates:
        if col in df.columns:
            return df.rename(columns={col: target})
    return df


def _canonicalize_ticker_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    mapping = {
        "ticker": ["symbol", "종목", "종목코드", "티커"],
        "market": ["시장", "market_name"],
        "direction_hit_rate": ["hit_rate", "direction_rate", "raw_direction_hit_rate", "adjusted_direction_hit_rate", "방향적중률"],
        "stop_touch_rate": ["stop_rate", "손절터치율"],
        "tp1_touch_rate": ["tp_rate", "target_touch_rate", "익절터치율"],
        "avg_final_pnl_pct": ["avg_pnl", "final_pnl_pct", "adjusted_avg_pnl_pct", "raw_avg_pnl_pct", "평균손익"],
    }
    for target, candidates in mapping.items():
        out = _rename_first(out, target, candidates)
    if not out.empty and {"ticker", "market"}.issubset(out.columns):
        out["_ticker_key"] = out.apply(lambda r: _ticker_key(r.get("ticker"), r.get("market")), axis=1)
        out["_market_key"] = out["market"].map(_normalize_market)
    return out


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists() and path.stat().st_size > 0:
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def load_no_buy_inputs() -> dict[str, Any]:
    prediction_path = _first_existing(PREDICTION_CANDIDATES)
    actual_path = _first_existing(ACTUAL_CANDIDATES)
    perf_path = DATA_DIR / "adjustment_performance_by_ticker.csv"
    return {
        "prediction_path": prediction_path,
        "actual_path": actual_path,
        "predictions": _read_csv(prediction_path) if prediction_path else pd.DataFrame(),
        "ticker_profile": _canonicalize_ticker_metrics(_read_csv(DATA_DIR / "ticker_error_profile.csv")),
        "prediction_adjustments": _canonicalize_ticker_metrics(_read_csv(DATA_DIR / "prediction_adjustments.csv")),
        "market_regime_summary": _load_json(DATA_DIR / "market_regime_summary.json"),
        "market_regime_history": _read_csv(DATA_DIR / "market_regime_history.csv"),
        "adjustment_performance_by_ticker": _canonicalize_ticker_metrics(_read_csv(perf_path)),
        "adjustment_performance_report": _read_csv(DATA_DIR / "adjustment_performance_report.csv"),
        "trade_simulations": _read_csv(DATA_DIR / "trade_simulations.csv"),
        "prediction_error_report": _read_csv(DATA_DIR / "prediction_error_report.csv"),
        "performance_path": perf_path if perf_path.exists() else None,
    }


def _live_inputs() -> dict[str, Any]:
    global _LIVE_INPUT_CACHE
    if _LIVE_INPUT_CACHE is None:
        _LIVE_INPUT_CACHE = load_no_buy_inputs()
    return _LIVE_INPUT_CACHE


def find_no_buy_metrics(ticker: str, market: str) -> dict[str, Any]:
    inputs = _live_inputs()
    return _find_metric(
        ticker,
        market,
        inputs.get("adjustment_performance_by_ticker", pd.DataFrame()),
        inputs.get("ticker_profile", pd.DataFrame()),
        inputs.get("prediction_adjustments", pd.DataFrame()),
    )


def load_no_buy_market_summary() -> dict[str, Any]:
    return _live_inputs().get("market_regime_summary", {})


def _find_metric(ticker: str, market: str, *frames: pd.DataFrame) -> dict[str, Any]:
    key = _ticker_key(ticker, market)
    mkt = _normalize_market(market)
    for df in frames:
        if df is None or df.empty or "_ticker_key" not in df.columns:
            continue
        hit = df[(df["_ticker_key"] == key) & (df.get("_market_key", df.get("market", "")).astype(str).map(_normalize_market) == mkt)]
        if not hit.empty:
            return hit.iloc[0].to_dict()
    return {}


def _infer_final_decision(text: Any) -> str:
    raw = _safe_str(text)
    for step in FINAL_DECISION_STEPS:
        if step in raw:
            return step
    if "손절" in raw:
        return "손절 우선"
    if "비중" in raw or "축소" in raw:
        return "비중 축소 우선"
    if "돌파" in raw:
        return "돌파 확인 후 접근"
    if "눌림" in raw or "지지선 근처" in raw or "반등" in raw or "매수" in raw or "진입" in raw:
        return "눌림목 매수 가능"
    return "관망 우위"


def downgrade_decision_by_no_buy_score(decision: Any, score: float, level: str = "") -> str:
    before = _infer_final_decision(decision)
    idx = FINAL_DECISION_STEPS.index(before)
    if score >= 86:
        return FINAL_DECISION_STEPS[min(idx, FINAL_DECISION_STEPS.index("비중 축소 우선"))]
    if score >= 71:
        return FINAL_DECISION_STEPS[min(idx, FINAL_DECISION_STEPS.index("관망 우위"))]
    if score >= 61 and before == "눌림목 매수 가능":
        return "관망 우위"
    if score >= 51 and before == "돌파 확인 후 접근":
        return "관망 우위"
    return before


def classify_no_buy_level(score: float, data_missing: bool = False) -> str:
    if data_missing:
        return "데이터 부족"
    if score <= 30:
        return "매수금지 아님"
    if score <= 50:
        return "주의"
    if score <= 70:
        return "관망 우위"
    if score <= 85:
        return "매수금지"
    return "강한 매수금지"


def _rr_value(row_or_pred: dict[str, Any]) -> float:
    for key in ["rr1", "risk_reward_ratio", "risk_reward", "손익비"]:
        val = _safe_float(row_or_pred.get(key), math.nan)
        if not math.isnan(val):
            return val
    entry = _safe_float(row_or_pred.get("preferred_entry"), math.nan)
    stop = _safe_float(row_or_pred.get("stop_loss"), math.nan)
    tp1 = _safe_float(row_or_pred.get("take_profit1"), math.nan)
    risk = entry - stop
    if not math.isnan(entry) and not math.isnan(stop) and not math.isnan(tp1) and risk > 0:
        return (tp1 - entry) / risk
    return math.nan


def build_no_buy_reasons(score_parts: list[str], existing_flags: Any = "") -> str:
    reasons = [x.strip() for x in score_parts if str(x).strip()]
    if isinstance(existing_flags, list):
        reasons.extend(str(x).strip() for x in existing_flags if str(x).strip())
    else:
        for sep in ["|", "/", ";"]:
            text = str(existing_flags or "")
            if sep in text:
                reasons.extend(x.strip() for x in text.split(sep) if x.strip())
                break
        else:
            if str(existing_flags or "").strip():
                reasons.append(str(existing_flags).strip())
    return " / ".join(dict.fromkeys(reasons))


def calculate_no_buy_score(
    row_or_prediction: dict[str, Any],
    ticker_metrics: dict[str, Any] | None = None,
    market_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    src = dict(row_or_prediction or {})
    metrics = ticker_metrics or {}
    market_summary = market_summary or {}
    score = 0.0
    reasons: list[str] = []

    market_regime = _safe_str(src.get("market_regime")) or _safe_str(market_summary.get("market_regime"))
    market_risk_score = _safe_float(src.get("market_risk_score"), _safe_float(market_summary.get("market_risk_score"), math.nan))
    direction_hit_rate = _safe_float(metrics.get("direction_hit_rate"), math.nan)
    stop_touch_rate = _safe_float(metrics.get("stop_touch_rate"), math.nan)
    tp1_touch_rate = _safe_float(metrics.get("tp1_touch_rate"), math.nan)
    avg_final_pnl = _safe_float(metrics.get("avg_final_pnl_pct"), math.nan)

    if not math.isnan(market_risk_score):
        if market_risk_score >= 80:
            score += 25; reasons.append("시장위험 80 이상")
        elif market_risk_score >= 60:
            score += 15; reasons.append("시장위험 60 이상")
        elif market_risk_score <= 30:
            score -= 10; reasons.append("시장위험 낮음")
    if market_regime == "급락장":
        score += 25; reasons.append("급락장")
    elif market_regime == "이벤트 변동성장":
        score += 15; reasons.append("이벤트 변동성장")

    if not math.isnan(direction_hit_rate):
        if direction_hit_rate < 35:
            score += 20; reasons.append("방향 적중률 35% 미만")
        elif direction_hit_rate < 45:
            score += 10; reasons.append("방향 적중률 45% 미만")
        elif direction_hit_rate >= 60:
            score -= 10; reasons.append("방향 적중률 60% 이상")
    if not math.isnan(stop_touch_rate):
        if stop_touch_rate >= 70:
            score += 20; reasons.append("손절 터치율 70% 이상")
        elif stop_touch_rate >= 60:
            score += 10; reasons.append("손절 터치율 60% 이상")
    if not math.isnan(tp1_touch_rate):
        if tp1_touch_rate < 20:
            score += 15; reasons.append("TP1 터치율 20% 미만")
        elif tp1_touch_rate >= 50:
            score -= 10; reasons.append("TP1 터치율 50% 이상")
    if not math.isnan(avg_final_pnl):
        if avg_final_pnl < 0:
            score += 15; reasons.append("평균 최종 손익 음수")
        elif avg_final_pnl > 0:
            score -= 10; reasons.append("평균 최종 손익 양수")

    rr = _rr_value(src)
    if math.isnan(rr):
        score += 10; reasons.append("손익비 데이터 부족")
    elif rr < 1.2:
        score += 20; reasons.append("손익비 1:1.2 미만")

    text = " ".join(str(src.get(k, "")) for k in ["no_buy_flags", "risk_reason", "market_filter_reason", "news_impact_reason", "event_label"])
    low = text.lower()
    if any(w in low for w in ["악재", "위험", "급락", "실적", "fomc", "cpi", "ppi", "전쟁", "감사", "상폐", "관리종목"]):
        score += 15; reasons.append("뉴스/이벤트 악재 또는 위험 문구")
    if any(w in low for w in ["거래량 부족", "data_missing", "데이터 부족"]):
        score += 10; reasons.append("거래량 부족 또는 데이터 부족")

    perf_label = _safe_str(metrics.get("improvement_label"))
    pnl_imp = _safe_float(metrics.get("pnl_improvement"), math.nan)
    loss = _safe_float(metrics.get("loss_avoided_cases"), 0)
    missed = _safe_float(metrics.get("missed_opportunity_cases"), 0)
    if perf_label == "악화" or (not math.isnan(pnl_imp) and pnl_imp < -0.2):
        score += 15; reasons.append("최근 보정 후 성과 악화")
    elif perf_label in {"개선", "손실 회피"} or (not math.isnan(pnl_imp) and pnl_imp > 0.2):
        score -= 5; reasons.append("최근 보정 성과 개선")
    if missed > loss:
        score += 5 if missed - loss <= 2 else 10
        reasons.append("기회 손실이 손실 회피보다 많음")

    data_missing = not metrics and math.isnan(market_risk_score)
    if data_missing:
        score = 50
        reasons.append("데이터 부족으로 보수 판단")

    score = int(round(_clip(score, 0, 100)))
    return {
        "no_buy_score": score,
        "no_buy_level": classify_no_buy_level(score, data_missing=data_missing),
        "no_buy_reasons": build_no_buy_reasons(reasons, src.get("no_buy_flags", "")),
        "market_regime": market_regime or "데이터 부족",
        "market_risk_score": "" if math.isnan(market_risk_score) else market_risk_score,
        "direction_hit_rate": "" if math.isnan(direction_hit_rate) else direction_hit_rate,
        "stop_touch_rate": "" if math.isnan(stop_touch_rate) else stop_touch_rate,
        "tp1_touch_rate": "" if math.isnan(tp1_touch_rate) else tp1_touch_rate,
        "avg_final_pnl_pct": "" if math.isnan(avg_final_pnl) else avg_final_pnl,
        "data_status": "DATA_MISSING" if data_missing else "OK",
    }


def apply_no_buy_filter(
    prediction: dict[str, Any],
    ticker: str = "",
    market: str = "한국주식",
    ticker_metrics: dict[str, Any] | None = None,
    market_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(prediction or {})
    before_decision = _infer_final_decision(out.get("primary_action", ""))
    before_conf = _safe_float(out.get("confidence_score"), math.nan)
    if ticker_metrics is None:
        ticker_metrics = find_no_buy_metrics(ticker, market)
    if market_summary is None:
        market_summary = load_no_buy_market_summary()
    metrics = calculate_no_buy_score(out, ticker_metrics=ticker_metrics, market_summary=market_summary)
    score = _safe_float(metrics.get("no_buy_score"), 50)
    level = _safe_str(metrics.get("no_buy_level"))
    after_decision = downgrade_decision_by_no_buy_score(before_decision, score, level)
    penalty = 0
    if score >= 86:
        penalty = 15
    elif score >= 71:
        penalty = 10
    elif score >= 51:
        penalty = 5
    if not math.isnan(before_conf):
        out["confidence_score"] = int(_clip(before_conf - penalty, 0, 100))
    after_conf = _safe_float(out.get("confidence_score"), math.nan)
    applied = bool(after_decision != before_decision or penalty > 0 or score >= 51)

    out["primary_action"] = after_decision
    no_buy_msg = f"매수금지 필터: {level} · {metrics.get('no_buy_reasons', '')}".strip()
    if applied and level not in {"매수금지 아님"}:
        if isinstance(out.get("no_buy_flags"), list):
            if no_buy_msg not in out["no_buy_flags"]:
                out["no_buy_flags"].append(no_buy_msg)
        else:
            flags = _safe_str(out.get("no_buy_flags"))
            out["no_buy_flags"] = (flags + " | " + no_buy_msg).strip(" |")

    out.update(
        {
            **metrics,
            "no_buy_filter_applied": int(applied),
            "final_decision_before_no_buy_filter": before_decision,
            "final_decision_after_no_buy_filter": after_decision,
            "confidence_score_before_no_buy_filter": "" if math.isnan(before_conf) else before_conf,
            "confidence_score_after_no_buy_filter": "" if math.isnan(after_conf) else after_conf,
        }
    )
    return out


def _row_metrics(row: pd.Series, inputs: dict[str, Any]) -> dict[str, Any]:
    market = _normalize_market(row.get("market"))
    ticker = _ticker_key(row.get("ticker"), market)
    return _find_metric(
        ticker,
        market,
        inputs.get("adjustment_performance_by_ticker", pd.DataFrame()),
        inputs.get("ticker_profile", pd.DataFrame()),
        inputs.get("prediction_adjustments", pd.DataFrame()),
    )


def _summary_row(row: pd.Series, inputs: dict[str, Any], now: str) -> dict[str, Any]:
    market = _normalize_market(row.get("market"))
    ticker = _ticker_key(row.get("ticker"), market)
    metrics = _row_metrics(row, inputs)
    market_summary = inputs.get("market_regime_summary", {})
    row_dict = row.to_dict()
    calc = calculate_no_buy_score(row_dict, metrics, market_summary)
    before = _infer_final_decision(row.get("final_decision_after_market_filter") or row.get("primary_action"))
    after = downgrade_decision_by_no_buy_score(before, _safe_float(calc.get("no_buy_score"), 50), calc.get("no_buy_level", ""))
    applied = int(before != after or _safe_float(calc.get("no_buy_score"), 0) >= 51)
    return {
        "ticker": ticker,
        "market": market,
        "target_date": _date_text(row.get("target_date")),
        "no_buy_score": calc.get("no_buy_score", 50),
        "no_buy_level": calc.get("no_buy_level", "데이터 부족"),
        "no_buy_reasons": calc.get("no_buy_reasons", "데이터 부족으로 보수 판단"),
        "market_regime": calc.get("market_regime", ""),
        "market_risk_score": calc.get("market_risk_score", ""),
        "direction_hit_rate": calc.get("direction_hit_rate", ""),
        "stop_touch_rate": calc.get("stop_touch_rate", ""),
        "tp1_touch_rate": calc.get("tp1_touch_rate", ""),
        "avg_final_pnl_pct": calc.get("avg_final_pnl_pct", ""),
        "raw_final_decision": _infer_final_decision(row.get("final_decision_before_adjustment") or row.get("primary_action")),
        "final_decision_before_no_buy_filter": before,
        "final_decision_after_no_buy_filter": after,
        "no_buy_filter_applied": applied,
        "updated_at": now,
        "source_prediction_path": str((inputs.get("prediction_path") or Path("")).relative_to(PROJECT_ROOT)) if inputs.get("prediction_path") else "",
        "source_adjustment_performance_path": str((inputs.get("performance_path") or Path("")).relative_to(PROJECT_ROOT)) if inputs.get("performance_path") else "",
        "data_status": calc.get("data_status", "OK"),
    }


def save_no_buy_summary(output_path: Path = NO_BUY_SUMMARY, history_path: Path = NO_BUY_HISTORY) -> dict[str, Any]:
    inputs = load_no_buy_inputs()
    pred = inputs.get("predictions", pd.DataFrame())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    if pred.empty:
        empty = pd.DataFrame(columns=SUMMARY_COLUMNS)
        empty.to_csv(output_path, index=False, encoding="utf-8-sig")
        empty.to_csv(history_path, index=False, encoding="utf-8-sig")
        return {"ok": True, "rows": 0, "generated_file": str(output_path.relative_to(PROJECT_ROOT)), "prediction_path": ""}

    rows = [_summary_row(row, inputs, now) for _, row in pred.iterrows()]
    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")

    hist = out.copy()
    if history_path.exists() and history_path.stat().st_size > 0:
        old = _read_csv(history_path)
        hist = pd.concat([old, hist], ignore_index=True)
        key_cols = [c for c in ["ticker", "market", "target_date", "updated_at"] if c in hist.columns]
        if key_cols:
            hist = hist.drop_duplicates(subset=key_cols, keep="last")
    hist.to_csv(history_path, index=False, encoding="utf-8-sig")

    return {
        "ok": True,
        "rows": int(len(out)),
        "history_rows": int(len(hist)),
        "generated_file": str(output_path.relative_to(PROJECT_ROOT)),
        "history_file": str(history_path.relative_to(PROJECT_ROOT)),
        "prediction_path": str(inputs["prediction_path"].relative_to(PROJECT_ROOT)) if inputs.get("prediction_path") else "",
    }


if __name__ == "__main__":
    print(json.dumps(save_no_buy_summary(), ensure_ascii=False, indent=2))
