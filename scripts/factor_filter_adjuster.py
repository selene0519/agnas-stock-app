"""팩터 회귀결과 → 필터 임계값 자동 조정.

factor_attribution.json의 회귀계수가 통계적으로 유의하면
generate_kr/us_recommendations.py에서 읽는 필터 임계값을 조정한다.

출력: reports/factor_based_filter_adjustments.json

조정 원칙 (보수적):
- R² < 0.03 또는 샘플 < 30건이면 조정 없음 (기본값 유지)
- RSI 계수 < -0.05 (높은 RSI → 낮은 수익): RSI 상한 2pt 낮춤
- RSI 계수 > +0.05 (높은 RSI → 높은 수익): RSI 상한 2pt 높임 (최대 82)
- volumeRatio 계수 > +0.02: 최소 거래량 비율 0.05 올림
- volumeRatio 계수 < -0.02: 최소 거래량 비율 0.05 내림
- distToMa20 계수 < -0.05: 최대 이격도 1pt 낮춤
- momentum5 계수 > +0.05: 임계값 없이 태그만 추가
각 방향 최대 ±3회 누적 (과도한 드리프트 방지).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTOR_JSON = ROOT / "reports" / "factor_attribution.json"
OUT_JSON    = ROOT / "reports" / "factor_based_filter_adjustments.json"

# 기본 필터값 (generate_kr/us_recommendations.py와 동일)
_DEFAULTS: dict[str, Any] = {
    "rsi_upper": {"conservative": 72, "balanced": 75, "aggressive": 78},
    "rsi_lower": {"conservative": 38, "balanced": 35, "aggressive": 30},
    "min_volume_ratio": {"conservative": 0.7, "balanced": 0.5, "aggressive": 0.3},
    "d20_max": {"short": 10, "swing": 12, "mid": 15},
}

# 조정 한계 (기본값에서 최대 ±이 값 이내)
_MAX_DELTA: dict[str, float] = {
    "rsi_upper":       6.0,
    "min_volume_ratio": 0.20,
    "d20_max":         4.0,
}

# 조정 단위
_STEP: dict[str, float] = {
    "rsi_upper":        2.0,
    "min_volume_ratio": 0.05,
    "d20_max":          1.0,
}


def _clamp_delta(current: float, default: float, max_delta: float, step: float, direction: int) -> float:
    """direction: +1 or -1. 최대 max_delta 내로 clamp."""
    new_val = current + direction * step
    if direction > 0:
        new_val = min(new_val, default + max_delta)
    else:
        new_val = max(new_val, default - max_delta)
    return round(new_val, 2)


def run() -> dict[str, Any]:
    if not FACTOR_JSON.exists():
        return {"status": "NO_FACTOR_JSON", "adjustments": {}}

    fa = json.loads(FACTOR_JSON.read_text(encoding="utf-8"))
    reg = fa.get("regressionFactors", {})
    ols_n = fa.get("olsSampleSize", 0)

    if "note" in reg or ols_n < 30:
        return {
            "status":      "INSUFFICIENT_DATA",
            "olsSamples":  ols_n,
            "message":     f"샘플 {ols_n}건 — 최소 30건 필요. 조정 없음.",
            "adjustments": {},
        }

    r2 = reg.get("rsi", {}).get("r2", 0)
    if r2 < 0.03:
        return {
            "status":      "LOW_R2",
            "r2":          r2,
            "message":     f"R²={r2:.4f} 미약 — 조정 없음 (최소 0.03 필요).",
            "adjustments": {},
        }

    rsi_coef  = reg.get("rsi", {}).get("coefficient", 0)
    vr_coef   = reg.get("volumeRatio", {}).get("coefficient", 0)
    d20_coef  = reg.get("distToMa20", {}).get("coefficient", 0)
    mom5_coef = reg.get("momentum5", {}).get("coefficient", 0)

    # 기존 조정값 로드 (누적용)
    existing: dict[str, Any] = {}
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("adjustments", {})
        except Exception:
            pass

    adj: dict[str, Any] = dict(existing)  # 기존값 복사 후 업데이트

    # ── RSI 상한 조정 ─────────────────────────────────────────────────────
    # 높은 RSI → 낮은 수익이면 상한 낮춤, 높은 수익이면 상한 높임
    for mode in ("conservative", "balanced", "aggressive"):
        default = float(_DEFAULTS["rsi_upper"][mode])
        current = float(adj.get(f"rsi_upper_{mode}", default))
        if abs(rsi_coef) > 0.05:
            direction = -1 if rsi_coef < 0 else +1
            adj[f"rsi_upper_{mode}"] = _clamp_delta(
                current, default, _MAX_DELTA["rsi_upper"], _STEP["rsi_upper"], direction
            )

    # ── 거래량 비율 최소값 조정 ───────────────────────────────────────────
    for mode in ("conservative", "balanced", "aggressive"):
        default = float(_DEFAULTS["min_volume_ratio"][mode])
        current = float(adj.get(f"min_vr_{mode}", default))
        if abs(vr_coef) > 0.02:
            direction = +1 if vr_coef > 0 else -1
            adj[f"min_vr_{mode}"] = _clamp_delta(
                current, default, _MAX_DELTA["min_volume_ratio"], _STEP["min_volume_ratio"], direction
            )

    # ── 이격도 최대값 조정 ───────────────────────────────────────────────
    for horizon in ("short", "swing", "mid"):
        default = float(_DEFAULTS["d20_max"][horizon])
        current = float(adj.get(f"d20_max_{horizon}", default))
        if abs(d20_coef) > 0.05:
            direction = -1 if d20_coef < 0 else +1
            adj[f"d20_max_{horizon}"] = _clamp_delta(
                current, default, _MAX_DELTA["d20_max"], _STEP["d20_max"], direction
            )

    # 모멘텀 인사이트 태그만 기록 (필터값 조정 없음)
    adj["momentum5_insight"] = (
        "양의 모멘텀이 수익 기여" if mom5_coef > 0.05
        else "음의 모멘텀이 수익 기여" if mom5_coef < -0.05
        else "모멘텀 영향 미미"
    )

    result = {
        "updatedAt":      datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "basedOnR2":      round(r2, 4),
        "olsSamples":     ols_n,
        "rsiCoefficient": round(rsi_coef, 4),
        "vrCoefficient":  round(vr_coef, 4),
        "d20Coefficient": round(d20_coef, 4),
        "mom5Coefficient": round(mom5_coef, 4),
        "adjustments":    adj,
        "status":         "APPLIED",
    }
    return result


def main() -> None:
    result = run()
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    status = result.get("status", "?")
    print(f"[factor_filter_adjuster] status={status}")
    if status == "APPLIED":
        print(f"  R²={result.get('basedOnR2')}, samples={result.get('olsSamples')}")
        for k, v in result.get("adjustments", {}).items():
            print(f"  {k}: {v}")
    else:
        print(f"  {result.get('message', '')}")


if __name__ == "__main__":
    main()
