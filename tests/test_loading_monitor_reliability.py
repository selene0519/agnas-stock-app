from __future__ import annotations

import csv
from pathlib import Path


class _Response:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


def test_github_monitor_retries_public_api_when_token_is_rejected(monkeypatch) -> None:
    from app.services import data_loader

    monkeypatch.setenv("GITHUB_TOKEN", "expired-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("MONE_GITHUB_TOKEN", raising=False)
    responses = iter(
        [
            _Response(401),
            _Response(401),
            _Response(200, {"workflows": [{"name": "Daily", "path": ".github/workflows/daily.yml"}]}),
            _Response(200, {"workflow_runs": [{"name": "Daily", "event": "schedule", "conclusion": "success"}]}),
        ]
    )
    calls: list[dict[str, str]] = []

    def fake_get(_url: str, *, headers: dict[str, str], timeout: int):
        assert timeout == 8
        calls.append(dict(headers))
        return next(responses)

    monkeypatch.setattr(data_loader.requests, "get", fake_get)
    result = data_loader.github_actions_status()

    assert result["status"] == "OK"
    assert result["authMode"] == "public_fallback"
    assert result["tokenRejected"] is True
    assert "Authorization" in calls[0]
    assert "Authorization" in calls[1]
    assert "Authorization" not in calls[2]
    assert "Authorization" not in calls[3]


def test_latest_ohlcv_date_reads_last_record_across_market_files(tmp_path: Path, monkeypatch) -> None:
    from app.engine import data_quality

    directory = tmp_path / "data" / "market" / "ohlcv"
    directory.mkdir(parents=True)
    for symbol, dates in (("AAA", ["2026-08-07", "2026-08-08"]), ("BBB", ["2026-08-06", "2026-08-09"])):
        path = directory / f"us_{symbol}_daily.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["date", "open", "close"])
            writer.writeheader()
            for day in dates:
                writer.writerow({"date": day, "open": "100", "close": "101"})

    monkeypatch.setattr(data_quality.data, "REPO_ROOT", tmp_path)

    assert data_quality.latest_ohlcv_date("us") == "2026-08-09"
