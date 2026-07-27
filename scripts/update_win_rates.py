"""
가상운용 검증 결과 누적 시 전략별 실제 승률로 자동 보정.

설계:
- reports/virtual_validation_results.csv를 읽어 전략별 승률 계산
- 최소 20건 이상일 때만 반영 (통계적 유의성)
- 결과를 reports/strategy_win_rates.json에 저장
- generate_kr/us_recommendations.py에서 이 파일을 읽어 EV 계산

실측 승률은 수정하지 않으며, 유효 확률 범위(1%~99%)만 적용
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
VALIDATION_CSV      = ROOT / "reports" / "virtual_validation_results.csv"
SIGNAL_LEDGER_CSV   = ROOT / "data" / "recommendation_validation_results.csv"
WIN_RATES_JSON = ROOT / "reports" / "strategy_win_rates.json"

MIN_SAMPLES   = 20     # 이 이상일 때만 실제 승률 반영
PROBABILITY_MIN = 0.01
PROBABILITY_MAX = 0.99

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
MARKETS = ["kr", "us"]


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
    result = str(
        row.get("result") or row.get("status") or row.get("win_loss_result") or ""
    ).upper()
    if result in ("PENDING", "DATA_PENDING", "FLAT", "NOT_EXECUTED", ""):
        return None
    # 성공: 목표 도달
    if any(k in result for k in ("WIN", "SUCCESS", "TP", "TARGET", "목표")):
        return True
    # 실패: 손절
    if any(k in result for k in ("LOSS", "FAIL", "STOP", "손절", "SL")):
        return False
    # 수익률 기반 판단
    ret = row.get("returnPct") or row.get("return_pct") or row.get("virtualReturnPct") or row.get("primaryReturn")
    if ret is not None:
        try:
            return float(str(ret).replace("%", "").strip()) > 0
        except Exception:
            pass
    return None


def _return_pct(row: dict) -> float | None:
    """Read a realized return without treating a missing value as zero."""
    for key in ("net_pnl_pct", "returnPct", "return_pct", "virtualReturnPct", "primaryReturn"):
        value = row.get(key)
        if value is None or str(value).strip() == "":
            continue
        try:
            return float(str(value).replace("%", "").replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    return None


def _is_realized_forward_result(row: dict) -> tuple[bool, str]:
    """Return whether this row is admissible for a public performance gate."""
    result = str(row.get("result") or row.get("status") or row.get("win_loss_result") or "").upper().strip()
    if result in {"", "PENDING", "DATA_PENDING", "NOT_EXECUTED", "CANCELLED", "INVALID_SYMBOL", "DATA_INVALID"}:
        return False, "NON_EXECUTED_OR_PENDING"
    if _return_pct(row) is None:
        return False, "MISSING_REALIZED_RETURN"
    return True, ""


def _is_same_day_close_placeholder(row: dict) -> bool:
    """Return true for zero-holding-period cost rows, not strategy outcomes."""
    result = str(row.get("result") or row.get("status") or "").strip().lower()
    if result != "close_exit":
        return False
    ret = _return_pct(row)
    return ret is not None and abs(ret) <= 0.15


def _empty_counts() -> dict[str, dict[str, Any]]:
    return {
        f"{mode}_{horizon}": {"win": 0, "loss": 0, "total": 0, "returns": []}
        for mode in MODES
        for horizon in HORIZONS
    }


def _rates_payload(counts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    win_rates: dict[str, float] = {}
    observed_win_rates: dict[str, float | None] = {}
    average_return_pct: dict[str, float | None] = {}
    sample_counts: dict[str, int] = {}

    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            bucket = counts[key]
            sample_counts[key] = bucket["total"]
            observed = round(bucket["win"] / bucket["total"], 4) if bucket["total"] else None
            observed_win_rates[key] = observed
            returns = bucket["returns"]
            average_return_pct[key] = round(sum(returns) / len(returns), 4) if returns else None
            win_rates[key] = (
                round(max(PROBABILITY_MIN, min(PROBABILITY_MAX, observed or 0.0)), 4)
                if bucket["total"] >= MIN_SAMPLES
                else DEFAULTS[f"{horizon}_base"]
            )

    for horizon in HORIZONS:
        base = DEFAULTS[f"{horizon}_base"]
        if sample_counts[f"conservative_{horizon}"] < MIN_SAMPLES:
            win_rates[f"conservative_{horizon}"] = round(min(PROBABILITY_MAX, base + 0.01), 4)
        if sample_counts[f"aggressive_{horizon}"] < MIN_SAMPLES:
            win_rates[f"aggressive_{horizon}"] = round(max(PROBABILITY_MIN, base - 0.01), 4)

    total_samples = sum(bucket["total"] for bucket in counts.values())
    total_wins = sum(bucket["win"] for bucket in counts.values())
    return {
        "totalSamples": total_samples,
        "totalWins": total_wins,
        "overallWinRate": round(total_wins / total_samples, 4) if total_samples else None,
        "sampleCounts": sample_counts,
        "winRates": win_rates,
        "observedWinRates": observed_win_rates,
        "averageReturnPct": average_return_pct,
    }


def calculate_win_rates() -> dict[str, Any]:
    # VTJ 검증 결과 + signal_ledger 검증 결과 병합 (중복 없이)
    rows = _read_csv(VALIDATION_CSV)
    sig_rows = _read_csv(SIGNAL_LEDGER_CSV)
    signal_ledger_row_count = len(sig_rows)
    # The ledger can contain reconstructed or unfilled rows.  It is
    # diagnostic-only and cannot influence the public performance gate.
    sig_rows = []
    # signal_ledger 결과는 weight 0.7로 조정 (forward paper trade 대비 신뢰도 낮음)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    excluded: dict[str, int] = {"NON_EXECUTED_OR_PENDING": 0, "MISSING_REALIZED_RETURN": 0}

    # 전략별 집계
    # Keep the aggregate document for old readers, but calibrate each market
    # independently. A KR loss must never alter a US trade decision.
    counts = _empty_counts()
    market_counts = {market: _empty_counts() for market in MARKETS}

    for row in rows:
        mode    = str(row.get("mode", "")).lower().strip()
        horizon = str(row.get("horizon", "")).lower().strip()
        market = str(row.get("market", "")).lower().strip()
        if mode not in MODES or horizon not in HORIZONS:
            continue
        if _is_same_day_close_placeholder(row):
            excluded["SAME_DAY_CLOSE_PLACEHOLDER"] = excluded.get("SAME_DAY_CLOSE_PLACEHOLDER", 0) + 1
            continue
        eligible, exclusion_reason = _is_realized_forward_result(row)
        if not eligible:
            excluded[exclusion_reason] = excluded.get(exclusion_reason, 0) + 1
            continue
        result = _is_win(row)
        if result is None:
            excluded["UNCLASSIFIED_RESULT"] = excluded.get("UNCLASSIFIED_RESULT", 0) + 1
            continue
        key = f"{mode}_{horizon}"
        bucket_sets = [counts]
        if market in market_counts:
            bucket_sets.append(market_counts[market])
        for bucket_set in bucket_sets:
            bucket_set[key]["total"] += 1
            if result:
                bucket_set[key]["win"] += 1
            else:
                bucket_set[key]["loss"] += 1
        realized_return = _return_pct(row)
        if realized_return is not None:
            counts[key]["returns"].append(realized_return)
            if market in market_counts:
                market_counts[market][key]["returns"].append(realized_return)

    # 기본값에서 출발
    win_rates: dict[str, float] = {}
    observed_win_rates: dict[str, float | None] = {}
    average_return_pct: dict[str, float | None] = {}
    sample_counts: dict[str, int] = {}

    for mode in MODES:
        for horizon in HORIZONS:
            key = f"{mode}_{horizon}"
            c = counts[key]
            sample_counts[key] = c["total"]

            default_base = DEFAULTS[f"{horizon}_base"]
            observed = round(c["win"] / c["total"], 4) if c["total"] else None
            observed_win_rates[key] = observed
            returns = c["returns"]
            average_return_pct[key] = round(sum(returns) / len(returns), 4) if returns else None

            if c["total"] >= MIN_SAMPLES:
                # Observed performance must remain unmodified: a losing strategy
                # must never be made to look viable through a probability floor.
                win_rates[key] = round(max(PROBABILITY_MIN, min(PROBABILITY_MAX, observed or 0.0)), 4)
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
            win_rates[cons_key] = round(min(PROBABILITY_MAX, base + 0.01), 4)
        if sample_counts.get(aggr_key, 0) < MIN_SAMPLES:
            win_rates[aggr_key] = round(max(PROBABILITY_MIN, base - 0.01), 4)

    total_validated = sum(c["total"] for c in counts.values())
    total_wins = sum(c["win"] for c in counts.values())
    overall_rate = round(total_wins / total_validated, 4) if total_validated > 0 else None
    by_market = {market: _rates_payload(market_counts[market]) for market in MARKETS}

    result_doc = {
        "updatedAt": now,
        "totalSamples": total_validated,
        "totalWins": total_wins,
        "overallWinRate": overall_rate,
        "minSamplesForUpdate": MIN_SAMPLES,
        "sampleCounts": sample_counts,
        "winRates": win_rates,
        "observedWinRates": observed_win_rates,
        "averageReturnPct": average_return_pct,
        "byMarket": by_market,
        "performanceDataPolicy": {
            "source": "reports/virtual_validation_results.csv",
            "requiresRealizedReturn": True,
            "excludedRows": excluded,
            "signalLedgerRowsExcluded": signal_ledger_row_count,
        },
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
