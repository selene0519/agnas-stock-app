"""
밴드를 완화해도(scripts/backtest_band_calibration.py 참고) 평균수익이 대부분 0 근처에
머무는 더 근본적인 문제 — entry/stop/target 가격 공식(_price_band의 ATR 배수) 자체가
실제로 엣지가 있는지를 진단하고, 대안 배수를 같은 방식(운영 코드 공유 + 과거 재현)으로
검증한다.

방법: backtest_band_calibration.py와 같은 105개 cutoff·필터·평가 엔진을 재사용하되,
1) 현재 ATR 배수로 실행해서 청산 이유별(목표도달/손절/기간종료) 빈도·평균수익을 분리해
   "왜 평균이 0 근처인지" 먼저 진단하고,
2) _price_band()의 새 atr_mult_override 파라미터로 대안 배수 몇 개를 같은 방식으로
   검증해 비교한다.

출력: reports/price_band_design_us.json
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

from app.engine.backtest_v2 import evaluate_recommendation  # noqa: E402

from scripts.generate_kr_recommendations import indicators, _final_score, _price_band  # noqa: E402
from scripts.generate_us_recommendations import (  # noqa: E402
    passes_us_quality_filters, _load_us_ohlcv, _load_us_sector_map,
)
from scripts.backtest_band_calibration import (  # noqa: E402
    _slice_rows, _index_regime_at, _cutoff_dates,
)

OHLCV_ALL = _load_us_ohlcv()
SECTOR_MAP = _load_us_sector_map()
MODES = ("conservative", "balanced")
HORIZONS = ("short", "swing", "mid")

CURRENT_ATR_MULT = {"short": (1.2, 2.8), "swing": (1.5, 4.5), "mid": (2.0, 5.5)}

# 후보 대안: (이름, {horizon: (stop_mult, target_mult)})
# 1차 진단(현재 배수)에서: 손절 빈도 33~42%(평균 -4~-5%)가 목표도달 빈도 5~6%(평균 +10~15%)
# 보다 훨씬 잦고, 기간종료(절반 이상)는 평균 +1~3%로 약하게만 양수 — 손절이 노이즈에
# 너무 자주 걸리는 것으로 보여 "손절을 넓히는" 방향도 같이 검증한다.
CANDIDATE_ATR_MULTS: list[tuple[str, dict[str, tuple[float, float]]]] = [
    ("current",            CURRENT_ATR_MULT),
    ("tighter_target",      {"short": (1.2, 1.8), "swing": (1.5, 2.6), "mid": (2.0, 3.2)}),
    ("tighter_stop",         {"short": (0.8, 2.8), "swing": (1.0, 4.5), "mid": (1.4, 5.5)}),
    ("wider_stop",            {"short": (1.8, 2.8), "swing": (2.2, 4.5), "mid": (2.8, 5.5)}),
    ("wider_stop_closer_target", {"short": (1.8, 2.2), "swing": (2.2, 3.2), "mid": (2.8, 4.0)}),
]


def _run_one(mode: str, horizon: str, atr_mult: dict[str, tuple[float, float]]) -> dict[str, Any]:
    import pandas as pd

    cutoffs = _cutoff_dates()
    results: list[dict] = []
    for cutoff in cutoffs:
        regime = _index_regime_at(cutoff)
        if regime["regime"] == "BEAR" and mode == "aggressive":
            continue
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
            score = _final_score(ind, mode, horizon)
            adj = max(0.0, min(100.0, score + regime["scoreAdjust"]))
            if adj < 50.0:
                continue
            sector = SECTOR_MAP.get(sym, "Unknown")
            passed, _ = passes_us_quality_filters(ind, sector, mode, horizon, {}, 99)
            if not passed:
                continue
            entry, stop, target, *_ = _price_band(adj, current, mode, horizon, ind, atr_mult_override=atr_mult)
            rec = {
                "symbol": sym, "market": "us", "entry": entry, "stop": stop, "target": target,
                "generatedAt": cutoff, "priceSession": "CLOSING",
            }
            df = pd.DataFrame(rows)
            df.columns = [str(c).lower() for c in df.columns]
            out = evaluate_recommendation(rec, df, {"slippage_pct": 0.001}, horizon)
            if out.get("filled"):
                results.append(out)

    by_reason: dict[str, dict[str, Any]] = {}
    for reason in ("목표도달", "손절", "손절(동시터치)", "기간종료"):
        rows_r = [r for r in results if str(r.get("exitStatus")) == reason]
        rets = [r["netPnlPct"] for r in rows_r if r.get("netPnlPct") is not None]
        by_reason[reason] = {
            "count": len(rows_r),
            "avgNetPnlPct": round(sum(rets) / len(rets), 3) if rets else None,
        }

    all_rets = [r["netPnlPct"] for r in results if r.get("netPnlPct") is not None]
    wins = [r for r in all_rets if r > 0]
    return {
        "trades": len(results),
        "winRateByReturn": round(len(wins) / len(all_rets), 4) if all_rets else None,
        "avgNetPnlPct": round(sum(all_rets) / len(all_rets), 3) if all_rets else None,
        "byExitReason": by_reason,
    }


def main() -> None:
    out: dict[str, Any] = {"generatedAt": datetime.now().isoformat(timespec="seconds"), "cutoffDates": len(_cutoff_dates()), "results": {}}
    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            out["results"][key] = {}
            for name, atr_mult in CANDIDATE_ATR_MULTS:
                print(f"[{key}] {name} 배수 백테스트 중...")
                res = _run_one(mode, horizon, atr_mult)
                out["results"][key][name] = res
                print(f"  {name:16s}: {res}")
    path = ROOT / "reports" / "price_band_design_us.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
