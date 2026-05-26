from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from app.services import data_loader as data
from app.services import quotes


app = FastAPI(title="MONE Web API", version="0.1.3")

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


@app.get("/api/status/files")
def api_status_files() -> dict:
    return data.status_files()


@app.get("/api/status/env")
def api_status_env() -> dict:
    return data.status_env()


@app.get("/api/market/summary")
def api_market_summary(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.market_summary(_market(market))


@app.get("/api/symbols")
def api_symbols(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.symbols(_market(market))


@app.get("/api/symbols/{symbol}")
def api_symbol_detail(symbol: str, market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.symbol_detail(symbol, _market(market))


@app.get("/api/candidates")
def api_candidates(
    market: str = Query("kr", pattern="^(kr|us)$"),
    type: str = Query("action", pattern="^(action|pullback|flow|risk)$"),
) -> dict:
    return data.candidate_rows(_market(market), type)


@app.get("/api/positions")
def api_positions(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.positions(_market(market))


@app.get("/api/news")
def api_news(market: str = Query("kr", pattern="^(kr|us)$")) -> dict:
    return data.news_rows(_market(market))


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


@app.get("/api/history/predictions")
def api_prediction_history() -> dict:
    return data.prediction_history()


@app.get("/api/history/outcomes")
def api_outcome_history() -> dict:
    return data.outcome_history()


@app.post("/api/quotes/refresh")
def api_quotes_refresh(
    market: str = Query("all", pattern="^(kr|us|all)$"),
    symbols: str | None = Query(None),
    max_symbols: int = Query(80, ge=1, le=150),
) -> dict:
    return quotes.refresh_quotes(market=market, symbols=symbols, max_symbols=max_symbols)
