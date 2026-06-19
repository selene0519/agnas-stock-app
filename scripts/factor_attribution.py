"""팩터 귀속분석 + Kelly 포지션 사이즈 계산.

분석:
- 어떤 팩터(모드/호라이즌/마켓/확률범위)가 실제 수익에 기여하는지
- Kelly criterion으로 전략별 최적 포지션 비율 계산
- 결과를 reports/factor_attribution.json, reports/kelly_position_sizes.json에 저장

Kelly 공식: f* = p - (1-p)/b
  p = 실제 승률
  b = 평균 수익 / 평균 손실 (payoff ratio)
  half-Kelly = f* / 2 (실무 권장, 과도한 베팅 방지)
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VTJ_CSV    = ROOT / "reports" / "virtual_validation_results.csv"
LEDGER_CSV = ROOT / "data"    / "recommendation_validation_results.csv"
OUT_FACTOR = ROOT / "reports" / "factor_attribution.json"
OUT_KELLY  = ROOT / "reports" / "kelly_position_sizes.json"

MODES    = ["conservative", "balanced", "aggressive"]
HORIZONS = ["short", "swing", "mid"]

# MONE 가격 밴드: (stop%, target%) — 이론적 payoff ratio 기준
_BANDS: dict[str, tuple[float, float]] = {
    "short": (3.5,  6.0),
    "swing": (6.5,  13.0),
    "mid":   (9.5,  22.5),
}
# 데이터 부족 시 사용할 기본 승률
_DEFAULT_WIN_RATE: dict[str, float] = {"short": 0.485, "swing": 0.505, "mid": 0.515}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size < 10:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _result_class(row: dict) -> str | None:
    result = str(
        row.get("result") or row.get("win_loss_result") or row.get("status") or ""
    ).upper()
    if any(k in result for k in ("WIN", "TARGET", "TP", "SUCCESS", "목표")):
        return "WIN"
    if any(k in result for k in ("LOSS", "STOP", "SL", "FAIL", "손절")):
        return "LOSS"
    return None


def _return_pct(row: dict) -> float | None:
    for key in ("returnPct", "return_pct", "primaryReturn", "return_10d", "virtualReturnPct"):
        v = row.get(key)
        if v not in (None, "", "nan"):
            try:
                return float(str(v).replace("%", "").strip())
            except (ValueError, TypeError):
                pass
    return None


def _probability(row: dict) -> float | None:
    for key in ("probability", "validationConfidence"):
        v = row.get(key)
        if v not in (None, "", "nan"):
            try:
                return float(v)
            except (ValueError, TypeError):
                pass
    return None


def _load_all() -> list[dict[str, str]]:
    vtj = _read_csv(VTJ_CSV)
    for r in vtj:
        r.setdefault("_src", "vtj")
    led = _read_csv(LEDGER_CSV)
    for r in led:
        r.setdefault("_src", "ledger")
    return vtj + led


def _kelly(p: float, b: float) -> float:
    if b <= 0 or p <= 0:
        return 0.0
    return max(0.0, p - (1 - p) / b)


def _generate_insights(strat: dict, market: dict, kelly: dict) -> list[str]:
    insights = []

    horizon_wr: dict[str, list[float]] = defaultdict(list)
    for key, v in strat.items():
        h = key.split("_")[1] if "_" in key else ""
        if h:
            horizon_wr[h].append(v["winRate"])

    if horizon_wr:
        best_h = max(horizon_wr, key=lambda h: sum(horizon_wr[h]) / len(horizon_wr[h]))
        avg = sum(horizon_wr[best_h]) / len(horizon_wr[best_h])
        insights.append(f"호라이즌: {best_h} 전략 평균 승률 {avg:.1%}로 최고")

    mode_payoff: dict[str, list[float]] = defaultdict(list)
    for key, v in strat.items():
        m = key.split("_")[0] if "_" in key else ""
        if m and v["payoffRatio"] > 0:
            mode_payoff[m].append(v["payoffRatio"])

    if mode_payoff:
        best_m = max(mode_payoff, key=lambda m: sum(mode_payoff[m]) / len(mode_payoff[m]))
        avg = sum(mode_payoff[best_m]) / len(mode_payoff[best_m])
        insights.append(f"모드: {best_m} 전략 평균 payoff {avg:.2f}x로 최고")

    if len(market) >= 2:
        best_mk = max(market, key=lambda m: market[m]["winRate"])
        insights.append(f"마켓: {best_mk.upper()} 승률 {market[best_mk]['winRate']:.1%}로 우위")

    if kelly:
        best_k = max(kelly, key=lambda k: kelly[k]["recommendedPct"])
        insights.append(
            f"Kelly 최대: {best_k} → 포트폴리오의 {kelly[best_k]['recommendedPct']}% 권장"
        )

    return insights


def run() -> tuple[dict[str, Any], dict[str, Any]]:
    rows = _load_all()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 전략별 집계
    bucket: dict[str, dict[str, list[float]]] = {
        f"{m}_{h}": {"wins": [], "losses": [], "probs": []}
        for m in MODES for h in HORIZONS
    }
    market_wins:   dict[str, list[float]] = defaultdict(list)
    market_losses: dict[str, list[float]] = defaultdict(list)
    prob_bucket: dict[str, list[float]] = {
        "low_50-60": [], "mid_60-75": [], "high_75+": [],
    }

    for row in rows:
        mode    = str(row.get("mode", "")).lower().strip()
        horizon = str(row.get("horizon", "")).lower().strip()
        if mode not in MODES or horizon not in HORIZONS:
            continue

        outcome = _result_class(row)
        if outcome is None:
            continue

        ret  = _return_pct(row) or 0.0
        prob = _probability(row)
        key  = f"{mode}_{horizon}"
        mk   = row.get("market", "?")

        if prob is not None:
            bucket[key]["probs"].append(prob)
            p_range = ("high_75+" if prob >= 75 else "mid_60-75" if prob >= 60 else "low_50-60")
            prob_bucket[p_range].append(1.0 if outcome == "WIN" else 0.0)

        if outcome == "WIN":
            bucket[key]["wins"].append(max(0.0, ret))
            market_wins[mk].append(max(0.0, ret))
        else:
            bucket[key]["losses"].append(abs(ret) if ret != 0 else 1.0)
            market_losses[mk].append(abs(ret))

    # 팩터 귀속분석
    factor_results: dict[str, Any] = {}
    for key, data in bucket.items():
        wins   = data["wins"]
        losses = data["losses"]
        total  = len(wins) + len(losses)
        if total == 0:
            continue

        p       = len(wins) / total
        avg_win = sum(wins)   / len(wins)   if wins   else 0.0
        avg_loss= sum(losses) / len(losses) if losses else 1.0
        payoff  = avg_win / avg_loss if avg_loss > 0 else 0.0
        avg_prob= sum(data["probs"]) / len(data["probs"]) if data["probs"] else None
        prob_acc= round(p - avg_prob / 100, 3) if avg_prob else None

        factor_results[key] = {
            "total":        total,
            "wins":         len(wins),
            "losses":       len(losses),
            "winRate":      round(p, 4),
            "avgWinPct":    round(avg_win,  3),
            "avgLossPct":   round(avg_loss, 3),
            "payoffRatio":  round(payoff,   3),
            "avgProbability": round(avg_prob, 1) if avg_prob else None,
            "probAccuracy": prob_acc,
        }

    # 마켓별
    market_factor: dict[str, Any] = {}
    for mk in ("kr", "us"):
        w = market_wins.get(mk, [])
        l = market_losses.get(mk, [])
        t = len(w) + len(l)
        if t == 0:
            continue
        avg_w = sum(w) / len(w) if w else 0.0
        avg_l = sum(l) / len(l) if l else 1.0
        market_factor[mk] = {
            "total":       t,
            "winRate":     round(len(w) / t, 4),
            "avgWinPct":   round(avg_w, 3),
            "avgLossPct":  round(avg_l, 3),
            "payoffRatio": round(avg_w / avg_l if avg_l > 0 else 0, 3),
        }

    # 확률 구간별 실제 승률
    prob_factor: dict[str, Any] = {
        band: {"count": len(o), "actualWinRate": round(sum(o) / len(o), 4)}
        for band, o in prob_bucket.items() if o
    }

    # Kelly 포지션 사이즈
    kelly_results: dict[str, Any] = {}
    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            stop_pct, target_pct = _BANDS[horizon]
            theoretical_b = target_pct / stop_pct

            fr = factor_results.get(key)
            if fr and fr["total"] >= 10:
                p = fr["winRate"]
                b = fr["payoffRatio"] if fr["payoffRatio"] > 0 else theoretical_b
                src = "actual"
            else:
                p = _DEFAULT_WIN_RATE[horizon]
                b = theoretical_b
                src = "theoretical"

            f_full = _kelly(p, b)
            f_half = f_full / 2
            rec_pct = round(min(f_half * 100, 20.0), 1)  # 최대 20% 캡

            kelly_results[key] = {
                "winRate":        round(p, 4),
                "payoffRatio":    round(b, 3),
                "kellyFull":      round(f_full, 4),
                "kellyHalf":      round(f_half, 4),
                "recommendedPct": rec_pct,
                "dataSource":     src,
                "sampleCount":    fr["total"] if fr else 0,
            }

    factor_doc: dict[str, Any] = {
        "updatedAt":   now,
        "totalRows":   sum(v["total"] for v in factor_results.values()),
        "byStrategy":  factor_results,
        "byMarket":    market_factor,
        "byProbBand":  prob_factor,
        "insight":     _generate_insights(factor_results, market_factor, kelly_results),
    }
    return factor_doc, kelly_results


def main() -> None:
    factor_doc, kelly_doc = run()

    OUT_FACTOR.parent.mkdir(parents=True, exist_ok=True)
    OUT_KELLY.parent.mkdir(parents=True, exist_ok=True)

    OUT_FACTOR.write_text(
        json.dumps(factor_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    OUT_KELLY.write_text(
        json.dumps(kelly_doc, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total = factor_doc.get("totalRows", 0)
    print(f"[factor_attribution] 총 {total}건 분석, 전략별 {len(factor_doc['byStrategy'])}개")
    for insight in factor_doc.get("insight", []):
        print(f"  [인사이트] {insight}")

    print(f"\n[kelly_position_sizes] {len(kelly_doc)}개 전략")
    for key, v in kelly_doc.items():
        src = "실측" if v["dataSource"] == "actual" else "이론"
        print(f"  {key:30s}: half-Kelly={v['kellyHalf']:.1%}  권장={v['recommendedPct']}%  ({src},{v['sampleCount']}건)")


if __name__ == "__main__":
    main()
