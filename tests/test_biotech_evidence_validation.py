import sys
from datetime import date
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import biotech_evidence_validation as validation


def _snapshot(status: str, *, captured: str, as_of: str, has_results: bool = False) -> dict:
    return {
        "snapshotId": f"snapshot-{as_of}-{status}",
        "capturedAt": captured,
        "asOfDate": as_of,
        "market": "us",
        "symbol": "ACME",
        "company": "Acme",
        "studies": {
            "NCT1": {
                "overallStatus": status,
                "phases": ["PHASE3"],
                "completionDate": "2027-01-01",
                "hasResults": has_results,
            }
        },
        "pmids": [],
    }


def test_baseline_capture_is_non_directional() -> None:
    current = _snapshot("RECRUITING", captured="2026-01-01T12:00:00Z", as_of="2026-01-01")

    events = validation.derive_events(None, current)

    assert len(events) == 1
    assert events[0]["eventType"] == "BASELINE_CAPTURE"
    assert events[0]["direction"] == 0
    assert events[0]["evaluationStatus"] == "NON_DIRECTIONAL"


def test_verified_status_transition_creates_directional_risk_event() -> None:
    previous = _snapshot("RECRUITING", captured="2026-01-01T12:00:00Z", as_of="2026-01-01")
    current = _snapshot("TERMINATED", captured="2026-01-02T12:00:00Z", as_of="2026-01-02")

    events = validation.derive_events(previous, current)

    risk = next(row for row in events if row["eventType"] == "CLINICAL_RISK_STARTED")
    assert risk["direction"] == -1
    assert risk["previousValue"] == "RECRUITING"
    assert risk["currentValue"] == "TERMINATED"


def test_event_evaluation_enters_next_session_and_subtracts_benchmark_and_cost(monkeypatch) -> None:
    stock = [
        {"date": "2026-01-01", "open": "90", "close": "100"},
        {"date": "2026-01-02", "open": "100", "close": "101"},
        {"date": "2026-01-05", "open": "101", "close": "102"},
        {"date": "2026-01-06", "open": "102", "close": "103"},
        {"date": "2026-01-07", "open": "103", "close": "104"},
        {"date": "2026-01-08", "open": "104", "close": "110"},
    ]
    benchmark = [
        {"date": "2026-01-02", "open": "200", "close": "201"},
        {"date": "2026-01-05", "open": "201", "close": "202"},
        {"date": "2026-01-06", "open": "202", "close": "203"},
        {"date": "2026-01-07", "open": "203", "close": "204"},
        {"date": "2026-01-08", "open": "204", "close": "210"},
    ]
    monkeypatch.setattr(validation, "_price_rows", lambda market, symbol: benchmark if symbol == "SPY" else stock)
    event = {
        "eventId": "event-1", "eventDate": "2026-01-01", "market": "us",
        "symbol": "ACME", "eventType": "CLINICAL_RISK_STARTED", "direction": -1,
    }

    out = validation.evaluate_event(event)

    assert out["evaluationStatus"] == "EVALUATED"
    assert out["entryDate"] == "2026-01-02"
    assert out["exitDate"] == "2026-01-08"
    assert out["rawReturnPct"] == 10.0
    assert out["benchmarkReturnPct"] == 5.0
    assert out["residualAlphaPct"] == 5.0
    assert out["signedNetResidualAlphaPct"] == -5.2
    assert out["lookaheadRule"] == "entry_at_next_trading_session_open"


def _evaluated_events(value: float) -> list[dict]:
    rows = []
    for day in range(12):
        count = 3 if day < 6 else 2
        for index in range(count):
            rows.append({
                "eventId": f"e-{day}-{index}",
                "eventDate": f"2026-01-{day + 1:02d}",
                "market": "us",
                "symbol": f"S{day:02d}{index}",
                "eventType": "CLINICAL_RISK_STARTED",
                "direction": -1,
                "evaluationStatus": "EVALUATED",
                "signedNetResidualAlphaPct": value,
            })
    return rows


def test_promotion_gate_requires_independent_chronological_holdout() -> None:
    insufficient = validation.build_validation(_evaluated_events(2.0)[:20])
    promoted = validation.build_validation(_evaluated_events(2.0))

    insufficient_gate = next(row for row in insufficient["gates"] if row["key"] == "us:CLINICAL_RISK_STARTED")
    promoted_gate = next(row for row in promoted["gates"] if row["key"] == "us:CLINICAL_RISK_STARTED")
    assert insufficient_gate["status"] == "INSUFFICIENT"
    assert insufficient_gate["promotionEligible"] is False
    assert promoted_gate["status"] == "PROMOTED"
    assert promoted_gate["holdoutDateCount"] >= 4
    assert promoted_gate["holdoutCi95"][0] > 0
    assert promoted_gate["scoreMagnitude"] <= 2.0


def test_gate_rejects_single_symbol_pseudoreplication() -> None:
    rows = _evaluated_events(2.0)
    for row in rows:
        row["symbol"] = "ACME"

    report = validation.build_validation(rows)
    gate = next(row for row in report["gates"] if row["key"] == "us:CLINICAL_RISK_STARTED")

    assert gate["promotionEligible"] is False
    assert gate["distinctSymbols"] == 1
    assert gate["effectiveDateSampleCount"] == 12
    assert gate["inferenceUnit"] == "event_date_mean"
    assert gate["maxSingleSymbolShare"] == 1.0

def test_score_decision_is_fail_closed_until_gate_promotes() -> None:
    item = {
        "market": "us",
        "symbol": "ACME",
        "clinicalTrials": {"riskStatusStudyCountInFetchedPage": 1},
    }
    recent_event = {
        "eventId": "recent-risk", "eventDate": "2026-01-10", "market": "us", "symbol": "ACME",
        "eventType": "CLINICAL_RISK_STARTED", "direction": -1,
    }
    blocked = validation.score_decision(
        item, validation.build_validation([]), events=[recent_event], as_of=date(2026, 1, 20)
    )
    promoted = validation.score_decision(
        item, validation.build_validation(_evaluated_events(2.0)),
        events=[recent_event], as_of=date(2026, 1, 20),
    )
    static_only = validation.score_decision(
        item, validation.build_validation(_evaluated_events(2.0)), events=[], as_of=date(2026, 1, 20)
    )

    assert blocked["scoreAdjustment"] == 0.0
    assert blocked["researchOnly"] is True
    assert promoted["scoreAdjustment"] < 0
    assert promoted["scoreAdjustment"] >= -2.0
    assert promoted["researchOnly"] is False
    assert static_only["scoreAdjustment"] == 0.0
    assert static_only["reason"] == "STATIC_CLINICAL_RISK_VISIBLE_BUT_NOT_A_NEW_EVENT"


def test_persist_point_in_time_deduplicates_same_snapshot(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(validation, "SNAPSHOT_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(validation, "EVENT_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(validation, "VALIDATION_PATH", tmp_path / "validation.json")
    payload = {
        "generatedAt": "2026-01-01T12:00:00Z",
        "items": [{
            "market": "us", "symbol": "ACME", "company": "Acme", "asOfDate": "2026-01-01",
            "status": "OK",
            "clinicalTrials": {
                "status": "OK", "verifiedStudyCountInFetchedPage": 1,
                "activeStudyCountInFetchedPage": 1, "phase3StudyCountInFetchedPage": 1,
                "riskStatusStudyCountInFetchedPage": 0,
                "studies": [{
                    "nctId": "NCT1", "overallStatus": "RECRUITING", "phases": ["PHASE3"],
                    "completionDate": "2027-01-01", "hasResults": False, "leadSponsor": "Acme",
                }],
            },
            "pubMed": {"status": "OK", "publicationCountRecent5y": 1, "publications": [{"pmid": "1"}]},
        }],
    }

    first = validation.persist_point_in_time(payload)
    second = validation.persist_point_in_time(payload)

    assert first["addedSnapshots"] == 1
    assert first["addedEvents"] == 1
    assert second["addedSnapshots"] == 0
    assert second["addedEvents"] == 0
    assert second["snapshotCount"] == 1
    assert second["eventCount"] == 1
