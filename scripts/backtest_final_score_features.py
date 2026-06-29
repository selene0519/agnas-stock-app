"""
_final_score()(scripts/generate_kr_recommendations.py)를 구성하는 7개 하위 피처
(upsideScore/riskScore/momentumScore/entryScore/rrScore/qualityScore/newsRiskPenalty)
가 각각 따로 미래 수익률과 상관이 있는지 진단한다.

배경: scripts/backtest_price_band_design.py에서 청산 가격(stop/target) 배수를 바꿔도
평균수익이 거의 안 변한다는 결과가 나왔다 — 후보를 고르는 신호(_final_score) 자체에
엣지가 약하다는 뜻일 가능성이 크다는 결론이었다. 이 스크립트는 그 결론을 검증하기 위해
_final_score 전체가 아니라 그걸 구성하는 피처를 하나씩 떼어서 본다 — 어떤 피처가
실제로 정보력이 있는지, 어떤 피처는 점수만 높고 성과가 없는지, 어떤 피처는 오히려
역효과인지.

중요: 이 결과를 보고 바로 _MODE_WEIGHTS를 다시 튜닝하지 않는다. 이건 진단이고,
가중치를 만지는 건 별도의, 더 조심스러운 단계다(과적합 위험).

방법: cutoff(5거래일 간격) x 전체 US 유니버스에 대해 _sub_scores()를 계산하고,
시장 레짐(BULL/BEAR/SIDE)별로 나눠서 각 피처의 forward return(3/5/10/20일) 상관을 본다.

출력: docs/validation/final_score_feature_diagnostics_us.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts.generate_kr_recommendations import indicators, _sub_scores  # noqa: E402
from scripts.generate_us_recommendations import _load_us_ohlcv  # noqa: E402
from scripts.backtest_band_calibration import _slice_rows, _cutoff_dates, _index_regime_at  # noqa: E402
from scripts.backtest_pre_rise_score import _future_closes, _multi_horizon_stats, _spearman, HORIZONS  # noqa: E402

OHLCV_ALL = _load_us_ohlcv()
FEATURES = ("upsideScore", "riskScore", "momentumScore", "entryScore", "rrScore",
            "qualityScore", "newsRiskPenalty")


def main() -> None:
    cutoffs = _cutoff_dates()
    samples: list[dict[str, Any]] = []

    for cutoff in cutoffs:
        regime = _index_regime_at(cutoff)["regime"]
        for sym, rows in OHLCV_ALL.items():
            if sym in {"SPY", "QQQ", "DIA"}:
                continue
            past = _slice_rows(rows, cutoff)
            if len(past) < 60:
                continue
            ind = indicators(past)
            current = ind.get("latest")
            if not current or current <= 0:
                continue
            future_closes = _future_closes(rows, cutoff)
            if len(future_closes) < min(HORIZONS):
                continue
            base_close = past[-1].get("close")
            base_close = float(base_close) if base_close else current
            mh = _multi_horizon_stats(base_close, future_closes)

            sub = _sub_scores(ind)
            sample: dict[str, Any] = {"symbol": sym, "regime": regime, **sub}
            for h in HORIZONS:
                sample[f"return_{h}d"] = mh[h]["return"]
            samples.append(sample)

    if not samples:
        print("샘플 없음")
        return

    def _corr_block(rows_subset: list[dict]) -> dict[str, Any]:
        return {
            feat: {
                f"{h}d": _spearman(rows_subset, feat, f"return_{h}d")
                for h in HORIZONS
            }
            for feat in FEATURES
        }

    out: dict[str, Any] = {
        "generatedAt": datetime.now().isoformat(timespec="seconds"),
        "cutoffDates": len(cutoffs),
        "horizonsTested": list(HORIZONS),
        "sampleCount": len(samples),
        "overall": _corr_block(samples),
        "byRegime": {},
    }
    for regime in sorted({s["regime"] for s in samples}):
        subset = [s for s in samples if s["regime"] == regime]
        out["byRegime"][regime] = {"n": len(subset), **_corr_block(subset)}

    path = ROOT / "docs" / "validation" / "final_score_feature_diagnostics_us.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
