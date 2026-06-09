"""adaptive_weights.py — 자가보정(adaptive score) 서비스 (5차 작업)

검증 결과(virtual_prediction_ledger / virtual_validation_results)에서
신호별 성과를 집계하고 추천 점수에 보정값을 반영합니다.

주요 함수:
    compute_adaptive_weights(validation_results) -> list[dict]
    load_adaptive_weights() -> dict
    get_adjustment(signal_key, market, horizon, mode) -> float
    save_adaptive_weights(weights)
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 경로 상수
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_DIR = REPO_ROOT / "data"
ADAPTIVE_WEIGHT_CSV = DATA_DIR / "adaptive_weight_table.csv"

# ---------------------------------------------------------------------------
# CSV 스키마
# ---------------------------------------------------------------------------

WEIGHT_FIELDS = [
    "signalKey",
    "signalType",
    "market",
    "horizon",
    "mode",
    "sampleCount",
    "winRate",
    "avgReturn",
    "avgLoss",
    "expectedValue",
    "mdd",
    "riskRewardRatio",
    "adjustment",
    "confidence",
    "lastUpdated",
    "learningEligible",
]

# ---------------------------------------------------------------------------
# 보정 제한 정책
# ---------------------------------------------------------------------------

MIN_SAMPLE_ANY = 30          # sampleCount < 30 → learningEligible=False, adjustment=0
MIN_SAMPLE_FULL = 100        # sampleCount >= 100 → 최대 ±3
MAX_ADJ_LOW = 1.5            # 30 <= n < 100 → 최대 ±1.5
MAX_ADJ_HIGH = 3.0           # n >= 100 → 최대 ±3
MAX_TOTAL_ADJ = 8.0          # 총합 절대값 상한
MAX_SAMPLES_PER_SYMBOL = 3   # 특정 종목 1개가 가중치를 지배하지 않도록

# ---------------------------------------------------------------------------
# 신호 키 분류
# ---------------------------------------------------------------------------

CHART_SIGNAL_TYPES: dict[str, str] = {
    "support_near": "support_signal",
    "resistance_break": "resistance_signal",
    "trendline_hold": "trendline_signal",
    "falling_trendline_break": "trendline_signal",
    "failed_anchor_history": "trendline_signal",
    "fake_breakout_risk": "fake_breakout_signal",
    "volume_or_resistance_overhead": "resistance_signal",
}

EVENT_SIGNAL_TYPES: dict[str, str] = {
    "positive_news": "news_event",
    "negative_news": "news_event",
    "positive_disclosure": "disclosure_event",
    "negative_disclosure": "disclosure_event",
    "earnings_beat": "earnings_event",
    "earnings_miss": "earnings_event",
    "guidance_up": "earnings_event",
    "guidance_down": "earnings_event",
    "fomc_risk": "macro_event",
    "rate_risk": "macro_event",
    "inflation_risk": "macro_event",
    "volatility_risk": "macro_event",
    "sector_strong": "sector_event",
    "sector_weak": "sector_event",
}


def _signal_type(signal_key: str) -> str:
    """신호 키에서 signalType 반환."""
    bare = signal_key.split("__")[0]
    if bare in CHART_SIGNAL_TYPES:
        return CHART_SIGNAL_TYPES[bare]
    if bare in EVENT_SIGNAL_TYPES:
        return EVENT_SIGNAL_TYPES[bare]
    if "chart_signal" in bare:
        return "chart_signal"
    if "trendline" in bare:
        return "trendline_signal"
    if "support" in bare:
        return "support_signal"
    if "resistance" in bare:
        return "resistance_signal"
    if "fake_breakout" in bare:
        return "fake_breakout_signal"
    if any(k in bare for k in ("news", "gnews")):
        return "news_event"
    if any(k in bare for k in ("disclosure", "dart")):
        return "disclosure_event"
    if any(k in bare for k in ("earnings", "eps", "guidance")):
        return "earnings_event"
    if any(k in bare for k in ("fomc", "rate", "macro", "cpi", "ppi", "pce")):
        return "macro_event"
    if "sector" in bare:
        return "sector_event"
    return "data_source"


def _make_signal_keys(row: dict[str, Any]) -> list[str]:
    """검증 행에서 활성화된 신호 키 목록을 추출."""
    keys: list[str] = []
    market = str(row.get("market", "")).lower() or "all"
    horizon = str(row.get("horizon", "")).lower() or "all"
    mode = str(row.get("mode", "")).lower() or "all"

    used_signals = row.get("usedSignals") or []
    if isinstance(used_signals, str):
        used_signals = [s.strip() for s in used_signals.split(",") if s.strip()]
    for sig in used_signals:
        if sig:
            dim = f"{market}_{horizon}_{mode}"
            keys.append(f"chart_signal_{dim}_{sig}")

    for tag_field in ("newsEventTag", "disclosureEventTag", "earningsEventTag",
                      "macroEventTag", "sectorEventTag"):
        tag = str(row.get(tag_field) or "").lower()
        if tag and tag not in {"unknown", "none", "neutral", ""}:
            dim = f"{market}_{horizon}_{mode}"
            keys.append(f"event_{tag}_{dim}")

    return keys


def _safe_float(value: Any) -> float | None:
    try:
        v = float(str(value).replace(",", "").strip())
        return v if math.isfinite(v) else None
    except Exception:
        return None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# 핵심 함수: compute_adaptive_weights
# ---------------------------------------------------------------------------

def compute_adaptive_weights(validation_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """검증 결과에서 신호별 성과를 집계해 weight 행 목록을 반환.

    - actual_ohlcv 소스 기반 결과만 학습 (fallback/mock/placeholder 제외)
    - 특정 종목이 전체 가중치를 지배하지 않도록 symbol당 최대 MAX_SAMPLES_PER_SYMBOL 행만 반영
    """
    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "returns": [], "losses": [], "wins": 0, "total": 0,
        "market": "all", "horizon": "all", "mode": "all",
    })
    symbol_counts: dict[tuple[str, str], int] = defaultdict(int)

    for row in validation_results:
        data_src = str(row.get("dataSourceType") or row.get("chartDataSourceType") or "").lower()
        ohlcv_src = str(row.get("ohlcvSource") or "").lower()

        is_actual = (
            data_src == "actual_ohlcv"
            or "actual_ohlcv" in ohlcv_src
        )
        if any(k in data_src for k in ("mock", "fallback", "placeholder", "unavailable")):
            is_actual = False
        if not is_actual:
            continue

        symbol = str(row.get("symbol") or "")
        market = str(row.get("market") or "all").lower()
        sym_key = (market, symbol)
        if symbol_counts[sym_key] >= MAX_SAMPLES_PER_SYMBOL:
            continue
        symbol_counts[sym_key] += 1

        pnl = _safe_float(row.get("pnlPct") or row.get("returnPct") or row.get("virtual_return_pct"))
        filled = str(row.get("filled") or row.get("isExecuted") or "").lower() in {"true", "1", "yes"}
        if not filled or pnl is None:
            continue

        signal_keys = _make_signal_keys(row)
        if not signal_keys:
            signal_keys = [f"baseline_{market}_{row.get('horizon','all')}_{row.get('mode','all')}"]

        for key in signal_keys:
            b = buckets[key]
            b["total"] += 1
            b["market"] = market
            b["horizon"] = str(row.get("horizon") or "all").lower()
            b["mode"] = str(row.get("mode") or "all").lower()
            if pnl >= 0:
                b["wins"] += 1
                b["returns"].append(pnl)
            else:
                b["losses"].append(pnl)

    weights: list[dict[str, Any]] = []
    for key, b in buckets.items():
        n = b["total"]
        if n == 0:
            continue

        eligible = n >= MIN_SAMPLE_ANY
        win_rate = b["wins"] / n if n > 0 else 0.0
        all_pnl = b["returns"] + b["losses"]
        avg_ret = sum(b["returns"]) / len(b["returns"]) if b["returns"] else 0.0
        avg_loss = sum(b["losses"]) / len(b["losses"]) if b["losses"] else 0.0
        ev = win_rate * avg_ret + (1 - win_rate) * avg_loss
        mdd = min(all_pnl) if all_pnl else 0.0
        rr = abs(avg_ret / avg_loss) if avg_loss != 0 else (avg_ret if avg_ret > 0 else 0.0)

        if not eligible:
            adjustment = 0.0
            confidence = 0.0
        else:
            max_adj = MAX_ADJ_HIGH if n >= MIN_SAMPLE_FULL else MAX_ADJ_LOW
            raw_adj = ev * 0.5
            if win_rate >= 0.6:
                raw_adj += (win_rate - 0.6) * 5.0
            elif win_rate <= 0.4:
                raw_adj -= (0.4 - win_rate) * 5.0
            adjustment = float(_clamp(raw_adj, -max_adj, max_adj))
            conf_base = min(n / 200, 1.0)
            conf_ev = min(abs(ev) / 10.0, 0.5)
            confidence = float(_clamp(conf_base + conf_ev, 0.0, 1.0))

        weights.append({
            "signalKey": key,
            "signalType": _signal_type(key),
            "market": b["market"],
            "horizon": b["horizon"],
            "mode": b["mode"],
            "sampleCount": n,
            "winRate": round(win_rate, 4),
            "avgReturn": round(avg_ret, 4),
            "avgLoss": round(avg_loss, 4),
            "expectedValue": round(ev, 4),
            "mdd": round(mdd, 4),
            "riskRewardRatio": round(rr, 4),
            "adjustment": round(adjustment, 4),
            "confidence": round(confidence, 4),
            "lastUpdated": _now(),
            "learningEligible": eligible,
        })

    return weights


# ---------------------------------------------------------------------------
# load / save
# ---------------------------------------------------------------------------

def load_adaptive_weights() -> dict[str, dict[str, Any]]:
    """CSV에서 weight table을 로드해 signalKey 기반 dict로 반환."""
    if not ADAPTIVE_WEIGHT_CSV.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        with open(ADAPTIVE_WEIGHT_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get("signalKey", "").strip()
                if not key:
                    continue
                result[key] = {
                    "signalKey": key,
                    "signalType": row.get("signalType", ""),
                    "market": row.get("market", "all"),
                    "horizon": row.get("horizon", "all"),
                    "mode": row.get("mode", "all"),
                    "sampleCount": int(row.get("sampleCount") or 0),
                    "winRate": _safe_float(row.get("winRate")) or 0.0,
                    "avgReturn": _safe_float(row.get("avgReturn")) or 0.0,
                    "avgLoss": _safe_float(row.get("avgLoss")) or 0.0,
                    "expectedValue": _safe_float(row.get("expectedValue")) or 0.0,
                    "mdd": _safe_float(row.get("mdd")) or 0.0,
                    "riskRewardRatio": _safe_float(row.get("riskRewardRatio")) or 0.0,
                    "adjustment": _safe_float(row.get("adjustment")) or 0.0,
                    "confidence": _safe_float(row.get("confidence")) or 0.0,
                    "lastUpdated": row.get("lastUpdated", ""),
                    "learningEligible": str(row.get("learningEligible", "")).lower() in {"true", "1", "yes"},
                }
    except Exception:
        return {}
    return result


def save_adaptive_weights(weights: list[dict[str, Any]]) -> None:
    """weight 목록을 CSV로 저장."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(ADAPTIVE_WEIGHT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=WEIGHT_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(weights)


# ---------------------------------------------------------------------------
# 조회 함수
# ---------------------------------------------------------------------------

def get_adjustment(
    signal_key: str,
    market: str = "all",
    horizon: str = "all",
    mode: str = "all",
) -> float:
    """특정 신호의 보정값 반환. 조건 불충족이면 0.0 반환."""
    table = load_adaptive_weights()
    if signal_key in table:
        row = table[signal_key]
        if not row.get("learningEligible"):
            return 0.0
        return float(row.get("adjustment") or 0.0)

    candidates: list[tuple[int, dict[str, Any]]] = []
    bare = signal_key.split("__")[0]
    for key, row in table.items():
        if bare not in key:
            continue
        if not row.get("learningEligible"):
            continue
        match_score = 0
        if row.get("market") in {market, "all"}:
            match_score += 1
        if row.get("horizon") in {horizon, "all"}:
            match_score += 1
        if row.get("mode") in {mode, "all"}:
            match_score += 1
        candidates.append((match_score, row))

    if not candidates:
        return 0.0
    best = max(candidates, key=lambda x: x[0])
    return float(best[1].get("adjustment") or 0.0)


# ---------------------------------------------------------------------------
# 추천 행에 adaptive 필드 적용
# ---------------------------------------------------------------------------

def apply_adaptive_adjustment(
    row: dict[str, Any],
    weight_table: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """추천 행에 adaptive 보정 필드를 추가해 반환.

    weight_table이 None이면 CSV에서 로드합니다.
    실제 반영 조건:
      - actual_ohlcv 기반 검증 결과에서 학습된 weight만 적용
      - 개별 ±3, 총합 ±8 제한
    """
    if weight_table is None:
        weight_table = load_adaptive_weights()

    market = str(row.get("market") or "all").lower()
    horizon = str(row.get("horizon") or "all").lower()
    mode = str(row.get("mode") or "all").lower()

    if not weight_table:
        return {
            **row,
            "adaptiveScoreUsed": False,
            "adaptiveScoreAdjustment": 0.0,
            "adaptiveScoreSummary": "",
            "adaptiveSignalBreakdown": {},
            "adaptiveConfidence": 0.0,
            "adaptiveLearningStatus": "LOW_SAMPLE",
        }

    used_signals: list[str] = []
    chart_signal_summary = row.get("chartSignalSummary", {})
    if isinstance(chart_signal_summary, dict):
        raw_used = chart_signal_summary.get("usedSignals") or []
        if isinstance(raw_used, list):
            used_signals.extend(raw_used)

    for field in ("usedSignals", "chartUsedSignals"):
        v = row.get(field)
        if isinstance(v, list):
            used_signals.extend(v)
        elif isinstance(v, str) and v:
            used_signals.extend(s.strip() for s in v.split(",") if s.strip())

    for tag_field in ("newsEventTag", "disclosureEventTag", "earningsEventTag",
                      "macroEventTag", "sectorEventTag"):
        tag = str(row.get(tag_field) or "").lower()
        if tag and tag not in {"unknown", "none", "neutral", ""}:
            used_signals.append(tag)

    breakdown: dict[str, float] = {}
    total_adj = 0.0
    total_conf = 0.0
    eligible_count = 0

    for sig in used_signals:
        if not sig:
            continue
        dim_key = f"chart_signal_{market}_{horizon}_{mode}_{sig}"
        event_key = f"event_{sig}_{market}_{horizon}_{mode}"

        adj = 0.0
        conf = 0.0
        matched_key = ""
        for candidate_key in (dim_key, event_key, sig):
            if candidate_key in weight_table:
                w = weight_table[candidate_key]
                if w.get("learningEligible"):
                    adj = float(w.get("adjustment") or 0.0)
                    conf = float(w.get("confidence") or 0.0)
                    matched_key = candidate_key
                    break

        if matched_key and adj != 0.0:
            clamped = float(_clamp(adj, -MAX_ADJ_HIGH, MAX_ADJ_HIGH))
            breakdown[sig] = round(clamped, 2)
            total_adj += clamped
            total_conf += conf
            eligible_count += 1

    if total_adj > MAX_TOTAL_ADJ:
        total_adj = MAX_TOTAL_ADJ
    elif total_adj < -MAX_TOTAL_ADJ:
        total_adj = -MAX_TOTAL_ADJ
    total_adj = round(total_adj, 2)

    avg_conf = round(total_conf / eligible_count, 4) if eligible_count > 0 else 0.0

    if not weight_table:
        status = "DATA_INSUFFICIENT"
    elif eligible_count == 0:
        status = "LOW_SAMPLE"
    else:
        status = "ACTIVE"

    summary_parts = [f"{sig}{adj:+.2f}" for sig, adj in breakdown.items() if adj != 0.0]
    summary = ", ".join(summary_parts[:6])

    return {
        **row,
        "adaptiveScoreUsed": eligible_count > 0,
        "adaptiveScoreAdjustment": total_adj,
        "adaptiveScoreSummary": summary,
        "adaptiveSignalBreakdown": breakdown,
        "adaptiveConfidence": avg_conf,
        "adaptiveLearningStatus": status,
    }


# ---------------------------------------------------------------------------
# 요약 집계 (API 노출용)
# ---------------------------------------------------------------------------

def weight_summary(weight_table: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """weight table을 다차원으로 집계한 요약 반환."""
    if weight_table is None:
        weight_table = load_adaptive_weights()

    by_signal_key: list[dict[str, Any]] = sorted(
        weight_table.values(),
        key=lambda r: abs(float(r.get("adjustment") or 0)),
        reverse=True,
    )
    by_signal_type: dict[str, list[float]] = defaultdict(list)
    by_horizon: dict[str, list[float]] = defaultdict(list)
    by_mode: dict[str, list[float]] = defaultdict(list)
    by_market: dict[str, list[float]] = defaultdict(list)

    for r in weight_table.values():
        if not r.get("learningEligible"):
            continue
        adj = float(r.get("adjustment") or 0.0)
        by_signal_type[r.get("signalType", "unknown")].append(adj)
        by_horizon[r.get("horizon", "all")].append(adj)
        by_mode[r.get("mode", "all")].append(adj)
        by_market[r.get("market", "all")].append(adj)

    def _agg(d: dict[str, list[float]]) -> dict[str, Any]:
        return {
            k: {"count": len(v), "avgAdjustment": round(sum(v) / len(v), 3) if v else 0.0}
            for k, v in d.items()
        }

    return {
        "totalSignals": len(weight_table),
        "eligibleSignals": sum(1 for r in weight_table.values() if r.get("learningEligible")),
        "bySignalKey": by_signal_key[:50],
        "bySignalType": _agg(by_signal_type),
        "byHorizon": _agg(by_horizon),
        "byMode": _agg(by_mode),
        "byMarket": _agg(by_market),
    }
