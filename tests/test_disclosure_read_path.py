from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import data_loader  # noqa: E402


def test_disclosure_read_never_runs_provider_refresh(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FINNHUB_API_KEY", "configured")
    monkeypatch.setattr(data_loader, "_disclosure_output_file", lambda market: tmp_path / f"{market}.csv")
    monkeypatch.setattr(data_loader, "_preferred_disclosure_files", lambda market: [])

    def fail_refresh(*args, **kwargs):
        raise AssertionError("read path must not invoke external collection")

    monkeypatch.setattr(data_loader, "refresh_disclosures", fail_refresh)

    result = data_loader.disclosure_rows("us")

    assert result["status"] == "MISSING"
    assert result["items"] == []
    assert result["count"] == 0
