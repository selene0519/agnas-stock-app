# Validation Notes

`oos_signal_validation_kr.json` and `oos_signal_validation_us.json` are diagnostic reports only.

They compare display-only signal scores with future 3, 5, 10, and 20 trading-day returns, MAE, and MFE using only data available at each cutoff. These files are not an approval to change `_final_score`, recommendation ranking, filters, or EV calculations.

The diagnostic fields `setupScore`, `overextensionRisk`, and `momentumContinuationScore` should be shown as setup, chase-risk, and trend-continuation diagnostics, not as buy probability or confirmed AI recommendations.

`trade_failure_analytics_kr.json` and `trade_failure_analytics_us.json` are static snapshots of virtual trade journal failure reasons by market, mode, horizon, holding-period bucket, setup bucket, and regime. They summarize why paper-trade evaluations failed or stayed data-limited, and they are diagnostic-only inputs for human review. They do not change `_final_score`, recommendation ranking, filters, EV calculations, or entry/stop/target formulas.

`trade_improvement_priorities_kr.json` and `trade_improvement_priorities_us.json` convert the failure-reason diagnostics into a ranked list of what to validate first. Every item keeps `shouldModifyTradingLogicNow` false: the report suggests review priorities, not automatic recommendation-logic changes.
