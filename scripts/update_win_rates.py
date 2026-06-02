"""
가상운용 검증 결과 누적 시 전략별 실제 승률로 자동 보정.

설계:
- reports/virtual_validation_results.csv를 읽어 전략별 승률 계산
- 최소 20건 이상일 때만 반영 (통계적 유의성)
- 결과를 reports/strategy_win_rates.json에 저장
- generate_kr/us_recommendations.py에서 이 파일을 읽어 EV 계산

승률 보정 범위: 35% ~ 65% (하드 클램프)
업데이트 주기: GitHub Actions에서 주 1회 실행

파일 구조:
{
  "updatedAt": "...",
  "sampleCounts": {"conservative_short": 45, ...},
  "winRates": {
    "conservative_short": 0.512,
    "balanced_swing": 0.534,
    ...
  },
  "defaultRates": {    ← 데이터 부족 시 사용
    "short_base": 0.485,
    "swing_base": 0.505,
    "mid_base": 0.515
  }
}
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALIDATION_CSV = ROOT / "reports" / "virtual_validation_results.csv"
WIN_RATES_JSON = ROOT / "reports" / "strategy_win_rates.json"

MIN_SAMPLES   = 20     # 이 이상일 때만 실제 승률 반영
MAX_ADJUST    = 0.08   # 기본값에서 최대 ±8% 보정 (너무 큰 편향 방지)
WIN_RATE_MIN  = 0.35
WIN_RATE_MAX  = 0.65

# 기본값 (데이터 부족 시 사용)
DEFAULTS = {
    "short_base":  0.485,
    "swing_base":  0.505,
    "mid_base":    0.515,
    "short_scale": 0.12,
    "swing_scale": 0.14,
    "mid_scale":   0.15,
}

MODES    = ["conservative", "balanced", "aggressive"]
HORIZONS = ["short", "swing", "mid"]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _is_win(row: dict) -> bool | None:
    """검증 결과에서 승/패 판단. None = 데이터 불충분."""
    result = str(row.get("result") or row.get("status") or "").upper()
    if result in ("PENDING", "DATA_PENDING", ""):
        return None
    # 성공: 목표 도달
    if any(k in result for k in ("WIN", "SUCCESS", "TP", "TARGET", "목표")):
        return True
    # 실패: 손절
    if any(k in result for k in ("LOSS", "FAIL", "STOP", "손절", "SL")):
        return False
    # 수익률 기반 판단
    ret = row.get("returnPct") or row.get("return_pct") or row.get("virtualReturnPct")
    if ret is not None:
        try:
            return float(str(ret).replace("%", "").strip()) > 0
        except Exception:
            pass
    return None


def calculate_win_rates() -> dict[str, Any]:
    rows = _read_csv(VALIDATION_CSV)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 전략별 집계
    counts: dict[str, dict[str, int]] = {}
    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            counts[key] = {"win": 0, "loss": 0, "total": 0}

    for row in rows:
        mode    = str(row.get("mode", "")).lower().strip()
        horizon = str(row.get("horizon", "")).lower().strip()
        if mode not in MODES or horizon not in HORIZONS:
            continue
        result = _is_win(row)
        if result is None:
            continue
        key = f"{mode}_{horizon}"
        counts[key]["total"] += 1
        if result:
            counts[key]["win"] += 1
        else:
            counts[key]["loss"] += 1

    # 기본값에서 출발
    win_rates: dict[str, float] = {}
    sample_counts: dict[str, int] = {}

    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            c = counts[key]
            sample_counts[key] = c["total"]

            default_base = DEFAULTS[f"{horizon}_base"]

            if c["total"] >= MIN_SAMPLES:
                # 실제 승률 계산
                actual_rate = c["win"] / c["total"]
                # 너무 큰 편차 방지: 기본값 ± MAX_ADJUST 범위 내로 클램프
                clamped = max(
                    default_base - MAX_ADJUST,
                    min(default_base + MAX_ADJUST, actual_rate)
                )
                # 절대 클램프
                win_rates[key] = round(max(WIN_RATE_MIN, min(WIN_RATE_MAX, clamped)), 4)
            else:
                # 데이터 부족: 기본값 사용
                win_rates[key] = default_base

    # 전략별 추가 보정
    # 공격형은 고변동성 → 기본 승률보다 약간 낮게 시작
    # 보수형은 리스크 낮음 → 약간 높게
    for horizon in HORIZONS:
        base = DEFAULTS[f"{horizon}_base"]
        cons_key  = f"conservative_{horizon}"
        aggr_key  = f"aggressive_{horizon}"
        if sample_counts.get(cons_key, 0) < MIN_SAMPLES:
            win_rates[cons_key] = round(min(WIN_RATE_MAX, base + 0.01), 4)
        if sample_counts.get(aggr_key, 0) < MIN_SAMPLES:
            win_rates[aggr_key] = round(max(WIN_RATE_MIN, base - 0.01), 4)

    total_validated = sum(c["total"] for c in counts.values())
    total_wins = sum(c["win"] for c in counts.values())
    overall_rate = round(total_wins / total_validated, 4) if total_validated > 0 else None

    result_doc = {
        "updatedAt": now,
        "totalSamples": total_validated,
        "totalWins": total_wins,
        "overallWinRate": overall_rate,
        "minSamplesForUpdate": MIN_SAMPLES,
        "sampleCounts": sample_counts,
        "winRates": win_rates,
        "defaultRates": DEFAULTS,
        "note": (
            f"샘플 {MIN_SAMPLES}건 미만 전략은 기본값 사용. "
            f"전체 {total_validated}건 검증됨."
        ),
    }
    return result_doc


def main() -> None:
    result = calculate_win_rates()
    WIN_RATES_JSON.parent.mkdir(parents=True, exist_ok=True)
    WIN_RATES_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    counts = result["sampleCounts"]
    rates  = result["winRates"]
    print(f"[{result['updatedAt']}] 승률 파일 업데이트")
    print(f"  전체 검증: {result['totalSamples']}건 / 전체 승률: {result['overallWinRate']}")
    for k, n in sorted(counts.items()):
        rate = rates.get(k, "-")
        src  = "실측" if n >= MIN_SAMPLES else "기본값"
        print(f"  {k:25s}: {rate:.1%}  ({n}건, {src})")


if __name__ == "__main__":
    main()
