from __future__ import annotations

import os

from fastapi import Body, FastAPI, Query
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
from app import db as _db


app = FastAPI(title="MONE Web API", version="3.6.1-operational-stable")

# 자동 동기화 초기화
try:
    from app.engine.auto_sync import register_auto_sync_routes, start_background_sync, startup_sync
    register_auto_sync_routes(app)
    startup_sync()           # MONE_STARTUP_SYNC=1 환경변수 설정 시 시작 시 pull
    start_background_sync()  # 백그라운드 30분마다 pull (GIT_AUTO_SYNC_INTERVAL_MIN 환경변수로 조정)
except Exception as _auto_sync_err:
    print("[AutoSync] 초기화 실패:", _auto_sync_err)

_default_origins = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
_extra = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
_allowed_origins = _default_origins + _extra

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _market(value: str) -> str:
    return "us" if str(value).lower() == "us" else "kr"


def _ensure_status(payload: dict, default_status: str = "OK") -> dict:
    if not isinstance(payload, dict):
        return {"status": "ERROR", "items": [], "count": 0, "error": "Invalid API payload"}
    if not payload.get("status"):
        count = payload.get("count")
        items = payload.get("items")
        if isinstance(items, list):
            payload["status"] = default_status if items else "NO_DATA"
            payload.setdefault("count", len(items))
        elif isinstance(count, int):
            payload["status"] = default_status if count > 0 else "NO_DATA"
        else:
            payload["status"] = default_status
    return payload


@app.api_route("/health", methods=["GET", "HEAD"])
def health() -> dict:
    return {
        "status": "OK",
        "app": "mone-web-app",
        "repoRoot": str(data.REPO_ROOT),
        "updatedAt": data.latest_updated_at(),
        "db": _db.backend_info(),
    }






@app.get("/api/final/recommendations")
def api_final_recommendations(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced", pattern="^(conservative|balanced|aggressive)$"),
    horizon: str = Query("swing", pattern="^(short|swing|mid)$"),
) -> dict:
    return final_engine.final_recommendations(_market(market), mode, horizon)


@app.get("/api/final/recommendation-detail")
def api_final_recommendation_detail(
    market: str = Query("kr", pattern="^(kr|us)$"),
    symbol: str = Query(..., min_length=1),
) -> dict:
    return final_engine.recommendation_detail(_market(market), symbol)


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


@app.get("/api/sector-strength")
def api_sector_strength(
    market: str = Query("kr", pattern="^(kr|us)$"),
    period: int = Query(5, ge=1, le=20),
) -> dict:
    """섹터별 강도 점수 반환 (5일 수익률 기반)."""
    try:
        from app.engine.dsg_signal_engine import sector_strength
        rows = sector_strength(market, period=period)
        return {"ok": True, "market": market, "period": period, "data": rows}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "data": []}


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


@app.get("/api/watchlist/auto-candidates")
def api_watchlist_auto_candidates(
    market: str = Query("all", pattern="^(all|kr|us)$"),
    limitPerMarket: int = Query(12, ge=3, le=30),
) -> dict:
    return user_data.auto_watchlist_candidates(market, limitPerMarket)


@app.post("/api/watchlist/auto-curate")
def api_watchlist_auto_curate(payload: dict = Body(default={})) -> dict:
    market = str((payload or {}).get("market") or "all").lower()
    if market not in {"all", "kr", "us"}:
        market = "all"
    limit_per_market = int((payload or {}).get("limitPerMarket") or 12)
    return user_data.apply_auto_watchlist(market, limit_per_market)


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
def api_news(
    market: str = Query("kr", pattern="^(kr|us)$"),
    watch_only: bool = Query(False),
    watchOnly: bool | None = Query(None),
) -> dict:
    from pathlib import Path as _NP
    import csv as _NC

    mk = _market(market)
    result = _ensure_status(data.news_rows(mk))
    effective_watch_only = watch_only if watchOnly is None else watchOnly
    if not effective_watch_only:
        return result

    relevant: set[str] = set()
    repo = _NP(__file__).resolve().parents[3]

    def _read_symbols(path: _NP) -> None:
        if not path.exists():
            return
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    for row in _NC.DictReader(f):
                        sym = data.normalize_symbol(
                            row.get("symbol") or row.get("종목코드") or row.get("ticker") or "", mk
                        )
                        if sym:
                            relevant.add(sym)
                return
            except Exception:
                continue

    for fname in (f"holdings_{mk}.csv", f"data/holdings_{mk}.csv", f"watchlist_{mk}.csv", f"data/watchlist_{mk}.csv"):
        _read_symbols(repo / fname)

    if not relevant:
        return {**result, "items": [], "count": 0, "watchOnly": True, "relevantSymbols": 0}

    filtered = [
        item for item in result.get("items", [])
        if data.normalize_symbol(item.get("symbol", ""), mk) in relevant
    ]
    return {**result, "items": filtered, "count": len(filtered), "watchOnly": True, "relevantSymbols": len(relevant)}


@app.get("/api/disclosures")
def api_disclosures(
    market: str = Query("kr", pattern="^(kr|us)$"),
    watch_only: bool = Query(True),
    watchOnly: bool | None = Query(None),
) -> dict:
    from pathlib import Path as _DP
    import csv as _DC

    mk = _market(market)
    result = data.disclosure_rows(mk)
    effective_watch_only = watch_only if watchOnly is None else watchOnly

    if effective_watch_only:
        # 보유종목 + 관심종목 심볼 수집
        relevant: set[str] = set()
        repo = _DP(__file__).resolve().parents[3]

        def _read_symbols(path: _DP) -> None:
            if not path.exists():
                return
            for enc in ("utf-8-sig", "utf-8", "cp949"):
                try:
                    with path.open("r", encoding=enc, newline="") as f:
                        for row in _DC.DictReader(f):
                            sym = data.normalize_symbol(
                                row.get("symbol") or row.get("종목코드") or row.get("ticker") or "", mk
                            )
                            if sym:
                                relevant.add(sym)
                    return
                except Exception:
                    continue

        # 보유종목 CSV
        for fname in (f"holdings_{mk}.csv", f"data/holdings_{mk}.csv"):
            _read_symbols(repo / fname)
        # 관심종목 CSV
        for fname in (f"watchlist_{mk}.csv", f"data/watchlist_{mk}.csv"):
            _read_symbols(repo / fname)
        # 추천 종목 (balanced swing 기준)
        for fname in (f"reports/mone_v36_final_recommendations_{mk}_balanced_swing.csv",):
            _read_symbols(repo / fname)

        if relevant:
            filtered = [
                item for item in result.get("items", [])
                if data.normalize_symbol(item.get("symbol", ""), mk) in relevant
            ]
            result = {**result, "items": filtered, "count": len(filtered),
                      "watchOnly": True, "relevantSymbols": len(relevant)}
        else:
            result = {**result, "watchOnly": True, "relevantSymbols": 0}

    return result


@app.post("/api/disclosures/refresh")
def api_disclosures_refresh(market: str = Query("all", pattern="^(kr|us|all)$"), days: int = Query(30, ge=1, le=365)) -> dict:
    return data.refresh_disclosures(market=market, days=days)


@app.post("/api/news/refresh")
def api_news_refresh(market: str = Query("all", pattern="^(kr|us|all)$")) -> dict:
    """GNews API를 호출해 최신 주식 뉴스를 수집하고 CSV에 저장한다."""
    return data.collect_gnews(market=market)


@app.get("/api/company-analysis")
def api_company_analysis(
    market: str = Query("kr", pattern="^(kr|us)$"),
    q: str = Query(""),       # 종목코드 또는 종목명 필터
    limit: int = Query(120),
) -> dict:
    result = data.company_analysis(_market(market))
    if q.strip():
        q_norm = q.strip().upper().lstrip("0") or q.strip()
        filtered = [
            item for item in result.get("items", [])
            if (
                str(item.get("symbol", "")).lstrip("0").upper() == q_norm
                or str(item.get("symbol", "")).upper() == q.strip().upper()
                or q.strip().lower() in str(item.get("name", "")).lower()
            )
        ]
        result = {**result, "items": filtered[:limit], "count": len(filtered)}
    else:
        items = result.get("items", [])
        result = {**result, "items": items[:limit], "count": len(items)}
    return result


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
def api_advanced_scanner(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return _ensure_status(advanced.advanced_scanner(_market(market), mode, horizon))


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


@app.get("/api/insights/prediction-accuracy")
def api_prediction_accuracy(market: str = Query("all", pattern="^(kr|us|all)$")) -> dict:
    mk = None if market == "all" else _market(market)
    return final_engine.prediction_accuracy_stats(mk)


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


def _virtual_summary_from_reports(market: str, mode: str = "balanced", horizon: str = "swing") -> dict:
    def _truth(value: object) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "filled", "executed", "체결"}

    def _num(value: object) -> float | None:
        try:
            text = str(value).replace("%", "").replace(",", "").strip()
            if not text:
                return None
            return float(text)
        except Exception:
            return None

    def _rows(name: str) -> list[dict]:
        path = data.REPORT_DIR / name
        if not path.exists() or path.stat().st_size <= 0:
            return []
        return data.dataframe_records(data.read_csv(path))

    market = _market(market)
    validations = [
        row for row in _rows("virtual_validation_results.csv")
        if str(row.get("market", "")).lower() == market
    ]
    ledger = [
        row for row in _rows("virtual_prediction_ledger.csv")
        if str(row.get("market", "")).lower() == market
    ]
    if mode and mode not in {"all", ""}:
        validations = [row for row in validations if str(row.get("mode", "")).lower() == mode.lower()]
        ledger = [row for row in ledger if str(row.get("mode", "")).lower() == mode.lower()]
    if horizon and horizon not in {"all", ""}:
        validations = [row for row in validations if str(row.get("horizon", "")).lower() == horizon.lower()]
        ledger = [row for row in ledger if str(row.get("horizon", "")).lower() == horizon.lower()]

    executed = [row for row in validations if _truth(row.get("isExecuted"))]
    unexecuted = [row for row in validations if not _truth(row.get("isExecuted"))]
    returns = [_num(row.get("returnPct")) for row in executed]
    returns = [value for value in returns if value is not None]
    wins = [value for value in returns if value > 0]
    cumulative = sum(returns)
    avg = cumulative / len(returns) if returns else 0.0
    pending = [
        row for row in ledger
        if str(row.get("status", "")).strip().upper() in {"", "PENDING", "DATA_PENDING"}
    ]
    latest_date = ""
    for row in validations:
        latest_date = max(latest_date, str(row.get("validatedAt") or row.get("validationDate") or row.get("createdAt") or ""))
    return {
        "status": "OK" if validations or ledger else "NO_DATA",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "source": "virtual_validation_results.csv + virtual_prediction_ledger.csv",
        "returnBasis": "virtual_validation_results executed rows; portfolio aggregate curve, not per-symbol curve",
        "pnlCurveScope": "portfolio_aggregate",
        "totalRecommendations": len(ledger) or len(validations),
        "latestRecommendations": len(validations),
        "executedTrades": len(executed),
        "latestExecutedTrades": len(executed),
        "unexecutedCount": len(unexecuted),
        "latestUnexecutedCount": len(unexecuted),
        "pendingCount": len(pending),
        "executionRate": round((len(executed) / len(validations)) * 100, 2) if validations else 0,
        "latestExecutionRate": round((len(executed) / len(validations)) * 100, 2) if validations else 0,
        "winRate": round((len(wins) / len(returns)) * 100, 2) if returns else 0,
        "latestWinRate": round((len(wins) / len(returns)) * 100, 2) if returns else 0,
        "executedReturnPct": round(avg, 3),
        "cumulativeReturnPct": round(cumulative, 3),
        "latestCumulativeReturnPct": round(cumulative, 3),
        "latestDate": latest_date[:10],
        "items": validations[:300],
        "count": len(validations),
    }


@app.get("/api/virtual/summary")
def api_virtual_summary_core(
    market: str = Query("kr", pattern="^(kr|us)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    return _virtual_summary_from_reports(_market(market), mode, horizon)


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
    if not rows:
        try:
            backfill = quotes.backfill_daily_ohlcv(symbol, normalized_market, days=max(limit, 120))
            if str(backfill.get("status", "")).upper() == "OK":
                payload = data.chart_data(symbol, normalized_market)
                rows = payload.get("items") or payload.get("rows") or []
                payload["backfill"] = backfill
        except Exception as exc:
            payload["backfill"] = {"status": "ERROR", "error": str(exc)[:160]}
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
    from app.engine.mone_v65_api_stabilizer import register_mone_v65_api_stabilizer
    register_mone_v65_api_stabilizer(app)
except Exception as exc:
    print("[MONE v6.5 final] api stabilizer registration failed:", exc)

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

# --- MONE live data-quality route patch v2 ascii ---
from pathlib import Path as _MONE_DQ_Path
from datetime import datetime as _MONE_DQ_Datetime
import csv as _MONE_DQ_csv
import re as _MONE_DQ_re

def _mone_dq_repo_root() -> _MONE_DQ_Path:
    return _MONE_DQ_Path(__file__).resolve().parents[3]

def _mone_dq_read_rows(path: _MONE_DQ_Path, max_rows: int = 5000):
    if not path.exists() or not path.is_file():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(_MONE_DQ_csv.DictReader(f))[:max_rows]
        except Exception:
            continue
    return []

def _mone_dq_symbol(row: dict) -> str:
    for key in ("symbol", "ticker", "code", "stock_code", "Symbol", "Ticker"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value.upper()
    return ""

def _mone_dq_time_value(row: dict) -> str:
    for key in (
        "timestamp", "updatedAt", "updated_at", "datetime", "dateTime",
        "time", "createdAt", "created_at", "date", "tradeDate",
        "asOfDate", "baseDate"
    ):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return ""

def _mone_dq_parse_time(value: str):
    value = str(value or "").strip()
    if not value:
        return None
    cleaned = value.replace("KST", "").replace("kst", "").strip().replace("/", "-")
    if _MONE_DQ_re.fullmatch(r"\d{8}", cleaned):
        cleaned = f"{cleaned[0:4]}-{cleaned[4:6]}-{cleaned[6:8]}"
    for fmt in (
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return _MONE_DQ_Datetime.strptime(cleaned, fmt)
        except Exception:
            pass
    try:
        return _MONE_DQ_Datetime.fromisoformat(cleaned)
    except Exception:
        return None

def _mone_dq_file_summary(path: _MONE_DQ_Path, role: str, market: str) -> dict:
    rows = _mone_dq_read_rows(path)
    symbols = set()
    latest_raw = ""
    latest_dt = None

    for row in rows:
        sym = _mone_dq_symbol(row)
        if sym:
            symbols.add(sym)

        raw = _mone_dq_time_value(row)
        dt = _mone_dq_parse_time(raw)
        if dt and (latest_dt is None or dt > latest_dt):
            latest_dt = dt
            latest_raw = raw

    mtime = None
    try:
        mtime = _MONE_DQ_Datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except Exception:
        pass

    return {
        "name": path.name,
        "role": role,
        "market": market,
        "path": str(path),
        "exists": path.exists(),
        "status": "NORMAL" if rows else "NO_DATA",
        "rowCount": len(rows),
        "uniqueSymbolCount": len(symbols),
        "sampleSymbols": sorted(symbols)[:12],
        "latestTimestamp": latest_raw,
        "mtime": mtime,
    }

def _mone_dq_market(market: str) -> dict:
    repo = _mone_dq_repo_root()
    market = (market or "kr").lower()

    price_files = [
        (repo / "data" / "stockapp" / f"kis_current_price_{market}.csv", "price_current_stockapp"),
        (repo / "reports" / f"kis_current_price_{market}.csv", "price_current_reports"),
        (repo / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv", "intraday_quote_stockapp"),
        (repo / "reports" / f"intraday_quote_snapshot_{market}.csv", "intraday_quote_reports"),
        (repo / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv", "intraday_realtime_stockapp"),
        (repo / "reports" / f"intraday_realtime_snapshot_{market}.csv", "intraday_realtime_reports"),
    ]

    files = [_mone_dq_file_summary(path, role, market) for path, role in price_files]
    good_files = [x for x in files if int(x.get("rowCount") or 0) > 0]

    all_symbols = set()
    for path, _role in price_files:
        for row in _mone_dq_read_rows(path):
            sym = _mone_dq_symbol(row)
            if sym:
                all_symbols.add(sym)

    warnings = []
    failures_path = repo / "reports" / "data_collection_failures_latest.csv"
    failures = _mone_dq_read_rows(failures_path, max_rows=1000)
    if failures:
        warnings.append(f"collection failures present: {len(failures)} rows")

    if good_files:
        data_status = "NORMAL"
        kill_switch = False
        message = "core price data found"
    else:
        data_status = "NO_DATA"
        kill_switch = True
        message = "core price csv not found"

    if good_files and len(all_symbols) < 5:
        data_status = "PARTIAL"
        warnings.append("price coverage is small")

    coverage = {}
    try:
        import json as _mone_dq_json
        summary_path = repo / "reports" / "kis_collection_coverage_summary.json"
        if summary_path.exists():
            coverage = _mone_dq_json.loads(summary_path.read_text(encoding="utf-8")).get("markets", {}).get(market, {})
    except Exception:
        coverage = {}

    return {
        "status": "OK",
        "market": market,
        "dataStatus": data_status,
        "priceDataStatus": "OK" if good_files else "NO_DATA",
        "killSwitch": kill_switch,
        "reviewMode": False,
        "message": message,
        "candidateCount": len(all_symbols),
        "targetCount": coverage.get("targetCount"),
        "currentPriceCount": coverage.get("currentPriceCount"),
        "missingTargetCount": coverage.get("missingTargetCount"),
        "currentPriceCoveragePct": coverage.get("currentPriceCoveragePct"),
        "files": files,
        "warnings": warnings,
        "errors": [] if good_files else ["core price data not found"],
        "updatedAt": _MONE_DQ_Datetime.now().astimezone().isoformat(),
    }

@app.get("/api/final/data-quality-live")
def api_final_data_quality_live(market: str = "kr"):
    market = (market or "kr").lower()

    if market == "all":
        kr = _mone_dq_market("kr")
        us = _mone_dq_market("us")
        kill = bool(kr.get("killSwitch")) or bool(us.get("killSwitch"))

        if kr.get("dataStatus") == "NORMAL" and us.get("dataStatus") == "NORMAL":
            data_status = "NORMAL"
        elif kr.get("dataStatus") == "NO_DATA" and us.get("dataStatus") == "NO_DATA":
            data_status = "NO_DATA"
        else:
            data_status = "PARTIAL"

        return {
            "status": "OK",
            "market": "all",
            "dataStatus": data_status,
            "priceDataStatus": data_status,
            "killSwitch": kill,
            "reviewMode": False,
            "message": "combined kr/us data quality",
            "targetCount": int(kr.get("targetCount") or 0) + int(us.get("targetCount") or 0),
            "currentPriceCount": int(kr.get("currentPriceCount") or 0) + int(us.get("currentPriceCount") or 0),
            "missingTargetCount": int(kr.get("missingTargetCount") or 0) + int(us.get("missingTargetCount") or 0),
            "currentPriceCoveragePct": round(
                ((int(kr.get("currentPriceCount") or 0) + int(us.get("currentPriceCount") or 0))
                 / max(1, int(kr.get("targetCount") or 0) + int(us.get("targetCount") or 0))) * 100,
                2,
            ),
            "markets": {"kr": kr, "us": us},
            "warnings": list(kr.get("warnings", [])) + list(us.get("warnings", [])),
            "errors": list(kr.get("errors", [])) + list(us.get("errors", [])),
            "updatedAt": _MONE_DQ_Datetime.now().astimezone().isoformat(),
        }

    if market not in ("kr", "us"):
        market = "kr"

    return _mone_dq_market(market)
# --- end MONE live data-quality route patch v2 ascii ---


# __MONE_AUTHORITATIVE_HOLDINGS_CLEAN_OVERRIDE_V3__
def _install_mone_authoritative_holdings_clean_v3():
    from pathlib import Path as _MonePath
    import csv as _mone_csv
    import re as _mone_re
    from datetime import datetime as _mone_datetime
    from fastapi import Query as _MoneQuery

    def _root() -> _MonePath:
        return _MonePath(__file__).resolve().parents[3]

    def _read_csv(path: _MonePath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _num(value, default=0.0) -> float:
        s = str(value or "").strip().replace(",", "").replace("₩", "").replace("$", "")
        s = _mone_re.sub(r"[^0-9.\\-]", "", s)
        try:
            return float(s) if s not in ("", "-", ".", "-.") else float(default)
        except Exception:
            return float(default)

    def _text(row: dict, keys: list[str], default: str = "") -> str:
        lower = {str(k).lower(): k for k in row.keys()}
        for key in keys:
            if key in row and str(row.get(key, "")).strip():
                return str(row.get(key, "")).strip()
            actual = lower.get(str(key).lower())
            if actual is not None and str(row.get(actual, "")).strip():
                return str(row.get(actual, "")).strip()
        return default

    def _symbol(value, market: str) -> str:
        raw = str(value or "").strip()
        if market == "kr":
            digits = _mone_re.sub(r"\\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return raw.upper()

    def _row_symbol(row: dict, market: str) -> str:
        value = _text(row, ["symbol", "ticker", "code", "stock_code", "stockCode", "종목코드", "Symbol", "Ticker"], "")
        if not value and row:
            value = row.get(next(iter(row.keys())), "")
        return _symbol(value, market)

    def _name(row: dict, symbol: str) -> str:
        return _text(row, ["name", "companyName", "company_name", "corp_name", "종목명", "Name"], symbol)

    def _price_index(market: str) -> dict[str, dict]:
        paths = [
            _root() / "data" / "stockapp" / f"kis_current_price_{market}.csv",
            _root() / "reports" / f"kis_current_price_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_realtime_snapshot_{market}.csv",
        ]
        out: dict[str, dict] = {}
        for path in paths:
            for row in _read_csv(path):
                sym = _row_symbol(row, market)
                if not sym:
                    continue
                price = _num(_text(row, ["currentPrice", "current_price", "price", "last", "close", "현재가"], ""), 0)
                if price <= 0:
                    price = _num(_text(row, ["currentPriceText", "priceText"], ""), 0)
                if price <= 0:
                    continue
                prev_close = _num(_text(row, ["prevClose", "previousClose", "prev_close", "basePrice", "stck_prdy_clpr", "전일종가", "기준가"], ""), 0)
                change_pct = _num(_text(row, ["changePct", "changeRate", "prdy_ctrt", "등락률"], ""), 0)
                if not change_pct and price > 0 and prev_close > 0:
                    change_pct = (price - prev_close) / prev_close * 100
                out[sym] = {
                    "currentPrice": price,
                    "currentPriceText": f"${price:,.2f}" if market == "us" else f"{round(price):,}원",
                    "priceSource": path.name,
                    "prevClose": prev_close,
                    "prevCloseText": f"${prev_close:,.2f}" if market == "us" and prev_close > 0 else f"{round(prev_close):,}원" if prev_close > 0 else "",
                    "changePct": change_pct,
                    "changePctText": f"{change_pct:+.2f}%" if change_pct else "",
                    "prevCloseSource": path.name if prev_close > 0 else "",
                    "quoteTimestamp": _text(row, ["timestamp", "time", "updatedAt", "datetime", "date"], ""),
                }
        return out

    def _v93_index(market: str) -> dict[str, dict]:
        path = _root() / "reports" / f"v93_position_cards_{market}.csv"
        out = {}
        for row in _read_csv(path):
            sym = _row_symbol(row, market)
            if sym:
                out[sym] = row
        return out

    def _ohlcv_prev_close(market: str, symbol: str) -> dict:
        paths = [
            _root() / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
            _root() / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
            _root() / "reports" / f"{market}_{symbol}_daily.csv",
        ]
        def _read_prev_close() -> dict:
            for path in paths:
                closes = []
                for row in _read_csv(path):
                    close = _num(_text(row, ["close", "Close", "종가"], ""), 0)
                    date = _text(row, ["date", "Date", "날짜"], "")
                    if close > 0:
                        closes.append((date, close))
                closes.sort(key=lambda item: item[0])
                if len(closes) >= 2:
                    return {"prevClose": closes[-2][1], "prevCloseSource": "ohlcv_prev_close", "prevCloseDate": closes[-2][0]}
            return {}

        found = _read_prev_close()
        if found:
            return found

        try:
            backfill = quotes.backfill_daily_ohlcv(symbol, market, days=120)
            if str(backfill.get("status", "")).upper() == "OK":
                found = _read_prev_close()
                if found:
                    found["prevCloseSource"] = "kis_ohlcv_backfill"
                    found["ohlcvBackfill"] = backfill
                    return found
        except Exception:
            pass
        return {}

    def _ohlcv_price_ref(market: str, symbol: str) -> dict:
        paths = [
            _root() / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
            _root() / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
            _root() / "reports" / f"{market}_{symbol}_daily.csv",
        ]
        for path in paths:
            closes = []
            for row in _read_csv(path):
                close = _num(_text(row, ["close", "Close", "stck_clpr", "종가"], ""), 0)
                date = _text(row, ["date", "Date", "tradeDate", "일자"], "")
                if close > 0:
                    closes.append((date, close))
            closes.sort(key=lambda item: item[0])
            if closes:
                prev = closes[-2][1] if len(closes) >= 2 else 0
                prev_date = closes[-2][0] if len(closes) >= 2 else ""
                return {
                    "currentPrice": closes[-1][1],
                    "currentPriceSource": "ohlcv_close",
                    "currentPriceDate": closes[-1][0],
                    "prevClose": prev,
                    "prevCloseSource": "ohlcv_prev_close",
                    "prevCloseDate": prev_date,
                    "ohlcvCount": len(closes),
                    "ohlcvSource": path.name,
                }
        return {}

    def _read_authoritative_holdings(market: str) -> list[dict]:
        markets = ["kr", "us"] if market == "all" else [market]
        rows = []
        seen_keys = set()
        for mk in markets:
            path = _root() / f"holdings_{mk}.csv"
            for row in _read_csv(path):
                sym = _row_symbol(row, mk)
                if not sym:
                    continue
                key = (mk, sym)
                if key in seen_keys:
                    continue
                qty = _num(_text(row, ["quantity", "qty", "수량"], ""), 0)
                avg = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "평균단가", "매입가"], ""), 0)
                if qty <= 0:
                    continue
                seen_keys.add(key)
                stop_csv = _num(_text(row, ["stopPrice", "stop_price", "stop", "손절가"], ""), 0)
                target_csv = _num(_text(row, ["targetPrice", "target_price", "target", "목표가"], ""), 0)
                rows.append({
                    "symbol": sym,
                    "name": _name(row, sym),
                    "market": mk,
                    "quantity": qty,
                    "avgPrice": avg,
                    "stopPriceCsv": stop_csv,
                    "targetPriceCsv": target_csv,
                    "source": path.name,
                    "holdingAuthority": "holdings_csv",
                    "holdingAuthoritySource": path.name,
                })
        return rows

    def _payload(market: str = "all", limit: int = 100) -> dict:
        market_key = str(market or "all").lower()
        if market_key not in ("all", "kr", "us"):
            market_key = "all"

        rows = _read_authoritative_holdings(market_key)
        quote_kr = _price_index("kr") if market_key in ("all", "kr") else {}
        quote_us = _price_index("us") if market_key in ("all", "us") else {}
        v93_kr = _v93_index("kr") if market_key in ("all", "kr") else {}
        v93_us = _v93_index("us") if market_key in ("all", "us") else {}

        items = []
        for row in rows:
            mk = row["market"]
            sym = row["symbol"]
            qty = _num(row.get("quantity"), 0)
            avg = _num(row.get("avgPrice"), 0)
            q = (quote_kr if mk == "kr" else quote_us).get(sym, {})
            v = (v93_kr if mk == "kr" else v93_us).get(sym, {})

            current = _num(q.get("currentPrice"), 0) or _num(_text(v, ["currentPrice", "current", "price", "현재가"], ""), 0)
            ohlcv_ref = {}
            price_source_type = "live_quote" if _num(q.get("currentPrice"), 0) > 0 else ""
            price_source = q.get("priceSource") or ""
            if current <= 0:
                ohlcv_ref = _ohlcv_price_ref(mk, sym)
                current = _num(ohlcv_ref.get("currentPrice"), 0)
                if current > 0:
                    price_source_type = "ohlcv_close"
                    price_source = ohlcv_ref.get("ohlcvSource", "")
            current_text = q.get("currentPriceText") or (f"${current:,.2f}" if mk == "us" and current > 0 else f"{round(current):,}원" if current > 0 else "-")
            prev_close = _num(q.get("prevClose"), 0) or _num(_text(v, ["prevClose", "previousClose", "prev_close", "전일종가", "기준가"], ""), 0)
            prev_close_source = q.get("prevCloseSource") or ""
            if prev_close <= 0 and ohlcv_ref:
                prev_close = _num(ohlcv_ref.get("prevClose"), 0)
                prev_close_source = ohlcv_ref.get("prevCloseSource", "")
            if prev_close <= 0:
                ohlcv_prev = _ohlcv_prev_close(mk, sym)
                prev_close = _num(ohlcv_prev.get("prevClose"), 0)
                prev_close_source = ohlcv_prev.get("prevCloseSource", "")
            change_pct = _num(q.get("changePct"), 0)
            if not change_pct and current > 0 and prev_close > 0:
                change_pct = (current - prev_close) / prev_close * 100
            change_value = _num(q.get("change"), 0)
            if not change_value and current > 0 and prev_close > 0:
                change_value = current - prev_close
            change_text = f"{change_value:+,.2f}" if mk == "us" and change_value else (f"{round(change_value):+,}" if change_value else "")
            change_pct_text = f"{change_pct:+.2f}%" if change_pct else ("전일 기준 없음" if current > 0 else "현재가 수집 대기")
            pnl = (current - avg) * qty if current > 0 and avg > 0 else 0
            invested = avg * qty if avg > 0 else 0
            pnl_pct = (pnl / invested * 100) if invested > 0 else 0

            # 손절/목표: holdings CSV 값 우선, 없으면 v93_position_cards
            stop_from_v93 = _num(_text(v, ["stopPrice", "stop", "stopText", "손절가"], ""), 0)
            target_from_v93 = _num(_text(v, ["targetPrice", "target", "targetText", "목표가"], ""), 0)
            stop = _num(row.get("stopPriceCsv"), 0) or stop_from_v93
            target = _num(row.get("targetPriceCsv"), 0) or target_from_v93
            stop_gap_pct = round((current - stop) / current * 100, 2) if current > 0 and stop > 0 else None
            target_gap_pct = round((target - current) / current * 100, 2) if current > 0 and target > 0 else None
            if current <= 0:
                risk_status = "WATCH"
            elif stop_gap_pct is not None and stop_gap_pct <= 2:
                risk_status = "HIGH"
            elif stop <= 0 or target <= 0 or (stop_gap_pct is not None and stop_gap_pct <= 5) or (target_gap_pct is not None and 0 <= target_gap_pct <= 3):
                risk_status = "WATCH"
            else:
                risk_status = "NORMAL"

            item = dict(row)
            item.update({
                "avgPriceText": f"${avg:,.2f}" if mk == "us" and avg > 0 else f"{round(avg):,}원" if avg > 0 else "-",
                "currentPrice": current,
                "currentPriceText": current_text,
                "prevClose": prev_close if prev_close > 0 else None,
                "prevCloseText": f"${prev_close:,.2f}" if mk == "us" and prev_close > 0 else f"{round(prev_close):,}원" if prev_close > 0 else "",
                "change": change_value if change_value else None,
                "changeText": change_text,
                "changePct": change_pct if current > 0 and prev_close > 0 else None,
                "changePctText": change_pct_text,
                "changePercent": change_pct if current > 0 and prev_close > 0 else None,
                "priceChange": change_value if change_value else None,
                "priceChangeText": change_text,
                "priceChangePercent": change_pct if current > 0 and prev_close > 0 else None,
                "priceChangePercentText": change_pct_text,
                "marketValue": current * qty if current > 0 else 0,
                "marketValueText": f"${current * qty:,.2f}" if mk == "us" and current > 0 else f"{round(current * qty):,}원" if current > 0 else "-",
                "pnl": pnl,
                "pnlText": f"${pnl:,.2f}" if mk == "us" else f"{round(pnl):,}원",
                "pnlPct": pnl_pct,
                "pnlPctText": f"{pnl_pct:+.2f}%",
                "stopPrice": stop,
                "stopText": f"${stop:,.2f}" if mk == "us" and stop > 0 else f"{round(stop):,}원" if stop > 0 else "-",
                "stopGapPct": stop_gap_pct,
                "targetPrice": target,
                "targetText": f"${target:,.2f}" if mk == "us" and target > 0 else f"{round(target):,}원" if target > 0 else "-",
                "targetGapPct": target_gap_pct,
                "riskLevel": _text(v, ["riskLevel", "risk", "status", "판정"], "NORMAL") or "NORMAL",
                "riskStatus": risk_status,
                "dataStatus": "NORMAL" if price_source_type == "live_quote" else ("PARTIAL" if current > 0 else "NO_PRICE"),
                "source": row["source"],
                "enrichSource": "v93_position_cards" if v else "",
                "priceSource": price_source,
                "priceSourceType": price_source_type or ("missing" if current <= 0 else "derived"),
                "ohlcvCount": ohlcv_ref.get("ohlcvCount", ""),
                "ohlcvDate": ohlcv_ref.get("currentPriceDate", ""),
                "prevCloseSource": prev_close_source,
                "quoteTimestamp": q.get("quoteTimestamp") or "",
            })
            items.append(item)

        def _money(amount: float, mk: str) -> str:
            if mk == "us":
                return f"${amount:,.2f}"
            return f"{round(amount):,}원"

        def _summary(rows: list[dict]) -> dict:
            by_market: dict[str, dict] = {
                "kr": {"market": "kr", "count": 0, "totalValue": 0.0, "totalPnl": 0.0, "missingPriceCount": 0, "missingStopCount": 0, "missingTargetCount": 0},
                "us": {"market": "us", "count": 0, "totalValue": 0.0, "totalPnl": 0.0, "missingPriceCount": 0, "missingStopCount": 0, "missingTargetCount": 0},
            }
            for it in rows:
                mk = "us" if str(it.get("market", "")).lower() == "us" else "kr"
                bucket = by_market[mk]
                bucket["count"] += 1
                bucket["totalValue"] += _num(it.get("marketValue"), 0)
                bucket["totalPnl"] += _num(it.get("pnl"), 0)
                if _num(it.get("currentPrice"), 0) <= 0:
                    bucket["missingPriceCount"] += 1
                if _num(it.get("stopPrice"), 0) <= 0:
                    bucket["missingStopCount"] += 1
                if _num(it.get("targetPrice"), 0) <= 0:
                    bucket["missingTargetCount"] += 1
            active = [v for v in by_market.values() if v["count"] > 0]
            for bucket in active:
                mk = bucket["market"]
                bucket["totalValueText"] = _money(bucket["totalValue"], mk)
                bucket["totalPnlText"] = _money(bucket["totalPnl"], mk)
            mixed = len(active) > 1
            if mixed:
                total_value_text = " / ".join(v["totalValueText"] for v in active)
                total_pnl_text = " / ".join(v["totalPnlText"] for v in active)
                total_pnl = sum(v["totalPnl"] for v in active)
            elif active:
                total_value_text = active[0]["totalValueText"]
                total_pnl_text = active[0]["totalPnlText"]
                total_pnl = active[0]["totalPnl"]
            else:
                total_value_text = "-"
                total_pnl_text = "-"
                total_pnl = 0.0
            return {
                "count": len(rows),
                "totalValue": sum(v["totalValue"] for v in active),
                "totalValueText": total_value_text,
                "totalPnl": total_pnl,
                "totalPnlText": total_pnl_text,
                "mixedCurrency": mixed,
                "marketBreakdown": active,
                "missingPriceCount": sum(v["missingPriceCount"] for v in active),
                "missingStopCount": sum(v["missingStopCount"] for v in active),
                "missingTargetCount": sum(v["missingTargetCount"] for v in active),
                "riskCount": sum(1 for it in rows if str(it.get("riskStatus", "")).upper() in {"HIGH", "WATCH"}),
            }

        unique = {(i["market"], i["symbol"]) for i in items}
        limit = max(1, min(int(limit or 100), 10000))
        limited_items = items[:limit]
        return {
            "status": "OK",
            "routeVersion": "holdings-authoritative-csv-v3",
            "market": market_key,
            "count": len(limited_items),
            "totalCount": len(items),
            "uniqueCount": len(unique),
            "items": limited_items,
            "summary": _summary(limited_items),
            "updatedAt": _mone_datetime.now().isoformat(),
            "authority": "holdings_kr.csv/holdings_us.csv",
        }

    global app
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in {"/api/holdings-clean", "/api/final/holdings-clean"}
    ]

    @app.get("/api/holdings-clean")
    def mone_authoritative_holdings_clean_v3(market: str = _MoneQuery("all"), limit: int = _MoneQuery(100)) -> dict:
        return _payload(market, limit)

    @app.get("/api/final/holdings-clean")
    def mone_authoritative_final_holdings_clean_v3(market: str = _MoneQuery("all"), limit: int = _MoneQuery(100)) -> dict:
        return _payload(market, limit)

try:
    _install_mone_authoritative_holdings_clean_v3()
except Exception as _mone_holdings_override_error:
    print("[MONE] holdings-clean override v3 failed:", _mone_holdings_override_error)


# __MONE_SYMBOLS_EXTRA_MASTER_OVERRIDE_V2__
def _install_mone_symbols_extra_master_v2():
    from pathlib import Path as _MonePath
    import csv as _mone_csv
    import re as _mone_re
    from datetime import datetime as _mone_datetime
    from fastapi import Query as _MoneQuery

    def _root() -> _MonePath:
        return _MonePath(__file__).resolve().parents[3]

    def _read_csv(path: _MonePath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _text(row: dict, keys: list[str], default: str = "") -> str:
        lower = {str(k).lower(): k for k in row.keys()}
        for key in keys:
            if key in row and str(row.get(key, "")).strip():
                return str(row.get(key, "")).strip()
            actual = lower.get(str(key).lower())
            if actual is not None and str(row.get(actual, "")).strip():
                return str(row.get(actual, "")).strip()
        return default

    def _num(value, default=0.0) -> float:
        s = str(value or "").strip().replace(",", "").replace("₩", "").replace("$", "")
        s = _mone_re.sub(r"[^0-9.\-]", "", s)
        try:
            return float(s) if s not in ("", "-", ".", "-.") else float(default)
        except Exception:
            return float(default)

    def _market(value: str, symbol: str = "") -> str:
        v = str(value or "").strip().lower()
        if v in ("kr", "kospi", "kosdaq", "konex", "국장", "한국", "korea"):
            return "kr"
        if v in ("us", "nasdaq", "nyse", "amex", "미장", "미국", "usa"):
            return "us"
        return "kr" if str(symbol).isdigit() else "us"

    def _symbol(value: str, market: str) -> str:
        raw = str(value or "").strip()
        if market == "kr":
            digits = _mone_re.sub(r"\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return raw.upper()

    def _row_symbol(row: dict, fallback_market: str = "") -> tuple[str, str]:
        raw = _text(row, ["symbol", "ticker", "code", "stock_code", "stockCode", "종목코드", "종목", "Symbol", "Ticker"], "")
        guessed_market = _market(_text(row, ["market", "시장", "exchange", "marketType"], fallback_market), raw)
        if not raw and row:
            raw = str(row.get(next(iter(row.keys())), "")).strip()
        sym = _symbol(raw, guessed_market)
        return sym, guessed_market

    def _name(row: dict, symbol: str) -> str:
        return _text(row, ["name", "companyName", "company_name", "corp_name", "종목명", "한글명", "Name"], symbol)

    def _price_index(market: str) -> dict[str, dict]:
        paths = [
            _root() / "data" / "stockapp" / f"kis_current_price_{market}.csv",
            _root() / "reports" / f"kis_current_price_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_quote_snapshot_{market}.csv",
            _root() / "data" / "stockapp" / f"intraday_realtime_snapshot_{market}.csv",
            _root() / "reports" / f"intraday_realtime_snapshot_{market}.csv",
        ]
        out: dict[str, dict] = {}
        for path in paths:
            for row in _read_csv(path):
                sym, mk = _row_symbol(row, market)
                if not sym or mk != market:
                    continue
                price = _num(_text(row, ["currentPrice", "current_price", "price", "last", "close", "현재가"], ""), 0)
                if price <= 0:
                    price = _num(_text(row, ["currentPriceText", "priceText"], ""), 0)
                if price <= 0:
                    continue
                out[sym] = {
                    "currentPrice": price,
                    "currentPriceText": f"${price:,.2f}" if market == "us" else f"{round(price):,}원",
                    "priceSource": path.name,
                }
        return out

    def _symbol_source_files() -> list[_MonePath]:
        root = _root()
        files: list[_MonePath] = [
            root / "holdings_kr.csv",
            root / "holdings_us.csv",
            root / "watchlist_kr.csv",
            root / "watchlist_us.csv",
            root / "watchlist_kr_growth.csv",
            root / "watchlist_us_growth.csv",
            root / "candidate_universe_kr.csv",
            root / "candidate_universe_us.csv",
            root / "data" / "symbol_master_kr_full.csv",
            root / "data" / "symbol_master_kr_extra.csv",
            root / "data" / "symbol_master_us_full.csv",
            root / "data" / "symbol_master_us_extra.csv",
            root / "data" / "stock_master_kr.csv",
            root / "data" / "stock_master_us.csv",
            root / "data" / "holdings_kr.csv",
            root / "data" / "holdings_us.csv",
            root / "data" / "watchlist_kr.csv",
            root / "data" / "watchlist_us.csv",
            root / "data" / "watchlist_kr_growth.csv",
            root / "data" / "watchlist_us_growth.csv",
            root / "data" / "candidate_universe_kr.csv",
            root / "data" / "candidate_universe_us.csv",
            root / "data" / "stockapp" / "kis_current_price_kr.csv",
            root / "data" / "stockapp" / "kis_current_price_us.csv",
            root / "data" / "stockapp" / "intraday_quote_snapshot_kr.csv",
            root / "data" / "stockapp" / "intraday_quote_snapshot_us.csv",
            root / "data" / "stockapp" / "intraday_realtime_snapshot_kr.csv",
            root / "data" / "stockapp" / "intraday_realtime_snapshot_us.csv",
            root / "reports" / "candidate_universe_kr.csv",
            root / "reports" / "candidate_universe_us.csv",
            root / "reports" / "kis_current_price_kr.csv",
            root / "reports" / "kis_current_price_us.csv",
            root / "reports" / "intraday_quote_snapshot_kr.csv",
            root / "reports" / "intraday_quote_snapshot_us.csv",
        ]
        if (root / "reports").exists():
            files.extend(sorted((root / "reports").glob("v*_symbol_snapshot_kr.csv")))
            files.extend(sorted((root / "reports").glob("v*_symbol_snapshot_us.csv")))
            files.extend(sorted((root / "reports").glob("v*_master_investors_kr.csv")))
            files.extend(sorted((root / "reports").glob("v*_master_investors_us.csv")))
            files.extend(sorted((root / "reports").glob("mone_v36_final_recommendations_kr_*.csv")))
            files.extend(sorted((root / "reports").glob("mone_v36_final_recommendations_us_*.csv")))
        return [p for p in files if p.exists()]

    def _symbols_payload(market: str = "all", q: str = "", limit: int = 10000) -> dict:
        market_key = str(market or "all").lower()
        if market_key not in ("all", "kr", "us"):
            market_key = "all"
        query = str(q or "").strip().lower()
        query_digits = _mone_re.sub(r"\D", "", query)
        price_kr = _price_index("kr") if market_key in ("all", "kr") else {}
        price_us = _price_index("us") if market_key in ("all", "us") else {}

        items_by_key: dict[tuple[str, str], dict] = {}

        for path in _symbol_source_files():
            lower_name = path.name.lower()
            fallback_market = "kr" if "_kr" in lower_name or "kr_" in lower_name else "us" if "_us" in lower_name or "us_" in lower_name else ""
            for row in _read_csv(path):
                sym, mk = _row_symbol(row, fallback_market)
                if not sym or mk not in ("kr", "us"):
                    continue
                if market_key != "all" and mk != market_key:
                    continue
                name = _name(row, sym)
                key = (mk, sym)
                base = items_by_key.get(key, {})
                source = _text(row, ["source"], path.name) or path.name
                items_by_key[key] = {
                    **base,
                    "symbol": sym,
                    "name": name if name and name != sym else base.get("name", name or sym),
                    "market": mk,
                    "source": base.get("source") or source,
                }

        for mk, pidx in [("kr", price_kr), ("us", price_us)]:
            if market_key not in ("all", mk):
                continue
            for sym in pidx.keys():
                key = (mk, sym)
                if key not in items_by_key:
                    items_by_key[key] = {"symbol": sym, "name": sym, "market": mk, "source": "price_snapshot"}

        rows = []
        for item in items_by_key.values():
            mk = item["market"]
            sym = item["symbol"]
            price = (price_kr if mk == "kr" else price_us).get(sym, {})
            row = {**item, **price}
            hay = f"{row.get('symbol','')} {row.get('name','')}".lower()
            sym_digits = _mone_re.sub(r"\D", "", str(row.get("symbol", "")))
            if query:
                if query not in hay and (not query_digits or query_digits not in sym_digits):
                    continue
            if not row.get("currentPrice"):
                row["currentPrice"] = None
            row.setdefault("currentPriceText", "")
            row.setdefault("priceSource", "")
            row["dataStatus"] = "NORMAL" if row.get("currentPrice") else "PRICE_PENDING"
            rows.append(row)

        def _search_rank(row: dict) -> tuple:
            symbol = str(row.get("symbol") or "").lower()
            name = str(row.get("name") or "").lower()
            q = query
            q_digits = query_digits
            exact_symbol = bool(q and (symbol == q or (q_digits and symbol == q_digits.zfill(6))))
            exact_name = bool(q and name == q)
            starts_name = bool(q and name.startswith(q))
            starts_symbol = bool(q and symbol.startswith(q))
            contains_name = bool(q and q in name)
            contains_symbol = bool(q and q in symbol)
            derivative_words = ("우", "2우", "3우", "리츠", "etf", "etn", "스팩", "증권", "인버스", "레버리지")
            derivative_penalty = 1 if any(word in name for word in derivative_words) and not exact_name else 0
            has_price_penalty = 0 if row.get("currentPrice") else 1
            return (
                0 if exact_symbol else 1,
                0 if exact_name else 1,
                0 if starts_name else 1,
                0 if starts_symbol else 1,
                0 if contains_name else 1,
                0 if contains_symbol else 1,
                derivative_penalty,
                has_price_penalty,
                row.get("market", ""),
                symbol,
            )

        rows.sort(key=_search_rank)
        limit = max(1, min(int(limit or 10000), 10000))
        return {
            "status": "OK",
            "routeVersion": "symbols-extra-master-v2",
            "market": market_key,
            "query": q,
            "count": len(rows[:limit]),
            "totalCount": len(rows),
            "items": rows[:limit],
            "updatedAt": _mone_datetime.now().isoformat(),
            "sources": [p.name for p in _symbol_source_files()],
        }

    global app
    app.router.routes = [
        r for r in app.router.routes
        if getattr(r, "path", "") not in {"/api/symbols", "/api/final/symbols"}
    ]

    @app.get("/api/symbols")
    def mone_symbols_extra_master_v2(
        market: str = _MoneQuery("all"),
        q: str = _MoneQuery(""),
        limit: int = _MoneQuery(10000),
        watchOnly: bool = _MoneQuery(False),
    ) -> dict:
        return _symbols_payload(market, q, limit)

    @app.get("/api/final/symbols")
    def mone_final_symbols_extra_master_v2(
        market: str = _MoneQuery("all"),
        q: str = _MoneQuery(""),
        limit: int = _MoneQuery(10000),
        watchOnly: bool = _MoneQuery(False),
    ) -> dict:
        return _symbols_payload(market, q, limit)

try:
    _install_mone_symbols_extra_master_v2()
except Exception as _mone_symbols_extra_error:
    print("[MONE] symbols extra master override failed:", _mone_symbols_extra_error)


# __MONE_QUOTE_REFRESH_PATCH_V1__
def _install_mone_quote_refresh_routes_v1():
    from datetime import datetime as _MoneQrDatetime
    from pathlib import Path as _MoneQrPath
    import csv as _mone_qr_csv
    import json as _mone_qr_json
    import re as _mone_qr_re
    from fastapi import Body as _MoneQrBody, Query as _MoneQrQuery

    root = _MoneQrPath(__file__).resolve().parents[3]
    stockapp = root / "data" / "stockapp"
    reports = root / "reports"
    fields = [
        "symbol", "market", "ok", "currentPrice", "current_price", "last_price", "priceTime",
        "priceSource", "source", "priceSourceType", "priceSourceFile", "priceSourceDate",
        "kis_quote_success", "quote_available", "error", "updated_at",
    ]

    def _read_csv(path: _MoneQrPath) -> list[dict]:
        if not path.exists() or path.stat().st_size <= 0:
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_qr_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _write_csv(path: _MoneQrPath, fieldnames: list[str], rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = _mone_qr_csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in fieldnames})

    def _market(value: str, symbol: str = "") -> str:
        raw = str(value or "").strip().lower()
        if raw == "us":
            return "us"
        if raw == "kr":
            return "kr"
        return "kr" if _mone_qr_re.fullmatch(r"\d{1,6}", str(symbol or "")) else "us"

    def _symbol(value: str, market: str) -> str:
        raw = str(value or "").strip().upper()
        if market == "kr":
            digits = _mone_qr_re.sub(r"\D", "", raw)
            return digits.zfill(6)[-6:] if digits else ""
        return _mone_qr_re.sub(r"[^A-Z0-9.\-]", "", raw)

    def _add_target(market: str, symbol: str, name: str, reason: str) -> None:
        path = stockapp / f"kis_collection_targets_{market}.csv"
        rows = _read_csv(path)
        keyed = {}
        for row in rows:
            sym = _symbol(row.get("symbol", ""), market)
            if sym:
                keyed[sym] = {
                    "market": market,
                    "symbol": sym,
                    "name": row.get("name") or sym,
                    "reason": row.get("reason") or "existing",
                    "updatedAt": row.get("updatedAt") or "",
                }
        keyed[symbol] = {
            "market": market,
            "symbol": symbol,
            "name": name or symbol,
            "reason": reason,
            "updatedAt": _MoneQrDatetime.now().isoformat(timespec="seconds"),
        }
        _write_csv(path, ["market", "symbol", "name", "reason", "updatedAt"], sorted(keyed.values(), key=lambda row: row["symbol"]))

    def _snapshot_row(market: str, symbol: str, quote: dict) -> dict:
        price = quote.get("price") or quote.get("currentPrice") or quote.get("current_price") or quote.get("last_price") or ""
        now = _MoneQrDatetime.now().strftime("%Y-%m-%d %H:%M:%S KST")
        source = quote.get("priceSource") or quote.get("source") or ("KIS 현재가" if market == "kr" else "KIS/Finnhub 현재가")
        return {
            "symbol": symbol,
            "market": market,
            "ok": "true" if quote.get("ok") else "false",
            "currentPrice": price,
            "current_price": price,
            "last_price": price,
            "priceTime": quote.get("priceTime") or now,
            "priceSource": source,
            "source": source,
            "priceSourceType": "manual_refresh",
            "priceSourceFile": f"data/stockapp/kis_current_price_{market}.csv",
            "priceSourceDate": quote.get("priceSourceDate") or now,
            "kis_quote_success": "true" if quote.get("ok") else "false",
            "quote_available": "true" if quote.get("ok") else "false",
            "error": quote.get("error") or "",
            "updated_at": now,
        }

    def _upsert_snapshot(market: str, row: dict) -> None:
        for path in [
            stockapp / f"kis_current_price_{market}.csv",
            stockapp / f"intraday_realtime_snapshot_{market}.csv",
            stockapp / f"intraday_quote_snapshot_{market}.csv",
            reports / f"kis_current_price_{market}.csv",
            reports / f"intraday_realtime_snapshot_{market}.csv",
            reports / f"intraday_quote_snapshot_{market}.csv",
        ]:
            rows = _read_csv(path)
            keyed = {str(existing.get("symbol") or "").upper(): existing for existing in rows}
            keyed[str(row["symbol"]).upper()] = row
            _write_csv(path, fields, sorted(keyed.values(), key=lambda item: str(item.get("symbol") or "")))

    def _refresh_one(payload: dict) -> dict:
        market = _market(payload.get("market", ""), payload.get("symbol", ""))
        symbol = _symbol(payload.get("symbol", ""), market)
        name = str(payload.get("name") or symbol).strip()
        if not symbol:
            return {"status": "ERROR", "error": "symbol is empty", "dataStatus": "PRICE_PENDING"}
        _add_target(market, symbol, name, "manual_refresh_one")
        quote = quotes._fetch_quote(symbol, market)
        if quote.get("ok"):
            row = _snapshot_row(market, symbol, quote)
            _upsert_snapshot(market, row)
            status = "OK"
            data_status = "NORMAL"
        else:
            status = "ERROR"
            data_status = "PRICE_PENDING"
        return {
            "status": status,
            "market": market,
            "symbol": symbol,
            "name": name,
            "dataStatus": data_status,
            "quote": quote,
            "error": quote.get("error", ""),
            "updatedAt": _MoneQrDatetime.now().isoformat(),
        }

    def _targets(market: str) -> list[dict]:
        paths = [
            root / f"holdings_{market}.csv",
            root / "data" / f"holdings_{market}.csv",
            root / f"watchlist_{market}.csv",
            root / "data" / f"watchlist_{market}.csv",
            stockapp / f"kis_collection_targets_{market}.csv",
            stockapp / f"price_collection_universe_{market}.csv",
        ]
        keyed = {}
        for path in paths:
            for row in _read_csv(path):
                sym = _symbol(row.get("symbol") or row.get("ticker") or row.get("code") or row.get("종목코드") or "", market)
                if sym and sym not in keyed:
                    keyed[sym] = {"market": market, "symbol": sym, "name": row.get("name") or row.get("종목명") or sym}
        return list(keyed.values())

    def _write_batch_status(payload: dict) -> None:
        reports.mkdir(parents=True, exist_ok=True)
        (reports / "quote_refresh_batch_status.json").write_text(_mone_qr_json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    global app
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/quotes/refresh-one", "/api/quotes/refresh-targets"}
    ]

    @app.post("/api/quotes/refresh-one")
    def mone_quote_refresh_one(payload: dict = _MoneQrBody(...)) -> dict:
        return _refresh_one(payload)

    @app.post("/api/quotes/refresh-targets")
    def mone_quote_refresh_targets(
        payload: dict = _MoneQrBody(default={}),
        market: str = _MoneQrQuery("all"),
        limit: int = _MoneQrQuery(20),
        max_symbols: int | None = _MoneQrQuery(None),
    ) -> dict:
        body_market = str((payload or {}).get("market") or market or "all").lower()
        markets = ["kr", "us"] if body_market == "all" else [_market(body_market)]
        requested_limit = (payload or {}).get("max_symbols") or (payload or {}).get("limit") or max_symbols or limit or 20
        max_count = max(1, min(int(requested_limit), 50))
        refreshed = []
        failed = []
        pending = 0
        for mk in markets:
            for target in _targets(mk)[:max_count]:
                result = _refresh_one(target)
                if result.get("status") == "OK":
                    refreshed.append(result)
                else:
                    failed.append(result)
            pending += max(0, len(_targets(mk)) - max_count)
        out = {
            "status": "OK" if refreshed else ("PARTIAL" if failed else "NO_DATA"),
            "market": body_market,
            "requestedLimit": max_count,
            "successCount": len(refreshed),
            "failureCount": len(failed),
            "pendingCount": pending,
            "lastRefreshAt": _MoneQrDatetime.now().isoformat(),
            "items": refreshed[:20],
            "failedItems": failed[:20],
        }
        _write_batch_status(out)
        return out

try:
    _install_mone_quote_refresh_routes_v1()
except Exception as _mone_quote_refresh_error:
    print("[MONE] quote refresh patch failed:", _mone_quote_refresh_error)


# __MONE_CLOSE_VALIDATION_ROUTES_V1__
def _install_mone_close_validation_routes_v1():
    from pathlib import Path as _MoneClosePath
    import csv as _mone_close_csv
    import json as _mone_close_json
    import re as _mone_close_re
    from fastapi import Query as _MoneCloseQuery

    root = _MoneClosePath(__file__).resolve().parents[3]
    reports = root / "reports"

    def _read_csv(path: _MoneClosePath) -> list[dict]:
        if not path.exists() or path.stat().st_size == 0:
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _mone_close_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _num(value):
        try:
            text = str(value if value is not None else "").replace(",", "").replace("%", "").strip()
            return float(text) if text not in {"", "-", "None", "nan", "NaN"} else None
        except Exception:
            return None

    def _validation_files(market: str, mode: str, horizon: str) -> list[_MoneClosePath]:
        files = []
        patterns = [
            f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}_*.csv",
            f"mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv",
        ]
        for pattern in patterns:
            files.extend(sorted(reports.glob(pattern), key=lambda p: p.name, reverse=True))
        return list(dict.fromkeys(files))

    def _date_from_file(path: _MoneClosePath) -> str:
        m = _mone_close_re.search(r"(20\d{6})", path.name)
        if not m:
            return ""
        raw = m.group(1)
        return f"{raw[:4]}-{raw[4:6]}-{raw[6:]}"

    def _latest_validation(market: str, mode: str, horizon: str) -> tuple[_MoneClosePath | None, list[dict]]:
        for path in _validation_files(market, mode, horizon):
            rows = _read_csv(path)
            if rows:
                return path, rows
        return None, []

    def _normalize_trade(row: dict, date_text: str, market: str, mode: str, horizon: str) -> dict:
        return {
            "date": row.get("date") or date_text,
            "symbol": row.get("symbol") or row.get("ticker") or "",
            "name": row.get("name") or row.get("companyName") or row.get("symbol") or "",
            "market": row.get("market") or market,
            "mode": row.get("mode") or mode,
            "horizon": row.get("horizon") or horizon,
            "executed": row.get("executed") if row.get("executed") not in (None, "") else row.get("체결", "false"),
            "entryPrice": row.get("entryPrice") or row.get("entry") or "",
            "entryText": row.get("entryText") or "",
            "exitPrice": row.get("exitPrice") or "",
            "exitText": row.get("exitText") or "",
            "returnPct": row.get("returnPct") or row.get("수익률") or "",
            "returnPctText": row.get("returnPctText") or "",
            "result": row.get("result") or row.get("결과") or "검증 대기",
            "dataStatus": row.get("dataStatus") or "NORMAL",
            "reason": row.get("reason") or "",
            "source": row.get("source") or "",
        }

    def _summary_payload(market: str, mode: str, horizon: str) -> dict:
        path, rows = _latest_validation(market, mode, horizon)
        if not path:
            status_path = reports / "kr_close_validation_status.json" if market == "kr" else reports / "us_close_validation_status.json"
            status = {}
            if status_path.exists():
                try:
                    status = _mone_close_json.loads(status_path.read_text(encoding="utf-8"))
                except Exception:
                    status = {}
            return {
                "status": "OK",
                "market": market,
                "mode": mode,
                "horizon": horizon,
                "todayStatus": "NO_DATA",
                "todayDate": "",
                "todayMessage": "오늘 장마감 원본 없음",
                "latestDate": "",
                "count": 0,
                "items": [],
                "closeValidationStatus": status,
            }
        date_text = _date_from_file(path) or str(rows[0].get("date") or "")
        normalized = [_normalize_trade(row, date_text, market, mode, horizon) for row in rows]
        executed = [row for row in normalized if str(row.get("executed", "")).lower() in {"true", "1", "yes", "체결"}]
        returns = [_num(row.get("returnPct")) for row in executed]
        returns = [r for r in returns if r is not None]
        win_count = sum(1 for r in returns if r > 0)
        avg_return = sum(returns) / len(returns) if returns else 0.0
        return {
            "status": "OK",
            "market": market,
            "mode": mode,
            "horizon": horizon,
            "todayStatus": "NORMAL" if rows else "NO_DATA",
            "todayDate": date_text,
            "todayMessage": "장마감 검증 파일 연결됨" if rows else "오늘 장마감 원본 없음",
            "latestDate": date_text,
            "latestSource": path.name,
            "latestRecommendations": len(normalized),
            "latestExecutedTrades": len(executed),
            "latestUnexecutedCount": max(0, len(normalized) - len(executed)),
            "latestExecutionRate": round(len(executed) / len(normalized) * 100, 2) if normalized else 0,
            "latestWinRate": round((win_count / len(returns)) * 100, 2) if returns else 0,
            "latestAverageReturnPct": round(avg_return, 4),
            "latestCumulativeReturnPct": round(sum(returns), 4),
            "items": normalized[:100],
            "count": len(normalized),
        }

    global app
    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/backtest/trades", "/api/backtest/summary", "/api/final/backtest-summary"}
    ]

    @app.get("/api/backtest/trades")
    def mone_close_backtest_trades(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
        limit: int = _MoneCloseQuery(250, ge=1, le=1000),
    ) -> dict:
        payload = _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)
        return {**payload, "items": payload.get("items", [])[:limit], "count": min(len(payload.get("items", [])), limit)}

    @app.get("/api/backtest/summary")
    def mone_close_backtest_summary(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
    ) -> dict:
        return _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)

    @app.get("/api/final/backtest-summary")
    def mone_close_final_backtest_summary(
        market: str = _MoneCloseQuery("kr", pattern="^(kr|us)$"),
        mode: str = _MoneCloseQuery("balanced"),
        horizon: str = _MoneCloseQuery("swing"),
    ) -> dict:
        return _summary_payload("us" if str(market).lower() == "us" else "kr", mode, horizon)

try:
    _install_mone_close_validation_routes_v1()
except Exception as _mone_close_validation_error:
    print("[MONE] close validation route patch failed:", _mone_close_validation_error)


# ════════════════════════════════════════════════════════════════════════
# MONE v10.2 — 누락 API 엔드포인트 일괄 구현 (2026-06-04)
# 프론트엔드에서 호출하지만 백엔드에 없던 28개 엔드포인트 추가
# ════════════════════════════════════════════════════════════════════════

import csv as _csv
import json as _json
import os as _os
import re as _re
import uuid as _uuid
from datetime import datetime as _dt
from pathlib import Path as _Path
from typing import Any as _Any

_REPO = data.REPO_ROOT
_DATA = _REPO / "data"
_REPORTS = _REPO / "reports"
_OHLCV_DIR = _DATA / "market" / "ohlcv"
_JOURNAL_FILE = _DATA / "journal.csv"
_JOURNAL_COLS = ["id", "date", "market", "symbol", "name", "action", "price", "qty", "memo", "review", "result", "returnPct", "tags", "createdAt"]


def _read_csv_safe(path: _Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(row) for row in _csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv_safe_v2(path: _Path, rows: list[dict], cols: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(path)


def _safe_float_v2(v: _Any, default: float = 0.0) -> float:
    try:
        return float(str(v).replace(",", "").strip()) if v not in (None, "", "nan") else default
    except Exception:
        return default


def _normalize_sym(sym: _Any, market: str = "kr") -> str:
    s = str(sym or "").strip()
    if market == "kr":
        return _re.sub(r"[^0-9]", "", s).zfill(6)[-6:] if _re.search(r"\d", s) else s
    return s.upper()


import re as _uid_re
from fastapi import Header as _Header

def _sanitize_uid(raw: str) -> str:
    return _uid_re.sub(r"[^a-zA-Z0-9_\-]", "", str(raw or ""))[:64]

def _user_holdings_dir(user_id: str) -> "Path":
    uid = _sanitize_uid(user_id)
    if not uid:
        return _REPO
    d = _REPO / "data" / "users" / uid
    d.mkdir(parents=True, exist_ok=True)
    return d

def _holdings_path(mk: str, user_id: str = "") -> "Path":
    return _user_holdings_dir(user_id) / f"holdings_{mk}.csv"

# ── 1. holdings-edit ──────────────────────────────────────────────────

@app.get("/api/holdings-edit")
def api_holdings_edit(
    market: str = Query("all"),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    uid = _sanitize_uid(x_mone_user)

    # uid가 있으면 SQLite 우선
    if uid:
        items = _db.get_holdings(uid, market)
        # SQLite에 없으면 CSV 폴백 (최초 사용자)
        if not items:
            csv_items: list[dict] = []
            for mk in (["kr", "us"] if market == "all" else [market]):
                for row in _read_csv_safe(_REPO / f"holdings_{mk}.csv"):
                    sym = str(row.get("symbol", "")).strip()
                    if sym:
                        csv_items.append({"market": mk, "symbol": sym,
                            "name": str(row.get("name", sym)).strip(),
                            "quantity": str(row.get("quantity", "0")).strip(),
                            "avgPrice": str(row.get("avgPrice", "0")).strip(),
                            "stopPrice": str(row.get("stopPrice", "")).strip(),
                            "targetPrice": str(row.get("targetPrice", "")).strip()})
            items = csv_items
        return {"status": "OK", "count": len(items), "items": items, "userId": uid, "storage": "sqlite"}

    # uid 없으면 기존 CSV (관리자 모드)
    items_csv: list[dict] = []
    for mk in (["kr", "us"] if market == "all" else [market]):
        path = _REPO / f"holdings_{mk}.csv"
        for row in _read_csv_safe(path):
            sym = str(row.get("symbol", "")).strip()
            if not sym:
                continue
            items_csv.append({"market": mk, "symbol": sym,
                "name": str(row.get("name", sym)).strip(),
                "quantity": str(row.get("quantity", "0")).strip(),
                "avgPrice": str(row.get("avgPrice", "0")).strip(),
                "stopPrice": str(row.get("stopPrice", "")).strip(),
                "targetPrice": str(row.get("targetPrice", "")).strip()})
    return {"status": "OK", "count": len(items_csv), "items": items_csv, "userId": "default", "storage": "csv"}


@app.post("/api/holdings-edit/save")
def api_holdings_edit_save(
    payload: dict = Body(...),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    uid = _sanitize_uid(x_mone_user)
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "ERROR", "error": "items must be a list"}

    # uid가 있으면 SQLite에 저장
    if uid:
        saved = _db.save_holdings(uid, items)
        return {"status": "OK", "saved": saved, "userId": uid, "storage": "sqlite"}

    # uid 없으면 CSV (관리자 모드)
    by_market: dict[str, list] = {"kr": [], "us": []}
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        by_market[mk].append(item)
    cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
    for mk, rows in by_market.items():
        path = _REPO / f"holdings_{mk}.csv"
        norm_rows = []
        for r in rows:
            sym = _normalize_sym(r.get("symbol", ""), mk)
            if not sym:
                continue
            norm_rows.append({"symbol": sym, "name": str(r.get("name", sym)).strip(), "market": mk,
                "quantity": str(r.get("quantity", "0")).strip(), "avgPrice": str(r.get("avgPrice", "0")).strip(),
                "stopPrice": str(r.get("stopPrice", "")).strip(), "targetPrice": str(r.get("targetPrice", "")).strip()})
        _write_csv_safe_v2(path, norm_rows, cols)
        data_copy = _REPO / "data" / f"holdings_{mk}.csv"
        if data_copy.exists():
            _write_csv_safe_v2(data_copy, norm_rows, cols)
    return {"status": "OK", "saved": len(items), "userId": "default", "storage": "csv"}


# ── KIS 보유종목 가져오기 ───────────────────────────────────────────────

@app.get("/api/kis/holdings")
def api_kis_holdings_preview() -> dict:
    """KIS 계좌 잔고 조회 (미리보기 — CSV 저장 안 함)"""
    return quotes.fetch_kis_holdings_kr()


@app.post("/api/kis/holdings/sync")
def api_kis_holdings_sync(
    payload: dict = Body(default={}),
    x_mone_user: str = _Header(default="", alias="x-mone-user"),
) -> dict:
    """KIS 계좌 잔고를 가져와 SQLite(uid 있음) 또는 CSV(관리자)에 병합 저장."""
    uid = _sanitize_uid(x_mone_user)
    mode = str(payload.get("mode", "merge"))
    result = quotes.fetch_kis_holdings_kr()
    if result.get("status") != "OK":
        return result

    kis_items = result.get("items", [])
    if not kis_items:
        return {"status": "NO_DATA", "error": "KIS 계좌에 보유종목이 없습니다."}

    added, updated = 0, 0

    if uid:
        # SQLite: 기존 보유 로드 후 병합
        existing_list = _db.get_holdings(uid, "kr") if mode == "merge" else []
        existing: dict[str, dict] = {r["symbol"]: r for r in existing_list}
        for item in kis_items:
            sym = str(item["symbol"]).strip()
            if not sym:
                continue
            if sym in existing:
                existing[sym]["quantity"] = str(item["quantity"])
                existing[sym]["avgPrice"] = str(item["avgPrice"])
                updated += 1
            else:
                existing[sym] = {"symbol": sym, "name": item.get("name", sym), "market": "kr",
                    "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                    "stopPrice": "", "targetPrice": ""}
                added += 1
        _db.save_holdings(uid, list(existing.values()))
        storage = "sqlite"
    else:
        # CSV 관리자 모드
        cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
        path = _REPO / "holdings_kr.csv"
        existing_csv: dict[str, dict] = {}
        if mode == "merge":
            for row in _read_csv_safe(path):
                sym = str(row.get("symbol", "")).strip()
                if sym:
                    existing_csv[sym] = row
        for item in kis_items:
            sym = str(item["symbol"]).strip()
            if not sym:
                continue
            if sym in existing_csv:
                existing_csv[sym]["quantity"] = str(item["quantity"])
                existing_csv[sym]["avgPrice"] = str(item["avgPrice"])
                updated += 1
            else:
                existing_csv[sym] = {"symbol": sym, "name": item.get("name", sym), "market": "kr",
                    "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                    "stopPrice": "", "targetPrice": ""}
                added += 1
        norm_rows = list(existing_csv.values())
        _write_csv_safe_v2(path, norm_rows, cols)
        data_copy = _REPO / "data" / "holdings_kr.csv"
        if data_copy.exists():
            _write_csv_safe_v2(data_copy, norm_rows, cols)
        storage = "csv"

    return {
        "status": "OK",
        "mode": mode,
        "added": added,
        "updated": updated,
        "total": added + updated,
        "isMock": result.get("isMock", False),
        "storage": storage,
    }


@app.post("/api/holdings/import-csv")
def api_holdings_import_csv(payload: dict = Body(...)) -> dict:
    """나무·토스 등에서 붙여넣은 CSV/탭 텍스트를 파싱해 holdings에 병합.
    body: { market: 'kr'|'us', csv_text: '...', mode: 'merge'|'replace' }
    필수 컬럼: symbol(종목코드), quantity(수량), avgPrice(평균단가)
    선택 컬럼: name(종목명)
    헤더 없이 붙여넣을 경우 열 순서: symbol, name, quantity, avgPrice
    """
    import io
    import csv as _csv

    market = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
    mode = str(payload.get("mode", "merge"))
    raw = str(payload.get("csv_text", "")).strip()
    if not raw:
        return {"status": "ERROR", "error": "csv_text가 비어 있습니다."}

    # 탭/콤마/파이프 자동 감지
    sample = raw[:500]
    delimiter = "\t" if raw.count("\t") >= raw.count(",") else ","

    reader = _csv.reader(io.StringIO(raw), delimiter=delimiter)
    rows_raw = [r for r in reader if any(c.strip() for c in r)]
    if not rows_raw:
        return {"status": "ERROR", "error": "파싱 가능한 행이 없습니다."}

    # 헤더 감지 (숫자가 있으면 데이터행, 없으면 헤더)
    def _is_header(row: list[str]) -> bool:
        return not any(c.strip().replace(".", "").replace("-", "").isdigit() for c in row)

    header_aliases = {
        "symbol": ["symbol", "종목코드", "code", "ticker", "종목번호"],
        "name": ["name", "종목명", "종목", "company"],
        "quantity": ["quantity", "수량", "qty", "보유수량", "잔량"],
        "avgPrice": ["avgprice", "평균단가", "avg", "평단가", "매입단가", "단가", "평균가"],
    }

    col_map: dict[str, int] = {}
    data_rows: list[list[str]] = []

    if _is_header(rows_raw[0]):
        header = [c.strip().lower() for c in rows_raw[0]]
        for field, aliases in header_aliases.items():
            for alias in aliases:
                if alias.lower() in header:
                    col_map[field] = header.index(alias.lower())
                    break
        data_rows = rows_raw[1:]
    else:
        # 헤더 없음: symbol, name, quantity, avgPrice 순 가정
        ncols = len(rows_raw[0])
        if ncols >= 4:
            col_map = {"symbol": 0, "name": 1, "quantity": 2, "avgPrice": 3}
        elif ncols == 3:
            col_map = {"symbol": 0, "quantity": 1, "avgPrice": 2}
        elif ncols == 2:
            col_map = {"symbol": 0, "quantity": 1}
        data_rows = rows_raw

    if "symbol" not in col_map or "quantity" not in col_map:
        return {"status": "ERROR", "error": "종목코드(symbol)와 수량(quantity) 컬럼을 찾지 못했습니다. 헤더를 포함해 붙여넣어 주세요."}

    parsed: list[dict] = []
    for row in data_rows:
        try:
            sym_raw = row[col_map["symbol"]].strip().replace(",", "").replace(" ", "")
            if not sym_raw:
                continue
            sym = _normalize_sym(sym_raw, market)
            qty_raw = row[col_map["quantity"]].strip().replace(",", "") if len(row) > col_map["quantity"] else "0"
            qty = int(float(qty_raw)) if qty_raw else 0
            if qty <= 0:
                continue
            avg_raw = row[col_map.get("avgPrice", -1)].strip().replace(",", "") if col_map.get("avgPrice") is not None and len(row) > col_map["avgPrice"] else "0"
            avg = float(avg_raw) if avg_raw else 0
            name = row[col_map["name"]].strip() if "name" in col_map and len(row) > col_map["name"] else sym
            parsed.append({"symbol": sym, "name": name, "market": market, "quantity": qty, "avgPrice": avg})
        except Exception:
            continue

    if not parsed:
        return {"status": "ERROR", "error": "유효한 종목 데이터를 파싱하지 못했습니다. 형식을 확인해 주세요."}

    cols = ["symbol", "name", "market", "quantity", "avgPrice", "stopPrice", "targetPrice"]
    path = _REPO / f"holdings_{market}.csv"

    existing: dict[str, dict] = {}
    if mode == "merge":
        for row in _read_csv_safe(path):
            s = str(row.get("symbol", "")).strip()
            if s:
                existing[s] = row

    added, updated = 0, 0
    for item in parsed:
        sym = item["symbol"]
        if sym in existing:
            existing[sym]["quantity"] = str(item["quantity"])
            existing[sym]["avgPrice"] = str(item["avgPrice"])
            if item["name"] and item["name"] != sym:
                existing[sym]["name"] = item["name"]
            updated += 1
        else:
            existing[sym] = {
                "symbol": sym, "name": item["name"], "market": market,
                "quantity": str(item["quantity"]), "avgPrice": str(item["avgPrice"]),
                "stopPrice": "", "targetPrice": "",
            }
            added += 1

    norm_rows = list(existing.values())
    _write_csv_safe_v2(path, norm_rows, cols)
    data_copy = _REPO / "data" / f"holdings_{market}.csv"
    if data_copy.exists():
        _write_csv_safe_v2(data_copy, norm_rows, cols)

    return {"status": "OK", "market": market, "mode": mode, "added": added, "updated": updated, "total": len(norm_rows), "parsed": len(parsed)}


# ── 2. watchlist-edit ─────────────────────────────────────────────────

@app.get("/api/watchlist-edit")
def api_watchlist_edit(market: str = Query("all")) -> dict:
    markets = ["kr", "us"] if market == "all" else [market]
    items: list[dict] = []
    for mk in markets:
        path = _REPO / f"watchlist_{mk}.csv"
        for row in _read_csv_safe(path):
            sym = str(row.get("symbol", "")).strip()
            if not sym:
                continue
            items.append({
                "market": mk,
                "symbol": sym,
                "name": str(row.get("name", sym)).strip(),
                "memo": str(row.get("memo", "")).strip(),
                "group": str(row.get("group", row.get("memo", ""))).strip(),
                "targetReason": str(row.get("targetReason", "")).strip(),
                "finalScore": _safe_float_v2(row.get("finalScore")),
                "mode": str(row.get("mode", "")).strip(),
                "horizon": str(row.get("horizon", "")).strip(),
            })
    return {"status": "OK", "count": len(items), "items": items}


@app.post("/api/watchlist-edit/save")
def api_watchlist_edit_save(payload: dict = Body(...)) -> dict:
    items = payload.get("items", [])
    if not isinstance(items, list):
        return {"status": "ERROR", "error": "items must be a list"}
    by_market: dict[str, list] = {"kr": [], "us": []}
    for item in items:
        mk = "us" if str(item.get("market", "kr")).lower() == "us" else "kr"
        by_market[mk].append(item)
    cols = ["market", "symbol", "name", "memo", "targetReason", "autoWatchCategory",
            "autoWatchScore", "finalScore", "expectedValue", "mode", "horizon",
            "decisionBucket", "timingLabel", "candidateTypeLabel", "updated_at", "group"]
    for mk, rows in by_market.items():
        path = _REPO / f"watchlist_{mk}.csv"
        existing = {str(r.get("symbol", "")).strip(): r for r in _read_csv_safe(path)}
        norm_rows = []
        for r in rows:
            sym = _normalize_sym(r.get("symbol", ""), mk)
            if not sym:
                continue
            base = existing.get(sym, {})
            norm_rows.append({**base, **{
                "market": mk,
                "symbol": sym,
                "name": str(r.get("name", base.get("name", sym))).strip(),
                "memo": str(r.get("memo", base.get("memo", ""))).strip(),
                "group": str(r.get("group", base.get("group", ""))).strip(),
                "updated_at": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
            }})
        _write_csv_safe_v2(path, norm_rows, cols)
    return {"status": "OK", "saved": len(items)}


# ── 3. predictions/table ──────────────────────────────────────────────

@app.get("/api/predictions/table")
def api_predictions_table(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    strategy: str = Query(""),
    term: str = Query(""),
    limit: int = Query(300),
) -> dict:
    # strategy/term 파라미터 폴백 처리
    eff_mode = strategy or mode
    eff_horizon = term or horizon
    try:
        rec = final_engine.final_recommendations(_market(market), eff_mode, eff_horizon)
        items = rec.get("items", [])
        return {"status": "OK", "count": len(items[:limit]), "items": items[:limit], "market": market}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0}


# ── 4. virtual/ledger ─────────────────────────────────────────────────

@app.get("/api/virtual/ledger")
def api_virtual_ledger(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(300),
) -> dict:
    try:
        result = operation_history.virtual_operation_history(
            market=None if market == "all" else _market(market),
            mode=None,
            limit=limit,
        )
        return _ensure_status(result)
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0}


# ── 5. virtual/validation ─────────────────────────────────────────────
# reports/virtual_validation_results.csv 를 소스로 사용
# (virtual_operation_history.csv 에는 result/returnPct 필드가 없어 항상 빈 배열 반환됐음)

@app.get("/api/virtual/validation")
def api_virtual_validation(
    market: str = Query("kr"),
    mode: str = Query(""),
    horizon: str = Query(""),
    limit: int = Query(300),
) -> dict:
    import csv as _vv_csv
    from pathlib import Path as _VVPath

    def _read_vv_csv(path: "_VVPath") -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _vv_csv.DictReader(f)]
            except Exception:
                continue
        return []

    try:
        reports_dir = _VVPath(__file__).resolve().parents[3] / "reports"
        rows = _read_vv_csv(reports_dir / "virtual_validation_results.csv")

        # 깨진 행 제거: symbol 비어있거나 market 이 정상 값이 아닌 행
        def _valid_row(r: dict) -> bool:
            sym = str(r.get("symbol", "")).strip()
            mkt = str(r.get("market", "")).strip().lower()
            return bool(sym) and mkt in ("kr", "us")

        rows = [r for r in rows if _valid_row(r)]

        mk = _market(market)
        if market not in ("all", ""):
            rows = [r for r in rows if str(r.get("market", "")).lower() == mk]

        # mode/horizon 는 선택 필터 (비어있으면 전체)
        if mode and mode not in ("all", ""):
            rows = [r for r in rows if str(r.get("mode", "")).lower() == mode.lower()]
        if horizon and horizon not in ("all", ""):
            rows = [r for r in rows if str(r.get("horizon", "")).lower() == horizon.lower()]

        pending   = [r for r in rows if str(r.get("status", r.get("result", ""))).upper() in ("PENDING", "DATA_PENDING", "")]
        validated = [r for r in rows if str(r.get("status", r.get("result", ""))).upper() not in ("PENDING", "DATA_PENDING", "")]

        return {
            "status": "OK",
            "count": len(validated),
            "items": rows[:limit],
            "totalCount": len(rows),
            "pendingCount": len(pending),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": [], "count": 0, "pendingCount": 0}


# ── 6. validation/dashboard ───────────────────────────────────────────

@app.get("/api/validation/dashboard")
def api_validation_dashboard(market: str = Query("kr")) -> dict:
    import csv as _vd_csv
    from pathlib import Path as _VDPath

    def _read_vd_csv(path: _VDPath) -> list[dict]:
        if not path.exists():
            return []
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open("r", encoding=enc, newline="") as f:
                    return [dict(row) for row in _vd_csv.DictReader(f)]
            except Exception:
                continue
        return []

    def _vd_pct(v) -> float | None:
        try:
            return float(str(v or "").replace(",", "").replace("%", "").replace("+", "").strip())
        except Exception:
            return None

    try:
        mk = _market(market)
        reports_dir = _VDPath(__file__).resolve().parents[3] / "reports"

        modes = ["conservative", "balanced", "aggressive"]
        horizons = ["short", "swing", "mid"]

        stats: dict = {}
        total_completed = 0
        total_pending = 0
        all_win_rates: list[float] = []

        for mode in modes:
            for horizon in horizons:
                key = f"{mode}_{horizon}"
                files = sorted(
                    reports_dir.glob(f"mone_v36_final_trade_validation_{mk}_{mode}_{horizon}_*.csv"),
                    key=lambda p: p.name, reverse=True,
                )
                if not files:
                    fallback = reports_dir / f"mone_v36_final_trade_validation_{mk}_{mode}_{horizon}.csv"
                    files = [fallback] if fallback.exists() else []
                rows = _read_vd_csv(files[0]) if files else []
                executed = [r for r in rows if str(r.get("executed", "")).lower() in {"true", "1", "yes", "체결"}]
                pending_count = max(0, len(rows) - len(executed))
                returns = [_vd_pct(r.get("returnPct")) for r in executed]
                returns = [r for r in returns if r is not None]
                wins = sum(1 for r in returns if r > 0)
                win_rate = round(wins / len(returns) * 100, 1) if returns else None
                avg_return = round(sum(returns) / len(returns), 2) if returns else None
                stats[key] = {
                    "completed": len(executed),
                    "pending": pending_count,
                    "pendingCount": pending_count,
                    "wins": wins,
                    "winRate": win_rate,
                    "avgReturn": avg_return,
                }
                total_completed += len(executed)
                total_pending += pending_count
                if win_rate is not None:
                    all_win_rates.append(win_rate)

        overall_win_rate = round(sum(all_win_rates) / len(all_win_rates), 1) if all_win_rates else None

        ledger_path = reports_dir / "virtual_prediction_ledger.csv"
        lifecycle: list[dict] = []
        for r in _read_vd_csv(ledger_path)[:100]:
            if market != "all" and r.get("market", "").lower() != mk:
                continue
            lifecycle.append({
                "predictionId": r.get("predictionId", ""),
                "symbol": r.get("symbol", ""),
                "name": r.get("name", ""),
                "market": r.get("market", ""),
                "mode": r.get("mode", ""),
                "horizon": r.get("horizon", ""),
                "createdAt": r.get("createdAt", ""),
                "status": r.get("status", "PENDING"),
                "returnPct": _vd_pct(r.get("returnPct")),
            })

        return {
            "status": "OK",
            "summary": {
                "overallWinRate": overall_win_rate,
                "totalCompleted": total_completed,
                "totalPending": total_pending,
            },
            "stats": stats,
            "lifecycle": lifecycle,
            "market": market,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "summary": None, "stats": {}, "lifecycle": []}


# ── 7. risk/sector-exposure ───────────────────────────────────────────

@app.get("/api/risk/sector-exposure")
def api_risk_sector_exposure(market: str = Query("kr")) -> dict:
    try:
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(_market(market) if market != "all" else "all", 200)
        items = hp.get("items", [])
        # 기업분석에서 섹터 가져오기
        ca = data.company_analysis(_market(market) if market != "all" else "kr")
        sector_map = {str(r.get("symbol", "")).strip(): str(r.get("sector", "기타")) for r in ca.get("items", [])}
        by_sector: dict[str, dict] = {}
        total_val = 0.0
        for h in items:
            sym = str(h.get("symbol", "")).strip()
            val = _safe_float_v2(h.get("valuation", 0) or h.get("marketValue", 0))
            stop = _safe_float_v2(h.get("stop", 0) or h.get("stopPrice", 0))
            current = _safe_float_v2(h.get("currentPrice", 0))
            sector = sector_map.get(sym, "기타")
            total_val += val
            if sector not in by_sector:
                by_sector[sector] = {"sector": sector, "value": 0.0, "symbols": [], "maxLoss": 0.0}
            by_sector[sector]["value"] += val
            by_sector[sector]["symbols"].append(sym)
            if stop > 0 and current > 0:
                by_sector[sector]["maxLoss"] += (current - stop) * _safe_float_v2(h.get("quantity", 0))
        sectors = []
        for s in sorted(by_sector.values(), key=lambda x: x["value"], reverse=True):
            pct = (s["value"] / total_val * 100) if total_val > 0 else 0
            sectors.append({**s, "pct": round(pct, 1)})
        top1 = sectors[0]["pct"] if sectors else 0
        total_loss = sum(s["maxLoss"] for s in by_sector.values())
        total_loss_pct = (total_loss / total_val * 100) if total_val > 0 else 0
        return {
            "status": "OK",
            "sectors": sectors,
            "concentration": {"top1Pct": round(top1, 1), "warning": top1 > 40},
            "maxLossSimulation": {"totalLoss": round(total_loss), "totalLossPct": round(total_loss_pct, 1)},
            "market": market,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "sectors": []}


# ── 8. risk/benchmark ────────────────────────────────────────────────

@app.get("/api/risk/benchmark")
def api_risk_benchmark(market: str = Query("kr")) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(mk, 200)
        items = hp.get("items", [])
        # 벤치마크: KOSPI (kr) / SPY (us)
        bench_sym = "KOSPI" if mk == "kr" else "SPY"
        bench_prefix = "kr" if mk == "kr" else "us"
        bench_path = _OHLCV_DIR / f"{bench_prefix}_{bench_sym}_daily.csv"
        bench_rows = _read_csv_safe(bench_path)[-30:]
        bench_latest = _safe_float_v2(bench_rows[-1].get("close", 0) if bench_rows else 0)
        bench_base = _safe_float_v2(bench_rows[0].get("close", 0) if bench_rows else 0)
        bench_return = ((bench_latest - bench_base) / bench_base * 100) if bench_base > 0 else 0.0
        result_items = []
        total_port_val = 0.0
        total_port_cost = 0.0
        for h in items:
            sym = str(h.get("symbol", "")).strip()
            name = str(h.get("name", sym)).strip()
            qty = _safe_float_v2(h.get("quantity", 0))
            avg = _safe_float_v2(h.get("avgPrice", 0))
            current = _safe_float_v2(h.get("currentPrice", 0))
            if qty <= 0 or avg <= 0:
                continue
            val = qty * current if current > 0 else qty * avg
            cost = qty * avg
            port_ret = ((current - avg) / avg * 100) if avg > 0 and current > 0 else 0.0
            alpha = port_ret - bench_return
            total_port_val += val
            total_port_cost += cost
            result_items.append({
                "symbol": sym, "name": name,
                "portfolioReturn": round(port_ret, 1),
                "benchmarkReturn": round(bench_return, 1),
                "alpha": round(alpha, 1),
            })
        total_port_return = ((total_port_val - total_port_cost) / total_port_cost * 100) if total_port_cost > 0 else 0.0
        return {
            "status": "OK" if result_items else "NO_DATA",
            "benchmark": bench_sym,
            "benchmarkReturn": round(bench_return, 1),
            "totalPortfolioReturn": round(total_port_return, 1),
            "benchmarkLatestDate": bench_rows[-1].get("date", "") if bench_rows else "",
            "items": result_items,
            "count": len(result_items),
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 9. risk/correlation ───────────────────────────────────────────────

@app.get("/api/risk/correlation")
def api_risk_correlation(market: str = Query("kr"), days: int = Query(60)) -> dict:
    try:
        result = advanced.correlation(_market(market) if market != "all" else "kr")
        return _ensure_status(result)
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matrix": []}


# ── 10. risk/near-alerts ──────────────────────────────────────────────

@app.get("/api/risk/near-alerts")
def api_risk_near_alerts(
    market: str = Query("all"),
    thresholdPct: float = Query(1.0),
    limit: int = Query(5),
) -> dict:
    try:
        from app.engine.mone_v77_holdings_risk import holdings_payload
        markets = ["kr", "us"] if market == "all" else [_market(market)]
        alerts = []
        for mk in markets:
            hp = holdings_payload(mk, 100)
            for h in hp.get("items", []):
                current = _safe_float_v2(h.get("currentPrice", 0))
                stop = _safe_float_v2(h.get("stop", 0) or h.get("stopPrice", 0))
                target = _safe_float_v2(h.get("target", 0) or h.get("targetPrice", 0))
                sym = str(h.get("symbol", "")).strip()
                name = str(h.get("name", sym)).strip()
                if current > 0 and stop > 0:
                    gap_pct = (current - stop) / current * 100
                    if 0 < gap_pct <= thresholdPct * 5:
                        alerts.append({
                            "type": "STOP", "symbol": sym, "name": name, "market": mk,
                            "currentPrice": current, "stopPrice": stop,
                            "gapPct": round(gap_pct, 2),
                            "message": f"손절가 {gap_pct:.1f}% 이내",
                        })
                if current > 0 and target > 0 and current < target:
                    gap_pct = (target - current) / current * 100
                    if 0 < gap_pct <= thresholdPct * 5:
                        alerts.append({
                            "type": "TARGET", "symbol": sym, "name": name, "market": mk,
                            "currentPrice": current, "targetPrice": target,
                            "gapPct": round(gap_pct, 2),
                            "message": f"목표가 {gap_pct:.1f}% 근접",
                        })
        alerts.sort(key=lambda x: x["gapPct"])
        return {"status": "OK" if alerts else "NO_DATA", "count": len(alerts[:limit]), "items": alerts[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 11. chart/index/{symbol} ──────────────────────────────────────────

@app.get("/api/chart/index/{index_symbol}")
def api_chart_index(
    index_symbol: str,
    market: str = Query("kr"),
    limit: int = Query(520),
) -> dict:
    try:
        mk = "kr" if str(market).lower() == "kr" else "us"
        sym = index_symbol.upper()
        path = _OHLCV_DIR / f"{mk}_{sym}_daily.csv"
        if not path.exists():
            # fallback: kr=KOSPI, us=SPY
            fallback = "KOSPI" if mk == "kr" else "SPY"
            path = _OHLCV_DIR / f"{mk}_{fallback}_daily.csv"
        rows = _read_csv_safe(path)
        items = []
        for r in rows[-limit:]:
            date = str(r.get("date") or r.get("Date") or "").strip()
            close = _safe_float_v2(r.get("close") or r.get("Close") or 0)
            if date and close > 0:
                items.append({"date": date, "close": close,
                               "open": _safe_float_v2(r.get("open") or close),
                               "high": _safe_float_v2(r.get("high") or close),
                               "low": _safe_float_v2(r.get("low") or close)})
        return {"status": "OK" if items else "NO_DATA", "count": len(items), "items": items, "symbol": sym}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 12. portfolio/nav ─────────────────────────────────────────────────

@app.get("/api/portfolio/nav")
def api_portfolio_nav(market: str = Query("kr"), days: int = Query(180)) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        from app.engine.mone_v77_holdings_risk import holdings_payload
        hp = holdings_payload(mk, 100)
        holdings = hp.get("items", [])
        if not holdings:
            return {"status": "NO_DATA", "items": [], "count": 0}
        # 각 보유종목의 OHLCV 읽어서 NAV 시계열 계산
        prefix = "kr" if mk == "kr" else "us"
        date_nav: dict[str, float] = {}
        date_cost: dict[str, float] = {}
        for h in holdings:
            sym = str(h.get("symbol", "")).strip()
            qty = _safe_float_v2(h.get("quantity", 0))
            avg = _safe_float_v2(h.get("avgPrice", 0))
            if qty <= 0 or avg <= 0:
                continue
            cost = qty * avg
            ohlcv_path = _OHLCV_DIR / f"{prefix}_{sym}_daily.csv"
            rows = _read_csv_safe(ohlcv_path)[-days:]
            for r in rows:
                date = str(r.get("date") or r.get("Date") or "").strip()
                close = _safe_float_v2(r.get("close") or r.get("Close") or 0)
                if date and close > 0:
                    date_nav[date] = date_nav.get(date, 0) + qty * close
                    date_cost[date] = date_cost.get(date, 0) + cost
        if not date_nav:
            return {"status": "NO_DATA", "items": [], "count": 0}
        first_nav = None
        items = []
        for date in sorted(date_nav.keys()):
            nav = date_nav[date]
            cost = date_cost.get(date, nav)
            if first_nav is None:
                first_nav = cost
            cum_return = ((nav - first_nav) / first_nav * 100) if first_nav > 0 else 0.0
            items.append({
                "date": date,
                "nav": round(nav),
                "cumulative_return": round(cum_return, 2),
                "is_backfill": "false",
            })
        return {"status": "OK", "count": len(items), "items": items}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 13. home/summary ──────────────────────────────────────────────────

@app.get("/api/home/summary")
def api_home_summary(market: str = Query("kr"), limit: int = Query(12)) -> dict:
    """HomePage 3×3 매트릭스용 통합 응답 — 9개 전략 셀 + 보유종목 + 마켓 레짐"""
    try:
        mk = _market(market) if market != "all" else "kr"
        MODES = ("conservative", "balanced", "aggressive")
        HORIZONS = ("short", "swing", "mid")

        # 마켓 레짐 (KOSPI/SPY 20일선 기반 — priority 9)
        regime = "UNKNOWN"
        regime_detail: dict = {}
        try:
            bench_sym = "KOSPI" if mk == "kr" else "SPY"
            bench_rows = _read_csv_safe(_OHLCV_DIR / f"{mk}_{bench_sym}_daily.csv")[-60:]
            closes = [_safe_float_v2(r.get("close") or r.get("Close") or 0) for r in bench_rows]
            closes = [c for c in closes if c > 0]
            if len(closes) >= 20:
                ma20 = sum(closes[-20:]) / 20
                ma60 = sum(closes[-60:]) / len(closes[-60:]) if len(closes) >= 60 else ma20
                current = closes[-1]
                if current > ma20 * 1.02:
                    regime = "BULL"
                elif current < ma20 * 0.98:
                    regime = "BEAR"
                else:
                    regime = "SIDEWAYS"
                regime_detail = {
                    "regime": regime,
                    "current": round(current, 2),
                    "ma20": round(ma20, 2),
                    "ma60": round(ma60, 2),
                    "distanceMa20Pct": round((current - ma20) / ma20 * 100, 2),
                    "benchmark": bench_sym,
                    "label": {"BULL": "강세장 (MA20 상회)", "BEAR": "약세장 (MA20 하회)", "SIDEWAYS": "중립"}[regime],
                    "description": {
                        "BULL": f"{bench_sym} 현재가 {current:,.0f} > MA20 {ma20:,.0f} (+{abs((current-ma20)/ma20*100):.1f}%) — 공격적 진입 허용",
                        "BEAR": f"{bench_sym} 현재가 {current:,.0f} < MA20 {ma20:,.0f} (-{abs((current-ma20)/ma20*100):.1f}%) — 보수적 접근 권장",
                        "SIDEWAYS": f"{bench_sym} 현재가 {current:,.0f} ≈ MA20 {ma20:,.0f} (±2%) — 중립, 종목별 선별",
                    }[regime],
                }
        except Exception:
            pass

        # 3×3 매트릭스 병렬 수집
        matrix: dict = {}
        for mode in MODES:
            for horizon in HORIZONS:
                cell_key = f"{mode}_{horizon}"
                try:
                    rec = final_engine.final_recommendations(mk, mode, horizon)
                    cell_items = rec.get("items", [])
                    # EV 양수 우선 정렬 (priority 5)
                    pos_ev = [i for i in cell_items if _safe_float_v2(i.get("expectedValue", 0)) > 0]
                    display = (pos_ev if pos_ev else cell_items)[:5]
                    matrix[cell_key] = {
                        "status": "OK" if display else "NO_DATA",
                        "items": display,
                        "count": len(cell_items),
                        "positiveEvCount": len(pos_ev),
                    }
                except Exception as e:
                    matrix[cell_key] = {"status": "ERROR", "error": str(e), "items": [], "count": 0}

        # 보유종목 (holdingsClean 엔드포인트 재사용)
        holdings_payload: dict = {"items": [], "summary": {}}
        try:
            from app.engine.mone_v77_holdings_risk import holdings_payload as _hp
            holdings_payload = _hp(mk, 50)
        except Exception:
            pass

        # 데이터 헬스
        data_health: dict = {}
        try:
            data_health = data.runner_status(mk)
        except Exception:
            pass

        return {
            "status": "OK",
            "market": mk,
            "matrix": matrix,
            "holdings": holdings_payload,
            "marketRegime": regime_detail if regime_detail else {"regime": regime},
            "dataHealth": data_health,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "matrix": {}, "holdings": {"items": []}}


# ── 14. sectors ───────────────────────────────────────────────────────

@app.get("/api/sectors")
def api_sectors(market: str = Query("kr")) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        ca = data.company_analysis(mk)
        sector_map: dict[str, list] = {}
        for r in ca.get("items", []):
            sector = str(r.get("sector", "기타")).strip() or "기타"
            sym = str(r.get("symbol", "")).strip()
            name = str(r.get("name", sym)).strip()
            if sym:
                sector_map.setdefault(sector, []).append({"symbol": sym, "name": name})
        items = [{"sector": s, "count": len(v), "symbols": v} for s, v in sorted(sector_map.items())]
        return {"status": "OK", "count": len(items), "items": items, "market": mk}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 15. watchlist/groups ──────────────────────────────────────────────

@app.get("/api/watchlist/groups")
def api_watchlist_groups(market: str = Query("kr")) -> dict:
    try:
        markets = ["kr", "us"] if market == "all" else [_market(market) if market != "all" else "kr"]
        group_map: dict[str, list] = {}
        for mk in markets:
            path = _REPO / f"watchlist_{mk}.csv"
            for r in _read_csv_safe(path):
                sym = str(r.get("symbol", "")).strip()
                group = str(r.get("group", r.get("memo", "기본"))).strip() or "기본"
                if sym:
                    group_map.setdefault(group, []).append({
                        "market": mk, "symbol": sym,
                        "name": str(r.get("name", sym)).strip(),
                        "group": group,
                        "finalScore": _safe_float_v2(r.get("finalScore", 0)),
                    })
        items = [{"group": g, "count": len(v), "items": v} for g, v in sorted(group_map.items())]
        return {"status": "OK", "count": len(items), "items": items, "groups": list(group_map.keys())}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 16. watchlist/set-group ───────────────────────────────────────────

@app.post("/api/watchlist/set-group")
def api_watchlist_set_group(payload: dict = Body(...)) -> dict:
    try:
        sym = str(payload.get("symbol", "")).strip()
        group = str(payload.get("group", "기본")).strip() or "기본"
        mk = "us" if str(payload.get("market", "kr")).lower() == "us" else "kr"
        path = _REPO / f"watchlist_{mk}.csv"
        rows = _read_csv_safe(path)
        updated = False
        for r in rows:
            if str(r.get("symbol", "")).strip() == sym:
                r["group"] = group
                updated = True
        if not updated:
            return {"status": "NOT_FOUND", "error": f"{sym} not in watchlist_{mk}"}
        # 기존 컬럼 유지 + group 추가
        existing_cols = []
        if rows:
            existing_cols = list(rows[0].keys())
        if "group" not in existing_cols:
            existing_cols.append("group")
        _write_csv_safe_v2(path, rows, existing_cols)
        return {"status": "OK", "symbol": sym, "group": group, "market": mk}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 17. watchlist/scored ──────────────────────────────────────────────

@app.get("/api/watchlist/scored")
def api_watchlist_scored(
    market: str = Query("kr"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        # 관심종목 심볼 목록
        watch_syms: set[str] = set()
        for wm in (["kr", "us"] if market == "all" else [mk]):
            for r in _read_csv_safe(_REPO / f"watchlist_{wm}.csv"):
                s = str(r.get("symbol", "")).strip()
                if s:
                    watch_syms.add(s)
        # 추천 리스트에서 관심종목만 필터
        rec = final_engine.final_recommendations(mk, mode, horizon)
        items = [i for i in rec.get("items", []) if str(i.get("symbol", "")).strip() in watch_syms]
        if not items:
            items = rec.get("items", [])[:20]
        return {"status": "OK", "count": len(items), "items": items, "watchlistCount": len(watch_syms)}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 18. disclosure-calendar ───────────────────────────────────────────

@app.get("/api/disclosure-calendar")
def api_disclosure_calendar(market: str = Query("kr"), days: int = Query(30)) -> dict:
    try:
        mk = _market(market) if market != "all" else "kr"
        disc = data.disclosure_rows(mk)
        items = disc.get("items", []) if isinstance(disc, dict) else []
        result = []
        for d in items[:50]:
            date_str = str(d.get("date") or d.get("disclosedAt") or d.get("publishedAt") or "").strip()
            result.append({
                "date": date_str,
                "title": str(d.get("title") or d.get("reportName") or "").strip(),
                "symbol": str(d.get("symbol", "")).strip(),
                "name": str(d.get("name") or d.get("company") or "").strip(),
                "type": str(d.get("type") or d.get("category") or "공시").strip(),
            })
        return {"status": "OK" if result else "NO_DATA", "count": len(result), "items": result}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


# ── 19. journal (투자장부) ────────────────────────────────────────────

def _ensure_journal() -> None:
    _JOURNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not _JOURNAL_FILE.exists():
        with _JOURNAL_FILE.open("w", encoding="utf-8-sig", newline="") as f:
            _csv.DictWriter(f, fieldnames=_JOURNAL_COLS).writeheader()


@app.get("/api/journal")
def api_journal_get(market: str = Query("all"), limit: int = Query(200)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        if market != "all":
            rows = [r for r in rows if r.get("market", "").lower() == market.lower()]
        rows = sorted(rows, key=lambda r: r.get("createdAt", ""), reverse=True)
        return {"status": "OK", "count": len(rows[:limit]), "items": rows[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


@app.post("/api/journal/add")
def api_journal_add(payload: dict = Body(...)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        new_row = {
            "id": str(_uuid.uuid4())[:8],
            "date": str(payload.get("date", _dt.now().strftime("%Y-%m-%d"))).strip(),
            "market": str(payload.get("market", "kr")).strip(),
            "symbol": str(payload.get("symbol", "")).strip(),
            "name": str(payload.get("name", "")).strip(),
            "action": str(payload.get("action", "메모")).strip(),
            "price": str(_safe_float_v2(payload.get("price", 0))),
            "qty": str(_safe_float_v2(payload.get("qty", 0))),
            "memo": str(payload.get("memo", "")).strip(),
            "review": str(payload.get("review", "")).strip(),
            "result": str(payload.get("result", "PENDING")).strip(),
            "returnPct": str(_safe_float_v2(payload.get("returnPct", 0))),
            "tags": _json.dumps(payload.get("tags", []), ensure_ascii=False),
            "createdAt": _dt.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        rows.append(new_row)
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "item": new_row}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.patch("/api/journal/{entry_id}")
def api_journal_update(entry_id: str, payload: dict = Body(...)) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        updated = False
        for r in rows:
            if r.get("id") == entry_id:
                for k in ("memo", "review", "result", "returnPct", "tags"):
                    if k in payload:
                        r[k] = _json.dumps(payload[k], ensure_ascii=False) if k == "tags" else str(payload[k])
                updated = True
        if not updated:
            return {"status": "NOT_FOUND", "error": f"id={entry_id} not found"}
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "id": entry_id}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


@app.delete("/api/journal/{entry_id}")
def api_journal_delete(entry_id: str) -> dict:
    try:
        _ensure_journal()
        rows = _read_csv_safe(_JOURNAL_FILE)
        before = len(rows)
        rows = [r for r in rows if r.get("id") != entry_id]
        if len(rows) == before:
            return {"status": "NOT_FOUND", "error": f"id={entry_id} not found"}
        _write_csv_safe_v2(_JOURNAL_FILE, rows, _JOURNAL_COLS)
        return {"status": "OK", "deleted": entry_id}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 20. health/github ─────────────────────────────────────────────────

@app.get("/api/health/github")
def api_health_github() -> dict:
    try:
        from app.engine.auto_sync import get_sync_status
        return _ensure_status(get_sync_status())
    except Exception:
        pass
    try:
        status = data.runner_status("kr")
        return {"status": "OK", "kr": status, "source": "runner_status"}
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 21. data/audit ───────────────────────────────────────────────────

@app.get("/api/data/audit")
def api_data_audit() -> dict:
    try:
        result: dict = {"status": "OK", "files": [], "summary": {}}
        report_files = list(_REPORTS.glob("*.csv")) if _REPORTS.exists() else []
        ohlcv_files = list(_OHLCV_DIR.glob("*.csv")) if _OHLCV_DIR.exists() else []
        holdings_files = [_REPO / f"holdings_{m}.csv" for m in ["kr", "us"]]
        watchlist_files = [_REPO / f"watchlist_{m}.csv" for m in ["kr", "us"]]
        audit_items = []
        for path in report_files[:20] + ohlcv_files[:10] + holdings_files + watchlist_files:
            if path.exists():
                stat = path.stat()
                audit_items.append({
                    "file": path.name,
                    "path": str(path.relative_to(_REPO)) if _REPO in path.parents else path.name,
                    "size": stat.st_size,
                    "mtime": _dt.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "rows": len(_read_csv_safe(path)),
                })
        result["files"] = audit_items
        result["summary"] = {
            "reportFiles": len(report_files),
            "ohlcvFiles": len(ohlcv_files),
            "totalAuditFiles": len(audit_items),
        }
        return result
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "files": []}


# ── 22-A. exchange-rate ───────────────────────────────────────────────
# 1순위: 한국수출입은행 API (KOREAEXIM_API_KEY)
# 2순위: open.er-api.com (무료, 키 불필요)
# 3순위: api.exchangerate-api.com (무료, 키 불필요)

_EXRATE_CACHE: dict = {}
_EXRATE_TTL = 4 * 3600  # 4시간 캐시

def _try_koreaexim(base: str, api_key: str) -> float | None:
    try:
        import requests as _req
        from datetime import date as _date, timedelta as _td
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.koreaexim.go.kr/site/main/index006",
        }
        for delta in range(5):
            search_date = (_date.today() - _td(days=delta)).strftime("%Y%m%d")
            try:
                resp = _req.get(
                    "https://www.koreaexim.go.kr/site/program/financial/exchangeJSON",
                    params={"authkey": api_key, "searchdate": search_date, "data": "AP01"},
                    headers=headers, timeout=8,
                )
                items = resp.json()
                if isinstance(items, list):
                    for item in items:
                        if item.get("cur_unit") == base:
                            rate_str = str(item.get("deal_bas_r", "")).replace(",", "")
                            rate = float(rate_str)
                            if rate > 0:
                                return rate
            except Exception:
                continue
    except Exception:
        pass
    return None

def _try_open_er_api(base: str) -> float | None:
    try:
        import requests as _req
        resp = _req.get(f"https://open.er-api.com/v6/latest/{base}", timeout=8)
        data = resp.json()
        if data.get("result") == "success":
            return float(data["rates"].get("KRW", 0)) or None
    except Exception:
        pass
    return None

def _try_exchangerate_api(base: str) -> float | None:
    try:
        import os as _os, requests as _req
        key = _os.getenv("EXCHANGERATE_API_KEY", "")
        if key:
            # 인증 엔드포인트 (더 정확, 더 높은 한도)
            resp = _req.get(f"https://v6.exchangerate-api.com/v6/{key}/latest/{base}", timeout=8)
            data = resp.json()
            if data.get("result") == "success":
                return float(data["conversion_rates"].get("KRW", 0)) or None
        # 무료 폴백
        resp = _req.get(f"https://api.exchangerate-api.com/v4/latest/{base}", timeout=8)
        data = resp.json()
        return float(data["rates"].get("KRW", 0)) or None
    except Exception:
        pass
    return None

@app.get("/api/exchange-rate")
def api_exchange_rate(base: str = Query("USD"), target: str = Query("KRW")) -> dict:
    import os as _os, time as _time

    cache_key = f"{base}_{target}"
    now_ts = _time.time()
    cached = _EXRATE_CACHE.get(cache_key, {})
    if cached and now_ts - cached.get("ts", 0) < _EXRATE_TTL:
        return {k: v for k, v in cached.items() if k != "ts"}

    api_key = _os.getenv("KOREAEXIM_API_KEY", "")

    # 1순위: 한국수출입은행
    if api_key:
        rate = _try_koreaexim(base, api_key)
        if rate:
            result = {"status": "OK", "rate": rate, "base": base, "target": target,
                      "source": "koreaexim"}
            _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
            return result

    # 2순위: open.er-api.com
    rate = _try_open_er_api(base)
    if rate:
        result = {"status": "OK", "rate": rate, "base": base, "target": target,
                  "source": "open.er-api.com"}
        _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
        return result

    # 3순위: exchangerate-api.com
    rate = _try_exchangerate_api(base)
    if rate:
        result = {"status": "OK", "rate": rate, "base": base, "target": target,
                  "source": "exchangerate-api.com"}
        _EXRATE_CACHE[cache_key] = {**result, "ts": now_ts}
        return result

    msg = "KOREAEXIM_API_KEY 미설정 — .env에 추가하세요" if not api_key else "모든 환율 소스 응답 없음"
    return {"status": "NO_DATA", "rate": None, "base": base, "target": target, "message": msg}


# ── 22. position/size ─────────────────────────────────────────────────

@app.get("/api/position/size")
def api_position_size(
    entry: float = Query(...),
    cash: float = Query(...),
    strategy: str = Query("balanced"),
    market: str = Query("kr"),
) -> dict:
    try:
        # Kelly 기반 포지션 계산
        kelly_map = {"conservative": 0.10, "balanced": 0.15, "aggressive": 0.20}
        kelly_f = kelly_map.get(strategy, 0.15)
        position_value = cash * kelly_f
        shares = int(position_value / entry) if entry > 0 else 0
        actual_value = shares * entry
        return {
            "status": "OK",
            "entry": entry,
            "cash": cash,
            "strategy": strategy,
            "kellyFraction": kelly_f,
            "positionValue": round(actual_value),
            "shares": shares,
            "pctOfCash": round(actual_value / cash * 100, 1) if cash > 0 else 0,
        }
    except Exception as e:
        return {"status": "ERROR", "error": str(e)}


# ── 23. kis/token/status ──────────────────────────────────────────────

@app.get("/api/kis/token/status")
def api_kis_token_status() -> dict:
    kis_key = _os.environ.get("KIS_APP_KEY", "")
    kis_secret = _os.environ.get("KIS_APP_SECRET", "")
    kis_account = _os.environ.get("KIS_ACCOUNT_NO", "")
    configured = bool(kis_key and kis_secret and kis_account)
    return {
        "status": "OK" if configured else "NO_KEY",
        "hasKey": bool(kis_key),
        "hasSecret": bool(kis_secret),
        "hasAccount": bool(kis_account),
        "configured": configured,
        "message": "KIS API 설정 완료" if configured else "KIS_APP_KEY / KIS_APP_SECRET / KIS_ACCOUNT_NO 환경변수 미설정",
    }


# ── 24. EV 필터 추천 (priority 5) ─────────────────────────────────────

@app.get("/api/final/recommendations-ev-filtered")
def api_recommendations_ev_filtered(
    market: str = Query("kr", pattern="^(kr|us|all)$"),
    mode: str = Query("balanced"),
    horizon: str = Query("swing"),
    limit: int = Query(20),
) -> dict:
    """EV(기댓값) 양수인 종목만 반환하는 필터드 추천 엔드포인트"""
    try:
        mk_list = ["kr", "us"] if market == "all" else [_market(market)]
        all_items = []
        for mk in mk_list:
            rec = final_engine.final_recommendations(mk, mode, horizon)
            for item in rec.get("items", []):
                ev = _safe_float_v2(item.get("expectedValue", 0))
                if ev > 0:
                    all_items.append(item)
        all_items.sort(key=lambda x: _safe_float_v2(x.get("expectedValue", 0)), reverse=True)
        return {"status": "OK" if all_items else "NO_DATA", "count": len(all_items[:limit]), "items": all_items[:limit]}
    except Exception as e:
        return {"status": "ERROR", "error": str(e), "items": []}


print("[MONE v10.2] 누락 API 엔드포인트 24종 등록 완료")
def _install_mone_virtual_report_routes_v1():
    from fastapi import Query as _MoneVirtualQuery

    app.router.routes = [
        route for route in app.router.routes
        if getattr(route, "path", "") not in {"/api/virtual/summary", "/api/virtual/trades"}
    ]

    @app.get("/api/virtual/summary")
    def mone_virtual_summary(
        market: str = _MoneVirtualQuery("kr", pattern="^(kr|us|all)$"),
        mode: str = _MoneVirtualQuery("all"),
        horizon: str = _MoneVirtualQuery("all"),
    ) -> dict:
        if str(market).lower() == "all":
            kr = _virtual_summary_from_reports("kr", mode, horizon)
            us = _virtual_summary_from_reports("us", mode, horizon)
            total = int(kr.get("totalRecommendations") or 0) + int(us.get("totalRecommendations") or 0)
            executed = int(kr.get("executedTrades") or 0) + int(us.get("executedTrades") or 0)
            unexecuted = int(kr.get("unexecutedCount") or 0) + int(us.get("unexecutedCount") or 0)
            cumulative = float(kr.get("cumulativeReturnPct") or 0) + float(us.get("cumulativeReturnPct") or 0)
            rate = round((executed / (executed + unexecuted)) * 100, 2) if executed + unexecuted else 0
            return {
                **us,
                "market": "all",
                "status": "OK" if total else "NO_DATA",
                "totalRecommendations": total,
                "latestRecommendations": int(kr.get("latestRecommendations") or 0) + int(us.get("latestRecommendations") or 0),
                "executedTrades": executed,
                "latestExecutedTrades": executed,
                "unexecutedCount": unexecuted,
                "latestUnexecutedCount": unexecuted,
                "executionRate": rate,
                "latestExecutionRate": rate,
                "cumulativeReturnPct": round(cumulative, 3),
                "latestCumulativeReturnPct": round(cumulative, 3),
                "items": (kr.get("items") or []) + (us.get("items") or []),
                "count": int(kr.get("count") or 0) + int(us.get("count") or 0),
                "source": "virtual_validation_results.csv + virtual_prediction_ledger.csv",
            }
        return _virtual_summary_from_reports(_market(market), mode, horizon)

    @app.get("/api/virtual/trades")
    def mone_virtual_trades(
        market: str = _MoneVirtualQuery("kr", pattern="^(kr|us|all)$"),
        mode: str = _MoneVirtualQuery("all"),
        horizon: str = _MoneVirtualQuery("all"),
        limit: int = _MoneVirtualQuery(300, ge=1, le=1000),
    ) -> dict:
        payload = mone_virtual_summary(market, mode, horizon)
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        return {**payload, "items": items[:limit], "count": min(len(items), limit)}


try:
    _install_mone_virtual_report_routes_v1()
except Exception as _mone_virtual_report_error:
    print("[MONE] virtual report route patch failed:", _mone_virtual_report_error)
