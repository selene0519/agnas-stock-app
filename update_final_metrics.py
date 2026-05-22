
from __future__ import annotations

import json

from core.portfolio_history_engine import save_benchmark_daily_history, save_daily_portfolio_snapshot

try:
    from core.backtest_beta_engine import save_backtest_beta_summary
except Exception:
    save_backtest_beta_summary = None

try:
    from core.news_cache_engine import summarize_news_cache
except Exception:
    summarize_news_cache = None

if __name__ == "__main__":
    benchmark = save_benchmark_daily_history()
    portfolio = save_daily_portfolio_snapshot()
    backtest = None
    if save_backtest_beta_summary is not None:
        try:
            backtest = save_backtest_beta_summary()
        except Exception as exc:
            backtest = {"status": "ERROR", "error": str(exc)}
    news_cache = None
    if summarize_news_cache is not None:
        try:
            news_cache = summarize_news_cache()
        except Exception as exc:
            news_cache = {"status": "ERROR", "error": str(exc)}
    v36 = {}
    try:
        from run_v36_full_update import run_once as run_v36_full_update_once
        v36 = run_v36_full_update_once()
    except Exception as exc:
        v36 = {"status": "ERROR", "error": str(exc)}
    print(json.dumps({
        "status": "OK",
        "benchmark_rows": int(len(benchmark)),
        "portfolio_metrics": portfolio,
        "backtest_beta": backtest,
        "news_cache": news_cache,
        "v36": v36,
    }, ensure_ascii=False, indent=2, default=str))
