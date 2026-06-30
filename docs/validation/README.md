# Validation Notes

`oos_signal_validation_kr.json` and `oos_signal_validation_us.json` are diagnostic reports only.

They compare display-only signal scores with future 3, 5, 10, and 20 trading-day returns, MAE, and MFE using only data available at each cutoff. These files are not an approval to change `_final_score`, recommendation ranking, filters, or EV calculations.

The diagnostic fields `setupScore`, `overextensionRisk`, and `momentumContinuationScore` should be shown as setup, chase-risk, and trend-continuation diagnostics, not as buy probability or confirmed AI recommendations.

`trade_failure_analytics_kr.json` and `trade_failure_analytics_us.json` are static snapshots of virtual trade journal failure reasons by market, mode, horizon, holding-period bucket, setup bucket, and regime. They summarize why paper-trade evaluations failed or stayed data-limited, and they are diagnostic-only inputs for human review. They do not change `_final_score`, recommendation ranking, filters, EV calculations, or entry/stop/target formulas.

`trade_improvement_priorities_kr.json` and `trade_improvement_priorities_us.json` convert the failure-reason diagnostics into a ranked list of what to validate first. Every item keeps `shouldModifyTradingLogicNow` false: the report suggests review priorities, not automatic recommendation-logic changes.

Failure-reason labels are display-only translations for diagnostics and do not change recommendation logic. Improvement-priority evidence separates overall share (`overallRatio`, count divided by total trades) from condition rate (`ratio`/`conditionRate` inside the priority rule), so these percentages should not be interpreted as the same denominator.

`trade_unknown_failure_reason_diagnostics.json` records the diagnostic-only UNKNOWN reclassification snapshot. Legacy rows such as "Entry window still open" and "Evaluation window still open" are mapped to evaluation-pending reason codes for analytics, without changing recommendation scoring, ranking, filtering, EV, or entry/target/stop formulas.

`evaluated_only_failure_analytics.json` separates all-trade failure analytics from evaluated-only analytics. Pending reasons such as `INSUFFICIENT_HOLDING_PERIOD`, `PENDING_EVALUATION`, and `NO_FUTURE_BARS_YET` are evaluation coverage states, not failed outcomes; logic changes should be considered only after checking evaluated-only diagnostics, and this file still does not modify recommendation logic.

`stop_loss_failure_diagnostics.json` and `stop_loss_failure_patch_report.json` diagnose STOP_TOO_TIGHT / STOP_BEFORE_TARGET outcomes using evaluated-only journal rows. The current report is diagnostic-only: it records the observed stop-failure pattern and why no action downgrade, score change, ranking change, EV change, candidate exclusion, or entry/target/stop formula change was applied.

`entry_timing_safety_diagnostics.json` and `entry_timing_safety_replay_report.json` add the v1 entry-timing safety guard snapshot. The guard computes `entryTimingRiskScore` and `adjustedAction` preview fields for review, but this report keeps live recommendation logic unchanged unless future out-of-sample validation explicitly justifies activation.

`entry_timing_guard_activation_validation.json` is the out-of-sample validation requested for v1 activation. It found that the naive before/after replay (stop-failure rate, return, win rate all improve when HIGH-risk trades are excluded) cannot be trusted as evidence for live activation: every HIGH-risk classification depends on at least one outcome-only field (`maxAdverseExcursion`/`maxFavorableExcursion`/`failureReason`) that does not exist at the moment a recommendation is issued, and the recommendation-time-only criteria (`overextensionRisk`, `momentumContinuationScore`) are not even populated in the current evaluation data. The guard stays `diagnostic_only`/`appliedGuard: false`. Activation requires first persisting recommendation-time features into the journal evaluation rows and building a strictly prospective risk score, then re-validating.

`entry_timing_prospective_score_attempt.json` is that follow-up: a genuinely lookahead-safe score built from already-recorded entry-time fields (`rsi_at_entry`, `distance_to_ma20_at_entry`, `momentum5_at_entry`, `volume_ratio_at_entry`), validated with time-based train/test splits instead of in-sample replay. The pattern found on the train split reversed sign on three different held-out test splits, so it was not activated either. No production code was added for it. The report also flags a likely regime-level performance decline in the most recent months that is unrelated to entry timing and should be investigated separately.
