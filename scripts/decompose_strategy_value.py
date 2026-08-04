#!/usr/bin/env python3
"""손실이 어디서 나오는지 **프레임 밖에서** 가른다.

지금까지 분석은 전부 앱의 프레임(진입 -> 목표/손절 -> 청산) 안에 있었다.
그 안에서는 "승률이 낮다 / 페이오프가 낮다"만 보인다. 프레임을 벗어나
같은 진입을 네 가지로 굴려 비교하면 손실의 출처가 갈린다.

  A) 실제 전략      기록된 결과 (목표/손절/만기)
  B) 밴드 제거      같은 종목·같은 진입일, 손절·목표 없이 만기까지 보유
  C) 시장           같은 기간에 지수를 들고 있었다면
  D) 진입 무시      추천일 종가에 사서 만기까지 (진입가 터치 조건 없음)

읽는 법:
  * B > A 면  **청산 기계가 가치를 파괴**하고 있다(휩소). 밴드 문제.
  * A ~ B 이고 둘 다 C 근처면  선택에 스킬이 없다(시장을 따라간 것).
  * A, B < C 면  **선택이 시장보다 못하다.** 종목 선정 문제.
  * D > A 면  진입가 터치 조건이 좋은 거래를 걸러내고 있다.

⚠️ 한계: 표본 구간이 KOSPI -24%인 한 국면뿐이다. 여기서 나온 결론은
   그 국면에 한정된다. 상승장에서 뒤집힐 수 있다.

실행: python scripts/decompose_strategy_value.py
쓰기: reports/strategy_value_decomposition.json
"""
from __future__ import annotations

import csv
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from settle_pending_validations import (  # noqa: E402
    COST_PCT, OHLCV_DIR, _num, _read_csv, _sym_norm,
)

LEDGER = ROOT / "reports" / "virtual_validation_results.csv"
OUT = ROOT / "reports" / "strategy_value_decomposition.json"
HOLD_BARS = {"short": 5, "swing": 10, "mid": 21}
BENCH = {"kr": "KOSPI", "us": "SPY"}


def _bars(market: str, symbol: str) -> list[dict]:
    return _read_csv(OHLCV_DIR / f"{market}_{_sym_norm(symbol, market)}_daily.csv")


def _bench_bars(market: str) -> list[dict]:
    for name in (BENCH.get(market, "KOSPI"), "KOSPI", "KS11"):
        for pat in (f"{market}_{name}_daily.csv", f"{name}_daily.csv"):
            rows = _read_csv(OHLCV_DIR / pat)
            if rows:
                return rows
    return []


def _series(bars: list[dict]) -> list[tuple[str, float, float, float]]:
    out = []
    for b in bars:
        d = str(b.get("date") or b.get("Date") or "")[:10]
        c = _num(b.get("close") or b.get("Close"))
        h = _num(b.get("high") or b.get("High"))
        lo = _num(b.get("low") or b.get("Low"))
        if d and c:
            out.append((d, c, h if h is not None else c, lo if lo is not None else c))
    return out


def _hold_return(series, start_date: str, bars: int, entry_price: float | None) -> float | None:
    """start_date 이후 첫 봉부터 bars 봉 뒤 종가까지의 수익률."""
    idx = [i for i, (d, *_) in enumerate(series) if d >= start_date]
    if not idx:
        return None
    i0 = idx[0]
    i1 = min(i0 + bars, len(series) - 1)
    if i1 <= i0:
        return None
    buy = entry_price if entry_price else series[i0][1]
    return (series[i1][1] - buy) / buy * 100


def run() -> dict:
    rows = list(csv.DictReader(LEDGER.open("r", encoding="utf-8-sig", newline="")))
    bench_cache: dict[str, list] = {}
    a, b, c, d = [], [], [], []
    matched = 0

    for r in rows:
        market = str(r.get("market") or "").lower()
        symbol = str(r.get("symbol") or "").strip()
        horizon = str(r.get("horizon") or "swing").lower()
        created = str(r.get("createdAt") or "")[:10]
        entry = _num(r.get("entryPrice"))
        actual = _num(r.get("returnPct"))
        if not (symbol and created and entry) or actual is None:
            continue
        series = _series(_bars(market, symbol))
        if len(series) < 30:
            continue
        bars_n = HOLD_BARS.get(horizon, 10)
        cost = COST_PCT.get(market, COST_PCT["kr"])

        # B) 밴드 제거 — 진입가에 샀다고 보고 만기까지 보유
        nb = _hold_return(series, created, bars_n, entry)
        # D) 진입 무시 — 추천일 종가에 사서 만기까지
        nd = _hold_return(series, created, bars_n, None)
        if nb is None or nd is None:
            continue

        if market not in bench_cache:
            bench_cache[market] = _series(_bench_bars(market))
        nc = _hold_return(bench_cache[market], created, bars_n, None) if bench_cache[market] else None
        if nc is None:
            continue

        matched += 1
        a.append(actual)
        b.append(nb - cost)
        d.append(nd - cost)
        c.append(nc)          # 지수는 개별 종목 비용을 안 문다

    def stat(v: list[float]) -> dict:
        if not v:
            return {"n": 0}
        wins = [x for x in v if x > 0]
        return {"n": len(v), "meanPct": round(statistics.fmean(v), 4),
                "medianPct": round(statistics.median(v), 4),
                "winRatePct": round(len(wins) / len(v) * 100, 2)}

    doc = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "matchedTrades": matched,
        "holdBars": HOLD_BARS,
        "variants": {
            "A_actual_strategy": stat(a),
            "B_no_bands_hold_to_horizon": stat(b),
            "C_index_same_window": stat(c),
            "D_ignore_entry_touch": stat(d),
        },
        "readingGuide": {
            "B>A": "청산 기계가 가치를 파괴한다(휩소). 밴드 문제.",
            "A~B~C": "선택에 스킬이 없다 — 시장을 따라간 것.",
            "A,B<C": "선택이 시장보다 못하다. 종목 선정 문제.",
            "D>A": "진입가 터치 조건이 좋은 거래를 걸러낸다.",
        },
        "caveat": ("표본 구간이 KOSPI -24%인 한 국면뿐이다. 여기서 나온 결론은 "
                   "그 국면에 한정되며 상승장에서 뒤집힐 수 있다."),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return doc


def main() -> int:
    doc = run()
    v = doc["variants"]
    print(f"=== 전략 가치 분해 (공통 {doc['matchedTrades']}건) ===\n")
    print(f"{'':<34}{'n':>6}{'평균%':>10}{'중앙%':>10}{'승률%':>9}")
    labels = {
        "A_actual_strategy": "A) 실제 전략 (목표/손절)",
        "B_no_bands_hold_to_horizon": "B) 밴드 제거, 만기까지 보유",
        "C_index_same_window": "C) 같은 기간 지수 보유",
        "D_ignore_entry_touch": "D) 진입조건 무시, 종가 매수",
    }
    for k, lab in labels.items():
        s = v[k]
        if not s.get("n"):
            print(f"{lab:<34}{'-':>6}")
            continue
        print(f"{lab:<34}{s['n']:>6}{s['meanPct']:>10.2f}{s['medianPct']:>10.2f}{s['winRatePct']:>9.1f}")
    print(f"\n{doc['caveat']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
