"""
US conservative/balanced 추천 가뭄(2~12건, aggressive는 20건 꽉 참)이 RSI/거래량
밴드가 실제로 너무 좁아서인지, 적절한 보수성인지를 과거 데이터로 검증한다.

방법:
- 과거 cutoff 날짜를 5거래일 간격으로 훑으면서, 그 시점까지의 OHLCV만 사용해
  (미래 데이터 누출 없음) 지수 레짐 감지 + 지표 계산을 재현한다.
- passes_us_quality_filters()(운영 스크립트와 100% 같은 함수)를 캘리브레이션 이전 밴드와
  현재(이후) 밴드 두 가지로 각각 적용해 통과 종목을 추린다.
- 통과한 종목은 _price_band()로 entry/stop/target을 만들고, backtest_v2.evaluate_recommendation
  (운영 백테스트 엔진과 동일)으로 실제 체결/승패를 채점한다.
- 같은 필터/평가 함수를 공유하므로 결과가 운영 로직과 어긋날 위험이 없다.

출력: reports/band_calibration_us.json
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BACKEND_DIR = ROOT / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# app.engine.backtest_v2를 먼저 import해 sys.modules에 캐싱해둔다 — 아래에서 import하는
# generate_us_recommendations.py가 ROOT를 sys.path 맨 앞에 다시 꽂아버려서(가드 없는
# insert), 그 뒤에 "app"을 처음 import하면 repo 루트의 app.py(레거시 Streamlit 진입점)가
# 먼저 잡혀 "app.engine" 패키지 解決에 실패하는 문제를 피한다.
from app.engine.backtest_v2 import evaluate_recommendation  # noqa: E402

from scripts.generate_kr_recommendations import indicators, _final_score, _price_band  # noqa: E402
from scripts.generate_us_recommendations import (  # noqa: E402
    passes_us_quality_filters, _load_us_ohlcv, _load_us_sector_map, OHLCV_DIR,
)

OHLCV_ALL = _load_us_ohlcv()
SECTOR_MAP = _load_us_sector_map()
MODES = ("conservative", "balanced")
HORIZONS = ("short", "swing", "mid")

# horizon별 entry_window/holding_days — backtest_v2.HORIZON_SETTINGS와 동일
_HOLD_DAYS = {"short": 3, "swing": 7, "mid": 22}

# 2026-06-28 밴드 캘리브레이션 적용 전 값. passes_us_quality_filters()의 mode 기본값은
# 이미 이 백테스트 결과로 33~76/30~78, min_vr 0.5/0.35로 느슨해졌으므로(이력은 그 함수의
# 주석 참고), "이전값"을 override로 명시해서 전/후 비교를 재현할 수 있게 한다.
PRE_CALIBRATION_BANDS = {
    "conservative": {"rsi_band": (38, 72), "min_vr": 0.7},
    "balanced":     {"rsi_band": (35, 75), "min_vr": 0.5},
}


def _read_csv_rows(path: Path) -> list[dict]:
    import csv
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _slice_rows(rows: list[dict], cutoff: str) -> list[dict]:
    return [r for r in rows if str(r.get("date") or "")[:10] <= cutoff]


def _index_regime_at(cutoff: str) -> dict[str, Any]:
    votes = []
    for symbol in ("SPY", "QQQ", "DIA"):
        rows = _slice_rows(OHLCV_ALL.get(symbol, []), cutoff)
        closes = [float(r["close"]) for r in rows if r.get("close")]
        if len(closes) < 20:
            continue
        latest = closes[-1]
        ma20 = sum(closes[-20:]) / 20
        dist = (latest - ma20) / ma20 * 100
        mom5 = (closes[-1] - closes[-6]) / closes[-6] * 100 if len(closes) >= 6 and closes[-6] else 0.0
        if dist > 0 and mom5 > 0:
            votes.append("BULL")
        elif dist < -2.0 or mom5 < -2.0:
            votes.append("BEAR")
        else:
            votes.append("SIDE")
    if not votes:
        return {"regime": "SIDE", "scoreAdjust": 0.0}
    bull_n = votes.count("BULL")
    bear_n = votes.count("BEAR")
    if bull_n >= 2:
        return {"regime": "BULL", "scoreAdjust": 5.0}
    if bear_n >= 2:
        return {"regime": "BEAR", "scoreAdjust": -8.0}
    return {"regime": "SIDE", "scoreAdjust": 0.0}


def _cutoff_dates() -> list[str]:
    """모든 심볼 교집합 거래일 중 5거래일 간격, 양 끝(지표용 60일/평가용 holding+버퍼)은 제외."""
    all_dates = sorted({str(r.get("date") or "")[:10] for rows in OHLCV_ALL.values() for r in rows})
    if len(all_dates) < 100:
        return []
    usable = all_dates[60:-30]  # 앞 60일은 지표 워밍업, 뒤 30일은 mid(22일) 평가용 버퍼
    return usable[::5]


def _run_one(mode: str, horizon: str, band_override: dict | None) -> dict[str, Any]:
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
            passed, _ = passes_us_quality_filters(
                ind, sector, mode, horizon, {}, 99,  # 섹터캡은 끄고 순수 밴드 효과만 본다
                rsi_band=(band_override or {}).get("rsi_band"),
                min_vr=(band_override or {}).get("min_vr"),
            )
            if not passed:
                continue
            entry, stop, target, *_ = _price_band(adj, current, mode, horizon, ind)
            rec = {
                "symbol": sym, "market": "us", "entry": entry, "stop": stop, "target": target,
                "generatedAt": cutoff, "priceSession": "CLOSING",
            }
            df = pd.DataFrame(rows)
            df.columns = [str(c).lower() for c in df.columns]
            out = evaluate_recommendation(rec, df, {"slippage_pct": 0.001}, horizon)
            if out.get("filled"):
                results.append(out)

    wins = [r for r in results if str(r.get("exitStatus")) == "목표도달"]
    losses = [r for r in results if str(r.get("exitStatus")) in ("손절", "손절(동시터치)")]
    rets = [r["netPnlPct"] for r in results if r.get("netPnlPct") is not None]
    return {
        "trades": len(results),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(len(wins) / len(results), 4) if results else None,
        "avgNetPnlPct": round(sum(rets) / len(rets), 3) if rets else None,
    }


def main() -> None:
    out: dict[str, Any] = {"generatedAt": datetime.now().isoformat(timespec="seconds"), "cutoffDates": len(_cutoff_dates()), "results": {}}
    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            print(f"[{key}] 캘리브레이션 이전 밴드 백테스트 중...")
            before = _run_one(mode, horizon, PRE_CALIBRATION_BANDS[mode])
            print(f"[{key}] 현재(캘리브레이션 후) 밴드 백테스트 중...")
            after = _run_one(mode, horizon, None)
            out["results"][key] = {"beforeCalibration": before, "afterCalibration": after}
            print(f"  이전  : {before}")
            print(f"  현재  : {after}")
    path = ROOT / "reports" / "band_calibration_us.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"저장: {path}")


if __name__ == "__main__":
    main()
