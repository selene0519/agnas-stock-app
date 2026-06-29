# Validation Notes

`oos_signal_validation_kr.json` and `oos_signal_validation_us.json` are diagnostic reports only.

They compare display-only signal scores with future 3, 5, 10, and 20 trading-day returns, MAE, and MFE using only data available at each cutoff. These files are not an approval to change `_final_score`, recommendation ranking, filters, or EV calculations.

The diagnostic fields `setupScore`, `overextensionRisk`, and `momentumContinuationScore` should be shown as setup, chase-risk, and trend-continuation diagnostics, not as buy probability or confirmed AI recommendations.
