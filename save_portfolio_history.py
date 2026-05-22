"""Manual runner for portfolio history accumulation.

Usage:
    python save_portfolio_history.py
"""
from __future__ import annotations

import json

from core.portfolio_history_engine import save_daily_portfolio_snapshot

if __name__ == "__main__":
    result = save_daily_portfolio_snapshot()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
