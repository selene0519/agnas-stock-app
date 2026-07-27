"""헬스체크의 자가보정 루프 지표 회귀 테스트.

파일이 최근에 쓰였는지만 보는 신선도 검사는 이 실패를 못 잡는다: 정산
스크립트가 매일 돌아 mtime은 새것이어도, 새 예측이 하나도 안 잡히면 루프는
죽은 것이다. 실제로 2026-07에 그 상태였고(6월 818건 → 7월 21건) 헬스체크는
계속 OK를 찍었다.
"""
from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEDGER_FIELDS = ["predictionId", "createdAt", "market", "symbol", "status"]
RESULT_FIELDS = ["predictionId", "createdAt", "market", "symbol", "result"]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "data_freshness_healthcheck", ROOT / "scripts" / "data_freshness_healthcheck.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _setup(tmp_path: Path, monkeypatch, ledger_rows, result_rows, clean_start="2026-07-10"):
    hc = _load_module()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    _write_csv(tmp_path / "reports" / "virtual_prediction_ledger.csv", LEDGER_FIELDS, ledger_rows)
    _write_csv(tmp_path / "reports" / "virtual_validation_results.csv", RESULT_FIELDS, result_rows)
    (tmp_path / "reports" / "clean_window_marker.json").write_text(
        json.dumps({"cleanWindowStart": clean_start}), encoding="utf-8"
    )
    return hc


def test_contaminated_window_only_reports_zero_clean_samples(tmp_path, monkeypatch) -> None:
    """정산 표본이 전부 clean window 이전이면 0건으로 잡혀야 한다."""
    hc = _setup(
        tmp_path, monkeypatch,
        ledger_rows=[{"predictionId": "a", "createdAt": "2026-06-15", "market": "kr",
                      "symbol": "005930", "status": "CLOSED"}],
        result_rows=[{"predictionId": "a", "createdAt": "2026-06-15", "market": "kr",
                      "symbol": "005930", "result": "STOP"}],
    )
    stats = hc._learning_loop_stats()
    assert stats["admissibleTotal"] == 1
    assert stats["cleanWindowAdmissible"] == 0
    assert stats["newestCapture"] == "2026-06-15"


def test_pending_rows_are_not_counted_as_settled_samples(tmp_path, monkeypatch) -> None:
    """PENDING/NOT_EXECUTED는 승률 분모가 아니므로 표본으로 세면 안 된다."""
    hc = _setup(
        tmp_path, monkeypatch,
        ledger_rows=[{"predictionId": "b", "createdAt": "2026-07-20", "market": "kr",
                      "symbol": "005930", "status": "PENDING"}],
        result_rows=[
            {"predictionId": "b", "createdAt": "2026-07-20", "market": "kr",
             "symbol": "005930", "result": "PENDING"},
            {"predictionId": "c", "createdAt": "2026-07-20", "market": "kr",
             "symbol": "000660", "result": "NOT_EXECUTED"},
        ],
    )
    stats = hc._learning_loop_stats()
    assert stats["admissibleTotal"] == 0
    assert stats["cleanWindowAdmissible"] == 0


def test_settled_clean_window_rows_are_counted(tmp_path, monkeypatch) -> None:
    hc = _setup(
        tmp_path, monkeypatch,
        ledger_rows=[{"predictionId": "d", "createdAt": "2026-07-20", "market": "kr",
                      "symbol": "005930", "status": "CLOSED"}],
        result_rows=[
            {"predictionId": "d", "createdAt": "2026-07-20", "market": "kr",
             "symbol": "005930", "result": "TARGET"},
            {"predictionId": "e", "createdAt": "2026-07-21", "market": "kr",
             "symbol": "000660", "result": "STOP"},
        ],
    )
    stats = hc._learning_loop_stats()
    assert stats["admissibleTotal"] == 2
    assert stats["cleanWindowAdmissible"] == 2
    assert stats["newestCapture"] == "2026-07-20"


def test_zero_clean_samples_surface_as_error_check(tmp_path, monkeypatch) -> None:
    """루프가 죽었으면 전체 리포트에 ERROR 항목으로 떠야 한다(예전엔 조용히 OK)."""
    hc = _setup(
        tmp_path, monkeypatch,
        ledger_rows=[{"predictionId": "a", "createdAt": "2026-06-15", "market": "kr",
                      "symbol": "005930", "status": "CLOSED"}],
        result_rows=[{"predictionId": "a", "createdAt": "2026-06-15", "market": "kr",
                      "symbol": "005930", "result": "STOP"}],
    )
    result = hc.run(max_stale_days=3.0)
    by_name = {c["name"]: c for c in result["checks"]}
    assert by_name["clean_window_samples"]["status"] == "ERROR"
    assert "오염" in by_name["clean_window_samples"]["detail"]
