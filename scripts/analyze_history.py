"""
MONE 전략 성과 분석 스크립트
=============================
data/history/ CSV 파일을 읽어 전략별 승률·수익률·점수 상관관계를 분석하고
reports/strategy_performance_report.json 으로 저장합니다.

실행:
    python scripts/analyze_history.py
"""
from __future__ import annotations

import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO  = Path(__file__).resolve().parents[1]
HIST  = REPO / "data" / "history"
REPT  = REPO / "reports"
REPT.mkdir(parents=True, exist_ok=True)

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ─────────────────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────────────────
def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc) as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _f(v: Any, default: float = float("nan")) -> float:
    try:
        s = str(v).replace("%", "").replace(",", "").strip()
        if not s or s.lower() in ("nan", "none", "null", "-", "대기", ""):
            return default
        return float(s)
    except Exception:
        return default


def _mean(vals: list[float]) -> float:
    clean = [v for v in vals if not math.isnan(v)]
    return sum(clean) / len(clean) if clean else float("nan")


def _corr(xs: list[float], ys: list[float]) -> float:
    """피어슨 상관계수"""
    pairs = [(x, y) for x, y in zip(xs, ys) if not math.isnan(x) and not math.isnan(y)]
    if len(pairs) < 5:
        return float("nan")
    n = len(pairs)
    mx = sum(p[0] for p in pairs) / n
    my = sum(p[1] for p in pairs) / n
    num = sum((p[0] - mx) * (p[1] - my) for p in pairs)
    dx  = math.sqrt(sum((p[0] - mx) ** 2 for p in pairs))
    dy  = math.sqrt(sum((p[1] - my) ** 2 for p in pairs))
    return num / (dx * dy) if dx * dy > 0 else float("nan")


# ─────────────────────────────────────────────────────────────────
# 1. virtual_operation_evaluation.csv 분석
# ─────────────────────────────────────────────────────────────────
def analyze_virtual_eval() -> dict[str, Any]:
    rows = _read(HIST / "virtual_operation_evaluation.csv")
    if not rows:
        return {"error": "파일 없음"}

    # 완료된 거래만 (outcome_result != "대기")
    done = [r for r in rows if r.get("outcome_result", "대기").strip() not in ("대기", "")]
    total = len(rows)
    evaluated = len(done)

    # 모드 × 기간별 집계
    bucket: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in done:
        mode     = r.get("mode", "balanced").strip() or "balanced"
        swing    = r.get("swing_group", "swing").strip() or "swing"
        ret      = _f(r.get("realized_return_pct", ""))
        outcome  = r.get("outcome_result", "").strip()
        win      = 1.0 if outcome in ("성공", "목표달성", "익절") else 0.0

        bucket[mode][swing].append(ret)
        bucket[mode]["_win_" + swing].append(win)

    stats: dict[str, Any] = {}
    for mode, swings in bucket.items():
        stats[mode] = {}
        for key, vals in swings.items():
            if key.startswith("_win_"):
                swing = key[5:]
                wins  = [v for v in vals if not math.isnan(v)]
                stats[mode][f"{swing}_win_rate"] = round(
                    sum(wins) / len(wins) * 100, 1) if wins else None
            else:
                rets = [v for v in vals if not math.isnan(v)]
                stats[mode][f"{key}_avg_return"] = round(_mean(rets), 2) if rets else None
                stats[mode][f"{key}_count"]       = len(rets)

    return {
        "total_records": total,
        "evaluated": evaluated,
        "pending": total - evaluated,
        "eval_rate_pct": round(evaluated / total * 100, 1) if total else 0,
        "by_mode": stats,
    }


# ─────────────────────────────────────────────────────────────────
# 2. outcome_history.csv — 실제 가격 추적 분석
# ─────────────────────────────────────────────────────────────────
def analyze_outcome_history() -> dict[str, Any]:
    rows = _read(HIST / "outcome_history.csv")
    if not rows:
        return {"error": "파일 없음"}

    completed = [
        r for r in rows
        if _f(r.get("return_5d", "")) == _f(r.get("return_5d", ""))  # NaN 제거
    ]

    ret1d  = [_f(r.get("return_1d",  "")) for r in completed]
    ret5d  = [_f(r.get("return_5d",  "")) for r in completed]
    ret20d = [_f(r.get("return_20d", "")) for r in completed]
    mdd    = [_f(r.get("max_drawdown", "")) for r in completed]

    def win_rate(rets: list[float]) -> float | None:
        clean = [v for v in rets if not math.isnan(v)]
        return round(sum(1 for v in clean if v > 0) / len(clean) * 100, 1) if clean else None

    return {
        "total": len(rows),
        "with_data": len(completed),
        "return_1d":  {"mean": round(_mean(ret1d), 2),  "win_rate": win_rate(ret1d)},
        "return_5d":  {"mean": round(_mean(ret5d), 2),  "win_rate": win_rate(ret5d)},
        "return_20d": {"mean": round(_mean(ret20d), 2), "win_rate": win_rate(ret20d)},
        "avg_mdd":    round(_mean(mdd), 2) if not math.isnan(_mean(mdd)) else None,
    }


# ─────────────────────────────────────────────────────────────────
# 3. strategy_score_history.csv — 전략별 점수 추이
# ─────────────────────────────────────────────────────────────────
def analyze_strategy_scores() -> dict[str, Any]:
    rows = _read(HIST / "strategy_score_history.csv")
    if not rows:
        return {"error": "파일 없음"}

    result = []
    for r in rows:
        win = _f(r.get("승률", r.get("win_rate", "")))
        avg = _f(r.get("평균수익률", r.get("avg_return", "")))
        result.append({
            "market":     r.get("market", ""),
            "category":   r.get("category", ""),
            "count":      int(_f(r.get("추천건수", r.get("count", "0")), 0)),
            "verified":   int(_f(r.get("검증완료", r.get("verified", "0")), 0)),
            "win_rate":   round(win, 1) if not math.isnan(win) else None,
            "avg_return": round(avg, 2) if not math.isnan(avg) else None,
        })
    return {"records": result}


# ─────────────────────────────────────────────────────────────────
# 4. prediction_snapshot_history.csv — finalScore vs 실제 수익률 상관
# ─────────────────────────────────────────────────────────────────
def analyze_score_correlation() -> dict[str, Any]:
    snap_rows = _read(HIST / "prediction_snapshot_history.csv")
    out_rows  = _read(HIST / "outcome_history.csv")
    if not snap_rows or not out_rows:
        return {"error": "데이터 부족"}

    # outcome을 symbol+date 로 인덱싱
    outcome_map: dict[str, dict[str, float]] = {}
    for r in out_rows:
        key = f"{r.get('symbol','')}_{r.get('date','')[:10]}"
        outcome_map[key] = {
            "r1d":  _f(r.get("return_1d",  "")),
            "r5d":  _f(r.get("return_5d",  "")),
            "r20d": _f(r.get("return_20d", "")),
        }

    # snapshot에서 finalScore 추출 후 outcome 매칭
    score_r5d_pairs: list[tuple[float, float]] = []
    for r in snap_rows:
        score = _f(r.get("finalScore", r.get("final_score", "")))
        sym   = r.get("symbol", "")
        date  = str(r.get("prediction_at", r.get("snapshot_at", "")))[:10]
        key   = f"{sym}_{date}"
        oc    = outcome_map.get(key, {})
        r5d   = oc.get("r5d", float("nan"))
        if not math.isnan(score) and not math.isnan(r5d):
            score_r5d_pairs.append((score, r5d))

    if len(score_r5d_pairs) < 5:
        return {
            "msg": f"매칭 데이터 부족 ({len(score_r5d_pairs)}건). 더 많은 데이터 축적 후 재실행 권장.",
            "matched_count": len(score_r5d_pairs),
        }

    scores = [p[0] for p in score_r5d_pairs]
    rets   = [p[1] for p in score_r5d_pairs]
    r_val  = _corr(scores, rets)

    # 점수 구간별 평균 수익률
    buckets = {"50-59": [], "60-69": [], "70-79": [], "80+": []}
    for s, ret in score_r5d_pairs:
        if s >= 80:    buckets["80+"].append(ret)
        elif s >= 70:  buckets["70-79"].append(ret)
        elif s >= 60:  buckets["60-69"].append(ret)
        else:          buckets["50-59"].append(ret)

    return {
        "matched_count":     len(score_r5d_pairs),
        "pearson_corr_r":    round(r_val, 3) if not math.isnan(r_val) else None,
        "interpretation":    (
            "강한 양의 상관" if r_val > 0.5 else
            "중간 양의 상관" if r_val > 0.3 else
            "약한 상관"      if r_val > 0.1 else
            "상관 없음 (데이터 더 필요)"
        ) if not math.isnan(r_val) else "계산 불가",
        "avg_return_by_score_band": {
            band: round(_mean(vals), 2) if vals else None
            for band, vals in buckets.items()
        },
    }


# ─────────────────────────────────────────────────────────────────
# 5. auto_correction_summary — 자동 보정 현황
# ─────────────────────────────────────────────────────────────────
def analyze_auto_correction() -> dict[str, Any]:
    rows = _read(HIST / "auto_correction_summary.csv")
    if not rows:
        return {"error": "파일 없음"}
    return {"records": [dict(r) for r in rows]}


# ─────────────────────────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 60)
    print("MONE 전략 성과 분석")
    print("=" * 60)

    report: dict[str, Any] = {
        "generated_at":       datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "virtual_eval":       analyze_virtual_eval(),
        "outcome_history":    analyze_outcome_history(),
        "strategy_scores":    analyze_strategy_scores(),
        "score_correlation":  analyze_score_correlation(),
        "auto_correction":    analyze_auto_correction(),
    }

    # 콘솔 요약 출력
    ve = report["virtual_eval"]
    print(f"\n[가상운용 평가]  총 {ve.get('total_records',0)}건 / 평가완료 {ve.get('evaluated',0)}건 ({ve.get('eval_rate_pct',0)}%)")
    for mode, stats in (ve.get("by_mode") or {}).items():
        parts = []
        for h in ("short", "swing", "mid"):
            wr  = stats.get(f"{h}_win_rate")
            avg = stats.get(f"{h}_avg_return")
            cnt = stats.get(f"{h}_count", 0)
            if cnt:
                parts.append(f"{h}: 승률 {wr}% / 수익 {avg:+.2f}% ({cnt}건)")
        if parts:
            print(f"  {mode:12s}: {' | '.join(parts)}")

    oh = report["outcome_history"]
    print(f"\n[실제 가격 추적]  {oh.get('with_data',0)}건 분석")
    for period in ("return_1d", "return_5d", "return_20d"):
        d = oh.get(period, {})
        if isinstance(d, dict):
            print(f"  {period:12s}: 평균 {d.get('mean',0):+.2f}% / 승률 {d.get('win_rate')}%")

    sc = report["score_correlation"]
    print(f"\n[점수-수익 상관]  {sc.get('matched_count',0)}건 매칭")
    print(f"  피어슨 r = {sc.get('pearson_corr_r')}  ({sc.get('interpretation','')})")
    for band, avg in (sc.get("avg_return_by_score_band") or {}).items():
        if avg is not None:
            print(f"  점수 {band:5s}: 평균 수익 {avg:+.2f}%")

    # 파일 저장
    out_path = REPT / "strategy_performance_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n리포트 저장: {out_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
