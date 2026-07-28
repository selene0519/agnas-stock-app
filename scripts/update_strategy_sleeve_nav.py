#!/usr/bin/env python3
"""전략별 가상 sleeve 자본곡선 — 9개 전략을 같은 자를 대고 나란히 재는 것.

왜 필요한가:
  현재 전략 간 비교는 `strategy_win_rates.json`의 셀별 승률뿐인데, 이건
  (1) 표본이 20건 미만이면 판정 불가고 (2) 승률만으론 손익 비대칭을 못 본다.
  승률 17.4%(aggressive_swing)가 15.4%(balanced_swing)보다 나은지는 **평균손익까지
  같이 봐야** 답이 나오고, 그걸 한 축으로 압축한 게 자본곡선이다.
  북극성이 "손익 비대칭 개선"이므로 비교축도 거기 맞춰야 한다.

무엇을 하지 않는가 (중요):
  - 새 예측을 만들지 않는다. 이미 정산된 표본을 다시 묶을 뿐이다.
  - 실현 손익만 쓴다. 미청산 건의 평가손익을 끼워넣지 않는다 —
    라이브 시세를 여기서 다시 끌어오면 정산 경로와 두 번째 산식이 생기고,
    이 레포는 손절가 3중 계산으로 이미 그 대가를 치렀다.
  - HISTORICAL_REPLAY 등 가중치 0 소스는 제외한다
    (virtual_trade_journal.SOURCE_CALIBRATION_WEIGHTS 정책. 2026-07-28에
     이 정책을 안 보고 풀링한 탓에 두 원장이 3배 어긋나 있었다).

시점(timing):
  각 거래를 **청산일(exitDate)**에 실현시킨다. exitDate가 없는 과거 행은
  만기일(validationDueDate)로 떨어뜨리고 `estimatedTimingRows`에 카운트해
  정직하게 표시한다 — 손절로 3일 만에 끝난 거래와 만기까지 끌고 간 거래를
  같은 날 실현된 것처럼 그리면 곡선의 모양이 거짓말을 한다.
  (settle_pending_validations.py가 2026-07-29부터 exitDate를 기록한다.)

포지션 사이즈:
  등가중(각 거래 = sleeve 자본의 `POSITION_FRACTION`). Kelly/신뢰도 가중을
  쓰면 사이징 스킬과 선택 스킬이 섞여서, 정작 알고 싶은 **선택(진입) 오차**가
  안 보인다. CLAUDE.md #3의 진단이 "선택 오차"였으므로 사이징은 고정한다.

실행: python scripts/update_strategy_sleeve_nav.py [--all-window]
쓰기: reports/strategy_sleeve_nav.json
stdlib만 사용.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "reports" / "virtual_validation_results.csv"
MARKER = ROOT / "reports" / "clean_window_marker.json"
OUT = ROOT / "reports" / "strategy_sleeve_nav.json"

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

# 각 거래에 투입하는 sleeve 자본 비율. 등가중 + 고정 비율이라
# 자본곡선은 로그 스케일에서 거래당 평균수익률의 누적과 같은 모양이 된다.
POSITION_FRACTION = 0.10
START_NAV = 100.0

# 실현 손익이 없는 결과 = 자본곡선에 반영할 게 없는 행.
# scripts/update_win_rates.py / data_freshness_healthcheck.py와 같은 기준.
NON_REALIZED = {
    "", "PENDING", "DATA_PENDING", "NOT_EXECUTED",
    "CANCELLED", "INVALID_SYMBOL", "DATA_INVALID", "EXPIRED",
}
# 라이브 forward 표본만. virtual_trade_journal.SOURCE_CALIBRATION_WEIGHTS에서
# 가중치가 0보다 큰 소스에 대응한다(리플레이/백테스트는 제외).
REPLAY_SOURCE_MARKERS = ("REPLAY", "BACKTEST", "SIMULAT")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _num(v) -> float | None:
    try:
        s = str(v or "").replace(",", "").strip()
        return float(s) if s and s.lower() not in ("", "-", "nan", "none") else None
    except Exception:
        return None


def _clean_window_start() -> str | None:
    if not MARKER.exists():
        return None
    try:
        return str(json.load(open(MARKER, encoding="utf-8")).get("cleanWindowStart") or "")[:10] or None
    except Exception:
        return None


def _is_forward(row: dict) -> bool:
    src = str(row.get("source") or "").upper()
    return not any(m in src for m in REPLAY_SOURCE_MARKERS)


def _realized_date(row: dict) -> tuple[str, bool]:
    """(실현일, 추정여부). exitDate가 있으면 그걸, 없으면 만기일로 떨어뜨린다."""
    exit_date = str(row.get("exitDate") or "")[:10]
    if exit_date:
        return exit_date, False
    return str(row.get("validationDueDate") or row.get("createdAt") or "")[:10], True


def _sleeve_key(row: dict) -> str | None:
    mode = str(row.get("mode") or "").strip().lower()
    horizon = str(row.get("horizon") or "").strip().lower()
    if mode not in MODES or horizon not in HORIZONS:
        return None
    return f"{mode}_{horizon}"


def _max_drawdown(curve: list[dict]) -> float:
    peak, mdd = START_NAV, 0.0
    for pt in curve:
        nav = pt["nav"]
        peak = max(peak, nav)
        if peak > 0:
            mdd = max(mdd, (peak - nav) / peak * 100.0)
    return round(mdd, 2)


def build(clean_only: bool = True) -> dict:
    rows = _read_csv(RESULTS)
    cw = _clean_window_start()
    cutoff = cw if (clean_only and cw) else None

    sleeves: dict[str, list[dict]] = {f"{m}_{h}": [] for m in MODES for h in HORIZONS}
    excluded = {"nonRealized": 0, "replaySource": 0, "beforeCleanWindow": 0,
                "unknownSleeve": 0, "noReturn": 0}
    estimated_timing = 0

    for row in rows:
        result = str(row.get("result") or row.get("status") or "").upper().strip()
        if result in NON_REALIZED:
            excluded["nonRealized"] += 1
            continue
        if not _is_forward(row):
            excluded["replaySource"] += 1
            continue
        created = str(row.get("createdAt") or "")[:10]
        if cutoff and created < cutoff:
            excluded["beforeCleanWindow"] += 1
            continue
        key = _sleeve_key(row)
        if key is None:
            excluded["unknownSleeve"] += 1
            continue
        ret = _num(row.get("returnPct"))
        if ret is None:
            excluded["noReturn"] += 1
            continue
        realized_on, estimated = _realized_date(row)
        if estimated:
            estimated_timing += 1
        sleeves[key].append({
            "date": realized_on, "returnPct": ret,
            "symbol": row.get("symbol"), "market": row.get("market"),
            "estimatedTiming": estimated,
        })

    out_sleeves: dict[str, dict] = {}
    for key, trades in sleeves.items():
        trades.sort(key=lambda t: (t["date"], str(t["symbol"] or "")))
        nav = START_NAV
        curve: list[dict] = []
        wins = 0
        gains: list[float] = []
        losses: list[float] = []
        for t in trades:
            # 등가중 고정 비율. 거래 수익률 r이면 sleeve는 r * fraction 만큼 움직인다.
            nav *= (1.0 + (t["returnPct"] / 100.0) * POSITION_FRACTION)
            curve.append({"date": t["date"], "nav": round(nav, 4),
                          "symbol": t["symbol"], "returnPct": t["returnPct"]})
            if t["returnPct"] > 0:
                wins += 1
                gains.append(t["returnPct"])
            else:
                losses.append(t["returnPct"])
        n = len(trades)
        avg_gain = round(sum(gains) / len(gains), 4) if gains else None
        avg_loss = round(sum(losses) / len(losses), 4) if losses else None
        # 손익 비대칭(payoff ratio) — 북극성이 "손실↓·수익↑"이므로 이게 핵심 지표.
        payoff = (round(abs(avg_gain / avg_loss), 3)
                  if avg_gain is not None and avg_loss not in (None, 0) else None)
        out_sleeves[key] = {
            "trades": n,
            "nav": round(nav, 4),
            "totalReturnPct": round((nav / START_NAV - 1.0) * 100.0, 4),
            "winRate": round(wins / n, 4) if n else None,
            "avgReturnPct": round(sum(t["returnPct"] for t in trades) / n, 4) if n else None,
            "avgGainPct": avg_gain,
            "avgLossPct": avg_loss,
            "payoffRatio": payoff,
            "maxDrawdownPct": _max_drawdown(curve),
            "estimatedTimingTrades": sum(1 for t in trades if t["estimatedTiming"]),
            "curve": curve,
        }

    ranked = sorted(
        (k for k, v in out_sleeves.items() if v["trades"] > 0),
        key=lambda k: out_sleeves[k]["totalReturnPct"], reverse=True,
    )
    total_trades = sum(v["trades"] for v in out_sleeves.values())
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "basis": {
            "positionFraction": POSITION_FRACTION,
            "startNav": START_NAV,
            "cleanWindowOnly": bool(cutoff),
            "cleanWindowStart": cw,
            "realizedOnly": True,
            "forwardSourcesOnly": True,
        },
        # 정직 disclosure — 이 숫자를 읽는 사람이 한계를 같이 보게 한다.
        "dataQuality": {
            "totalTrades": total_trades,
            "estimatedTimingTrades": estimated_timing,
            "estimatedTimingNote": (
                "exitDate가 없는 과거 정산분은 만기일로 실현 시점을 근사했다. "
                "곡선의 시점 정확도만 영향받고 최종 NAV는 영향받지 않는다."
            ),
            "excluded": excluded,
            "sampleWarning": (
                None if total_trades >= 30
                else f"표본 {total_trades}건 — 30건 미만이면 순위는 노이즈로 봐야 한다"
            ),
        },
        "ranking": ranked,
        "sleeves": out_sleeves,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-window", action="store_true",
                    help="clean window 이전 표본까지 포함(오염 구간 포함, 진단용).")
    args = ap.parse_args()

    data = build(clean_only=not args.all_window)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    dq = data["dataQuality"]
    print(f"=== 전략 sleeve 자본곡선 ({'전체' if args.all_window else 'clean window'}) ===")
    print(f"  거래 {dq['totalTrades']}건 / 제외 {sum(dq['excluded'].values())}건 "
          f"{dq['excluded']}")
    if dq["sampleWarning"]:
        print(f"  [!] {dq['sampleWarning']}")
    if dq["estimatedTimingTrades"]:
        print(f"  [!] 시점 근사 {dq['estimatedTimingTrades']}건 (exitDate 없음)")
    if not data["ranking"]:
        print("  판정 가능한 sleeve 없음 — 표본이 쌓이면 채워진다.")
        return 0
    print(f"  {'sleeve':<22}{'거래':>5}{'NAV':>9}{'수익%':>9}{'승률':>8}{'페이오프':>9}{'MDD%':>8}")
    for key in data["ranking"]:
        s = data["sleeves"][key]
        wr = f"{s['winRate'] * 100:.1f}%" if s["winRate"] is not None else "-"
        po = f"{s['payoffRatio']:.2f}" if s["payoffRatio"] is not None else "-"
        print(f"  {key:<22}{s['trades']:>5}{s['nav']:>9.2f}{s['totalReturnPct']:>9.2f}"
              f"{wr:>8}{po:>9}{s['maxDrawdownPct']:>8.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
