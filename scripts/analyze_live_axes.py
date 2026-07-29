#!/usr/bin/env python3
"""국면·점수 축을 **라이브 표본으로** 검증한다 (VTJ 저널 기반).

왜 이 스크립트가 따로 있는가:
  앙상블(`run_ensemble_calibration`, walk-forward 82,251건)이 두 가설을 냈다.
    ① 국면: BULL +0.241% / SIDE +0.064% / BEAR -0.714%  (BEAR가 최악)
    ② 점수: 70-100 구간이 60-65보다 나쁨 (단조가 아님)
  이걸 게이트에 반영하려면 라이브가 같은 말을 하는지 먼저 봐야 하는데,
  예측 원장(`virtual_prediction_ledger.csv`)에는 `finalScore`도 `regime`도
  없었다(2026-07-29에 추가했지만 그날 이후 표본부터 쌓인다).

  그런데 **VTJ 저널에는 처음부터 둘 다 있었다** —
  `final_rank_score`, `market_regime_at_signal`. 결과는
  `virtual_trade_evaluations.csv`의 `net_pnl_pct`/`outcome`에 있다.
  즉 기다릴 필요 없이 지금 있는 표본으로 검증할 수 있었다.

무엇을 하지 않는가:
  - `HISTORICAL_REPLAY`는 제외한다(SOURCE_CALIBRATION_WEIGHTS 가중치 0.0).
    2026-07-28에 두 원장이 3배 어긋난 원인이 정확히 이 풀링이었다.
  - 미정산(PENDING)은 제외한다.
  - 게이트를 바꾸지 않는다. 이 스크립트는 관측만 한다.

실행: python scripts/analyze_live_axes.py [--since YYYY-MM-DD]
쓰기: reports/live_axis_analysis.json
stdlib만 사용.
"""
from __future__ import annotations

import argparse
import collections
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
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALS = ROOT / "data" / "virtual_trade_evaluations.csv"
MARKER = ROOT / "reports" / "clean_window_marker.json"
OUT = ROOT / "reports" / "live_axis_analysis.json"

# 국면 라벨이 한 파일 안에서 RISK_ON / 횡보장 / BULL / SIDE / 약세장 / NEUTRAL로
# 뒤섞여 있다. 정규화하지 않으면 같은 국면이 여러 버킷으로 흩어져 n이 쪼개진다.
REGIME_NORM = {
    "RISK_ON": "BULL", "BULL": "BULL", "강세장": "BULL",
    "SIDE": "SIDE", "횡보장": "SIDE", "NEUTRAL": "SIDE",
    "BEAR": "BEAR", "약세장": "BEAR", "RISK_OFF": "BEAR",
}
SCORE_BINS = [(0, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 101)]
MIN_TRUSTWORTHY_N = 30


def _read(path: Path) -> list[dict]:
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
        s = str(v or "").strip()
        return float(s) if s else None
    except Exception:
        return None


def _clean_window_start() -> str | None:
    try:
        return str(json.load(open(MARKER, encoding="utf-8")).get("cleanWindowStart") or "")[:10] or None
    except Exception:
        return None


def _regime(raw: str) -> str:
    key = str(raw or "").strip()
    return REGIME_NORM.get(key.upper(), REGIME_NORM.get(key, "OTHER"))


def _score_bin(score: float | None) -> str | None:
    if score is None:
        return None
    for lo, hi in SCORE_BINS:
        if lo <= score < hi:
            return f"{lo}-{min(hi, 100)}"
    return None


def collect(since: str | None) -> list[dict]:
    journal = {r.get("journal_id", ""): r for r in _read(JOURNAL)}
    out: list[dict] = []
    for ev in _read(EVALS):
        jr = journal.get(ev.get("journal_id", ""))
        if not jr:
            continue
        # 리플레이는 라이브 근거가 아니다(가중치 0.0 정책).
        if str(jr.get("source_type") or "").strip().upper() != "FORWARD_PAPER_TRADE":
            continue
        if str(ev.get("outcome") or "").strip().upper() in ("", "PENDING"):
            continue
        pnl = _num(ev.get("net_pnl_pct"))
        if pnl is None:
            continue
        date = str(jr.get("as_of_date") or jr.get("captured_at") or "")[:10]
        if since and date and date < since:
            continue
        out.append({
            "date": date,
            "score": _num(jr.get("final_rank_score")),
            "regime": _regime(jr.get("market_regime_at_signal")),
            "pnlPct": pnl,
        })
    return out


def _stats(values: list[float]) -> dict:
    wins = [v for v in values if v > 0]
    return {
        "trades": len(values),
        "winRate": round(len(wins) / len(values), 4) if values else None,
        "avgPnlPct": round(sum(values) / len(values), 4) if values else None,
        "sampleWarning": (None if len(values) >= MIN_TRUSTWORTHY_N
                          else f"표본 {len(values)}건 — {MIN_TRUSTWORTHY_N}건 미만이라 순위는 노이즈"),
    }


def build(since: str | None) -> dict:
    rows = collect(since)
    by_regime: dict[str, list[float]] = collections.defaultdict(list)
    by_bin: dict[str, list[float]] = collections.defaultdict(list)
    for r in rows:
        by_regime[r["regime"]].append(r["pnlPct"])
        b = _score_bin(r["score"])
        if b:
            by_bin[b].append(r["pnlPct"])
    scores = [r["score"] for r in rows if r["score"] is not None]
    all_pnl = [r["pnlPct"] for r in rows]
    dates = [r["date"] for r in rows if r["date"]]
    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "since": since,
        "cleanWindowStart": _clean_window_start(),
        "source": "virtual_trade_journal + virtual_trade_evaluations (FORWARD_PAPER_TRADE only)",
        "overall": _stats(all_pnl),
        "dateRange": {"min": min(dates) if dates else None, "max": max(dates) if dates else None},
        # 서빙이 실제로 만들어내는 점수 범위. 앙상블 표가 다루는 50-70 구간이
        # 여기 없으면 그 표는 게이트 근거로 쓸 수 없다.
        "observedScoreRange": ({"min": round(min(scores), 2), "max": round(max(scores), 2),
                                "median": round(sorted(scores)[len(scores) // 2], 2)}
                               if scores else None),
        "byRegime": {k: _stats(v) for k, v in sorted(by_regime.items())},
        "byScoreBin": {k: _stats(v) for k, v in sorted(by_bin.items())},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None,
                    help="이 날짜 이후 표본만. 생략하면 clean window 마커를 쓴다.")
    ap.add_argument("--all", action="store_true", help="기간 제한 없이 전체.")
    args = ap.parse_args()

    since = None if args.all else (args.since or _clean_window_start())
    data = build(since)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    o = data["overall"]
    print(f"=== 라이브 축 분석 (forward only{', ' + since + '~' if since else ', 전체'}) ===")
    print(f"  표본 {o['trades']}건 · 승률 {(o['winRate'] or 0) * 100:.1f}% · "
          f"평균손익 {o['avgPnlPct']:+.3f}%")
    if data["dateRange"]["min"]:
        print(f"  기간 {data['dateRange']['min']} ~ {data['dateRange']['max']}")
    if data["observedScoreRange"]:
        s = data["observedScoreRange"]
        print(f"  실제 점수 범위 {s['min']}~{s['max']} (중앙 {s['median']})")
    for title, key in (("국면별", "byRegime"), ("점수구간별", "byScoreBin")):
        print(f"\n  [{title}]  {'n':>6}{'승률%':>8}{'평균손익%':>11}")
        for k, v in data[key].items():
            warn = " ⚠" if v["sampleWarning"] else ""
            print(f"  {k:<12}{v['trades']:>6}{(v['winRate'] or 0) * 100:>8.1f}"
                  f"{v['avgPnlPct']:>11.3f}{warn}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
