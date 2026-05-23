"""Stock app v30 automatic accumulator.

Keep this process running on the PC to keep portfolio, benchmark, backtest, and
news-cache summaries updated even when the Streamlit browser tab is closed.
It does not place orders and does not require Streamlit.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from core.auto_accumulator_status_engine import (
    STATUS_PATH,
    append_log,
    create_daily_backup,
    safe_write_json,
    update_status,
)


def _has_error_keys(data: dict[str, Any]) -> bool:
    for key, value in data.items():
        if "error" in str(key).lower():
            return True
        if isinstance(value, dict) and str(value.get("status", "")).upper() == "ERROR":
            return True
    return False


def _run_once(*, interval_min: float = 15.0, loop_count: int = 0) -> dict[str, Any]:
    out: dict[str, Any] = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    append_log(f"auto accumulation started loop={loop_count}")

    try:
        from core.portfolio_history_engine import save_benchmark_daily_history, save_daily_portfolio_snapshot
        bench = save_benchmark_daily_history()
        port = save_daily_portfolio_snapshot()
        out["benchmark_rows"] = int(len(bench)) if hasattr(bench, "__len__") else 0
        out["portfolio"] = port
        append_log(f"portfolio/benchmark update success benchmark_rows={out.get('benchmark_rows')}")
    except Exception as exc:
        out["portfolio_error"] = str(exc)
        append_log(f"portfolio/benchmark update failed: {exc}", "ERROR")

    try:
        from core.backtest_beta_engine import save_backtest_beta_summary
        out["backtest_beta"] = save_backtest_beta_summary()
        append_log(f"backtest beta update success status={out['backtest_beta'].get('status', '-') if isinstance(out.get('backtest_beta'), dict) else '-'}")
    except Exception as exc:
        out["backtest_beta_error"] = str(exc)
        append_log(f"backtest beta update failed: {exc}", "ERROR")

    try:
        from core.news_cache_engine import summarize_news_cache
        out["news_cache"] = summarize_news_cache()
        append_log(f"news cache summary success status={out['news_cache'].get('status', '-') if isinstance(out.get('news_cache'), dict) else '-'}")
    except Exception as exc:
        out["news_cache_error"] = str(exc)
        append_log(f"news cache summary failed: {exc}", "ERROR")

    try:
        from core.market_session_engine import current_session_for_market, should_run_intraday_refresh
        auto_intraday = str(os.environ.get("AUTO_INTRADAY_REFRESH_ENABLED", "1") or "1").lower() in {"1", "true", "yes", "y"}
        kr_session = current_session_for_market("한국주식")
        us_session = current_session_for_market("미국주식")
        out["market_sessions"] = {"한국주식": kr_session, "미국주식": us_session}
        if auto_intraday and should_run_intraday_refresh():
            from run_intraday_refresh import run_once as run_intraday_refresh_once
            out["intraday_refresh"] = run_intraday_refresh_once()
            append_log(
                "intraday refresh success "
                f"kr={kr_session.get('session_status')} us={us_session.get('session_status')}"
            )
        else:
            out["intraday_refresh"] = {
                "status": "SKIPPED",
                "reason": "market_inactive_or_disabled",
                "auto_intraday": auto_intraday,
                "kr_session_status": kr_session.get("session_status"),
                "us_session_status": us_session.get("session_status"),
            }
            append_log(
                "intraday refresh skipped "
                f"kr={kr_session.get('session_status')} us={us_session.get('session_status')} auto={auto_intraday}"
            )
    except Exception as exc:
        out["intraday_refresh_error"] = str(exc)
        append_log(f"intraday refresh failed: {exc}", "ERROR")

    # v33-v36: prediction learning, risk-first candidates, API status center, and cloud readiness
    try:
        from core.prediction_learning_engine import save_prediction_learning_summary
        out["prediction_learning"] = save_prediction_learning_summary()
        append_log(f"prediction learning update success status={out['prediction_learning'].get('status', '-') if isinstance(out.get('prediction_learning'), dict) else '-'}")
    except Exception as exc:
        out["prediction_learning_error"] = str(exc)
        append_log(f"prediction learning update failed: {exc}", "ERROR")

    try:
        from core.risk_priority_engine import save_risk_priority_candidates
        out["risk_priority"] = save_risk_priority_candidates()
        append_log(f"risk priority update success status={out['risk_priority'].get('status', '-') if isinstance(out.get('risk_priority'), dict) else '-'}")
    except Exception as exc:
        out["risk_priority_error"] = str(exc)
        append_log(f"risk priority update failed: {exc}", "ERROR")

    try:
        from core.api_status_center_engine import save_api_status_center
        out["api_status_center"] = save_api_status_center()
        append_log(f"api status center update success status={out['api_status_center'].get('status', '-') if isinstance(out.get('api_status_center'), dict) else '-'}")
    except Exception as exc:
        out["api_status_center_error"] = str(exc)
        append_log(f"api status center update failed: {exc}", "ERROR")

    try:
        from core.cloud_readiness_engine import save_cloud_readiness_status
        out["cloud_readiness"] = save_cloud_readiness_status()
        append_log(f"cloud readiness check success status={out['cloud_readiness'].get('status', '-') if isinstance(out.get('cloud_readiness'), dict) else '-'}")
    except Exception as exc:
        out["cloud_readiness_error"] = str(exc)
        append_log(f"cloud readiness check failed: {exc}", "ERROR")


    # v41: keep operational tables and v40 analysis reports fresh automatically.
    try:
        from core.operational_plus_engine import (
            build_buy_budget_table, build_sell_budget_table, build_news_narrative_table,
            build_financial_kpi_table, build_macro_table, _market_slug, REPORT_DIR
        )
        for mkt in ["미국주식", "한국주식"]:
            slug = _market_slug(mkt)
            build_buy_budget_table(mkt).to_csv(REPORT_DIR / f"operational_buy_budget_{slug}.csv", index=False, encoding="utf-8-sig")
            build_sell_budget_table(mkt).to_csv(REPORT_DIR / f"operational_sell_budget_{slug}.csv", index=False, encoding="utf-8-sig")
            build_news_narrative_table(mkt).to_csv(REPORT_DIR / f"operational_news_narrative_{slug}.csv", index=False, encoding="utf-8-sig")
            build_financial_kpi_table(mkt).to_csv(REPORT_DIR / f"operational_financial_kpi_{slug}.csv", index=False, encoding="utf-8-sig")
            build_macro_table(mkt).to_csv(REPORT_DIR / f"operational_macro_{slug}.csv", index=False, encoding="utf-8-sig")
        out["v41_operational_tables"] = {"status": "OK"}
        append_log("v41 operational tables update success")
    except Exception as exc:
        out["v41_operational_tables_error"] = str(exc)
        append_log(f"v41 operational tables update failed: {exc}", "ERROR")

    try:
        from core.v40_analysis_engine import save_v40_reports
        out["v40_analysis"] = save_v40_reports()
        append_log(f"v40 analysis update success status={out['v40_analysis'].get('status', '-') if isinstance(out.get('v40_analysis'), dict) else '-'}")
    except Exception as exc:
        out["v40_analysis_error"] = str(exc)
        append_log(f"v40 analysis update failed: {exc}", "ERROR")

    # v43: actual GNews fetch/cache and app-calculated strategy backtest.
    try:
        from core.v43_operational_engine import run_v43_update
        out["v43_update"] = run_v43_update()
        append_log(f"v43 update success status={out['v43_update'].get('status', '-') if isinstance(out.get('v43_update'), dict) else '-'}")
    except Exception as exc:
        out["v43_update_error"] = str(exc)
        append_log(f"v43 update failed: {exc}", "ERROR")

    try:
        backup = create_daily_backup(force=False)
        out["backup"] = backup
        append_log(f"daily backup checked copied={backup.get('copied_count')} skipped={backup.get('skipped_count')}")
    except Exception as exc:
        out["backup_error"] = str(exc)
        append_log(f"daily backup failed: {exc}", "ERROR")

    success = not _has_error_keys(out)
    status = update_status(out, interval_min=interval_min, loop_count=loop_count, success=success)
    try:
        safe_write_json(STATUS_PATH, status)
    except Exception as exc:
        append_log(f"status write failed: {exc}", "ERROR")

    append_log(f"auto accumulation finished loop={loop_count} status={status.get('status')}")
    return status


def main() -> int:
    interval_min = float(os.environ.get("AUTO_ACCUMULATOR_INTERVAL_MIN", "15") or "15")
    once = str(os.environ.get("AUTO_ACCUMULATOR_ONCE", "") or "").lower() in {"1", "true", "yes", "y"}
    sleep_sec = max(60, int(interval_min * 60))
    loop_count = 0

    append_log(f"auto accumulator process launched interval_min={interval_min} once={once}")
    while True:
        loop_count += 1
        result = _run_once(interval_min=interval_min, loop_count=loop_count)
        print(json.dumps(result, ensure_ascii=False, default=str), flush=True)
        if once:
            return 0 if str(result.get("status", "")).upper() == "OK" else 2
        time.sleep(sleep_sec)


if __name__ == "__main__":
    raise SystemExit(main())
