#!/usr/bin/env python3
"""앱의 **시그널 자체**에 정보가 있는지 전수 검정한다 — 홀드아웃 포함.

지금까지의 분석은 전부 청산 규칙(밴드·비용·창)에 있었다. 그건 "이미 고른
종목을 어떻게 파느냐"의 문제다. 정작 **"고르는 것 자체가 정보를 담고 있나"**는
한 번도 테스트하지 않았다. 밴드 최적화가 표본 밖에서 실패한 것도, 알파가
0으로 나온 것도, 전부 이 질문으로 수렴한다.

방법:
  * VTJ 저널(피처) + 평가(net_pnl_pct)를 조인. FORWARD_PAPER_TRADE만.
  * 추천일 날짜순 60/40 분할. **train에서 방향을 보고 test에서 확인한다.**
  * 수치 피처: 스피어만 순위상관 + 상·하위 5분위 평균 격차
  * 범주 피처: 그룹별 평균

읽는 법:
  * train과 test에서 **부호가 같고** 격차가 유지되면 -> 정보가 있다
  * train만 크고 test가 0이거나 부호가 뒤집히면 -> 우연이다
  * 여러 피처를 동시에 보므로 **다중비교**를 감안해야 한다. 피처 12개면
    우연히 |상관|>0.1이 한둘 나오는 건 정상이다.

실행: python scripts/test_signal_predictiveness.py
쓰기: reports/signal_predictiveness.json
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
JOURNAL = ROOT / "data" / "virtual_trade_journal.csv"
EVALS = ROOT / "data" / "virtual_trade_evaluations.csv"
OUT = ROOT / "reports" / "signal_predictiveness.json"

NUMERIC = ["final_rank_score", "probability", "risk_score", "event_risk_score",
           "rsi_at_entry", "volume_ratio_at_entry", "atr14_pct_at_entry",
           "mdd20_at_entry", "momentum5_at_entry", "event_reliability_score"]
CATEGORICAL = ["market_regime_at_signal", "sector", "mode", "horizon", "market"]
TRAIN_SHARE = 0.6
MIN_N = 40


def _f(v):
    try:
        s = str(v or "").replace(",", "").strip()
        return float(s) if s not in ("", "-", "nan", "None") else None
    except Exception:
        return None


def _rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 10:
        return None

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


def _quintile_gap(xs: list[float], ys: list[float]) -> dict:
    """상위 20% 평균 − 하위 20% 평균. 순위 스킬의 직관적 크기."""
    pairs = sorted(zip(xs, ys))
    k = max(1, len(pairs) // 5)
    lo = statistics.fmean([y for _, y in pairs[:k]])
    hi = statistics.fmean([y for _, y in pairs[-k:]])
    return {"bottomMeanPct": round(lo, 3), "topMeanPct": round(hi, 3),
            "gapPct": round(hi - lo, 3), "perQuintileN": k}


def run() -> dict:
    ev = {}
    for r in _rows(EVALS):
        v = _f(r.get("net_pnl_pct"))
        if v is not None and str(r.get("status") or "").upper() == "EVALUATED":
            ev[str(r.get("journal_id") or "")] = v

    joined = []
    for r in _rows(JOURNAL):
        if str(r.get("source_type") or "").upper() != "FORWARD_PAPER_TRADE":
            continue
        jid = str(r.get("journal_id") or "")
        if jid not in ev:
            continue
        d = str(r.get("as_of_date") or r.get("captured_at") or "")[:10]
        if not d:
            continue
        r["_pnl"] = ev[jid]
        r["_date"] = d
        joined.append(r)

    joined.sort(key=lambda x: x["_date"])
    split = int(len(joined) * TRAIN_SHARE)
    train, test = joined[:split], joined[split:]

    def numeric_block(rows, feat):
        xs, ys = [], []
        for r in rows:
            v = _f(r.get(feat))
            if v is not None:
                xs.append(v)
                ys.append(r["_pnl"])
        if len(xs) < MIN_N:
            return None
        return {"n": len(xs), "spearman": _spearman(xs, ys), **_quintile_gap(xs, ys)}

    numeric = {}
    for feat in NUMERIC:
        a, b = numeric_block(train, feat), numeric_block(test, feat)
        if not a or not b:
            continue
        sa, sb = a.get("spearman"), b.get("spearman")
        confirmed = bool(sa and sb and sa * sb > 0 and abs(sb) >= 0.05)
        numeric[feat] = {"train": a, "test": b, "confirmedOutOfSample": confirmed}

    categorical = {}
    for feat in CATEGORICAL:
        groups: dict[str, dict[str, list]] = {}
        for label, rows in (("train", train), ("test", test)):
            for r in rows:
                k = str(r.get(feat) or "").strip() or "?"
                groups.setdefault(k, {"train": [], "test": []})[label].append(r["_pnl"])
        out = {k: {lab: {"n": len(v[lab]),
                         "meanPct": round(statistics.fmean(v[lab]), 3) if v[lab] else None}
                   for lab in ("train", "test")}
               for k, v in groups.items()
               if len(v["train"]) >= 15 and len(v["test"]) >= 10}
        if out:
            categorical[feat] = out

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "totalJoined": len(joined), "trainN": len(train), "testN": len(test),
        "dateRange": {"min": joined[0]["_date"], "max": joined[-1]["_date"]} if joined else {},
        "method": ("추천일 날짜순 60/40 분할. train에서 방향을 보고 test에서 확인. "
                   "수치 피처는 스피어만 순위상관 + 상·하위 5분위 평균 격차."),
        "numeric": numeric,
        "categorical": categorical,
        "confirmedFeatures": [k for k, v in numeric.items() if v["confirmedOutOfSample"]],
        "caveats": [
            f"피처 {len(numeric)}개를 동시에 본다 — 다중비교로 우연히 |상관|>0.1이 "
            "한둘 나오는 건 정상이다. 부호 일치와 격차 유지를 같이 봐야 한다.",
            "표본 구간이 KOSPI -24%인 한 국면뿐이라 국면 한정 결론이다.",
            "net_pnl_pct는 원장 B 기준(평가창 60일, 왕복비용). 원장 A와 규칙이 다르다.",
        ],
    }


def main() -> int:
    d = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"=== 시그널 예측력 검정 (조인 {d['totalJoined']}건 · "
          f"train {d['trainN']} / test {d['testN']}) ===\n")
    print(f"{'피처':<24}{'train ρ':>9}{'test ρ':>9}{'train격차%':>12}{'test격차%':>12}  확인")
    for feat, v in sorted(d["numeric"].items(),
                          key=lambda x: -abs(x[1]["test"].get("spearman") or 0)):
        a, b = v["train"], v["test"]
        mark = "✓" if v["confirmedOutOfSample"] else ""
        print(f"{feat:<24}{str(a.get('spearman')):>9}{str(b.get('spearman')):>9}"
              f"{a['gapPct']:>12.2f}{b['gapPct']:>12.2f}  {mark}")
    cf = d["confirmedFeatures"]
    print(f"\n표본 밖에서 확인된 피처: {cf if cf else '**없음**'}")
    for c in d["caveats"]:
        print(f"  · {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
