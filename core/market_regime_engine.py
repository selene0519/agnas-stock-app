"""Market regime classifier and post-prediction risk filter."""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from core.paths import PROJECT_ROOT
from core.prediction_adjustment_engine import find_adjustment


DATA_DIR = PROJECT_ROOT / "data"
MARKET_REGIME_SUMMARY = DATA_DIR / "market_regime_summary.json"
MARKET_REGIME_HISTORY = DATA_DIR / "market_regime_history.csv"
FINAL_DECISION_STEPS = ["손절 우선", "비중 축소 우선", "관망 우위", "눌림목 매수 가능", "돌파 확인 후 접근"]


def _safe_float(value: Any, default: float = math.nan) -> float:
    try:
        if value is None:
            return default
        text = str(value).strip().replace(",", "").replace("%", "")
        if text == "" or text.lower() in {"nan", "none", "nat", "n/a", "na"}:
            return default
        return float(text)
    except Exception:
        return default


def _clip(value: float, lo: float, hi: float) -> float:
    if math.isnan(value):
        return lo
    return max(lo, min(hi, value))


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pct_from_yfinance(symbol: str) -> float:
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period="5d", interval="1d", auto_adjust=False)
        if hist is None or hist.empty or len(hist) < 2:
            return math.nan
        close = pd.to_numeric(hist["Close"], errors="coerce").dropna()
        if len(close) < 2:
            return math.nan
        prev = float(close.iloc[-2])
        last = float(close.iloc[-1])
        if prev == 0:
            return math.nan
        return (last / prev - 1) * 100
    except Exception:
        return math.nan


def _latest_news_text() -> str:
    candidates = [DATA_DIR / "news" / "today_news.csv", DATA_DIR / "news" / "market_summary.json"]
    texts: list[str] = []
    for path in candidates:
        try:
            if not path.exists() or path.stat().st_size == 0:
                continue
            if path.suffix.lower() == ".json":
                obj = json.loads(path.read_text(encoding="utf-8"))
                texts.append(json.dumps(obj, ensure_ascii=False)[:3000])
            else:
                df = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
                texts.extend(df.head(50).astype(str).agg(" ".join, axis=1).tolist())
        except Exception:
            continue
    return " ".join(texts)[:6000]


def load_market_inputs(market: str = "한국주식") -> dict[str, Any]:
    """Load best-effort market inputs. Missing data is allowed."""
    is_kr = str(market) == "한국주식"
    symbols = {
        "nasdaq_pct": "^IXIC",
        "sp500_pct": "^GSPC",
        "russell_pct": "^RUT",
        "qqq_pct": "QQQ",
        "soxx_pct": "SOXX",
        "smh_pct": "SMH",
        "nasdaq_future_change_pct": "NQ=F",
        "sp500_future_change_pct": "ES=F",
        "vix_pct": "^VIX",
        "us10y_pct": "^TNX",
        "dxy_pct": "DX-Y.NYB",
        "wti_pct": "CL=F",
        "bitcoin_pct": "BTC-USD",
    }
    if is_kr:
        symbols.update({"kospi_pct": "^KS11", "kosdaq_pct": "^KQ11", "usdkrw_pct": "KRW=X"})
    out: dict[str, Any] = {"market": market, "updated_at": _now_text(), "news_text": _latest_news_text()}
    for key, symbol in symbols.items():
        out[key] = _pct_from_yfinance(symbol)
    return out


def _has_event_risk(text: str) -> tuple[bool, list[str]]:
    low = str(text or "").lower()
    mapping = {
        "FOMC": ["fomc", "fed", "연준", "금리"],
        "CPI/PPI": ["cpi", "ppi", "물가", "inflation"],
        "고용지표": ["jobs", "payroll", "employment", "고용", "실업"],
        "실적": ["earnings", "실적", "guidance", "가이던스"],
        "지정학": ["war", "전쟁", "iran", "israel", "지정학", "중동"],
        "금융위험": ["credit", "bank", "default", "신용", "위기"],
    }
    hits: list[str] = []
    for label, words in mapping.items():
        if any(w in low for w in words):
            hits.append(label)
    return bool(hits), hits


def calculate_market_risk_score(inputs: dict[str, Any]) -> dict[str, Any]:
    score = 35.0
    positive: list[str] = []
    negative: list[str] = []
    reasons: list[str] = []

    def pct(name: str) -> float:
        return _safe_float(inputs.get(name), math.nan)

    main_index = pct("kospi_pct") if str(inputs.get("market")) == "한국주식" else pct("nasdaq_pct")
    nasdaq = pct("nasdaq_pct")
    soxx = pct("soxx_pct")
    smh = pct("smh_pct")
    vix = pct("vix_pct")
    us10y = pct("us10y_pct")
    usdkrw = pct("usdkrw_pct")
    wti = pct("wti_pct")

    for label, val in [("주요지수", main_index), ("나스닥", nasdaq)]:
        if not math.isnan(val):
            if val <= -2:
                score += 25; negative.append(f"{label} 급락 {val:.2f}%")
            elif val <= -1:
                score += 15; negative.append(f"{label} 하락 {val:.2f}%")
            elif val >= 1:
                score -= 10; positive.append(f"{label} 강세 {val:.2f}%")

    semi = min([x for x in [soxx, smh] if not math.isnan(x)] or [math.nan])
    if not math.isnan(semi):
        if semi <= -2:
            score += 15; negative.append(f"반도체 ETF 약세 {semi:.2f}%")
        elif semi >= 1:
            score -= 5; positive.append(f"반도체 ETF 강세 {semi:.2f}%")

    if not math.isnan(vix):
        if vix >= 8:
            score += 15; negative.append(f"VIX 급등 {vix:.2f}%")
        elif vix <= -3:
            score -= 5; positive.append(f"VIX 하락 {vix:.2f}%")

    if not math.isnan(us10y) and us10y >= 1.2:
        score += 15; negative.append(f"미국채 금리 상승 {us10y:.2f}%")
    if not math.isnan(usdkrw):
        if usdkrw >= 0.7:
            score += 10; negative.append(f"원/달러 환율 상승 {usdkrw:.2f}%")
        elif abs(usdkrw) <= 0.2:
            score -= 5; positive.append("환율 안정")
    if not math.isnan(wti) and wti >= 2.5:
        score += 8; negative.append(f"WTI 유가 상승 {wti:.2f}%")

    event_risk, events = _has_event_risk(str(inputs.get("news_text", "")))
    if event_risk:
        bump = 25 if any(x in events for x in ["FOMC", "CPI/PPI", "지정학", "금융위험"]) else 15
        score += bump
        negative.append("이벤트 리스크: " + ", ".join(events))

    score = int(round(_clip(score, 0, 100)))
    reasons.extend(negative[:5])
    if not reasons and not positive:
        reasons.append("시장 데이터 부족 또는 중립")
    return {"market_risk_score": score, "positive_factors": positive, "negative_factors": negative, "main_reasons": reasons}


def classify_market_regime(inputs: dict[str, Any], risk: dict[str, Any] | None = None) -> str:
    risk = risk or calculate_market_risk_score(inputs)
    score = int(risk.get("market_risk_score", 50))
    text = str(inputs.get("news_text", ""))
    has_event, _events = _has_event_risk(text)
    main_index = _safe_float(inputs.get("kospi_pct"), math.nan) if str(inputs.get("market")) == "한국주식" else _safe_float(inputs.get("nasdaq_pct"), math.nan)
    nasdaq = _safe_float(inputs.get("nasdaq_pct"), math.nan)

    if has_event and score >= 55:
        return "이벤트 변동성장"
    if score >= 75 or (not math.isnan(main_index) and main_index <= -2) or (not math.isnan(nasdaq) and nasdaq <= -2):
        return "급락장"
    if not math.isnan(main_index) and main_index >= 1.2 and score <= 35:
        return "강한 상승장"
    if not math.isnan(main_index) and main_index >= 0.3 and score <= 45:
        return "약한 상승장"
    if score >= 55 or (not math.isnan(main_index) and main_index <= -0.5):
        return "약한 하락장"
    if math.isnan(main_index) and score == 35:
        return "데이터 부족"
    return "횡보장"


def _risk_level(score: int) -> str:
    if score <= 20:
        return "위험 낮음"
    if score <= 40:
        return "보통"
    if score <= 60:
        return "주의"
    if score <= 80:
        return "위험"
    return "매우 위험"


def _candidate_file_for_market(market: str) -> Path:
    name = "swing_candidates_kr.csv" if str(market) == "한국주식" else "swing_candidates_us.csv"
    return PROJECT_ROOT / "reports" / name


def _load_candidate_breadth_context(market: str) -> dict[str, Any]:
    try:
        from core.market_breadth_engine import calculate_candidate_breadth, calculate_sector_internal_strength

        path = _candidate_file_for_market(market)
        if not path.exists() or path.stat().st_size == 0:
            return {
                "candidate_up_ratio": 0.0,
                "candidate_down_ratio": 0.0,
                "candidate_avg_change_pct": 0.0,
                "candidate_median_change_pct": 0.0,
                "candidate_volume_strength": 0.0,
                "breadth_risk_score": 50,
                "market_breadth_warning": "후보군 CSV 없음",
                "sector_spread_score": 0,
                "sector_internal_strength": [],
            }
        df = pd.read_csv(path, dtype=str).fillna("")
        breadth = calculate_candidate_breadth(df)
        sector = calculate_sector_internal_strength(df)
        breadth["sector_spread_score"] = int(sector["sector_spread_score"].iloc[0]) if not sector.empty and "sector_spread_score" in sector.columns else 0
        breadth["sector_internal_strength"] = sector.head(10).to_dict(orient="records") if not sector.empty else []
        return breadth
    except Exception as exc:
        return {
            "candidate_up_ratio": 0.0,
            "candidate_down_ratio": 0.0,
            "candidate_avg_change_pct": 0.0,
            "candidate_median_change_pct": 0.0,
            "candidate_volume_strength": 0.0,
            "breadth_risk_score": 50,
            "market_breadth_warning": f"후보군 breadth 계산 실패: {exc}",
            "sector_spread_score": 0,
            "sector_internal_strength": [],
        }


def build_market_regime_summary(market: str = "한국주식", *, write: bool = True) -> dict[str, Any]:
    try:
        inputs = load_market_inputs(market)
        breadth_ctx = _load_candidate_breadth_context(market)
        inputs.update(breadth_ctx)
        try:
            from core.market_hardblock_engine import evaluate_market_hardblock

            hardblock = evaluate_market_hardblock(inputs)
        except Exception:
            hardblock = {"market_hardblock": False, "hardblock_level": "없음", "hardblock_reasons": [], "new_buy_blocked": False}
        risk = calculate_market_risk_score(inputs)
        breadth_risk = int(_clip(_safe_float(breadth_ctx.get("breadth_risk_score"), 0), 0, 100))
        if breadth_risk >= 60:
            risk["market_risk_score"] = int(_clip(_safe_float(risk.get("market_risk_score"), 50) + min(20, breadth_risk // 5), 0, 100))
            risk.setdefault("negative_factors", []).append(f"후보군 breadth 위험 {breadth_risk}")
            risk.setdefault("main_reasons", []).append(str(breadth_ctx.get("market_breadth_warning", "후보군 breadth 악화")))
        if hardblock.get("market_hardblock"):
            risk["market_risk_score"] = int(_clip(_safe_float(risk.get("market_risk_score"), 50) + (25 if hardblock.get("hardblock_level") == "매우 강함" else 15), 0, 100))
            risk.setdefault("negative_factors", []).extend(hardblock.get("hardblock_reasons", []))
            risk.setdefault("main_reasons", []).append("시장 하드블록: " + " / ".join(hardblock.get("hardblock_reasons", []) or [hardblock.get("hardblock_level", "")]))
        regime = classify_market_regime(inputs, risk)
        score = int(risk.get("market_risk_score", 50))
    except Exception as exc:
        inputs = {"market": market, "updated_at": _now_text()}
        breadth_ctx = {}
        hardblock = {"market_hardblock": False, "hardblock_level": "없음", "hardblock_reasons": [], "new_buy_blocked": False}
        risk = {"market_risk_score": 50, "main_reasons": [f"시장상태 계산 실패: {exc}"], "positive_factors": [], "negative_factors": []}
        regime = "데이터 부족"
        score = 50

    if regime == "급락장" and score >= 80:
        penalty, down, allow = 15, 2, False
        action = "신규매수 관망, 보유종목 손절/비중 관리 우선"
    elif regime == "급락장":
        penalty, down, allow = 10, 1, False
        action = "신규매수 축소, 반등 확인 전 관망 우선"
    elif regime == "이벤트 변동성장":
        penalty, down, allow = 10, 1 if score >= 70 else 0, score < 70
        action = "이벤트 확인 전 신규매수 보수, 변동성 확대 주의"
    elif score >= 70:
        penalty, down, allow = 10, 1, False
        action = "고위험 구간, 돌파/추격매수 금지"
    elif score >= 60:
        penalty, down, allow = 7, 1, True
        action = "눌림목도 관망 우선, 소액/분할만 검토"
    else:
        penalty, down, allow = 0, 0, True
        action = "기존 판단 유지, 추격매수는 가격 확인"

    summary = {
        "updated_at": inputs.get("updated_at", _now_text()),
        "market": market,
        "market_regime": regime,
        "market_risk_score": score,
        "risk_level": _risk_level(score),
        "main_reasons": risk.get("main_reasons", []),
        "positive_factors": risk.get("positive_factors", []),
        "negative_factors": risk.get("negative_factors", []),
        "recommended_action": action,
        "new_buy_allowed": bool(allow),
        "confidence_penalty": int(penalty),
        "decision_downgrade_level": int(down),
        "kospi_change_pct": inputs.get("kospi_pct", ""),
        "kosdaq_change_pct": inputs.get("kosdaq_pct", ""),
        "nasdaq_change_pct": inputs.get("nasdaq_pct", ""),
        "sp500_change_pct": inputs.get("sp500_pct", ""),
        "russell2000_change_pct": inputs.get("russell_pct", ""),
        "semi_etf_change_pct": inputs.get("soxx_pct", inputs.get("smh_pct", "")),
        "nasdaq_future_change_pct": inputs.get("nasdaq_future_change_pct", ""),
        "sp500_future_change_pct": inputs.get("sp500_future_change_pct", ""),
        "vix_change_pct": inputs.get("vix_pct", ""),
        "us10y_change_pct": inputs.get("us10y_pct", ""),
        "usdkrw_change_pct": inputs.get("usdkrw_pct", ""),
        "dollar_index_change_pct": inputs.get("dxy_pct", ""),
        "wti_change_pct": inputs.get("wti_pct", ""),
        "bitcoin_change_pct": inputs.get("bitcoin_pct", ""),
        **{k: breadth_ctx.get(k) for k in [
            "candidate_up_ratio",
            "candidate_down_ratio",
            "candidate_avg_change_pct",
            "candidate_median_change_pct",
            "candidate_volume_strength",
            "breadth_risk_score",
            "market_breadth_warning",
            "sector_spread_score",
            "sector_internal_strength",
        ]},
        "market_hardblock": bool(hardblock.get("market_hardblock", False)),
        "hardblock_level": hardblock.get("hardblock_level", "없음"),
        "hardblock_reasons": hardblock.get("hardblock_reasons", []),
        "new_buy_blocked": bool(hardblock.get("new_buy_blocked", False)),
    }
    if summary["new_buy_blocked"]:
        summary["new_buy_allowed"] = False
    if write:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        MARKET_REGIME_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        row = {**summary}
        for col in ["main_reasons", "positive_factors", "negative_factors", "hardblock_reasons", "sector_internal_strength"]:
            row[col] = " / ".join(map(str, row.get(col, []) or []))
        hist = pd.DataFrame([row])
        if MARKET_REGIME_HISTORY.exists() and MARKET_REGIME_HISTORY.stat().st_size > 0:
            old = pd.read_csv(MARKET_REGIME_HISTORY, dtype=str).fillna("")
            hist = pd.concat([old, hist], ignore_index=True)
        hist.to_csv(MARKET_REGIME_HISTORY, index=False, encoding="utf-8-sig")
    return summary


def load_market_regime_summary(market: str = "한국주식") -> dict[str, Any]:
    for path in [MARKET_REGIME_SUMMARY, PROJECT_ROOT / "market_regime_summary.json"]:
        try:
            if path.exists() and path.stat().st_size > 0:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not market or str(data.get("market", "")) == str(market):
                    return data
        except Exception:
            continue
    return {
        "updated_at": "",
        "market": market,
        "market_regime": "데이터 부족",
        "market_risk_score": 50,
        "risk_level": "주의",
        "main_reasons": ["시장 데이터 부족으로 필터 미적용"],
        "positive_factors": [],
        "negative_factors": [],
        "recommended_action": "시장 데이터 확인 후 판단",
        "new_buy_allowed": True,
        "confidence_penalty": 0,
        "decision_downgrade_level": 0,
    }


def _infer_final_decision(text: str) -> str:
    raw = str(text or "")
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


def downgrade_final_decision(decision: str, level: int = 0, *, cap_at_watch: bool = False) -> str:
    before = _infer_final_decision(decision)
    idx = FINAL_DECISION_STEPS.index(before)
    after_idx = max(0, idx - max(0, int(level)))
    if cap_at_watch:
        after_idx = min(after_idx, FINAL_DECISION_STEPS.index("관망 우위"))
    return FINAL_DECISION_STEPS[after_idx]


def apply_market_regime_filter(
    prediction: dict[str, Any],
    ticker: str = "",
    market: str = "한국주식",
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    out = dict(prediction or {})
    summary = summary or load_market_regime_summary(market)
    regime = str(summary.get("market_regime", "데이터 부족") or "데이터 부족")
    score = int(_clip(_safe_float(summary.get("market_risk_score"), 50), 0, 100))
    before_decision = _infer_final_decision(out.get("primary_action", ""))
    before_conf = _safe_float(out.get("confidence_score"), math.nan)
    reason_parts = list(map(str, summary.get("main_reasons", []) or []))
    penalty = int(_clip(_safe_float(summary.get("confidence_penalty"), 0), 0, 25))
    downgrade = int(_clip(_safe_float(summary.get("decision_downgrade_level"), 0), 0, 2))
    cap_watch = False

    if regime == "급락장":
        downgrade = max(downgrade, 1)
        reason_parts.append("급락장 신규매수 판단 하향")
        if score >= 80:
            cap_watch = True
            reason_parts.append("급락장 위험점수 80 이상: 관망 이하 제한")
    if regime == "이벤트 변동성장":
        penalty = max(penalty, 10 if score >= 70 else 5)
        reason_parts.append("이벤트 변동성장 신뢰도 감점")
    if score >= 70 and before_decision == "돌파 확인 후 접근":
        cap_watch = True
        reason_parts.append("시장위험 70 이상: 돌파 접근 관망 하향")
    if score >= 60 and before_decision == "눌림목 매수 가능":
        cap_watch = True
        reason_parts.append("시장위험 60 이상: 눌림목 매수 관망 하향")

    adj = find_adjustment(ticker, market)
    direction_hit_rate = _safe_float((adj or {}).get("direction_hit_rate"), math.nan)
    if score >= 80 and before_decision == "관망 우위" and not math.isnan(direction_hit_rate) and direction_hit_rate < 45:
        downgrade = max(downgrade, 1)
        reason_parts.append("고위험장 + 종목 방향 적중률 낮음: 비중 축소 우선")

    after_decision = downgrade_final_decision(before_decision, downgrade, cap_at_watch=cap_watch)
    if not math.isnan(before_conf):
        out["confidence_score"] = int(_clip(before_conf - penalty, 0, 100))
    after_conf = _safe_float(out.get("confidence_score"), math.nan)
    applied = bool(after_decision != before_decision or penalty > 0 or regime in {"급락장", "이벤트 변동성장"} or score >= 60)
    if regime in {"데이터 부족", "중립"} and score == 50:
        applied = False
        reason = "시장 데이터 부족으로 필터 미적용"
    else:
        reason = " / ".join(dict.fromkeys([x for x in reason_parts if x])) or "시장 필터 적용 조건 없음"

    out["primary_action"] = after_decision
    no_buy = str(out.get("no_buy_flags", "") or "")
    if applied and (score >= 60 or regime in {"급락장", "이벤트 변동성장"}):
        msg = f"시장 필터: {regime} · 위험점수 {score} · {reason}"
        if isinstance(out.get("no_buy_flags"), list):
            if msg not in out["no_buy_flags"]:
                out["no_buy_flags"].append(msg)
        elif msg not in no_buy:
            out["no_buy_flags"] = (no_buy + " | " + msg).strip(" |")

    out.update(
        {
            "market_regime": regime,
            "market_risk_score": score,
            "market_filter_applied": int(applied),
            "market_filter_reason": reason,
            "final_decision_before_market_filter": before_decision,
            "final_decision_after_market_filter": after_decision,
            "confidence_score_before_market_filter": "" if math.isnan(before_conf) else before_conf,
            "confidence_score_after_market_filter": "" if math.isnan(after_conf) else after_conf,
            "no_buy_market_reason": reason if applied else "",
        }
    )
    return out


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default="한국주식")
    args = parser.parse_args()
    print(json.dumps(build_market_regime_summary(args.market, write=True), ensure_ascii=False, indent=2))
