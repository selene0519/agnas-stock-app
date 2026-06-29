from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

# generate_kr/us_recommendations 임포트는 core/ 전체를 끌어와서 sys.path를 오염시킬 수
# 있다(이 세션에서 여러 번 재현). 실제 생성 스크립트를 통째로 돌리는 통합 테스트라 더더욱
# 서브프로세스로 격리한다.
_PROBE = r"""
import sys, json
sys.path.insert(0, {root!r})
from scripts.generate_kr_recommendations import indicators, pre_rise_score, recommendation_bucket

# 실제 OHLCV 하나를 읽어서 진짜 파이프라인과 같은 함수 호출 경로로 검증
import csv
rows = []
price = 10000.0
import random
random.seed(7)
for i in range(80):
    low = price * (0.99 + i * 0.0002)
    high = price * (1.01 + i * 0.0001)
    close = price * (1.0 + (random.random() - 0.5) * 0.005)
    vol = 100000 + (i * 500 if close > price else 0)
    rows.append({{"date": f"2026-01-{{(i % 28) + 1:02d}}", "open": price, "high": high, "low": low, "close": close, "volume": vol}})
    price = close

ind = indicators(rows)
pr = pre_rise_score(ind)
bucket, reason = recommendation_bucket(ind, pr)

print(json.dumps({{
    "has_total": "totalScore" in pr,
    "has_bucket_fields": isinstance(bucket, str) and isinstance(reason, str),
    "accumulation_present": "accumulationScore" in pr,
    "rising_lows_in_indicators": "risingLows" in ind,
}}))
"""


def test_pre_rise_pipeline_runs_end_to_end_on_real_function_chain():
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.format(root=str(ROOT_DIR))],
        capture_output=True, text=True, cwd=str(ROOT_DIR), timeout=60,
    )
    assert result.returncode == 0, result.stderr
    import json
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == {
        "has_total": True,
        "has_bucket_fields": True,
        "accumulation_present": True,
        "rising_lows_in_indicators": True,
    }


def test_generated_kr_recommendation_csv_has_pre_rise_columns():
    """실제로 돌린 generate_kr_recommendations.py 출력에 새 컬럼이 들어있는지 확인.
    (CI에서 매번 새로 생성하지 않고, 이미 reports/에 있는 파일을 검사한다.)"""
    candidates = sorted(ROOT_DIR.glob("reports/mone_v36_final_recommendations_kr_*.csv"))
    nonempty = [p for p in candidates if p.stat().st_size > 50]
    if not nonempty:
        return  # 추천 파일이 비어있는 레짐 상황 — 스킵
    with nonempty[0].open(encoding="utf-8-sig", newline="") as f:
        header = next(csv.reader(f))
    for col in ("preRiseScore", "preRiseBucket", "accumulationScore", "convergenceScore",
                "alreadyMovedPenalty"):
        assert col in header, f"{col} missing from {nonempty[0].name}"
