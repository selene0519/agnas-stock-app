"""
calibration_gate_shadow.py — 롤링 보정 + 선택게이트 결합이 EV를 (+)로 넘기는지 검증.

규칙(누적):
  R0 없음(베이스)
  R1 롤링보정 calibratedWinRate >= 45%            (게이트를 정직하게)
  R2 R1 + ATR<5% + MDD>-11% + RR<2.2               (킬존/깊은낙폭/과욕목표 배제)
  R3 R2 + vol>=0.9                                  (거래량 확인)

보정은 walk-forward(그 시점 이전 거래로만 재빌드) → 룩어헤드 없음.
선택 임계값은 고정 휴리스틱 → 과적합 배제 위해 후반부(OOS)에서 별도 리포트.
실행: python scripts/calibration_gate_shadow.py
"""
from __future__ import annotations
import csv, sys, statistics as st
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))
from app.engine.live_calibrator import build_live_calibration, lookup_win_rate  # noqa: E402


def load(p):
    for e in ("utf-8-sig", "cp949", "utf-8"):
        try:
            with open(p, encoding=e, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def ff(x):
    try:
        return float(str(x).replace(",", ""))
    except Exception:
        return None


ev = load(ROOT / "data" / "virtual_trade_evaluations.csv")
jr = {r["journal_id"]: r for r in load(ROOT / "data" / "virtual_trade_journal.csv")}
rows = []
for r in ev:
    net = ff(r.get("net_pnl_pct"))
    if net is None:
        continue
    j = jr.get(r.get("journal_id"))
    if not j:
        continue
    fs = ff(j.get("final_rank_score")); d = (j.get("as_of_date") or "")[:10]
    if fs is None or not d:
        continue
    rows.append({
        "date": d, "finalScore": fs, "regime": j.get("market_regime_at_signal", ""),
        "atr": ff(j.get("atr14_pct_at_entry")), "mdd": ff(j.get("mdd20_at_entry")),
        "rr": ff(j.get("risk_reward_ratio")), "vol": ff(j.get("volume_ratio_at_entry")),
        "netPnlPct": net, "win": 1 if net > 0 else 0,
    })
rows.sort(key=lambda x: x["date"])
mid = len(rows) // 2
split_date = rows[mid]["date"]
print(f"세틀 {len(rows)}건  {rows[0]['date']}~{rows[-1]['date']}  (OOS 경계 {split_date})\n")

# walk-forward 롤링 보정 예측
_cache = {}
def roll_pred(idx, row):
    if idx < 30:
        return None
    d = row["date"]
    if d not in _cache:
        prior = [{"finalScore": x["finalScore"], "regime": x["regime"], "netPnlPct": x["netPnlPct"], "date": x["date"]} for x in rows[:idx]]
        _cache[d] = build_live_calibration(prior, as_of=date.fromisoformat(d), prior_table={"table": {}, "global": {"winRate": 40.0}})
    wr = lookup_win_rate(_cache[d], row["finalScore"], row["regime"])
    return wr / 100.0 if wr is not None else None


def sel_ok(x):  # ATR<5 & MDD>-11 & RR<2.2
    return (x["atr"] is not None and x["atr"] < 5.0 and
            x["mdd"] is not None and x["mdd"] > -11.0 and
            x["rr"] is not None and x["rr"] < 2.2)


def vol_ok(x):
    return x["vol"] is not None and x["vol"] >= 0.9


# 각 거래에 예측 부여
for i, x in enumerate(rows):
    x["_p"] = roll_pred(i, x)

rules = {
    "R0 없음(베이스)":       lambda x: True,
    "R1 롤링>=45%":          lambda x: x["_p"] is not None and x["_p"] >= 0.45,
    "R2 R1+ATR/MDD/RR":      lambda x: x["_p"] is not None and x["_p"] >= 0.45 and sel_ok(x),
    "R3 R2+vol>=0.9":        lambda x: x["_p"] is not None and x["_p"] >= 0.45 and sel_ok(x) and vol_ok(x),
}


def report(tag, subset):
    scored = [x for x in subset if x["_p"] is not None]  # 예측 가능한 것만(warmup 이후)
    tot = len(scored)
    print(f"[{tag}]  (예측가능 {tot}건)")
    for name, rule in rules.items():
        acc = [x for x in scored if rule(x)]
        if not acc:
            print(f"    {name:22s} N=   0"); continue
        n = len(acc); wr = sum(a["win"] for a in acc) / n * 100
        evv = st.mean(a["netPnlPct"] for a in acc)
        keep = n / tot * 100
        flag = "  ← (+)" if evv > 0 else ""
        print(f"    {name:22s} N={n:4d} ({keep:4.0f}%)  승률{wr:5.1f}%  EV{evv:+.3f}%{flag}")
    print()


report("전체", rows)
report("후반부(OOS)", [x for x in rows if x["date"] >= split_date])
