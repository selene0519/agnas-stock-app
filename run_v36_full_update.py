"""Run all v33-v36 local update jobs once.

Safe to run manually. It does not place orders. It only reads/writes local report
files used by the Streamlit app.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def run_once() -> dict[str, Any]:
    result: dict[str, Any] = {"status": "OK", "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    jobs: list[tuple[str, str, str]] = [
        ("prediction_learning", "core.prediction_learning_engine", "save_prediction_learning_summary"),
        ("risk_priority", "core.risk_priority_engine", "save_risk_priority_candidates"),
        ("api_status_center", "core.api_status_center_engine", "save_api_status_center"),
        ("cloud_readiness", "core.cloud_readiness_engine", "save_cloud_readiness_status"),
    ]
    for key, module_name, func_name in jobs:
        try:
            mod = __import__(module_name, fromlist=[func_name])
            func = getattr(mod, func_name)
            result[key] = func()
        except Exception as exc:
            result["status"] = "ERROR"
            result[f"{key}_error"] = f"{type(exc).__name__}: {exc}"
    Path("reports").mkdir(parents=True, exist_ok=True)
    Path("reports/v36_full_update_status.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


if __name__ == "__main__":
    out = run_once()
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if out.get("status") == "OK" else 2)
