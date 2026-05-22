"""Refresh intraday reports in the correct dependency order.

This script is safe to run manually or from the auto accumulator. It does not
place orders. It refreshes saved reports only.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from core.market_session_engine import current_session_for_market


def run_once() -> dict[str, Any]:
    result: dict[str, Any] = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "market_sessions": {
            "한국주식": current_session_for_market("한국주식"),
            "미국주식": current_session_for_market("미국주식"),
        },
    }

    try:
        from core.intraday_orderbook_engine import save_intraday_orderbook_snapshot, save_intraday_orderbook_summary
        result["orderbook_snapshot"] = save_intraday_orderbook_snapshot()
        result["orderbook_summary"] = save_intraday_orderbook_summary()
    except Exception as exc:
        result["orderbook_error"] = str(exc)

    try:
        from core.intraday_realtime_engine import save_intraday_realtime_snapshot, save_intraday_realtime_summary
        result["realtime_snapshot"] = save_intraday_realtime_snapshot()
        result["realtime_summary"] = save_intraday_realtime_summary()
    except Exception as exc:
        result["realtime_error"] = str(exc)

    try:
        from core.intraday_flow_engine import save_intraday_flow_snapshot, save_intraday_flow_summary
        result["flow_snapshot"] = save_intraday_flow_snapshot()
        result["flow_summary"] = save_intraday_flow_summary()
    except Exception as exc:
        result["flow_error"] = str(exc)

    try:
        from core.intraday_sector_flow_engine import save_intraday_sector_flow_report, save_intraday_sector_flow_summary
        result["sector_report"] = save_intraday_sector_flow_report()
        result["sector_summary"] = save_intraday_sector_flow_summary()
    except Exception as exc:
        result["sector_error"] = str(exc)

    try:
        from core.intraday_data_coverage_diagnosis import save_intraday_data_coverage_diagnosis
        result["coverage"] = save_intraday_data_coverage_diagnosis()
    except Exception as exc:
        result["coverage_error"] = str(exc)

    return result


def main() -> int:
    result = run_once()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    has_error = any("error" in str(k).lower() for k in result)
    return 2 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
