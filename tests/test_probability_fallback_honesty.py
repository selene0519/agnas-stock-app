from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.engine import mone_v65_api_stabilizer as stabilizer


def _candidate(probability: str | None = None) -> dict:
    row = {"symbol": "AAPL", "currentPrice": "100", "entry": "100", "stop": "95", "target": "110"}
    if probability is not None:
        row["probability"] = probability
    result = stabilizer._recommendation_item(
        row, "us", "balanced", "swing", "EXACT", "balanced", "swing", {}, {}, set()
    )
    assert result is not None
    return result


def test_missing_probability_is_not_replaced_with_a_favourable_auto_estimate():
    result = _candidate()

    assert result["probability"] is None
    assert result["probabilitySource"] == "UNAVAILABLE_NOT_MEASURED"
    assert result["probabilityText"] == "실측 확률 미산출"


def test_low_source_probability_is_preserved_not_lifted_to_a_floor():
    result = _candidate("14.6")

    assert result["probability"] == 14.6
    assert result["probabilitySource"] == "SOURCE_UNVERIFIED"
