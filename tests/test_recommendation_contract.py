from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"))
from app.services import recommendation_contract as contract


def candidate(**changes):
    return {
        "symbol": "TEST", "market": "us", "mode": "balanced", "horizon": "swing",
        "generatedAt": "2026-10-27T07:28:00+00:00", "entry": "$100.00",
        "stop": "$95", "target": "$115", "publicTradeStatus": "TRADE_CANDIDATE",
        "decisionBucket": "오늘 진입", **changes,
    }


def test_plan_preserves_prices_and_expires_at_exchange_close():
    plan = contract.execution_plan(candidate(), datetime(2026, 10, 27, 12, tzinfo=timezone.utc))
    assert plan["status"] == "READY"
    assert (plan["entry"], plan["stop"], plan["target"]) == (100, 95, 115)
    assert plan["validUntil"] == "2026-10-27T20:00:00+00:00"
    assert plan["validFrom"] == "2026-10-27T13:30:00+00:00"


def test_us_holiday_and_early_close():
    # Thanksgiving is closed; Friday closes at 13:00 ET after DST ends.
    plan = contract.execution_plan(candidate(generatedAt="2026-11-26T12:00:00Z"), datetime(2026, 11, 26, 13, tzinfo=timezone.utc))
    assert plan["validUntil"] == "2026-11-27T18:00:00+00:00"


def test_expired_plan_is_observation_even_if_old_gate_was_positive():
    payload = contract.attach_execution_plans({"items": [candidate()]}, datetime(2026, 10, 28, tzinfo=timezone.utc))
    item = payload["items"][0]
    assert item["decisionBucket"] == "관찰"
    assert "PLAN_EXPIRED" in item["executionPlan"]["reasonCodes"]


def test_blocked_missing_timezone_and_invalid_prices_cannot_be_ready():
    now = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
    for changes in ({"isTradeBlocked": True}, {"sourceStatus": "FALLBACK"}, {"generatedAt": "2026-10-27T07:28:00"}, {"stop": "$101"}, {"target": "nan"}, {"decisionBucket": "대기 관찰"}):
        assert contract.execution_plan(candidate(**changes), now)["status"] == "WATCH"


def test_public_reader_uses_canonical_policy_without_journal_write(monkeypatch):
    from app.engine import mone_v65_api_stabilizer as engine
    calls = []
    payload = {"items": [{"symbol": "TEST", "isTradeBlocked": True}]}
    def read(*args, **kwargs):
        calls.append((args, kwargs))
        return payload
    monkeypatch.setattr(engine, "_recommendations_payload", read)
    result = contract.public_recommendations("us", "balanced", "swing")
    assert calls == [(("us", "balanced", "swing", 0, 50, False), {"record_ledger": False})]
    result["items"][0]["isTradeBlocked"] = False
    assert payload["items"][0]["isTradeBlocked"] is True


def test_published_prices_are_not_scaled_by_display_profile():
    original = candidate(finalScore="70", finalRankScore="70", expectedValue="2", rrActual="3", isTradeBlocked="true")
    changed = {"entry": 102, "stop": 80, "target": 140, "computedFields": ["strategy_horizon_adjusted_from_source"]}
    result = contract.preserve_published_inputs(changed, original)
    assert (result["entry"], result["stop"], result["target"]) == (100, 95, 115)
    assert result["entryText"] == "$100.00"
    assert result["computedFields"] == []
    assert result["isTradeBlocked"] is True


def test_multiple_updates_in_same_five_minutes_invalidate_cache(monkeypatch, tmp_path):
    import os
    from app.engine import mone_v65_api_stabilizer as engine
    reports = tmp_path / "reports"
    reports.mkdir()
    file = reports / "mone_v36_final_recommendations_us_balanced_swing.csv"
    file.write_text("symbol\nAAPL\n")
    monkeypatch.setattr(engine, "_repo_root", lambda: tmp_path)
    os.utime(file, ns=(1_800_000_000_000_000_000, 1_800_000_000_000_000_000))
    first = engine._reco_file_version("us", "balanced", "swing")
    os.utime(file, ns=(1_800_000_001_000_000_000, 1_800_000_001_000_000_000))
    assert engine._reco_file_version("us", "balanced", "swing") != first


def test_detail_preserves_analysis_but_uses_public_prices_and_block(monkeypatch):
    original = candidate(entry=100, stop=95, target=115, isTradeBlocked=True, stopText="$95")
    monkeypatch.setattr(contract, "public_recommendations", lambda *_args: {"items": [original]})
    payload = {"items": [{**original, "stop": 80, "stopLoss": 80, "stopPriceText": "$80", "companyAnalysis": "business evidence"}]}
    row = contract.bind_public_detail(payload, "us")["item"]
    assert row["stop"] == row["stopPrice"] == row["stopLoss"] == 95
    assert row["stopPriceText"] == "$95"
    assert row["isTradeBlocked"] is True
    assert row["companyAnalysis"] == "business evidence"


def test_nonrecommended_detail_remains_analysis_only(monkeypatch):
    monkeypatch.setattr(contract, "public_recommendations", lambda *_args: {"items": []})
    row = contract.bind_public_detail({"items": [candidate()]}, "us")["item"]
    assert row["planSource"] == "ANALYSIS_ONLY"
    assert row["executionPlan"]["status"] == "WATCH"
    assert row["publicTradeStatus"] == "NO_TRADE"
