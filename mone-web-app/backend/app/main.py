from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.services import advanced
from app.services import data_loader as data
from app.services import insights
from app.services import operation_history
from app.services import quotes
from app.services import user_data


app = FastAPI(title="MONE Web API", version="0.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _market(value: str) -> str:
    return "us" if str(value).lower() == "us" else "kr"


@app.get("/health")
def health() -> dict:
    return {
        "status": "OK",
        "app": "mone-web-app",
        "repoRoot": str(data.REPO_ROOT),
        "updatedAt": data.latest_updated_at(),
    }




@app.get("/api/status")
def api_status() -> dict:
    files = data.status_files()
    env = data.status_env()
    return {"status": "OK", "files": files, "env": env, "updatedAt": data.latest_updated_at()}


@app.get("/api/market-home")
def api_market_home_compat(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.market_summary(_market(market))

@app.get("/api/status/files")
def api_status_files() -> dict:
    return data.status_files()


@app.get("/api/status/env")
def api_status_env() -> dict:
    return data.status_env()


@app.get("/api/status/data-sources")
def api_status_data_sources() -> dict:
    return data.data_source_status()


@app.get("/api/status/github-actions")
def api_status_github_actions() -> dict:
    return data.github_actions_status()


@app.get("/api/market/summary")
def api_market_summary(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.market_summary(_market(market))


@app.get("/api/symbols")
def api_symbols(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.symbols(_market(market))


@app.get("/api/symbols/{symbol}")
def api_symbol_detail(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.symbol_detail(symbol, _market(market))


@app.get("/api/chart/{symbol}")
def api_chart_data(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.chart_data(symbol, _market(market))


@app.get("/api/candidates")
def api_candidates(
    market: str = Query("kr", pattern="^(kr|us)$"),
    type: str = Query("action", pattern="^(action|pullback|flow|risk)$"),
) -> dict:
    return data.candidate_rows(_market(market), type)


@app.get("/api/positions")
def api_positions(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.positions(_market(market))




@app.get("/api/watchlist")
def api_watchlist(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.get_watchlist(_market(market))


@app.post("/api/watchlist")
def api_watchlist_add(payload: dict) -> dict:
    return user_data.add_watchlist(payload)


@app.delete("/api/watchlist/{symbol}")
def api_watchlist_delete(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.delete_watchlist(symbol, _market(market))


@app.get("/api/holdings")
def api_holdings(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.get_holdings(_market(market))


@app.post("/api/holdings")
def api_holdings_add(payload: dict) -> dict:
    return user_data.upsert_holding(payload, mode="post")


@app.patch("/api/holdings/{symbol}")
def api_holdings_patch(symbol: str, payload: dict) -> dict:
    return user_data.upsert_holding(payload, mode="patch", symbol_arg=symbol)


@app.delete("/api/holdings/{symbol}")
def api_holdings_delete(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return user_data.delete_holding(symbol, _market(market))

@app.get("/api/news")
def api_news(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.news_rows(_market(market))


@app.get("/api/disclosures")
def api_disclosures(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.disclosure_rows(_market(market))


@app.post("/api/disclosures/refresh")
def api_disclosures_refresh(market: str = Query("all", pattern="^(kr|us|all)$"), days: int = Query(30, ge=1, le=365)) -> dict:
    return data.refresh_disclosures(market=market, days=days)


@app.get("/api/company-analysis")
def api_company_analysis(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.company_analysis(_market(market))


@app.get("/api/virtual/preview")
def api_virtual_preview(market: str = Query("kr", pattern="^(kr|us)$"), mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$")) -> dict:
    return data.virtual_operation_preview(_market(market), mode)


@app.get("/api/virtual/portfolio")
def api_virtual_portfolio(market: str = Query("kr", pattern="^(kr|us)$"), mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$")) -> dict:
    return data.virtual_portfolio_summary(_market(market), mode)


@app.get("/api/history/files")
def api_history_files() -> dict:
    return operation_history.history_file_summary()


@app.get("/api/history/virtual-operations")
def api_virtual_operation_history(
    market: str | None = Query(None, pattern="^(kr|us)$"),
    mode: str | None = Query(None, pattern="^(conservative|balanced|aggressive)$"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return operation_history.virtual_operation_history(market, mode, limit)


@app.get("/api/history/prediction-snapshots")
def api_prediction_snapshot_history(
    market: str | None = Query(None, pattern="^(kr|us)$"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return operation_history.prediction_snapshot_history(market, limit)


@app.post("/api/history/snapshot")
def api_save_history_snapshot(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    modes: str = Query("all"),
    source: str = Query("manual"),
    backfill_existing: bool = Query(False),
) -> dict:
    return operation_history.save_current_snapshot(market=market, modes=modes, source=source, include_backfill=backfill_existing)


@app.post("/api/history/backfill")
def api_backfill_existing_history(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    modes: str = Query("all"),
) -> dict:
    return operation_history.backfill_existing_records(market=market, modes=modes)


@app.post("/api/history/evaluate")
def api_evaluate_virtual_history() -> dict:
    evaluation = operation_history.evaluate_virtual_operations(write=True)
    correction = operation_history.build_auto_correction_summary(write=True)
    return {"status": "OK", "evaluation": evaluation, "autoCorrection": correction}


@app.get("/api/history/auto-correction")
def api_auto_correction_summary() -> dict:
    return operation_history.build_auto_correction_summary(write=False)


@app.get("/api/predictions")
def api_predictions(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.predictions(_market(market))


@app.get("/api/reports/premarket")
def api_report_premarket(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.premarket_report(_market(market))


@app.get("/api/reports/intraday")
def api_report_intraday(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.intraday_report(_market(market))


@app.get("/api/reports/closing")
def api_report_closing(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.closing_report(_market(market))


@app.get("/api/reports/files")
def api_report_files() -> dict:
    return data.report_files()


@app.get("/api/reports/preview")
def api_report_preview(path: str = Query(..., min_length=1)) -> dict:
    return data.report_preview(path)


@app.get("/api/advanced/backtest")
def api_advanced_backtest(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return advanced.advanced_backtest(_market(market))


@app.get("/api/advanced/scanner")
def api_advanced_scanner(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return advanced.advanced_scanner(_market(market))


@app.post("/api/advanced/calculator/kelly")
def api_calculator_kelly(payload: dict) -> dict:
    return advanced.kelly(payload)


@app.post("/api/advanced/calculator/var")
def api_calculator_var(payload: dict) -> dict:
    return advanced.var_cvar(payload)


@app.post("/api/advanced/calculator/risk-reward")
def api_calculator_risk_reward(payload: dict) -> dict:
    return advanced.risk_reward(payload)


@app.post("/api/advanced/monte-carlo")
def api_monte_carlo(payload: dict) -> dict:
    return advanced.monte_carlo(payload)


@app.get("/api/advanced/correlation")
def api_advanced_correlation(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return advanced.correlation(_market(market))


@app.get("/api/insights/prediction")
def api_prediction_insights(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return insights.prediction_insights(_market(market))


@app.get("/api/history/predictions")
def api_prediction_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return data.prediction_history(_market(market) if market else None)


@app.get("/api/history/outcomes")
def api_outcome_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return data.outcome_history(_market(market) if market else None)


@app.post("/api/quotes/refresh")
def api_quotes_refresh(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    symbols: str | None = Query(None),
    max_symbols: int = Query(80, ge=1, le=150),
) -> dict:
    return quotes.refresh_quotes(market=market, symbols=symbols, max_symbols=max_symbols)
