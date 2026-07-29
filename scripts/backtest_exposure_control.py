#!/usr/bin/env python3
"""국면별 총 노출 상한(gross exposure cap)을 15년 데이터로 검증한다.

왜: 오늘 측정에서 **손실의 89%가 시장 노출(베타)**이었다. 알파는 0과 구별되지
않는다. 그런데 MONE에는 노출을 조절하는 장치가 **아예 없다** — 국면과 무관하게
매일 비슷한 수의 후보를 같은 비중으로 낸다. 베타 0.411은 설계가 아니라 우연이다.

참고: `virattt/ai-hedge-fund` v2/risk/limits.py
    "Exposure removed by a clamp is NOT redistributed to other names;
     it stays in cash. Redistributing would let the risk stage *increase*
     positions, which inverts its job."
    -> 상한에 걸려 빠진 노출은 **현금으로 남긴다.** 다른 종목에 재분배하지 않는다.

밴드 튜닝과 다른 점: 밴드는 과거 성과에 맞춘 **적합 파라미터**라 표본 밖에서
무너졌다(KR train 1위 -> test 최하위권). 노출 상한은 적합이 아니라 **구조적
한도**다. "약세장에서 덜 산다"는 규칙에 자유도가 거의 없다.

방법: 15년 KOSPI를 국면별로 나누고, 각 국면에서 지수에 노출된 비율을 바꿔가며
자본곡선을 굴린다. 종목 선택은 재현할 수 없으므로 **지수 수익 x 노출**로
근사한다 — 알파가 0이라는 측정과 일관된 가정이다.

실행: python scripts/backtest_exposure_control.py
쓰기: reports/exposure_control_backtest.json
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
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "reports" / "exposure_control_backtest.json"
KOSPI = ROOT / "data" / "market" / "ohlcv" / "kr_KOSPI_daily.csv"

# 검증할 국면별 노출 조합 (BULL, SIDE, BEAR)
POLICIES = {
    "현행(상시 만기 노출)":      (1.00, 1.00, 1.00),
    "약세장 절반":               (1.00, 1.00, 0.50),
    "약세장 정지":               (1.00, 1.00, 0.00),
    "약세장 정지+횡보 감축":     (1.00, 0.60, 0.00),
    "강세장만":                  (1.00, 0.00, 0.00),
    "보수(강세 80/횡보 40/약세 0)": (0.80, 0.40, 0.00),
}
# 노출을 바꾸면 거래가 생긴다 — 왕복 비용(국장 0.41%)을 전환 시마다 문다.
SWITCH_COST_PCT = 0.41


def _closes() -> list[tuple[str, float]]:
    out = []
    with KOSPI.open("r", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            d = str(r.get("date") or "")[:10]
            try:
                c = float(r.get("close") or 0)
            except (TypeError, ValueError):
                continue
            if d and c > 0:
                out.append((d, c))
    out.sort()
    return out


def run() -> dict:
    import regime_kr as R
    series = R.kospi_regime_series(str(ROOT))
    rows = _closes()

    results = {}
    for name, (w_bull, w_side, w_bear) in POLICIES.items():
        nav = 100.0
        prev_w = None
        switches = 0
        daily = []
        exposed_days = 0
        for i in range(1, len(rows)):
            d, c = rows[i]
            reg = series.get(rows[i - 1][0])       # **전일** 국면으로 오늘 노출 결정(룩어헤드 방지)
            if reg is None:
                continue
            w = {"BULL": w_bull, "SIDE": w_side, "BEAR": w_bear}.get(reg, w_side)
            if prev_w is not None and abs(w - prev_w) > 1e-9:
                nav *= (1 - SWITCH_COST_PCT / 100 * abs(w - prev_w))
                switches += 1
            prev_w = w
            r = (c - rows[i - 1][1]) / rows[i - 1][1]
            nav *= (1 + w * r)
            daily.append(w * r * 100)
            if w > 0:
                exposed_days += 1
        if not daily:
            continue
        sd = statistics.pstdev(daily)
        results[name] = {
            "weights": {"BULL": w_bull, "SIDE": w_side, "BEAR": w_bear},
            "finalNav": round(nav, 2),
            "totalReturnPct": round(nav - 100, 2),
            "days": len(daily),
            "exposedDayShare": round(exposed_days / len(daily), 3),
            "switches": switches,
            "dailyVolPct": round(sd, 4),
            # 위험 대비 성과 — 노출을 줄이면 수익도 줄지만 변동성이 더 줄면 개선이다.
            "returnPerVol": round((nav - 100) / sd, 2) if sd else None,
        }

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "KOSPI 일봉 15년 (2011-07-29~2026-07-29)",
        "method": ("전일 국면으로 당일 노출을 정한다(룩어헤드 없음). 종목 선택은 "
                   "재현 불가라 지수 수익 x 노출로 근사한다 — 알파가 0과 구별되지 "
                   "않는다는 측정과 일관된 가정이다."),
        "reference": "virattt/ai-hedge-fund v2/risk/limits.py (상한에 걸린 노출은 현금으로 남긴다)",
        "switchCostPct": SWITCH_COST_PCT,
        "policies": results,
        "caveats": [
            "알파가 (+)면 노출을 줄일수록 손해다. 이 표는 '알파 0' 가정 위에 있다.",
            "국면 라벨이 실제와 어긋나 있다(reports/regime_label_audit.md). "
            "라벨이 고쳐지면 이 결과도 다시 재야 한다.",
            "지수 근사라 종목 분산·개별 손절 효과가 빠져 있다.",
        ],
    }


def main() -> int:
    d = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"=== 국면별 노출 상한 백테스트 ({d['source']}) ===\n")
    print(f"{'정책':<28}{'최종NAV':>10}{'총수익%':>10}{'노출일%':>9}{'일변동%':>9}{'수익/변동':>10}")
    for k, v in d["policies"].items():
        print(f"{k:<28}{v['finalNav']:>10.1f}{v['totalReturnPct']:>10.1f}"
              f"{v['exposedDayShare']*100:>9.1f}{v['dailyVolPct']:>9.3f}"
              f"{str(v['returnPerVol']):>10}")
    print()
    for c in d["caveats"]:
        print(f"  · {c}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
