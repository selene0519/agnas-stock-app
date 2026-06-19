"""팩터 귀속분석 + Kelly 포지션 사이즈 계산.

분석 순서:
1. VTJ journal CSV + evaluation CSV 조인 → 입력 시점 기술지표 + 결과 매칭
2. OLS 회귀: returnPct ~ rsi + volumeRatio + distanceToMa20 + probability + momentum5
3. 팩터별 회귀계수로 각 신호의 수익 기여도 산출
4. Kelly criterion으로 전략별 최적 포지션 비율 계산

출력:
  reports/factor_attribution.json  — 팩터 기여도 + 회귀 결과
  reports/kelly_position_sizes.json — 전략별 Kelly 포지션 권장치

Kelly: f* = p - (1-p)/b  (p=승률, b=payoff ratio)
half-Kelly 실무 권장 (최대 20% 캡)
"""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VTJ_JOURNAL_CSV = ROOT / "data"    / "virtual_trade_journal.csv"
VTJ_EVAL_CSV    = ROOT / "data"    / "virtual_trade_evaluations.csv"
VALIDATION_CSV  = ROOT / "reports" / "virtual_validation_results.csv"
LEDGER_CSV      = ROOT / "data"    / "recommendation_validation_results.csv"
OUT_FACTOR      = ROOT / "reports" / "factor_attribution.json"
OUT_KELLY       = ROOT / "reports" / "kelly_position_sizes.json"

MODES    = ["conservative", "balanced", "aggressive"]
HORIZONS = ["short", "swing", "mid"]

_BANDS: dict[str, tuple[float, float]] = {
    "short": (3.5,  6.0),
    "swing": (6.5,  13.0),
    "mid":   (9.5,  22.5),
}
_DEFAULT_WIN_RATE: dict[str, float] = {
    "short": 0.485, "swing": 0.505, "mid": 0.515,
}


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


def _f(v: Any) -> float | None:
    try:
        x = float(str(v).replace("%", "").strip())
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _result_class(row: dict) -> str | None:
    t = str(
        row.get("result") or row.get("win_loss_result") or row.get("outcome") or row.get("status") or ""
    ).upper()
    if any(k in t for k in ("WIN", "TARGET", "TP", "SUCCESS", "목표")):
        return "WIN"
    if any(k in t for k in ("LOSS", "STOP", "SL", "FAIL", "손절", "EXPIRED")):
        return "LOSS"
    return None


def _return_pct(row: dict) -> float | None:
    for k in ("gross_pnl_pct", "net_pnl_pct", "returnPct", "return_pct",
              "primaryReturn", "return_10d", "virtualReturnPct"):
        v = _f(row.get(k))
        if v is not None:
            return v
    return None


def _probability(row: dict) -> float | None:
    for k in ("probability", "signal_confidence", "validationConfidence", "final_rank_score"):
        v = _f(row.get(k))
        if v is not None:
            return v
    return None


def _load_vtj_joined() -> list[dict[str, Any]]:
    """VTJ journal + evaluation 조인. journal에 기술지표, evaluation에 결과."""
    journal_rows = _read_csv(VTJ_JOURNAL_CSV)
    eval_rows = _read_csv(VTJ_EVAL_CSV)

    # evaluation을 journal_id로 인덱스
    eval_by_id: dict[str, dict] = {r.get("journal_id", ""): r for r in eval_rows}

    joined = []
    for j in journal_rows:
        jid = j.get("journal_id", "")
        ev = eval_by_id.get(jid, {})
        merged = {**j, **ev}  # evaluation 값이 우선 (결과 필드)
        joined.append(merged)

    return joined


def _load_all_outcomes() -> list[dict[str, Any]]:
    """VTJ 조인 + validation CSV + signal ledger — 모든 결과 데이터."""
    rows: list[dict[str, Any]] = _load_vtj_joined()
    for r in rows:
        r.setdefault("_src", "vtj_journal")

    vtj_val = _read_csv(VALIDATION_CSV)
    for r in vtj_val:
        r.setdefault("_src", "vtj_validation")

    led = _read_csv(LEDGER_CSV)
    for r in led:
        r.setdefault("_src", "ledger")

    return rows + vtj_val + led


# ── OLS 회귀 (numpy 없이 정규방정식으로) ────────────────────────────────────

def _ols(X: list[list[float]], y: list[float]) -> list[float] | None:
    """최소제곱법. 반환: β 계수 벡터. n < k+2 이면 None."""
    n = len(y)
    k = len(X[0]) if X else 0
    if n < k + 2:
        return None
    # X^T X 와 X^T y 계산
    xtx = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(k)] for a in range(k)]
    xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(k)]
    # Gauss elimination
    try:
        aug = [xtx[r][:] + [xty[r]] for r in range(k)]
        for col in range(k):
            pivot = max(range(col, k), key=lambda r: abs(aug[r][col]))
            aug[col], aug[pivot] = aug[pivot], aug[col]
            if abs(aug[col][col]) < 1e-12:
                return None
            scale = aug[col][col]
            aug[col] = [v / scale for v in aug[col]]
            for row in range(k):
                if row != col:
                    f = aug[row][col]
                    aug[row] = [aug[row][c] - f * aug[col][c] for c in range(k + 1)]
        return [aug[r][k] for r in range(k)]
    except Exception:
        return None


def _r_squared(X: list[list[float]], y: list[float], beta: list[float]) -> float:
    ybar = sum(y) / len(y)
    ss_tot = sum((yi - ybar) ** 2 for yi in y)
    if ss_tot < 1e-12:
        return 0.0
    ss_res = sum(
        (y[i] - sum(beta[j] * X[i][j] for j in range(len(beta)))) ** 2
        for i in range(len(y))
    )
    return max(0.0, 1.0 - ss_res / ss_tot)


def _kelly(p: float, b: float) -> float:
    if b <= 0 or p <= 0:
        return 0.0
    return max(0.0, p - (1 - p) / b)


def _generate_insights(strat: dict, market: dict, kelly: dict, regression: dict) -> list[str]:
    insights = []

    horizon_wr: dict[str, list[float]] = defaultdict(list)
    for key, v in strat.items():
        h = key.split("_")[1] if "_" in key else ""
        if h and v.get("total", 0) >= 5:
            horizon_wr[h].append(v["winRate"])
    if horizon_wr:
        best_h = max(horizon_wr, key=lambda h: sum(horizon_wr[h]) / len(horizon_wr[h]))
        avg = sum(horizon_wr[best_h]) / len(horizon_wr[best_h])
        insights.append(f"호라이즌: {best_h} 전략 평균 승률 {avg:.1%}로 최고")

    mode_payoff: dict[str, list[float]] = defaultdict(list)
    for key, v in strat.items():
        m = key.split("_")[0] if "_" in key else ""
        if m and v.get("payoffRatio", 0) > 0:
            mode_payoff[m].append(v["payoffRatio"])
    if mode_payoff:
        best_m = max(mode_payoff, key=lambda m: sum(mode_payoff[m]) / len(mode_payoff[m]))
        avg = sum(mode_payoff[best_m]) / len(mode_payoff[best_m])
        insights.append(f"모드: {best_m} 전략 평균 payoff {avg:.2f}x로 최고")

    if len(market) >= 2:
        best_mk = max(market, key=lambda m: market[m]["winRate"])
        insights.append(f"마켓: {best_mk.upper()} 승률 {market[best_mk]['winRate']:.1%}로 우위")

    # 회귀 결과 인사이트
    if regression:
        factors_sorted = sorted(
            regression.items(), key=lambda kv: abs(kv[1].get("coefficient", 0)), reverse=True
        )
        if factors_sorted:
            top_f, top_v = factors_sorted[0]
            coef = top_v.get("coefficient", 0)
            direction = "높을수록" if coef > 0 else "낮을수록"
            insights.append(
                f"회귀분석: {top_f} {direction} 수익률 향상 (β={coef:+.3f})"
            )
        r2_vals = [v.get("r2", 0) for v in regression.values() if v.get("r2") is not None]
        if r2_vals:
            avg_r2 = sum(r2_vals) / len(r2_vals)
            insights.append(f"전체 팩터 설명력 R²={avg_r2:.3f} (0~1, 높을수록 예측력 강함)")

    if kelly:
        best_k = max(kelly, key=lambda k: kelly[k]["recommendedPct"])
        insights.append(
            f"Kelly 최대: {best_k} → 포트폴리오 {kelly[best_k]['recommendedPct']}% 권장"
        )
    return insights


def run() -> tuple[dict[str, Any], dict[str, Any]]:
    rows = _load_all_outcomes()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 전략별 집계 ───────────────────────────────────────────────────────────
    bucket: dict[str, dict] = {
        f"{m}_{h}": {"wins": [], "losses": [], "probs": []}
        for m in MODES for h in HORIZONS
    }
    market_wins:   dict[str, list[float]] = defaultdict(list)
    market_losses: dict[str, list[float]] = defaultdict(list)
    prob_bucket: dict[str, list[float]] = {
        "low_50-60": [], "mid_60-75": [], "high_75+": [],
    }

    # OLS 용 데이터 수집
    ols_data: list[dict[str, float]] = []

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

        # OLS 피처 수집 (기술지표 있는 행만)
        rsi  = _f(row.get("rsi_at_entry") or row.get("rsi14"))
        vr   = _f(row.get("volume_ratio_at_entry") or row.get("volumeRatio20"))
        d20  = _f(row.get("distance_to_ma20_at_entry") or row.get("distanceToMa20"))
        mom5 = _f(row.get("momentum5_at_entry") or row.get("recentMomentum5"))
        if rsi is not None and vr is not None:
            ols_data.append({
                "rsi":        rsi,
                "volumeRatio": vr,
                "distToMa20": d20 if d20 is not None else 0.0,
                "probability": prob / 100.0 if prob is not None else 0.6,
                "momentum5":  mom5 if mom5 is not None else 0.0,
                "return":     ret,
                "isWin":      1.0 if outcome == "WIN" else 0.0,
            })

    # ── OLS 회귀 ─────────────────────────────────────────────────────────────
    FEATURE_NAMES = ["rsi", "volumeRatio", "distToMa20", "probability", "momentum5"]
    regression: dict[str, Any] = {}

    if len(ols_data) >= 10:
        y_ret = [d["return"] for d in ols_data]
        # intercept 포함 (첫 컬럼 = 1)
        X_ret = [[1.0] + [d[f] for f in FEATURE_NAMES] for d in ols_data]
        beta = _ols(X_ret, y_ret)

        if beta is not None:
            r2 = _r_squared(X_ret, y_ret, beta)
            regression["intercept"] = {"coefficient": round(beta[0], 4), "r2": round(r2, 4)}
            for i, fname in enumerate(FEATURE_NAMES, 1):
                regression[fname] = {
                    "coefficient": round(beta[i], 4),
                    "r2": round(r2, 4),
                    "description": {
                        "rsi":         "RSI14 — 높을수록 과매수 (보통 음의 계수)",
                        "volumeRatio": "거래량비율 — 높을수록 모멘텀 강함 (보통 양의 계수)",
                        "distToMa20":  "MA20 이격도% — 너무 높으면 리스크 증가",
                        "probability": "확률 (0~1) — 모델 신뢰도",
                        "momentum5":   "5일 모멘텀% — 단기 추세",
                    }.get(fname, ""),
                }
        else:
            regression["note"] = "행렬 특이값 — 회귀 불가"

        # 승률 예측 회귀 (isWin ~ factors)
        y_win = [d["isWin"] for d in ols_data]
        beta_win = _ols(X_ret, y_win)
        if beta_win is not None:
            r2_win = _r_squared(X_ret, y_win, beta_win)
            regression["_winRateRegression"] = {
                "r2":         round(r2_win, 4),
                "sampleSize": len(ols_data),
                "factors": {
                    FEATURE_NAMES[i]: round(beta_win[i + 1], 4)
                    for i in range(len(FEATURE_NAMES))
                },
            }
    else:
        regression["note"] = f"기술지표 보유 샘플 {len(ols_data)}건 — 최소 10건 필요 (VTJ 누적 후 자동 갱신)"

    # ── 팩터 귀속분석 ────────────────────────────────────────────────────────
    factor_results: dict[str, Any] = {}
    for key, data in bucket.items():
        wins   = data["wins"]
        losses = data["losses"]
        total  = len(wins) + len(losses)
        if total == 0:
            continue
        p        = len(wins) / total
        avg_win  = sum(wins)   / len(wins)   if wins   else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 1.0
        payoff   = avg_win / avg_loss if avg_loss > 0 else 0.0
        avg_prob = sum(data["probs"]) / len(data["probs"]) if data["probs"] else None
        factor_results[key] = {
            "total":          total,
            "wins":           len(wins),
            "losses":         len(losses),
            "winRate":        round(p, 4),
            "avgWinPct":      round(avg_win, 3),
            "avgLossPct":     round(avg_loss, 3),
            "payoffRatio":    round(payoff, 3),
            "avgProbability": round(avg_prob, 1) if avg_prob else None,
            "probAccuracy":   round(p - avg_prob / 100, 3) if avg_prob else None,
        }

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

    prob_factor: dict[str, Any] = {
        band: {"count": len(o), "actualWinRate": round(sum(o) / len(o), 4)}
        for band, o in prob_bucket.items() if o
    }

    # ── Kelly 포지션 사이즈 ───────────────────────────────────────────────────
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
            rec_pct = round(min(f_half * 100, 20.0), 1)

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
        "updatedAt":         now,
        "totalRows":         sum(v["total"] for v in factor_results.values()),
        "olsSampleSize":     len(ols_data),
        "byStrategy":        factor_results,
        "byMarket":          market_factor,
        "byProbBand":        prob_factor,
        "regressionFactors": regression,
        "insight":           _generate_insights(factor_results, market_factor, kelly_results, regression),
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
    ols_n = factor_doc.get("olsSampleSize", 0)
    print(f"[factor_attribution] 총 {total}건 분석 / OLS 회귀 샘플 {ols_n}건")

    reg = factor_doc.get("regressionFactors", {})
    if "note" in reg:
        print(f"  [회귀] {reg['note']}")
    else:
        print("  [회귀계수]")
        for fname, fv in reg.items():
            if fname.startswith("_"):
                continue
            coef = fv.get("coefficient", 0)
            print(f"    {fname:20s}: β={coef:+.4f}")
        wr_reg = reg.get("_winRateRegression", {})
        if wr_reg:
            print(f"  [승률예측 R²={wr_reg.get('r2', 0):.3f}, n={wr_reg.get('sampleSize', 0)}]")

    print(f"\n[kelly_position_sizes]")
    for key, v in kelly_doc.items():
        src = "실측" if v["dataSource"] == "actual" else "이론"
        print(f"  {key:30s}: half-Kelly={v['kellyHalf']:.1%}  권장={v['recommendedPct']}%  ({src},{v['sampleCount']}건)")

    for insight in factor_doc.get("insight", []):
        print(f"  [인사이트] {insight}")


if __name__ == "__main__":
    main()
