from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.engine import backtest, correction, data_quality, risk, session
from app.services import advanced
from app.services import data_loader as data
from app.services import final_engine
from app.services import insights
from app.services import operation_history
from app.services import quotes
from app.services import user_data


app = FastAPI(title="MONE Web API", version="3.6.1-operational-stable")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ],
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






@app.get("/api/final/recommendations")
def api_final_recommendations(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.final_recommendations(_market(market), mode, horizon)


@app.get("/api/final/conditional-executions")
def api_final_conditional_executions(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.conditional_execution_summary(_market(market), mode, horizon)


@app.get("/api/final/prediction-validation")
def api_final_prediction_validation(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.prediction_validation(_market(market))


@app.get("/api/final/trade-validation")
def api_final_trade_validation(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.trade_validation(_market(market), mode, horizon)


@app.get("/api/final/data-center")
def api_final_data_center(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.data_center(_market(market))


@app.get("/api/final/discovery")
def api_final_discovery(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.discovery(_market(market), mode, horizon)


@app.get("/api/final/macro-events")
def api_final_macro_events(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return final_engine.macro_event_risk(_market(market))


@app.get("/api/final/portfolio-risk")
def api_final_portfolio_risk(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.portfolio_risk(_market(market), mode, horizon)


@app.post("/api/final/generate-reports")
def api_final_generate_reports() -> dict:
    return final_engine.write_final_reports()


@app.get("/api/final/operational-readiness")
def api_final_operational_readiness() -> dict:
    return final_engine.operational_readiness()


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


@app.get("/api/status/stockapp-bridge")
def api_status_stockapp_bridge() -> dict:
    return data.stockapp_bridge_status()


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


@app.get("/api/virtual/conditional")
def api_virtual_conditional(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    # v3.6-final: keep the old endpoint path, but return the final conditional execution engine.
    return final_engine.conditional_execution_summary(_market(market), mode, horizon)


@app.get("/api/virtual/portfolio")
def api_virtual_portfolio(market: str = Query("kr", pattern="^(kr|us)$"), mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$")) -> dict:
    return data.virtual_portfolio_summary(_market(market), mode)


@app.get("/api/virtual/portfolios")
def api_virtual_portfolios(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    mk = _market(market)
    modes = ["conservative", "balanced", "aggressive"]
    items = {mode: data.virtual_portfolio_summary(mk, mode) for mode in modes}
    return {
        "market": mk,
        "modes": items,
        "counts": {mode: items[mode].get("count", 0) for mode in modes},
        "source": "virtual_portfolio_summary",
    }


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
    return final_engine.admin_backtest(_market(market))


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
    return final_engine.admin_prediction_insights(_market(market))


@app.get("/api/history/predictions")
def api_prediction_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_prediction_history(_market(market) if market else None)


@app.get("/api/history/outcomes")
def api_outcome_history(market: str | None = Query(None, pattern="^(kr|us)$")) -> dict:
    return final_engine.admin_outcome_history(_market(market) if market else None)


@app.post("/api/quotes/refresh")
def api_quotes_refresh(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    symbols: str | None = Query(None),
    max_symbols: int = Query(80, ge=1, le=150),
) -> dict:
    return quotes.refresh_quotes(market=market, symbols=symbols, max_symbols=max_symbols)


def _remove_routes(paths: set[str]) -> None:
    app.router.routes = [
        route
        for route in app.router.routes
        if not (isinstance(route, APIRoute) and getattr(route, "path", "") in paths)
    ]


_remove_routes(
    {
        "/api/session",
        "/api/final/data-quality",
        "/api/v1/candidates",
        "/api/backtest/trades",
        "/api/backtest/summary",
        "/api/virtual/summary",
        "/api/admin/pipeline",
        "/api/admin/correction",
        "/api/ohlcv",
    }
)


@app.get("/api/session")
def api_session_core(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return {"status": "OK", **session.get_price_session(_market(market))}


@app.get("/api/final/data-quality")
def api_final_data_quality_core(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data_quality.data_quality(_market(market))


@app.get("/api/v1/candidates")
def api_v1_candidates_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    strategy: str = Query("balanced"),
    term: str = Query("swing"),
    cash: float = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
) -> dict:
    return risk.candidates(_market(market), strategy, term, cash, limit)


@app.get("/api/backtest/trades")
def api_backtest_trades_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(250, ge=1, le=1000),
) -> dict:
    return backtest.trades(_market(market), mode, horizon, limit)


@app.get("/api/backtest/summary")
def api_backtest_summary_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return backtest.summary(_market(market), mode, horizon)


@app.get("/api/virtual/summary")
def api_virtual_summary_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return backtest.summary(_market(market), mode, horizon)


@app.get("/api/admin/pipeline")
def api_admin_pipeline_core(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data_quality.admin_pipeline(_market(market))


@app.get("/api/admin/correction")
def api_admin_correction_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return correction.correction_summary(_market(market), mode, horizon)


@app.get("/api/ohlcv")
def api_ohlcv_core(
    symbol: str = Query(..., min_length=1),
    market: str = Query("kr"),
    limit: int = Query(120, ge=1, le=500),
) -> dict:
    normalized_market = _market(market)
    payload = data.chart_data(symbol, normalized_market)
    rows = payload.get("items") or payload.get("rows") or []
    payload["items"] = rows[-limit:] if len(rows) > limit else rows
    payload["count"] = len(payload["items"])
    return payload


try:
    from app.engine.mone_v55_backend_aliases import register_mone_v55_backend_aliases
    register_mone_v55_backend_aliases(app)
except Exception as exc:
    print("[MONE v5.5] backend alias registration failed:", exc)

try:
    from app.engine.mone_v61_virtual_summary import register_mone_v61_virtual_summary
    register_mone_v61_virtual_summary(app)
except Exception as exc:
    print("[MONE v6.1] virtual summary registration failed:", exc)

try:
    from app.engine.mone_v65_api_stabilizer import register_mone_v65_api_stabilizer
    register_mone_v65_api_stabilizer(app)
except Exception as exc:
    print("[MONE v6.5] api stabilizer registration failed:", exc)

try:
    from app.engine.mone_v75_session_guard import register_mone_v75_session_guard_routes
    register_mone_v75_session_guard_routes(app)
except Exception as exc:
    print("[MONE v7.5] session guard registration failed:", exc)

try:
    from app.engine.mone_v77_holdings_risk import register_mone_v77_holdings_routes
    register_mone_v77_holdings_routes(app)
except Exception as exc:
    print("[MONE v7.7] holdings risk registration failed:", exc)

try:
    from app.engine.mone_v80_company_prediction import register_mone_v80_company_prediction_routes
    register_mone_v80_company_prediction_routes(app)
except Exception as exc:
    print("[MONE v8.0] company/prediction route registration failed:", exc)

try:
    from app.engine.mone_v802_holdings_clean import register_mone_v802_holdings_clean_routes
    register_mone_v802_holdings_clean_routes(app)
except Exception as exc:
    print("[MONE v8.0.2] holdings clean final route failed:", exc)

try:
    from app.engine.mone_v803_holdings_clean_guard import register_mone_v803_holdings_clean_guard
    register_mone_v803_holdings_clean_guard(app)
except Exception as exc:
    print("[MONE v8.0.3] holdings clean guard route failed:", exc)
