#!/usr/bin/env python3
"""손절/목표 밴드 반사실 스윕 — **진단용이지 파라미터 선택용이 아니다.**

왜 만드나: 2026-07-29 sleeve 실측에서 **승률 순위와 자본곡선 순위의 스피어만
상관이 -0.3**이었다. 승률 1위(aggressive_mid 19.4%)가 NAV 8위(-44.5%)였고,
승률 4위(conservative_short 14.3%)가 NAV 1위(-11.7%)였다. 차이를 만든 건
페이오프(0.59 vs 1.40)다. 북극성이 "손익 비대칭 개선"이므로 **밴드가 페이오프를
구조적으로 깎고 있는지**를 봐야 한다.

무엇을 하나: 이미 정산된 예측의 진입가·심볼·기간은 그대로 두고, **손절/목표
폭만 바꿔** 같은 OHLCV로 재판정한다. 새 예측을 만들지 않으므로 선택 스킬은
고정되고 **청산 설계만** 분리된다.

⚠️ **이 결과로 파라미터를 고르면 과적합이다.** 같은 데이터에서 최적점을 뽑아
그 데이터로 성과를 주장하는 것이기 때문이다. 쓰임새는 딱 하나 —
"현재 밴드가 페이오프를 구조적으로 깎고 있는가"라는 **예/아니오 진단**이다.
실제 변경은 clean window 표본에서 재확인한 뒤에만 한다.

청산 규칙과 비용은 `settle_pending_validations`의 것을 그대로 쓴다. 이 레포엔
손절가를 세 군데서 따로 계산하다 어긋난 전례가 있어, 두 번째 산식을 만들지 않는다.

실행: python scripts/sweep_exit_bands.py [--clean-window] [--market kr]
쓰기: reports/exit_band_sweep.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

# 청산 규칙·비용·심볼 정규화를 **한 곳에서만** 정의한다.
from settle_pending_validations import (  # noqa: E402
    COST_PCT, OHLCV_DIR, _num, _read_csv, _sym_norm,
)

LEDGER = ROOT / "reports" / "virtual_validation_results.csv"
OUT = ROOT / "reports" / "exit_band_sweep.json"
CLEAN_WINDOW_START = "2026-07-10"

# 현재 밴드(CLAUDE.md 기준)를 가운데 두고 좌우로 훑는다.
#   short: 손절 -2.5~-5%  목표 +4~+8%
#   swing: 손절 -5~-8%    목표 +8~+18%
#   mid:   손절 -7~-12%   목표 +15~+30%
STOP_PCTS = [-2.0, -3.0, -4.0, -5.0, -6.0, -8.0, -10.0, -12.0]
TARGET_PCTS = [4.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0]

MIN_TRADES = 30   # 이보다 적은 셀은 결론 금지


def _load_bars(market: str, symbol: str) -> list[dict] | None:
    path = OHLCV_DIR / f"{market}_{_sym_norm(symbol, market)}_daily.csv"
    rows = _read_csv(path)
    return rows or None


def _simulate(bars: list[dict], created: str, due: str, entry: float,
              stop: float, target: float, cost: float) -> float | None:
    """settle_pending_validations._reconstruct_from_ohlcv와 **같은 규칙**.

    진입일 이후 봉을 훑어 진입가가 당일 범위 안에 들어온 날부터 체결로 보고,
    목표·손절이 같은 날 둘 다 닿으면 **손절 먼저**(보수적)로 판정한다.
    """
    executed = False
    last_close = None
    for row in bars:
        date = str(row.get("date") or row.get("Date") or "")[:10]
        if not date or date < created[:10] or date > due:
            continue
        low = _num(row.get("low") or row.get("Low"))
        high = _num(row.get("high") or row.get("High"))
        close = _num(row.get("close") or row.get("Close"))
        if low is None or high is None or close is None:
            continue
        if not executed:
            if not (low <= entry <= high):
                continue
            executed = True
        target_hit = high >= target
        stop_hit = low <= stop
        if target_hit and stop_hit:
            target_hit = False          # 동시 도달 -> 손절 우선
        if target_hit:
            return ((target - entry) / entry * 100) - cost
        if stop_hit:
            return ((stop - entry) / entry * 100) - cost
        last_close = close
    if not executed or last_close is None:
        return None                      # 미체결은 표본에서 뺀다
    return ((last_close - entry) / entry * 100) - cost


def _stats(returns: list[float]) -> dict:
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean(losses) if losses else 0.0
    return {
        "trades": len(returns),
        "winRatePct": round(len(wins) / len(returns) * 100, 2) if returns else 0.0,
        "meanReturnPct": round(statistics.fmean(returns), 4) if returns else 0.0,
        "medianReturnPct": round(statistics.median(returns), 4) if returns else 0.0,
        "avgWinPct": round(avg_win, 4),
        "avgLossPct": round(avg_loss, 4),
        # 페이오프 = 평균이익 / |평균손실|. 승률과 **따로** 봐야 한다.
        "payoffRatio": round(avg_win / abs(avg_loss), 3) if avg_loss else None,
    }


def _baseline_check(trades: list[dict]) -> dict:
    """**원래 밴드로 원래 결과를 재현하는가.** 이걸 통과 못 하면 표는 못 쓴다.

    2026-07-29 실측: 재현이 안 됐다. 중앙값 차이는 -0.06%p로 좋은데 **평균은
    +2.39%p**(낙관 쪽)였고 0.5%p 이내 일치가 60.8%뿐이었다. 원인을 파보니
    원장에 **서로 다른 정산 규약이 섞여** 있었다 —
      대문자 STOP / STOP_FIRST / TARGET / HOLDING_EVAL  (600건+)
      소문자 stop_hit / close_exit / target_hit          (26건, 이 규칙과 동일)
    소문자 계열은 잘 맞고(stop_hit 평균 +0.37 / 중앙 -0.00) STOP_FIRST는
    +5.7~+22.9%p 어긋난다. 즉 이 시뮬레이터는 원장의 일부만 재현한다.
    """
    diffs, by_result = [], {}
    for t in trades:
        if t["origStop"] is None or t["origTarget"] is None or t["recorded"] is None:
            continue
        cost = COST_PCT.get(t["market"], COST_PCT["kr"])
        v = _simulate(t["bars"], t["created"], t["due"], t["entry"],
                      t["origStop"], t["origTarget"], cost)
        if v is None:
            continue
        d = v - t["recorded"]
        diffs.append(d)
        by_result.setdefault(t["result"] or "?", []).append(d)
    if not diffs:
        return {"reproducible": False, "reason": "비교 가능한 건이 없다"}
    within = sum(1 for d in diffs if abs(d) < 0.5) / len(diffs)
    return {
        "comparedTrades": len(diffs),
        "meanDiffPp": round(statistics.fmean(diffs), 4),
        "medianDiffPp": round(statistics.median(diffs), 4),
        "withinHalfPointShare": round(within, 4),
        # 평균이 0.5%p 넘게 치우치거나 일치율이 90% 미만이면 못 쓴다.
        "reproducible": bool(abs(statistics.fmean(diffs)) <= 0.5 and within >= 0.90),
        "byResultVocabulary": {k: {"n": len(v), "meanDiffPp": round(statistics.fmean(v), 2)}
                               for k, v in sorted(by_result.items(), key=lambda x: -len(x[1]))},
        "note": ("원장에 정산 규약이 두 계열 섞여 있다(대문자 STOP/STOP_FIRST/... 와 "
                 "소문자 stop_hit/close_exit/...). 이 시뮬레이터는 소문자 계열과 같은 "
                 "규칙이라 그쪽만 재현한다. reproducible=false면 grid의 절대 수준을 "
                 "인용하지 말 것."),
    }


def run(clean_window: bool, market_filter: str | None) -> dict:
    rows = _read_csv(LEDGER)
    trades = []
    skipped = {"noEntry": 0, "noBars": 0, "marketFilter": 0, "beforeCleanWindow": 0}
    for r in rows:
        market = str(r.get("market") or "").lower()
        if market_filter and market != market_filter:
            skipped["marketFilter"] += 1
            continue
        created = str(r.get("createdAt") or "")[:10]
        due = str(r.get("validationDueDate") or "")[:10]
        entry = _num(r.get("entryPrice"))
        symbol = str(r.get("symbol") or "").strip()
        if not created or not due or entry is None or not symbol:
            skipped["noEntry"] += 1
            continue
        if clean_window and created < CLEAN_WINDOW_START:
            skipped["beforeCleanWindow"] += 1
            continue
        bars = _load_bars(market, symbol)
        if not bars:
            skipped["noBars"] += 1
            continue
        trades.append({"market": market, "symbol": symbol, "created": created,
                       "due": due, "entry": entry, "bars": bars,
                       "mode": r.get("mode"), "horizon": r.get("horizon"),
                       "origStop": _num(r.get("stopPrice")),
                       "origTarget": _num(r.get("targetPrice")),
                       "recorded": _num(r.get("returnPct")),
                       "result": str(r.get("result") or "")})

    # **표를 만들기 전에** 원래 밴드로 원장을 재현하는지부터 본다.
    baseline = _baseline_check(trades)

    grid = []
    for sp in STOP_PCTS:
        for tp in TARGET_PCTS:
            rets = []
            for t in trades:
                cost = COST_PCT.get(t["market"], COST_PCT["kr"])
                stop = t["entry"] * (1 + sp / 100)
                target = t["entry"] * (1 + tp / 100)
                v = _simulate(t["bars"], t["created"], t["due"], t["entry"],
                              stop, target, cost)
                if v is not None:
                    rets.append(v)
            if not rets:
                continue
            cell = {"stopPct": sp, "targetPct": tp,
                    "rrDesign": round(tp / abs(sp), 2), **_stats(rets)}
            cell["usable"] = cell["trades"] >= MIN_TRADES
            grid.append(cell)

    return {
        "generatedAt": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "cleanWindowOnly": clean_window,
        "cleanWindowStart": CLEAN_WINDOW_START if clean_window else None,
        "marketFilter": market_filter,
        "sourceLedger": "virtual_validation_results.csv",
        "candidateTrades": len(trades),
        "skipped": skipped,
        "minTradesForUsable": MIN_TRADES,
        "baselineCheck": baseline,
        "exitRule": ("settle_pending_validations와 동일: 진입가가 당일 범위에 들어오면 "
                     "체결, 목표·손절 동시 도달 시 손절 우선(보수적), 만기 미도달 시 종가 청산. "
                     "비용은 COST_PCT를 그대로 쓴다."),
        "purpose": ("진단 전용. 이 표에서 최적 셀을 골라 파라미터로 쓰면 같은 데이터에서 "
                    "최적점을 뽑아 그 데이터로 성과를 주장하는 과적합이 된다. "
                    "'현재 밴드가 페이오프를 구조적으로 깎고 있는가'만 읽을 것."),
        "caveats": [
            "정산된 예측만 쓰므로 미체결·진행중 건은 빠져 있다(생존 쪽으로 편향될 수 있다).",
            "진입가·종목·기간은 원본 그대로다 — 밴드를 바꿔도 **선택 스킬은 고정**이다.",
            "밴드를 넓히면 만기 종가청산 비중이 늘어 손절·목표 판정 자체가 줄어든다. "
            "trades 수가 같아도 결과의 성격이 달라진다는 뜻이다.",
        ],
        "grid": sorted(grid, key=lambda c: -c["meanReturnPct"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean-window", action="store_true",
                    help=f"{CLEAN_WINDOW_START} 이후 표본만")
    ap.add_argument("--market", default=None, help="kr 또는 us")
    args = ap.parse_args()

    data = run(args.clean_window, args.market)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    scope = "clean window" if args.clean_window else "전체"
    print(f"=== 손절/목표 밴드 스윕 ({scope}, 표본 {data['candidateTrades']}건) ===")
    print(f"제외: {data['skipped']}")

    b = data["baselineCheck"]
    print(f"\n[재현 검증] 원래 밴드로 원장을 재현하는가: "
          f"{'예' if b.get('reproducible') else '**아니오**'}")
    print(f"  비교 {b.get('comparedTrades')}건 · 평균차이 {b.get('meanDiffPp')}%p · "
          f"중앙차이 {b.get('medianDiffPp')}%p · 0.5%p이내 {b.get('withinHalfPointShare')}")
    if not b.get("reproducible"):
        print("  ⛔ 재현 실패 — 아래 표의 **절대 수준은 인용 금지**.")
        print(f"     규약별 차이: {b.get('byResultVocabulary')}")
    print("\n⚠ 진단 전용 — 이 표에서 최적 셀을 고르면 과적합이다.\n")
    print(f"{'손절%':>7}{'목표%':>7}{'설계RR':>8}{'n':>6}{'승률%':>8}"
          f"{'평균이익':>10}{'평균손실':>10}{'페이오프':>9}{'평균손익%':>11}")
    for c in data["grid"][:16]:
        mark = "" if c["usable"] else "  (표본부족)"
        payoff = f"{c['payoffRatio']:.2f}" if c["payoffRatio"] else "-"
        print(f"{c['stopPct']:>7.1f}{c['targetPct']:>7.1f}{c['rrDesign']:>8.2f}"
              f"{c['trades']:>6}{c['winRatePct']:>8.1f}{c['avgWinPct']:>10.2f}"
              f"{c['avgLossPct']:>10.2f}{payoff:>9}{c['meanReturnPct']:>11.3f}{mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
