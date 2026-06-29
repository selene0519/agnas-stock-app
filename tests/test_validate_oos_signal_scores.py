from __future__ import annotations

from scripts import validate_oos_signal_scores as oos


def test_oos_summary_includes_required_horizon_tercile_metrics() -> None:
    rows = []
    for idx in range(12):
        row = {
            "setup_score": float(idx),
            "overextension_risk": float(12 - idx),
            "momentum_continuation_score": float(idx * 2),
            "final_score_balanced_swing": float(idx + 50),
            "upside_score": float(idx),
            "risk_score": float(idx),
            "momentum_score": float(idx),
            "entry_score": float(idx),
            "rr_score": float(idx),
            "quality_score": float(idx),
            "news_risk_penalty": float(idx),
        }
        for horizon in oos.HORIZONS:
            row[f"return_{horizon}d"] = float(idx - 5)
            row[f"mae_{horizon}d"] = float(-idx)
            row[f"mfe_{horizon}d"] = float(idx + 1)
        rows.append(row)

    summary = oos.summarize(rows)
    horizon = summary["features"]["setup_score"]["3d"]

    assert horizon["sample_count"] == 12
    assert horizon["spearman"] == 1.0
    assert set(horizon["terciles"]) == {"low", "mid", "high"}
    assert horizon["terciles"]["low"]["sample_count"] == 4
    assert horizon["terciles"]["mid"]["median_return_pct"] == 0.5
    assert horizon["terciles"]["high"]["avg_mae_pct"] == -9.5
    assert horizon["terciles"]["high"]["avg_mfe_pct"] == 10.5
