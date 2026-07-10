"""
live_calibrator.py — 라이브 가상매매(VTJ) 실측 기반 롤링 보정 테이블

배경:
  기존 calibratedWinRate 두 소스는 모두 낙관 편향:
    (1) ensemble_calibrator: walk-forward '백테스트' 승률 44~55% (라이브 실측 ~35% 대비 낙관)
    (2) quant_scanner: 하드코딩 선형공식 48.5~65% (레짐 무시·비경험적)
  둘 다 45% 게이트를 약세장에서 무력화 → 음의 엣지가 그대로 통과.

이 모듈:
  - 소스를 '라이브 정산 결과'(virtual_trade_evaluations × journal)로 교체
  - recency 지수감쇠 가중 (반감기 기본 30거래일) → 레짐 전환에 며칠 내 적응
  - thin 버킷은 prior(백테스트 테이블 or global)로 베이지안 shrinkage → 노이즈 억제
  - 출력 구조는 ensemble_calibration_*.json과 호환 (drop-in 가능)

stdlib만 사용 (ensemble_calibrator와 동일 정책).
"""
from __future__ import annotations

import json
import math
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

# finalScore 분포(라이브 KR 68~91)에 맞춘 상단 세분화 bin.
# 기존 _SCORE_BINS는 상단이 70-100 단일이라 선택 스킬(75-80 vs 85+)을 뭉갬 → 상단을 쪼갬.
DEFAULT_BINS: list[tuple[float, float]] = [
    (0, 72), (72, 76), (76, 80), (80, 84), (84, 88), (88, 200),
]
DEFAULT_HALF_LIFE_DAYS = 30.0
DEFAULT_SHRINK_K = 20.0  # prior로 끌어당기는 강도(유효표본 k건과 동등)


def bin_label(score: float, bins: list[tuple[float, float]] = DEFAULT_BINS) -> str:
    for lo, hi in bins:
        if lo <= score < hi:
            return f"{int(lo)}-{int(hi)}"
    return f"{int(bins[-1][0])}-{int(bins[-1][1])}"


def norm_regime(raw: str) -> str:
    """저널/서빙 레짐 라벨을 3분류로 정규화 (RISK_ON/약세장 ↔ BULL/SIDE/BEAR 정합)."""
    r = (raw or "").strip().upper()
    if r in {"RISK_ON", "BULL", "STRONG_BULL", "UPTREND"}:
        return "BULL"
    if r in {"BEAR", "RISK_OFF", "약세장", "DOWNTREND", "STRONG_BEAR"}:
        return "BEAR"
    return "SIDE"


def _to_date(s: str) -> date | None:
    s = (s or "")[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _decay_weight(trade_day: date, as_of: date, half_life_days: float) -> float:
    age = max(0, (as_of - trade_day).days)
    if half_life_days <= 0:
        return 1.0
    return 0.5 ** (age / half_life_days)


def build_live_calibration(
    trade_records: Iterable[dict[str, Any]],
    *,
    as_of: date | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    shrink_k: float = DEFAULT_SHRINK_K,
    prior_table: dict[str, Any] | None = None,
    bins: list[tuple[float, float]] = DEFAULT_BINS,
) -> dict[str, Any]:
    """
    라이브 정산 거래로 (scoreBin × regime) 롤링 보정 테이블 생성.

    trade_records: 각 dict에 finalScore, regime, netPnlPct, date(YYYY-MM-DD) 필요.
    prior_table: 기존 백테스트 테이블의 {"table": {...}, "global": {...}} (shrinkage prior).
    반환: {"table": {"bin|REGIME": {...}}, "global": {...}, "bins": [...], "params": {...}}
    """
    as_of = as_of or date.today()
    prior_tab = (prior_table or {}).get("table", {}) if prior_table else {}
    prior_global = (prior_table or {}).get("global", {}) if prior_table else {}
    prior_global_wr = _num(prior_global.get("winRate"))

    # (bin,regime) → 가중 합계
    agg: dict[str, dict[str, float]] = {}
    g_wins = g_n = 0.0
    g_pnl_w = 0.0
    for rec in trade_records:
        score = _num(rec.get("finalScore"))
        net = _num(rec.get("netPnlPct"))
        d = _to_date(str(rec.get("date") or ""))
        if score is None or net is None or d is None:
            continue
        w = _decay_weight(d, as_of, half_life_days)
        if w <= 0:
            continue
        reg = norm_regime(str(rec.get("regime") or ""))
        key = f"{bin_label(score, bins)}|{reg}"
        cell = agg.setdefault(key, {"wins": 0.0, "n": 0.0, "pnl_w": 0.0})
        win = 1.0 if net > 0 else 0.0
        cell["wins"] += w * win
        cell["n"] += w
        cell["pnl_w"] += w * net
        g_wins += w * win
        g_n += w
        g_pnl_w += w * net

    global_wr = (g_wins / g_n * 100.0) if g_n > 0 else (prior_global_wr or 0.0)
    global_pnl = (g_pnl_w / g_n) if g_n > 0 else 0.0

    table: dict[str, dict[str, Any]] = {}
    for key, cell in agg.items():
        n = cell["n"]
        raw_wr = (cell["wins"] / n * 100.0) if n > 0 else 0.0
        # prior: 백테스트 같은 버킷 winRate, 없으면 라이브 global
        prior_wr = _num((prior_tab.get(key) or {}).get("winRate"))
        if prior_wr is None:
            prior_wr = global_wr
        # 베이지안 shrinkage: (nΣwin + k·prior) / (n + k)
        shrunk = (cell["wins"] * 100.0 + shrink_k * prior_wr) / (n + shrink_k) if (n + shrink_k) > 0 else prior_wr
        table[key] = {
            "winRate": round(shrunk, 1),           # 게이트가 읽는 값(shrunk)
            "rawWinRate": round(raw_wr, 1),          # 참고: 순수 라이브 실측
            "avgPnl": round(cell["pnl_w"] / n, 3) if n > 0 else 0.0,
            "effN": round(n, 1),                     # 유효표본(가중합)
            "priorWinRate": round(prior_wr, 1),
        }

    return {
        "table": table,
        "global": {"winRate": round(global_wr, 1), "avgPnl": round(global_pnl, 3), "effN": round(g_n, 1)},
        "bins": [f"{int(l)}-{int(h)}" for l, h in bins],
        "params": {"halfLifeDays": half_life_days, "shrinkK": shrink_k, "asOf": as_of.isoformat()},
    }


def lookup_win_rate(
    cal: dict[str, Any],
    final_score: float | None,
    regime: str,
    bins: list[tuple[float, float]] = DEFAULT_BINS,
) -> float | None:
    """보정 테이블에서 (score,regime) 승률 조회. 버킷 없으면 same-bin SIDE→global 폴백."""
    if final_score is None or not cal:
        return None
    table = cal.get("table", {})
    b = bin_label(final_score, bins)
    reg = norm_regime(regime)
    for key in (f"{b}|{reg}", f"{b}|SIDE"):
        cell = table.get(key)
        if cell and cell.get("winRate") is not None:
            return float(cell["winRate"])
    gw = cal.get("global", {}).get("winRate")
    return float(gw) if gw is not None else None


def _num(x: Any) -> float | None:
    try:
        if x is None or x == "" or (isinstance(x, float) and math.isnan(x)):
            return None
        return float(str(x).replace(",", ""))
    except Exception:
        return None


def save_live_calibration(cal: dict[str, Any], market: str, mode: str, horizon: str, repo_root: Path) -> Path:
    cal = {**cal, "market": market, "mode": mode, "horizon": horizon, "source": "live_vtj_rolling"}
    path = repo_root / "reports" / f"live_calibration_{market}_{mode}_{horizon}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(cal, f, ensure_ascii=False, indent=2)
    return path


_POOLED_CACHE: dict[str, Any] = {}


def load_pooled_live_calibration(market: str, repo_root: Path) -> dict[str, Any]:
    """통합 라이브 보정 테이블(reports/live_calibration_{market}.json) 로드 (메모리 캐시)."""
    if market in _POOLED_CACHE:
        return _POOLED_CACHE[market]
    path = Path(repo_root) / "reports" / f"live_calibration_{market}.json"
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    _POOLED_CACHE[market] = data
    return data


def lookup_cell(
    cal: dict[str, Any],
    final_score: float | None,
    regime: str,
    bins: list[tuple[float, float]] = DEFAULT_BINS,
) -> dict[str, Any] | None:
    """(score,regime) 버킷 셀 전체 반환 (winRate/effN 등). 없으면 same-bin SIDE 폴백."""
    if final_score is None or not cal:
        return None
    table = cal.get("table", {})
    b = bin_label(final_score, bins)
    reg = norm_regime(regime)
    for key in (f"{b}|{reg}", f"{b}|SIDE"):
        cell = table.get(key)
        if cell:
            return cell
    return None
