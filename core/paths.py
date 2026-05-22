"""Shared paths for decision_system (no dependency on Streamlit)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DECISION_DATA = PROJECT_ROOT / "data" / "decision_system"
DECISION_CONFIG = PROJECT_ROOT / "config" / "decision_system"
LEGACY_PREDICTIONS = PROJECT_ROOT / "predictions.csv"
WEIGHT_CONFIG = DECISION_CONFIG / "weight_config.json"
LEARNING_PATTERNS = DECISION_CONFIG / "learning_patterns.json"
ERROR_LOGS = DECISION_DATA / "error_logs.csv"
ACTUAL_RESULTS = DECISION_DATA / "actual_results.csv"
TRADE_SIMULATIONS = DECISION_DATA / "trade_simulations.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"
