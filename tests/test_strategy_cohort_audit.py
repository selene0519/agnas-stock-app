from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_strategy_cohorts",
    ROOT / "scripts" / "audit_strategy_cohorts.py",
)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_build_deduplicates_economic_decisions_and_separates_fingerprints(tmp_path: Path, monkeypatch) -> None:
    journal = tmp_path / "journal.csv"
    evaluations = tmp_path / "evaluations.csv"
    journal.write_text(
        "journal_id,source_type,journal_session,as_of_date,market,symbol,final_rank_score,strategy_fingerprint\n"
        "j1,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE,2026-01-01,kr,005930,70,fp-a\n"
        "j2,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE,2026-01-01,kr,005930,90,fp-a\n"
        "j3,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE,2026-01-02,kr,000660,80,fp-b\n",
        encoding="utf-8",
    )
    evaluations.write_text(
        "journal_id,status,net_pnl_pct,evaluated_at\n"
        "j1,EVALUATED,-2,2026-01-05\n"
        "j2,EVALUATED,3,2026-01-05\n"
        "j3,EVALUATED,1,2026-01-06\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "JOURNAL", journal)
    monkeypatch.setattr(audit, "EVALUATIONS", evaluations)

    report = audit.build(min_decisions=1, min_signal_dates=1)

    assert report["summary"]["evaluatedRows"] == 3
    assert report["summary"]["independentDecisions"] == 2
    assert report["summary"]["duplicateRowsRemoved"] == 1
    assert {item["strategyFingerprint"] for item in report["cohorts"]} == {"fp-a", "fp-b"}
    assert all(item["promotionEvidenceReady"] for item in report["cohorts"])


def test_legacy_negative_cohort_is_never_promotion_ready(tmp_path: Path, monkeypatch) -> None:
    journal = tmp_path / "journal.csv"
    evaluations = tmp_path / "evaluations.csv"
    journal.write_text(
        "journal_id,source_type,journal_session,as_of_date,market,symbol,final_rank_score\n"
        "j1,FORWARD_PAPER_TRADE,AFTER_CLOSE_TRADE,2026-01-01,kr,005930,70\n",
        encoding="utf-8",
    )
    evaluations.write_text(
        "journal_id,status,net_pnl_pct,evaluated_at\n"
        "j1,EVALUATED,-2,2026-01-05\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(audit, "JOURNAL", journal)
    monkeypatch.setattr(audit, "EVALUATIONS", evaluations)

    cohort = audit.build(min_decisions=1, min_signal_dates=1)["cohorts"][0]

    assert cohort["promotionEvidenceReady"] is False
    assert "LEGACY_IDENTITY" in cohort["blockingReasons"]
    assert "NON_POSITIVE_AFTER_COST_EXPECTANCY" in cohort["blockingReasons"]
