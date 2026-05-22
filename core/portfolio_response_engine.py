"""Portfolio holding response summary for existing positions."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import PROJECT_ROOT


DATA_DIR = PROJECT_ROOT / "data"
PORTFOLIO_RESPONSE_SUMMARY = DATA_DIR / "portfolio_response_summary.csv"
PORTFOLIO_RESPONSE_HISTORY = DATA_DIR / "portfolio_response_history.csv"

HOLDING_COLUMNS = [
    "ticker", "market", "name", "avg_price", "quantity", "buy_amount",
    "current_price", "memo", "holding_type", "created_at", "updated_at",
]

SUMMARY_COLUMNS = [
    "ticker", "market", "name", "avg_price", "quantity", "buy_amount",
    "current_price", "current_price_source", "current_price_updated_at",
    "evaluation_amount", "unrealized_pnl_pct", "unrealized_pnl_amount",
    "latest_target_date", "latest_final_decision", "latest_confidence_score",
    "preferred_entry", "stop_loss", "take_profit1", "take_profit2",
    "no_buy_score", "no_buy_level", "no_buy_reasons",
    "market_regime", "market_risk_score", "current_rr",
    "distance_to_stop_pct", "distance_to_tp1_pct", "holding_risk_score",
    "portfolio_action", "portfolio_action_reason", "add_buy_allowed",
    "trim_required", "stop_loss_required", "take_profit_suggested",
    "data_status", "updated_at",
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

NO_BUY_CANDIDATES = [
    DATA_DIR / "no_buy_filter_summary.csv",
    PROJECT_ROOT / "no_buy_filter_summary.csv",
    PROJECT_ROOT / "stock_ai_app_new" / "data" / "no_buy_filter_summary.csv",
]

HOLDING_CANDIDATES = [
    (PROJECT_ROOT / "holdings_kr.csv", "한국주식"),
    (PROJECT_ROOT / "holdings_us.csv", "미국주식"),
    (DATA_DIR / "holdings_kr.csv", "한국주식"),
    (DATA_DIR / "holdings_us.csv", "미국주식"),
    (PROJECT_ROOT / "stock_ai_app_new" / "data" / "holdings_kr.csv", "한국주식"),
    (PROJECT_ROOT / "stock_ai_app_new" / "data" / "holdings_us.csv", "미국주식"),
    (DATA_DIR / "holdings.csv", ""),
]

VALID_ACTIONS = {"보유 유지", "추가매수 금지", "비중 축소 우선", "손절 우선", "익절 분할", "관망", "데이터 부족"}


def _safe_str(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in {"nan", "none", "nat"} else text


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        text = _safe_str(value).replace(",", "").replace("%", "").replace("$", "").replace("원", "")
        if not text or text.lower() in {"na", "n/a"}:
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


def _write_empty_holdings_if_missing() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for path in [DATA_DIR / "holdings_kr.csv", DATA_DIR / "holdings_us.csv"]:
        if not path.exists():
            pd.DataFrame(columns=HOLDING_COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")


def _first_path(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists() and path.stat().st_size > 0:
            return path
    return None


def _normalize_market(value: Any, ticker: Any = "", default_market: str = "") -> str:
    text = _safe_str(value)
    if text in {"KR", "Korea", "KOSPI", "KOSDAQ", "국장"}:
        return "한국주식"
    if text in {"US", "USA", "미장"}:
        return "미국주식"
    if text:
        return text
    if default_market:
        return default_market
    ticker_text = _safe_str(ticker)
    return "한국주식" if ticker_text.replace(".0", "").isdigit() else "미국주식"


def _ticker_key(value: Any, market: Any = "") -> str:
    text = _safe_str(value).upper().replace(".KS", "").replace(".KQ", "")
    if text.endswith(".0"):
        text = text[:-2]
    if _normalize_market(market, text) == "한국주식" and text.isdigit():
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


def _first(row: pd.Series | dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        try:
            value = row.get(name, "")
        except Exception:
            value = ""
        if _safe_str(value) != "":
            return value
    return default


def _canonicalize_holdings(df: pd.DataFrame, default_market: str = "") -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=HOLDING_COLUMNS)
    out = pd.DataFrame()
    mapping = {
        "ticker": ["ticker", "symbol", "종목", "종목코드"],
        "market": ["market", "시장", "market_type"],
        "name": ["name", "종목명", "회사명"],
        "avg_price": ["avg_price", "average_price", "avg_buy_price", "평균단가", "매수가"],
        "quantity": ["quantity", "qty", "수량", "보유수량"],
        "buy_amount": ["buy_amount", "매수금액", "투입금액"],
        "current_price": ["current_price", "현재가"],
        "memo": ["memo", "메모"],
        "holding_type": ["holding_type", "유형"],
        "created_at": ["created_at", "생성일"],
        "updated_at": ["updated_at", "수정일"],
    }
    for target, candidates in mapping.items():
        src = next((c for c in candidates if c in df.columns), None)
        out[target] = df[src] if src else ""
    out["market"] = out.apply(lambda r: _normalize_market(r.get("market"), r.get("ticker"), default_market), axis=1)
    out["ticker"] = out.apply(lambda r: _ticker_key(r.get("ticker"), r.get("market")), axis=1)
    out = out[out["ticker"].astype(str).str.strip() != ""].copy()
    return out[HOLDING_COLUMNS]


def load_holdings() -> tuple[pd.DataFrame, list[str]]:
    _write_empty_holdings_if_missing()
    frames: list[pd.DataFrame] = []
    used: list[str] = []
    for path, default_market in HOLDING_CANDIDATES:
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = _canonicalize_holdings(_read_csv(path), default_market)
        if df.empty:
            used.append(str(path.relative_to(PROJECT_ROOT)))
            continue
        frames.append(df)
        used.append(str(path.relative_to(PROJECT_ROOT)))
    if not frames:
        return pd.DataFrame(columns=HOLDING_COLUMNS), used
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["ticker", "market"], keep="last")
    return out, used


def _canonicalize_keyed(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "ticker" not in out.columns:
        for c in ["symbol", "종목", "종목코드"]:
            if c in out.columns:
                out = out.rename(columns={c: "ticker"})
                break
    if "market" not in out.columns:
        out["market"] = ""
    out["_market_key"] = out.apply(lambda r: _normalize_market(r.get("market"), r.get("ticker")), axis=1)
    out["_ticker_key"] = out.apply(lambda r: _ticker_key(r.get("ticker"), r.get("_market_key")), axis=1)
    return out


def load_latest_predictions_for_holdings() -> tuple[pd.DataFrame, str]:
    path = _first_path(PREDICTION_CANDIDATES)
    df = _canonicalize_keyed(_read_csv(path)) if path else pd.DataFrame()
    if df.empty:
        return df, ""
    if "target_date" in df.columns:
        df["_target_dt"] = pd.to_datetime(df["target_date"], errors="coerce")
    else:
        df["_target_dt"] = pd.NaT
    if "created_at" in df.columns:
        df["_created_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
    else:
        df["_created_dt"] = pd.NaT
    df["_row_order"] = range(len(df))
    df = df.sort_values(["_market_key", "_ticker_key", "_target_dt", "_created_dt", "_row_order"])
    latest = df.groupby(["_market_key", "_ticker_key"], dropna=False).tail(1).copy()
    return latest, str(path.relative_to(PROJECT_ROOT)) if path else ""


def load_no_buy_data_for_holdings() -> tuple[pd.DataFrame, str]:
    path = _first_path(NO_BUY_CANDIDATES)
    df = _canonicalize_keyed(_read_csv(path)) if path else pd.DataFrame()
    if df.empty:
        return df, ""
    if "target_date" in df.columns:
        df["_target_dt"] = pd.to_datetime(df["target_date"], errors="coerce")
    else:
        df["_target_dt"] = pd.NaT
    df["_row_order"] = range(len(df))
    df = df.sort_values(["_market_key", "_ticker_key", "_target_dt", "_row_order"])
    latest = df.groupby(["_market_key", "_ticker_key"], dropna=False).tail(1).copy()
    return latest, str(path.relative_to(PROJECT_ROOT)) if path else ""


def _load_actual_results() -> pd.DataFrame:
    path = _first_path(ACTUAL_CANDIDATES)
    df = _canonicalize_keyed(_read_csv(path)) if path else pd.DataFrame()
    if df.empty:
        return df
    date_col = "date" if "date" in df.columns else "actual_date" if "actual_date" in df.columns else ""
    if date_col:
        df["_date_dt"] = pd.to_datetime(df[date_col], errors="coerce")
    else:
        df["_date_dt"] = pd.NaT
    df["_row_order"] = range(len(df))
    return df.sort_values(["_market_key", "_ticker_key", "_date_dt", "_row_order"]).groupby(["_market_key", "_ticker_key"], dropna=False).tail(1).copy()


def _lookup(df: pd.DataFrame, ticker: str, market: str) -> dict[str, Any]:
    if df.empty or "_ticker_key" not in df.columns:
        return {}
    hit = df[(df["_ticker_key"] == _ticker_key(ticker, market)) & (df["_market_key"] == _normalize_market(market, ticker))]
    if hit.empty:
        return {}
    return hit.iloc[0].to_dict()


def calculate_current_rr(current_price: float, stop_loss: float, take_profit1: float) -> float:
    risk = current_price - stop_loss
    if any(math.isnan(x) for x in [current_price, stop_loss, take_profit1]) or risk <= 0:
        return math.nan
    return (take_profit1 - current_price) / risk


def _final_decision(pred: dict[str, Any]) -> str:
    for col in [
        "final_decision_after_no_buy_filter", "final_decision_after_market_filter",
        "final_decision_after_adjustment", "final_decision", "primary_action",
    ]:
        text = _safe_str(pred.get(col))
        if text:
            return text
    return ""


def calculate_holding_status(holding: dict[str, Any], pred: dict[str, Any], actual: dict[str, Any]) -> dict[str, Any]:
    avg = _safe_float(holding.get("avg_price"), math.nan)
    qty = _safe_float(holding.get("quantity"), math.nan)
    current = _safe_float(holding.get("current_price"), math.nan)
    source = "holdings.current_price" if not math.isnan(current) else ""
    if math.isnan(current):
        for col in ["current_price_at_prediction", "basis_close", "prev_close", "pred_close_mid"]:
            current = _safe_float(pred.get(col), math.nan)
            if not math.isnan(current):
                source = f"predictions.{col}"
                break
    if math.isnan(current):
        current = _safe_float(_first(actual, ["close", "actual_close"]), math.nan)
        if not math.isnan(current):
            source = "actual_results.close"
    buy_amount = _safe_float(holding.get("buy_amount"), math.nan)
    if math.isnan(buy_amount) and not math.isnan(avg) and not math.isnan(qty):
        buy_amount = avg * qty
    evaluation = current * qty if not math.isnan(current) and not math.isnan(qty) else math.nan
    pnl_amount = (current - avg) * qty if not math.isnan(current) and not math.isnan(avg) and not math.isnan(qty) else math.nan
    pnl_pct = (current / avg - 1) * 100 if not math.isnan(current) and not math.isnan(avg) and avg > 0 else math.nan
    return {
        "avg_price": avg, "quantity": qty, "buy_amount": buy_amount,
        "current_price": current, "current_price_source": source,
        "evaluation_amount": evaluation, "unrealized_pnl_amount": pnl_amount,
        "unrealized_pnl_pct": pnl_pct,
    }


def _metric_for_ticker(ticker: str, market: str, perf: pd.DataFrame, profile: pd.DataFrame) -> dict[str, Any]:
    return _lookup(_canonicalize_keyed(perf), ticker, market) or _lookup(_canonicalize_keyed(profile), ticker, market)


def calculate_position_risk(status: dict[str, Any], pred: dict[str, Any], no_buy: dict[str, Any], metric: dict[str, Any], market_summary: dict[str, Any]) -> tuple[int, list[str]]:
    score = 0.0
    reasons: list[str] = []
    current = _safe_float(status.get("current_price"), math.nan)
    stop = _safe_float(pred.get("stop_loss"), math.nan)
    tp1 = _safe_float(pred.get("take_profit1"), math.nan)
    pnl = _safe_float(status.get("unrealized_pnl_pct"), math.nan)
    no_buy_score = _safe_float(no_buy.get("no_buy_score", pred.get("no_buy_score")), math.nan)
    market_risk = _safe_float(pred.get("market_risk_score"), _safe_float(market_summary.get("market_risk_score"), math.nan))
    decision = _final_decision(pred)
    rr = calculate_current_rr(current, stop, tp1)
    direction_hit = _safe_float(metric.get("direction_hit_rate"), math.nan)
    stop_touch = _safe_float(metric.get("stop_touch_rate"), math.nan)
    regime = _safe_str(pred.get("market_regime")) or _safe_str(market_summary.get("market_regime"))

    if not math.isnan(current) and not math.isnan(stop) and stop > 0:
        if current <= stop:
            score += 40; reasons.append("현재가가 손절가 아래")
        elif (current / stop - 1) * 100 <= 2:
            score += 25; reasons.append("현재가가 손절가 2% 이내")
    if not math.isnan(pnl):
        if pnl <= -10:
            score += 25; reasons.append("미실현손익률 -10% 이하")
        elif pnl <= -5:
            score += 15; reasons.append("미실현손익률 -5% 이하")
        elif pnl >= 10:
            score -= 10; reasons.append("미실현수익 +10% 이상")
    if not math.isnan(no_buy_score):
        if no_buy_score >= 70:
            score += 25; reasons.append("no_buy_score 70 이상")
        elif no_buy_score >= 50:
            score += 15; reasons.append("no_buy_score 50 이상")
    if not math.isnan(market_risk):
        if market_risk >= 80:
            score += 20; reasons.append("시장위험 80 이상")
        elif market_risk >= 60:
            score += 10; reasons.append("시장위험 60 이상")
        elif market_risk <= 30:
            score -= 5; reasons.append("시장위험 낮음")
    if "손절 우선" in decision:
        score += 35; reasons.append("최신 예측판단 손절 우선")
    elif "비중 축소 우선" in decision:
        score += 25; reasons.append("최신 예측판단 비중 축소 우선")
    elif "관망 우위" in decision:
        score += 10; reasons.append("최신 예측판단 관망 우위")
    if not math.isnan(direction_hit) and direction_hit < 45:
        score += 10; reasons.append("방향 적중률 낮음")
    if not math.isnan(stop_touch) and stop_touch >= 60:
        score += 15; reasons.append("손절 터치율 높음")
    if regime == "이벤트 변동성장":
        score += 15; reasons.append("이벤트 변동성장")
    elif regime == "급락장":
        score += 20; reasons.append("급락장")
    if not math.isnan(rr):
        if rr < 1:
            score += 15; reasons.append("현재 손익비 1:1 미만")
        elif rr < 1.5:
            score += 8; reasons.append("현재 손익비 1:1.5 미만")
    if not math.isnan(current) and not math.isnan(tp1) and tp1 > 0 and current >= tp1 * 0.98:
        reasons.append("take_profit1 근접 또는 도달")
    if any(x in decision for x in ["눌림목 매수 가능", "돌파 확인 후 접근"]) and (math.isnan(no_buy_score) or no_buy_score <= 30) and (math.isnan(market_risk) or market_risk <= 40):
        score -= 5; reasons.append("예측 긍정 + 위험 낮음")
    return int(round(_clip(score, 0, 100))), reasons


def classify_portfolio_action(status: dict[str, Any], pred: dict[str, Any], no_buy: dict[str, Any], risk_score: int, reasons: list[str]) -> str:
    current = _safe_float(status.get("current_price"), math.nan)
    avg = _safe_float(status.get("avg_price"), math.nan)
    qty = _safe_float(status.get("quantity"), math.nan)
    stop = _safe_float(pred.get("stop_loss"), math.nan)
    tp1 = _safe_float(pred.get("take_profit1"), math.nan)
    pnl = _safe_float(status.get("unrealized_pnl_pct"), math.nan)
    no_buy_score = _safe_float(no_buy.get("no_buy_score", pred.get("no_buy_score")), math.nan)
    market_risk = _safe_float(pred.get("market_risk_score"), math.nan)
    decision = _final_decision(pred)
    if math.isnan(current) or math.isnan(avg) or math.isnan(qty):
        return "데이터 부족"
    if not math.isnan(stop) and current <= stop:
        return "손절 우선"
    if "손절 우선" in decision:
        return "손절 우선"
    if not math.isnan(stop) and stop > 0 and (current / stop - 1) * 100 <= 2 and (not math.isnan(market_risk) and market_risk >= 60):
        return "손절 우선" if risk_score >= 75 else "비중 축소 우선"
    if not math.isnan(tp1) and (current >= tp1 or (current >= tp1 * 0.98 and not math.isnan(pnl) and pnl > 0)):
        return "익절 분할"
    if not math.isnan(pnl) and pnl <= -10 and any(x in decision for x in ["손절 우선", "비중 축소 우선", "관망 우위"]):
        return "손절 우선"
    if "비중 축소 우선" in decision:
        return "비중 축소 우선"
    if not math.isnan(no_buy_score) and no_buy_score >= 85 and not math.isnan(pnl) and pnl < 0:
        return "비중 축소 우선"
    if not math.isnan(pnl) and pnl <= -5 and any(x in decision for x in ["비중 축소 우선", "관망 우위"]):
        return "비중 축소 우선"
    if not math.isnan(no_buy_score) and no_buy_score >= 70:
        return "추가매수 금지"
    if not math.isnan(market_risk) and market_risk >= 80:
        return "비중 축소 우선" if risk_score >= 70 else "관망"
    if any(x in decision for x in ["눌림목 매수 가능", "돌파 확인 후 접근"]) and (math.isnan(no_buy_score) or no_buy_score <= 30) and (math.isnan(market_risk) or market_risk <= 40):
        return "보유 유지"
    if risk_score >= 70:
        return "비중 축소 우선"
    if risk_score >= 50:
        return "추가매수 금지"
    return "보유 유지"


def build_portfolio_response_reason(status: dict[str, Any], pred: dict[str, Any], reasons: list[str], action: str) -> str:
    out = list(reasons)
    if action == "손절 우선":
        out.append("손절 기준 확인 필요")
    if _safe_str(status.get("current_price_source")) and status.get("current_price_source") != "holdings.current_price":
        out.append(f"현재가 대체값 사용: {status.get('current_price_source')}")
    if action == "추가매수 금지":
        out.append("보유 매도 판단이 아니라 신규 추가매수 제한")
    if not out:
        out.append("보유종목 대응 기준 정상 범위")
    return " / ".join(dict.fromkeys([x for x in out if x]))


def _row_for_holding(holding: pd.Series, pred: dict[str, Any], no_buy: dict[str, Any], actual: dict[str, Any], metric: dict[str, Any], market_summary: dict[str, Any], now: str) -> dict[str, Any]:
    h = holding.to_dict()
    status = calculate_holding_status(h, pred, actual)
    risk, risk_reasons = calculate_position_risk(status, pred, no_buy, metric, market_summary)
    action = classify_portfolio_action(status, pred, no_buy, risk, risk_reasons)
    current = _safe_float(status.get("current_price"), math.nan)
    stop = _safe_float(pred.get("stop_loss"), math.nan)
    tp1 = _safe_float(pred.get("take_profit1"), math.nan)
    tp2 = _safe_float(pred.get("take_profit2"), math.nan)
    distance_stop = (current / stop - 1) * 100 if not math.isnan(current) and not math.isnan(stop) and stop > 0 else math.nan
    distance_tp1 = (tp1 / current - 1) * 100 if not math.isnan(current) and not math.isnan(tp1) and current > 0 else math.nan
    no_buy_score = _safe_float(no_buy.get("no_buy_score", pred.get("no_buy_score")), math.nan)
    no_buy_level = _safe_str(no_buy.get("no_buy_level")) or _safe_str(pred.get("no_buy_level"))
    market_regime = _safe_str(pred.get("market_regime")) or _safe_str(market_summary.get("market_regime"))
    market_risk = _safe_float(pred.get("market_risk_score"), _safe_float(market_summary.get("market_risk_score"), math.nan))
    conf = _first(pred, ["confidence_score_after_no_buy_filter", "confidence_score_after_market_filter", "confidence_score_after_adjustment", "confidence_score"])
    data_missing = action == "데이터 부족" or not pred
    return {
        "ticker": h.get("ticker", ""),
        "market": h.get("market", ""),
        "name": h.get("name", ""),
        "avg_price": "" if math.isnan(_safe_float(status.get("avg_price"), math.nan)) else status.get("avg_price"),
        "quantity": "" if math.isnan(_safe_float(status.get("quantity"), math.nan)) else status.get("quantity"),
        "buy_amount": "" if math.isnan(_safe_float(status.get("buy_amount"), math.nan)) else status.get("buy_amount"),
        "current_price": "" if math.isnan(current) else current,
        "current_price_source": status.get("current_price_source", ""),
        "current_price_updated_at": _safe_str(h.get("updated_at")) or now,
        "evaluation_amount": "" if math.isnan(_safe_float(status.get("evaluation_amount"), math.nan)) else status.get("evaluation_amount"),
        "unrealized_pnl_pct": "" if math.isnan(_safe_float(status.get("unrealized_pnl_pct"), math.nan)) else status.get("unrealized_pnl_pct"),
        "unrealized_pnl_amount": "" if math.isnan(_safe_float(status.get("unrealized_pnl_amount"), math.nan)) else status.get("unrealized_pnl_amount"),
        "latest_target_date": _date_text(pred.get("target_date")),
        "latest_final_decision": _final_decision(pred),
        "latest_confidence_score": conf,
        "preferred_entry": pred.get("preferred_entry", ""),
        "stop_loss": "" if math.isnan(stop) else stop,
        "take_profit1": "" if math.isnan(tp1) else tp1,
        "take_profit2": "" if math.isnan(tp2) else tp2,
        "no_buy_score": "" if math.isnan(no_buy_score) else no_buy_score,
        "no_buy_level": no_buy_level,
        "no_buy_reasons": _safe_str(no_buy.get("no_buy_reasons")) or _safe_str(pred.get("no_buy_reasons")),
        "market_regime": market_regime,
        "market_risk_score": "" if math.isnan(market_risk) else market_risk,
        "current_rr": "" if math.isnan(calculate_current_rr(current, stop, tp1)) else calculate_current_rr(current, stop, tp1),
        "distance_to_stop_pct": "" if math.isnan(distance_stop) else distance_stop,
        "distance_to_tp1_pct": "" if math.isnan(distance_tp1) else distance_tp1,
        "holding_risk_score": risk,
        "portfolio_action": action if action in VALID_ACTIONS else "데이터 부족",
        "portfolio_action_reason": build_portfolio_response_reason(status, pred, risk_reasons, action),
        "add_buy_allowed": int(action in {"보유 유지"} and (math.isnan(no_buy_score) or no_buy_score < 50)),
        "trim_required": int(action == "비중 축소 우선"),
        "stop_loss_required": int(action == "손절 우선"),
        "take_profit_suggested": int(action == "익절 분할"),
        "data_status": "DATA_MISSING" if data_missing else "OK",
        "updated_at": now,
    }


def save_portfolio_response_summary(output_path: Path = PORTFOLIO_RESPONSE_SUMMARY, history_path: Path = PORTFOLIO_RESPONSE_HISTORY) -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    holdings, holding_paths = load_holdings()
    pred, prediction_path = load_latest_predictions_for_holdings()
    no_buy, no_buy_path = load_no_buy_data_for_holdings()
    actual = _load_actual_results()
    perf = _read_csv(DATA_DIR / "adjustment_performance_by_ticker.csv")
    profile = _read_csv(DATA_DIR / "ticker_error_profile.csv")
    try:
        market_summary = json.loads((DATA_DIR / "market_regime_summary.json").read_text(encoding="utf-8"))
    except Exception:
        market_summary = {}
    now = datetime.now().isoformat(timespec="seconds")
    if holdings.empty:
        empty = pd.DataFrame(columns=SUMMARY_COLUMNS)
        empty.to_csv(output_path, index=False, encoding="utf-8-sig")
        empty.to_csv(history_path, index=False, encoding="utf-8-sig")
        return {
            "ok": True, "rows": 0, "history_rows": 0,
            "generated_file": str(output_path.relative_to(PROJECT_ROOT)),
            "history_file": str(history_path.relative_to(PROJECT_ROOT)),
            "holdings_paths": holding_paths,
            "prediction_path": prediction_path,
            "note": "no holdings rows",
        }

    rows: list[dict[str, Any]] = []
    for _, holding in holdings.iterrows():
        ticker = _ticker_key(holding.get("ticker"), holding.get("market"))
        market = _normalize_market(holding.get("market"), ticker)
        pred_row = _lookup(pred, ticker, market)
        no_buy_row = _lookup(no_buy, ticker, market)
        actual_row = _lookup(actual, ticker, market)
        metric = _metric_for_ticker(ticker, market, perf, profile)
        rows.append(_row_for_holding(holding, pred_row, no_buy_row, actual_row, metric, market_summary, now))

    out = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    out.to_csv(output_path, index=False, encoding="utf-8-sig")
    hist = out.copy()
    if history_path.exists() and history_path.stat().st_size > 0:
        old = _read_csv(history_path)
        hist = pd.concat([old, hist], ignore_index=True)
    hist.to_csv(history_path, index=False, encoding="utf-8-sig")
    return {
        "ok": True,
        "rows": int(len(out)),
        "history_rows": int(len(hist)),
        "generated_file": str(output_path.relative_to(PROJECT_ROOT)),
        "history_file": str(history_path.relative_to(PROJECT_ROOT)),
        "holdings_paths": holding_paths,
        "prediction_path": prediction_path,
        "no_buy_path": no_buy_path,
    }


if __name__ == "__main__":
    print(json.dumps(save_portfolio_response_summary(), ensure_ascii=False, indent=2))
