"""
pattern_performance_tracker.py
──────────────────────────────────────────────────────────────────────────
퀀트 시스템 — 패턴 성과 누적 엔진 (3가지 방법 통합)

방법 1: 롤링 패턴 성과 (Rolling Pattern Performance)
  - 각 strategyTag/chartPattern별 최근 100건 실적 누적
  - 누적 승률이 높은 패턴 → finalScore 보너스
  - 누적 승률이 낮은 패턴 → 경고 플래그

방법 2: 지지/저항 강도 학습 (Support/Resistance Zone)
  - 과거 OHLCV에서 반복적으로 반등/하락이 일어난 가격대 추출
  - 현재 추천의 목표가/손절가가 강한 저항/지지에 위치하는지 확인

방법 3: 레짐별 조건부 성과 (Regime-Conditional Stats)
  - BULL/BEAR/SIDE 레짐에서 각 패턴의 승률 분리
  - 현재 레짐에 맞는 패턴 우선 추천

실행:
  python scripts/pattern_performance_tracker.py --update  # 검증 결과로 성과 업데이트
  python scripts/pattern_performance_tracker.py --analyze # 현재 성과 출력
  python scripts/pattern_performance_tracker.py --build   # OHLCV로 지지/저항 재계산
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PERF_PATH   = ROOT / "reports" / "pattern_performance.json"
SR_PATH     = ROOT / "reports" / "support_resistance_zones.json"
OHLCV_DIR   = ROOT / "data" / "market" / "ohlcv"
VALID_DIR   = ROOT / "data" / "validation"
BT_CSV      = ROOT / "data" / "backtest" / "walk_forward_results.csv"

ROLLING_N   = 100   # 최근 N건 기준 (충분한 표본)
MIN_SAMPLE  = 10    # 최소 표본 수 (이하면 중립)
SR_WINDOW   = 20    # 지지/저항 탐색 윈도우
SR_CLUSTER  = 0.015 # 1.5% 이내 같은 구역으로 묶음


# ────────────────────────────────────────────────────────────────────
# 유틸
# ────────────────────────────────────────────────────────────────────

def _num(v: Any) -> float | None:
    try:
        raw = str(v or "").replace(",", "").replace("원", "").replace("%", "").strip()
        if not raw or raw.lower() in {"nan", "none", ""}: return None
        f = float(raw)
        return None if math.isnan(f) else f
    except Exception:
        return None


def _read_json(path: Path) -> dict:
    if path.exists():
        try: return json.loads(path.read_text(encoding="utf-8"))
        except Exception: pass
    return {}


def _write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_csv(path: Path) -> list[dict]:
    if not path.exists(): return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _series(rows: list[dict], key: str) -> list[float]:
    aliases = {
        "close":  ["close", "Close", "종가"],
        "high":   ["high",  "High",  "고가"],
        "low":    ["low",   "Low",   "저가"],
        "volume": ["volume","Volume","거래량"],
    }.get(key, [key])
    out = []
    for row in rows:
        for a in aliases:
            v = _num(row.get(a))
            if v is not None:
                out.append(v)
                break
    return out


# ────────────────────────────────────────────────────────────────────
# 방법 1: 롤링 패턴 성과 추적
# ────────────────────────────────────────────────────────────────────

def update_pattern_performance():
    """
    walk_forward_results.csv 와 validation CSV에서
    패턴별 최근 ROLLING_N건 성과를 누적.
    reports/pattern_performance.json 에 저장.
    """
    perf = _read_json(PERF_PATH)
    if "patterns" not in perf:
        perf["patterns"] = {}
    if "regimePatterns" not in perf:
        perf["regimePatterns"] = {"BULL": {}, "BEAR": {}, "SIDE": {}}

    # 백테스트 결과 로드
    bt_rows = _read_csv(BT_CSV)
    print(f"백테스트 결과: {len(bt_rows)}건")

    for row in bt_rows:
        pattern = str(row.get("chart_pattern") or row.get("primary_tag") or "UNKNOWN").strip()
        if not pattern or pattern == "UNKNOWN":
            continue
        outcome_raw = str(row.get("outcome") or row.get("exit_reason") or "").strip()
        net_return = _num(row.get("net_return_pct") or row.get("net_return"))
        if net_return is None:
            continue

        win = net_return > 0
        regime = str(row.get("regime") or "SIDE").strip()

        # 전체 성과 누적
        bucket = perf["patterns"].setdefault(pattern, {"trades": [], "summary": {}})
        bucket["trades"].append({
            "date": str(row.get("test_date") or row.get("date") or ""),
            "symbol": str(row.get("symbol") or ""),
            "net_return": round(net_return, 4),
            "win": win,
            "regime": regime,
        })
        # ROLLING_N 이내만 유지
        if len(bucket["trades"]) > ROLLING_N:
            bucket["trades"] = bucket["trades"][-ROLLING_N:]

        # 레짐별 성과 누적
        rb = perf["regimePatterns"].setdefault(regime, {}).setdefault(pattern, {"trades": []})
        rb["trades"].append({"net_return": round(net_return, 4), "win": win})
        if len(rb["trades"]) > ROLLING_N:
            rb["trades"] = rb["trades"][-ROLLING_N:]

    # 요약 통계 계산
    for pattern, bucket in perf["patterns"].items():
        trades = bucket["trades"]
        if not trades:
            continue
        wins = [t for t in trades if t.get("win")]
        returns = [t["net_return"] for t in trades]
        bucket["summary"] = {
            "n": len(trades),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "avg_return": round(sum(returns) / len(returns), 3),
            "max_return": round(max(returns), 3),
            "min_return": round(min(returns), 3),
            # 점수 보너스 계산: 승률 50% 기준 ±최대 15점
            "score_bonus": round((len(wins)/len(trades)*100 - 50) * 0.3, 1) if len(trades) >= MIN_SAMPLE else 0.0,
        }

    for regime, patterns in perf["regimePatterns"].items():
        for pattern, rb in patterns.items():
            trades = rb["trades"]
            if not trades:
                continue
            wins = [t for t in trades if t.get("win")]
            returns = [t["net_return"] for t in trades]
            rb["summary"] = {
                "n": len(trades),
                "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0,
                "avg_return": round(sum(returns) / len(returns), 3) if returns else 0,
            }

    perf["updatedAt"] = datetime.now().isoformat()
    _write_json(PERF_PATH, perf)
    print(f"패턴 성과 저장: {PERF_PATH}")

    # 결과 출력
    print("\n─── 패턴별 누적 성과 ───")
    for pattern, bucket in sorted(perf["patterns"].items()):
        s = bucket.get("summary", {})
        if not s:
            continue
        bonus_str = f"({s['score_bonus']:+.1f}점)" if s.get("n", 0) >= MIN_SAMPLE else "(표본부족)"
        print(f"  {pattern:<25} n={s['n']:>4}  승률={s['win_rate']:>5.1f}%  평균={s['avg_return']:>+6.3f}%  보너스={bonus_str}")


# ────────────────────────────────────────────────────────────────────
# 방법 2: 지지/저항 강도 학습
# ────────────────────────────────────────────────────────────────────

def build_support_resistance():
    """
    100개 KR 종목 OHLCV에서 지지/저항 구역 추출.
    알고리즘:
      1. 각 종목의 로컬 고점/저점을 찾음
      2. 같은 가격대(±1.5%)에 반복 등장하면 강도(strength) 누적
      3. 전체 종목에 공통으로 나타나는 지수화 구간 상위 20개 저장
    reports/support_resistance_zones.json 에 저장.
    """
    print("지지/저항 구역 계산 중...")
    all_zones: dict[str, dict] = {}  # price_level_str → {level, strength, touches, type}

    kr_files = sorted(OHLCV_DIR.glob("kr_[0-9]*.csv"))
    processed = 0
    for fpath in kr_files:
        rows = _read_csv(fpath)
        if len(rows) < 50:
            continue
        symbol = fpath.stem.replace("kr_", "").replace("_daily", "")
        closes = _series(rows, "close")
        highs  = _series(rows, "high")
        lows   = _series(rows, "low")

        if not closes:
            continue

        # 로컬 고점/저점 찾기
        def local_extrema(vals: list[float], window: int = 5) -> tuple[list[float], list[float]]:
            peaks, troughs = [], []
            for i in range(window, len(vals) - window):
                seg = vals[i - window:i + window + 1]
                if vals[i] == max(seg): peaks.append(vals[i])
                if vals[i] == min(seg): troughs.append(vals[i])
            return peaks, troughs

        peaks, troughs = local_extrema(closes, window=5)
        all_levels = [(p, "resistance") for p in peaks] + [(t, "support") for t in troughs]

        for level, zone_type in all_levels:
            if level <= 0:
                continue
            # 클러스터링: ±SR_CLUSTER 이내 기존 구역과 합침
            merged = False
            for key, zone in all_zones.items():
                existing = zone["level"]
                if abs(existing - level) / existing <= SR_CLUSTER:
                    zone["touches"] += 1
                    zone["strength"] += 1
                    zone["level"] = (zone["level"] * (zone["touches"] - 1) + level) / zone["touches"]
                    if zone_type not in zone.get("types", []):
                        zone.setdefault("types", []).append(zone_type)
                    merged = True
                    break
            if not merged:
                key = f"{level:.0f}"
                all_zones[key] = {
                    "level": round(level, 2),
                    "strength": 1,
                    "touches": 1,
                    "types": [zone_type],
                    "symbols": [symbol],
                }
            else:
                for key, zone in all_zones.items():
                    if abs(zone["level"] - level) / level <= SR_CLUSTER:
                        if symbol not in zone.get("symbols", []):
                            zone.setdefault("symbols", []).append(symbol)
                        break
        processed += 1

    # 강도 상위 구역만 저장
    sorted_zones = sorted(all_zones.values(), key=lambda z: z["strength"], reverse=True)
    top_zones = sorted_zones[:200]  # 상위 200개

    result = {
        "updatedAt": datetime.now().isoformat(),
        "totalZones": len(all_zones),
        "topZones": top_zones,
        "method": "local_extrema_clustering_1.5pct",
        "symbolsProcessed": processed,
    }
    _write_json(SR_PATH, result)
    print(f"지지/저항 구역 계산 완료: {len(top_zones)}개 → {SR_PATH}")

    # 상위 10개 출력
    print("\n─── 상위 지지/저항 구역 (강도순) ───")
    for z in top_zones[:10]:
        types = "/".join(z.get("types", []))
        print(f"  {z['level']:>10,.0f}  강도={z['strength']:>4}  터치={z['touches']:>3}  {types}")


# ────────────────────────────────────────────────────────────────────
# 방법 3: 레짐별 성과 통계 요약
# ────────────────────────────────────────────────────────────────────

def analyze_regime_patterns():
    """레짐별 패턴 성과 분석 출력"""
    perf = _read_json(PERF_PATH)
    regime_patterns = perf.get("regimePatterns", {})
    if not regime_patterns:
        print("레짐별 성과 데이터 없음 — --update 먼저 실행")
        return

    print("\n─── 레짐별 패턴 성과 ───")
    for regime in ("BULL", "SIDE", "BEAR"):
        patterns = regime_patterns.get(regime, {})
        if not patterns:
            continue
        print(f"\n[{regime}]")
        for pat, data in sorted(patterns.items()):
            s = data.get("summary", {})
            if not s or s.get("n", 0) < 3:
                continue
            print(f"  {pat:<25} n={s['n']:>3}  승률={s['win_rate']:>5.1f}%  평균={s['avg_return']:>+6.3f}%")


# ────────────────────────────────────────────────────────────────────
# quant_scanner.py 에서 사용하는 런타임 조회 함수
# ────────────────────────────────────────────────────────────────────

_perf_cache: dict | None = None
_sr_cache: dict | None = None


def get_pattern_score_bonus(pattern_tag: str, regime: str = "SIDE") -> float:
    """
    패턴 태그의 누적 성과 기반 점수 보너스 반환.
    - 누적 승률 60%+ → 최대 +10점
    - 누적 승률 40%- → 최대 -8점
    - 표본 부족(< MIN_SAMPLE) → 0점
    """
    global _perf_cache
    if _perf_cache is None:
        _perf_cache = _read_json(PERF_PATH)

    # 레짐별 성과 우선, 없으면 전체 성과
    regime_data = _perf_cache.get("regimePatterns", {}).get(regime, {}).get(pattern_tag, {})
    overall     = _perf_cache.get("patterns", {}).get(pattern_tag, {})

    summary = regime_data.get("summary") or overall.get("summary") or {}
    n = summary.get("n", 0)
    if n < MIN_SAMPLE:
        return 0.0

    win_rate = summary.get("win_rate", 50.0)
    # 50% 기준으로 ±10점 리니어 매핑 (40%→-8점, 60%→+8점, 70%→최대+10점)
    bonus = (win_rate - 50.0) * 0.2
    return round(max(-8.0, min(10.0, bonus)), 1)


def check_sr_proximity(price: float, tolerance_pct: float = 2.0) -> dict:
    """
    목표가/손절가가 강한 지지/저항 구역 근처에 있는지 확인.
    반환: {"nearResistance": bool, "nearSupport": bool, "strength": int, "level": float}
    """
    global _sr_cache
    if _sr_cache is None:
        _sr_cache = _read_json(SR_PATH)

    zones = _sr_cache.get("topZones", [])
    for zone in zones:
        level = zone.get("level", 0)
        if level <= 0:
            continue
        dist_pct = abs(price - level) / level * 100
        if dist_pct <= tolerance_pct:
            types = zone.get("types", [])
            return {
                "nearResistance": "resistance" in types,
                "nearSupport":    "support" in types,
                "strength":       zone.get("strength", 0),
                "level":          round(level, 2),
                "distPct":        round(dist_pct, 2),
            }
    return {"nearResistance": False, "nearSupport": False, "strength": 0, "level": 0.0, "distPct": 99.9}


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MONE 패턴 성과 누적 시스템")
    parser.add_argument("--update",  action="store_true", help="백테스트/검증 결과로 패턴 성과 업데이트")
    parser.add_argument("--analyze", action="store_true", help="현재 패턴 성과 출력")
    parser.add_argument("--build",   action="store_true", help="OHLCV로 지지/저항 구역 재계산")
    parser.add_argument("--all",     action="store_true", help="전체 실행 (update + build + analyze)")
    args = parser.parse_args()

    if args.all or args.update:
        update_pattern_performance()
    if args.all or args.build:
        build_support_resistance()
    if args.all or args.analyze:
        analyze_regime_patterns()

    if not any([args.update, args.analyze, args.build, args.all]):
        parser.print_help()


if __name__ == "__main__":
    main()
