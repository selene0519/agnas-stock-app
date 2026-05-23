# v43 update notes

## Fixed/updated

1. News/API
   - Added GNews collection through `GNEWS_API_KEY` or `NEWS_API_KEY`.
   - Added `reports/gnews_latest_kr.csv`, `reports/gnews_latest_us.csv`, `reports/gnews_summary.json`.
   - GitHub Actions now passes `GNEWS_API_KEY`, `DART_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` to the runner.

2. Budget / holdings sell table
   - Sell quantity table now attempts to fill current price from saved quote reports and Yahoo Finance fallback.
   - Current price, return %, and expected recovery amount are filled when price data is available.

3. Chart / flow UI
   - One chart screen only in General Mode.
   - Korean symbols are shown as `종목명 (종목코드)` when names are known.
   - Direct search was restored inside the chart screen.
   - Flow/quote/orderbook summary is rendered as beginner-friendly cards.

4. Quant backtesting
   - The app now calculates a basic MA10/MA20 strategy test by itself and records it in `reports/v43_strategy_backtest_summary.csv`.
   - This is a first automatic benchmark. Later versions can use real historical app signals for error correction.

## Still requires user/API setup

- Full LLM news narrative requires `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`.
- Full Korean fundamentals require valid DART/Finnhub data availability.
- GitHub data updates still need local sync/pull before the PC Streamlit app sees latest reports.
