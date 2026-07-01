from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]

_PROBE = r"""
import csv, json, sys, tempfile
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, r"__ROOT__")
import scripts.generate_us_recommendations as gen

tmp = Path(tempfile.mkdtemp())
market_dir = tmp / "data" / "market"
market_dir.mkdir(parents=True)
gen.ROOT = tmp
gen.BENCHMARK_FALLBACK_MAX_AGE_DAYS = 7

def write_benchmark(end):
    path = market_dir / "benchmark_daily.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["date", "benchmark", "close"])
        writer.writeheader()
        for i in range(30):
            day = end - timedelta(days=29 - i)
            writer.writerow({"date": day.isoformat(), "benchmark": "SPY", "close": 100 + i})

write_benchmark(date(2020, 1, 31))
stale = gen._load_us_market_regime()

write_benchmark(date.today())
fresh = gen._load_us_market_regime()

print(json.dumps({"stale": stale, "fresh": fresh}, ensure_ascii=False))
"""


def test_us_market_regime_ignores_stale_benchmark_daily_fallback() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE.replace("__ROOT__", str(ROOT_DIR))],
        capture_output=True,
        text=True,
        cwd=str(ROOT_DIR),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["stale"]["dataStatus"] == "STALE"
    assert out["stale"]["scoreAdjust"] == 0.0
    assert out["stale"]["source"] == "benchmark_daily.csv"
    assert out["fresh"].get("dataStatus") != "STALE"
    assert out["fresh"]["source"] == "benchmark_daily.csv"
