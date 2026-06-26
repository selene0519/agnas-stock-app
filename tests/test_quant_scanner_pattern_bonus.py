import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1] / "mone-web-app" / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
loaded_app = sys.modules.get("app")
if loaded_app is not None and not hasattr(loaded_app, "__path__"):
    sys.modules.pop("app", None)

from app.engine import quant_scanner as qs  # noqa: E402


def test_walkforward_pattern_bonus_uses_regime_specific_stats(monkeypatch, tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "pattern_walkforward_us.json").write_text(
        json.dumps(
            {
                "horizonDays": 20,
                "geometricRegimeSummary": {
                    "BULL": {
                        "FAILED_BREAKDOWN:BREAKOUT_CANDIDATE": {
                            "sampleCount": 80,
                            "directionalWinRate": 0.34,
                            "avgReturn": -0.08,
                            "stopRate": 0.56,
                        }
                    },
                    "BEAR": {
                        "FAILED_BREAKDOWN:BREAKOUT_CANDIDATE": {
                            "sampleCount": 80,
                            "directionalWinRate": 0.63,
                            "avgReturn": 0.07,
                            "stopRate": 0.30,
                        }
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(qs, "_REPO_ROOT", tmp_path)
    qs._load_pattern_walkforward_report.cache_clear()

    bull = qs._walkforward_pattern_bonus("us", "BULL", "swing", ["FAILED_BREAKDOWN"])
    bear = qs._walkforward_pattern_bonus("us", "BEAR", "swing", ["FAILED_BREAKDOWN"])

    assert bull["status"] == "OK"
    assert bear["status"] == "OK"
    assert bull["bonus"] < 0
    assert bear["bonus"] > 0
