"""Cloud/CI friendly one-shot accumulator.

Use this from GitHub Actions, VPS cron, or another always-on machine. It runs the
same local report update jobs as the PC accumulator once, then exits.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def main() -> int:
    result = {"status": "OK", "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    try:
        from run_auto_accumulator import _run_once
        result["auto_accumulator"] = _run_once(interval_min=15.0, loop_count=1)
    except Exception as exc:
        result["status"] = "ERROR"
        result["auto_accumulator_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from run_v36_full_update import run_once as run_v36_once
        result["v36"] = run_v36_once()
    except Exception as exc:
        result["status"] = "ERROR"
        result["v36_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from core.v43_operational_engine import run_v43_update
        result["v43"] = run_v43_update()
    except Exception as exc:
        result["status"] = "ERROR"
        result["v43_error"] = f"{type(exc).__name__}: {exc}"
    try:
        from core.v44_learning_calibration_engine import run_v44_update
        result["v44"] = run_v44_update()
    except Exception as exc:
        result["status"] = "ERROR"
        result["v44_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.v45_calibrated_decision_engine import run_v45_update
        result["v45"] = run_v45_update()
    except Exception as exc:
        result["status"] = "ERROR"
        result["v45_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.v50_stability_engine import run_v50_update
        result["v50"] = run_v50_update()
    except Exception as exc:
        result["status"] = "ERROR"
        result["v50_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.v51_fast_light_engine import run_v51_update
        result["v51"] = run_v51_update(fetch_news=True)
    except Exception as exc:
        result["status"] = "ERROR"
        result["v51_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.v52_market_split_engine import run_v52_update
        result["v52"] = run_v52_update(fetch_news=True, fetch_missing_prices=True)
    except Exception as exc:
        result["status"] = "ERROR"
        result["v52_error"] = f"{type(exc).__name__}: {exc}"

    try:
        from core.v60_final_engine import run_v60_update
        result["v60"] = run_v60_update(fetch_news=True, fetch_missing_prices=True)
    except Exception as exc:
        result["status"] = "ERROR"
        result["v60_error"] = f"{type(exc).__name__}: {exc}"

    Path("reports").mkdir(parents=True, exist_ok=True)
    Path("reports/cloud_accumulator_last_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") == "OK" else 2


if __name__ == "__main__":
    raise SystemExit(main())
