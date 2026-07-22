from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.services import data_loader  # noqa: E402


def test_similar_pattern_history_uses_full_history_and_separates_episodes(monkeypatch) -> None:
    rows = []
    for index in range(360):
        close = 100 + index * 0.08 + math.sin(index / 7) * 4
        rows.append(
            {
                "date": (pd.Timestamp("2020-01-01") + pd.Timedelta(days=index)).date().isoformat(),
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1000 + index,
            }
        )
    history = pd.DataFrame(rows)
    monkeypatch.setattr(data_loader, "_load_full_ohlcv", lambda symbol, market: (history, "test-history"))

    result = data_loader.similar_pattern_history("TEST", "us", top_n=12)

    assert result["status"] == "OK"
    assert result["period"]["totalRows"] == 360
    assert result["period"]["independentSpacingBars"] == 20
    dates = [pd.Timestamp(item["date"]) for item in result["matches"]]
    assert all(abs((later - earlier).days) >= 20 for pos, earlier in enumerate(dates) for later in dates[pos + 1:])
