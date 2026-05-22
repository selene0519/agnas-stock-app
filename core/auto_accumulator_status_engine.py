"""v30 automatic accumulation status, logging, and backup helpers.

This module is intentionally dependency-light so it can be used by both
Streamlit and the headless accumulator process.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
REPORT_DIR = BASE_DIR / "reports"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
BACKUP_DIR = BASE_DIR / "backups"
STATUS_PATH = REPORT_DIR / "auto_accumulator_status.json"
LOG_PATH = LOG_DIR / "auto_accumulator.log"


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_read_json(path: str | Path, default: Any | None = None) -> Any:
    p = Path(path)
    if default is None:
        default = {}
    try:
        if not p.exists() or p.stat().st_size <= 0:
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def safe_write_json(path: str | Path, data: Any) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def append_log(message: str, level: str = "INFO") -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        line = f"[{now_text()}] [{str(level).upper()}] {message}\n"
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _count_csv_rows(path: Path) -> int:
    try:
        if not path.exists() or path.stat().st_size <= 0:
            return 0
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            rows = sum(1 for _ in reader)
        return max(0, rows - 1)
    except Exception:
        return 0


def summarize_data_files() -> dict[str, Any]:
    """Return lightweight counts for files that matter to accumulation."""
    paths = {
        "portfolio_daily_nav": DATA_DIR / "portfolio" / "portfolio_daily_nav.csv",
        "position_daily_snapshot": DATA_DIR / "portfolio" / "position_daily_snapshot.csv",
        "benchmark_daily": DATA_DIR / "market" / "benchmark_daily.csv",
        "news_cache": DATA_DIR / "news" / "news_cache.csv",
        "backtest_beta_summary": REPORT_DIR / "backtest_beta_summary.csv",
        "intraday_realtime_snapshot": REPORT_DIR / "intraday_realtime_snapshot.csv",
        "intraday_orderbook_snapshot": REPORT_DIR / "intraday_orderbook_snapshot.csv",
        "intraday_flow_snapshot": REPORT_DIR / "intraday_flow_snapshot.csv",
        "intraday_data_coverage_diagnosis": REPORT_DIR / "intraday_data_coverage_diagnosis.csv",
        "prediction_learning_summary": REPORT_DIR / "prediction_learning_summary.csv",
        "prediction_learning_symbol_summary": REPORT_DIR / "prediction_learning_symbol_summary.csv",
        "risk_priority_candidates": REPORT_DIR / "risk_priority_candidates.csv",
        "api_data_status_center": REPORT_DIR / "api_data_status_center.csv",
        "cloud_readiness_checklist": REPORT_DIR / "cloud_readiness_checklist.csv",
    }
    out: dict[str, Any] = {}
    for key, path in paths.items():
        out[key] = {
            "path": str(path.relative_to(BASE_DIR)) if path.exists() else str(path.relative_to(BASE_DIR)),
            "exists": bool(path.exists()),
            "rows": _count_csv_rows(path),
            "modified_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if path.exists() else "",
        }
    return out


def create_daily_backup(force: bool = False) -> dict[str, Any]:
    """Copy important CSV/JSON files into backups/YYYY-MM-DD.

    The function is safe to call often. By default it skips files already backed
    up today unless force=True.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    dest = BACKUP_DIR / today
    dest.mkdir(parents=True, exist_ok=True)

    candidate_files = [
        DATA_DIR / "portfolio" / "portfolio_daily_nav.csv",
        DATA_DIR / "portfolio" / "position_daily_snapshot.csv",
        DATA_DIR / "market" / "benchmark_daily.csv",
        DATA_DIR / "news" / "news_cache.csv",
        REPORT_DIR / "portfolio_risk_metrics.json",
        REPORT_DIR / "backtest_beta_summary.csv",
        REPORT_DIR / "backtest_beta_summary.json",
        REPORT_DIR / "auto_accumulator_status.json",
        REPORT_DIR / "intraday_realtime_snapshot.csv",
        REPORT_DIR / "intraday_realtime_summary.json",
        REPORT_DIR / "intraday_orderbook_snapshot.csv",
        REPORT_DIR / "intraday_orderbook_summary.json",
        REPORT_DIR / "intraday_flow_snapshot.csv",
        REPORT_DIR / "intraday_flow_summary.json",
        REPORT_DIR / "intraday_data_coverage_diagnosis.csv",
        REPORT_DIR / "intraday_data_coverage_diagnosis.json",
        REPORT_DIR / "prediction_learning_summary.csv",
        REPORT_DIR / "prediction_learning_symbol_summary.csv",
        REPORT_DIR / "prediction_learning_summary.json",
        REPORT_DIR / "risk_priority_candidates.csv",
        REPORT_DIR / "risk_priority_summary.json",
        REPORT_DIR / "api_data_status_center.csv",
        REPORT_DIR / "api_data_status_center.json",
        REPORT_DIR / "cloud_readiness_checklist.csv",
        REPORT_DIR / "cloud_readiness_status.json",
        REPORT_DIR / "v36_full_update_status.json",
    ]

    copied: list[str] = []
    skipped: list[str] = []
    missing: list[str] = []
    for src in candidate_files:
        rel = str(src.relative_to(BASE_DIR)) if src.is_absolute() else str(src)
        if not src.exists() or src.stat().st_size <= 0:
            missing.append(rel)
            continue
        target = dest / src.name
        try:
            if target.exists() and not force:
                skipped.append(rel)
                continue
            shutil.copy2(src, target)
            copied.append(rel)
        except Exception as exc:
            append_log(f"backup failed for {rel}: {exc}", "WARN")

    result = {
        "backup_date": today,
        "backup_path": str(dest.relative_to(BASE_DIR)),
        "copied_count": len(copied),
        "skipped_count": len(skipped),
        "missing_count": len(missing),
        "copied": copied,
        "skipped": skipped,
        "missing": missing,
        "updated_at": now_text(),
    }
    safe_write_json(dest / "backup_summary.json", result)
    return result


def update_status(base: dict[str, Any], *, interval_min: float = 15.0, loop_count: int = 0, success: bool = True) -> dict[str, Any]:
    status = dict(base or {})
    run_at = now_text()
    status["last_run_at"] = run_at
    status["updated_at"] = run_at
    status["interval_min"] = float(interval_min)
    status["loop_count"] = int(loop_count)
    status["status"] = "OK" if success else "ERROR"
    status["last_success_at"] = run_at if success else str(status.get("last_success_at", ""))
    try:
        status["next_run_estimated_at"] = (datetime.now() + timedelta(minutes=float(interval_min))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        status["next_run_estimated_at"] = ""
    status["data_files"] = summarize_data_files()
    return status


def read_status_for_display() -> dict[str, Any]:
    status = safe_read_json(STATUS_PATH, {})
    if not isinstance(status, dict):
        status = {}
    status.setdefault("status", "NO_STATUS")
    status.setdefault("last_run_at", status.get("updated_at", ""))
    status.setdefault("last_success_at", "")
    status.setdefault("next_run_estimated_at", "")
    status.setdefault("interval_min", "")
    status.setdefault("data_files", summarize_data_files())
    status["status_path"] = str(STATUS_PATH.relative_to(BASE_DIR))
    status["log_path"] = str(LOG_PATH.relative_to(BASE_DIR))
    status["backup_root"] = str(BACKUP_DIR.relative_to(BASE_DIR))
    return status
