"""
calibration_shadow_compare.py — calibratedWinRate 소스 3종 walk-forward 대결.

비교 대상(각 거래를 그 시점 '이전' 정보로만 예측 → 룩어헤드 없음):
  A) formula : quant_scanner 하드코딩 선형공식 (현행 폴백)
  B) served  : 현행 서빙 = 백테스트 테이블 승률, 없으면 formula 폴백 (production 재현)
  C) rolling : 신규 라이브 롤링 보정 (recency 감쇠 + 백테스트 prior shrinkage)

측정: Brier(낮을수록 정확), 신뢰성표(예측대역→실제승률), 레벨편향(평균예측−평균실제),
      45% 게이트 적용 시 통과/차단 EV.
실행: python scripts/calibration_shadow_compare.py
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

from app.engine.live_calibrator import build_live_calibration, lookup_win_rate, norm_regime  # noqa: E402
from app.engine.ensemble_calibrator import _bin_label as bt_bin  # noqa: E402

COST = 0.345


def load(p: Path) -> list[dict]:
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


# ── 데이터 로드 ─────────────────────────────────────────────
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
    fs = ff(j.get("final_rank_score"))
    d = (j.get("as_of_date") or j.get("generated_at") or "")[:10]
    if fs is None or not d:
        continue
    rows.append({
        "date": d, "finalScore": fs, "regime": j.get("market_regime_at_signal", ""),
        "mode": j.get("mode", ""), "horizon": j.get("horizon", ""),
        "netPnlPct": net, "win": 1 if net > 0 else 0,
    })
rows.sort(key=lambda x: x["date"])
print(f"세틀+조인 {len(rows)}건  {rows[0]['date']}~{rows[-1]['date']}\n")

# ── A) formula ──────────────────────────────────────────────
_HB = {"short": 0.485, "swing": 0.505, "mid": 0.515}
_HS = {"short": 0.12, "swing": 0.14, "mid": 0.15}


def pred_formula(row) -> float:
    base = _HB.get(row["horizon"], 0.505)
    scale = _HS.get(row["horizon"], 0.14)
    p = base + ((row["finalScore"] - 50.0) / 50.0) * scale
    return max(0.35, min(0.65, p))


# ── B) served: 백테스트 테이블 or formula ──────────────────
_bt_cache: dict[str, dict] = {}


def _bt_table(mode, horizon) -> dict:
    key = f"{mode}_{horizon}"
    if key not in _bt_cache:
        p = ROOT / "reports" / f"ensemble_calibration_kr_{mode}_{horizon}.json"
        _bt_cache[key] = json.load(open(p, encoding="utf-8")) if p.exists() else {}
    return _bt_cache[key]


def pred_served(row) -> float:
    cal = _bt_table(row["mode"], row["horizon"])
    table = cal.get("table", {})
    reg = norm_regime(row["regime"])
    b = bt_bin(row["finalScore"])
    bucket = table.get(f"{b}|{reg}") or {}
    fb = table.get(f"{b}|SIDE") or {}
    # 서빙 재현: BEAR & 실측버킷 비면 None → formula 폴백 (quant_scanner.py:2258 `or`)
    if reg == "BEAR" and not bucket.get("count"):
        return pred_formula(row)
    wr = bucket.get("winRate") or fb.get("winRate") or cal.get("global", {}).get("winRate")
    return (wr / 100.0) if wr is not None else pred_formula(row)


# ── C) rolling: 그 시점 이전 거래로 매일 재빌드 ────────────
_roll_cache: dict[str, dict] = {}


def _roll_table(as_of_str: str, prior_rows) -> dict:
    if as_of_str not in _roll_cache:
        recs = [{"finalScore": x["finalScore"], "regime": x["regime"],
                 "netPnlPct": x["netPnlPct"], "date": x["date"]} for x in prior_rows]
        # prior = 해당일까지 유효한 백테스트 global (combo 무시 통합 prior)
        _roll_cache[as_of_str] = build_live_calibration(
            recs, as_of=date.fromisoformat(as_of_str),
            prior_table={"table": {}, "global": {"winRate": 40.0}},
        )
    return _roll_cache[as_of_str]


def pred_rolling(row, idx, all_rows) -> float | None:
    prior = all_rows[:idx]  # 엄격히 이전
    if len(prior) < 30:
        return None
    cal = _roll_table(row["date"], prior)
    wr = lookup_win_rate(cal, row["finalScore"], row["regime"])
    return (wr / 100.0) if wr is not None else None


# ── 평가 ────────────────────────────────────────────────────
def evaluate(name, preds_actuals):
    pa = [(p, a) for p, a in preds_actuals if p is not None]
    if not pa:
        print(f"[{name}] 표본 없음")
        return
    n = len(pa)
    brier = sum((p - a) ** 2 for p, a in pa) / n
    mean_pred = sum(p for p, _ in pa) / n
    mean_act = sum(a for _, a in pa) / n
    print(f"[{name}]  N={n}  Brier={brier:.4f}  평균예측={mean_pred*100:.1f}%  평균실제={mean_act*100:.1f}%  레벨편향={(mean_pred-mean_act)*100:+.1f}%p")
    bands = [(0, .40), (.40, .45), (.45, .50), (.50, .60), (.60, 1.01)]
    for lo, hi in bands:
        seg = [(p, a) for p, a in pa if lo <= p < hi]
        if seg:
            wr = sum(a for _, a in seg) / len(seg)
            print(f"     예측[{lo*100:.0f}~{hi*100:.0f}%): 실제 {wr*100:5.1f}%  (N={len(seg)})")


rows_idx = list(enumerate(rows))
pa_formula = [(pred_formula(r), r["win"]) for _, r in rows_idx]
pa_served = [(pred_served(r), r["win"]) for _, r in rows_idx]
pa_rolling = [(pred_rolling(r, i, rows), r["win"]) for i, r in rows_idx]

print("=== 예측 정확도 (walk-forward, 룩어헤드 없음) ===")
evaluate("A formula ", pa_formula)
print()
evaluate("B served  ", pa_served)
print()
evaluate("C rolling ", pa_rolling)

# ── 45% 게이트 성과 ────────────────────────────────────────
import statistics as st  # noqa: E402


def gate_perf(name, preds):
    kept = [rows[i] for i, (p, _) in enumerate(preds) if p is not None and p >= 0.45]
    drop = [rows[i] for i, (p, _) in enumerate(preds) if p is not None and p < 0.45]
    def s(g):
        return (len(g), sum(x["win"] for x in g) / len(g) * 100 if g else 0,
                st.mean(x["netPnlPct"] for x in g) if g else 0)
    kn, kwr, kev = s(kept)
    dn, dwr, dev = s(drop)
    print(f"[{name}] 통과 N={kn} 승률{kwr:.1f}% EV{kev:+.3f}%  |  차단 N={dn} 승률{dwr:.1f}% EV{dev:+.3f}%")


print("\n=== 45% 게이트 적용 성과 (통과=추천됨) ===")
gate_perf("A formula", pa_formula)
gate_perf("B served ", pa_served)
gate_perf("C rolling", pa_rolling)
