from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import scripts.settle_pending_validations as settle  # noqa: E402
import scripts.generate_kr_close_validation as gen  # noqa: E402
import scripts.update_win_rates as winrates  # noqa: E402


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


LEDGER_FIELDS = [
    "predictionId", "createdAt", "market", "symbol", "name", "mode", "horizon",
    "entryPrice", "stopPrice", "targetPrice", "expectedPrice", "probability",
    "validationWindowDays", "validationDueDate", "status", "source",
    "returnPct", "result", "exitStatus", "exitPrice", "validatedAt",
]

VALIDATION_FIELDS = [
    "date", "symbol", "name", "market", "mode", "horizon", "executed",
    "entryPrice", "stopPrice", "targetPrice", "exitPrice", "returnPct",
    "result", "dataStatus", "reason",
]


def _ledger_row(**overrides) -> dict:
    row = {f: "" for f in LEDGER_FIELDS}
    row.update({
        "predictionId": "kr|000001|balanced|swing|2026-06-01",
        "createdAt": "2026-06-01",
        "market": "kr",
        "symbol": "000001",
        "name": "테스트종목",
        "mode": "balanced",
        "horizon": "swing",
        "entryPrice": "10000",
        "stopPrice": "9000",
        "targetPrice": "12000",
        "validationDueDate": "2026-06-05",
        "status": "PENDING",
        "source": "api/final/recommendations",
    })
    row.update(overrides)
    return row


def _snapshot_row(date: str, symbol: str, result: str, **overrides) -> dict:
    row = {f: "" for f in VALIDATION_FIELDS}
    row.update({
        "date": date, "symbol": symbol, "name": symbol, "market": "kr",
        "mode": "balanced", "horizon": "swing", "result": result,
    })
    row.update(overrides)
    return row


OHLCV_FIELDS = ["date", "market", "symbol", "open", "high", "low", "close", "volume"]


def _setup(tmp_path: Path, monkeypatch, ledger_rows: list[dict], snapshots: dict[str, list[dict]],
           ohlcv: dict[str, list[dict]] | None = None):
    reports = tmp_path / "reports"
    monkeypatch.setattr(settle, "REPORTS", reports)
    monkeypatch.setattr(settle, "TODAY", "2026-06-27")
    # 진짜 repo의 data/market/ohlcv를 우연히 건드리지 않도록 격리
    monkeypatch.setattr(settle, "OHLCV_DIR", tmp_path / "ohlcv")
    _write_csv(reports / "virtual_prediction_ledger.csv", ledger_rows, LEDGER_FIELDS)
    for fname, rows in snapshots.items():
        _write_csv(reports / fname, rows, VALIDATION_FIELDS)
    for fname, rows in (ohlcv or {}).items():
        _write_csv(tmp_path / "ohlcv" / fname, rows, OHLCV_FIELDS)
    return reports


def _read_ledger(reports: Path) -> list[dict]:
    with (reports / "virtual_prediction_ledger.csv").open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ── 진입가 미터치를 EXPIRED와 구분 ────────────────────────────────────────

def test_not_executed_observation_is_settled_as_not_executed_not_expired(tmp_path, monkeypatch):
    ledger = [_ledger_row()]
    snapshots = {
        "mone_v36_final_trade_validation_kr_balanced_swing_20260601.csv": [
            _snapshot_row("2026-06-01", "000001", "not_executed", reason="entry_not_touched"),
        ],
        "mone_v36_final_trade_validation_kr_balanced_swing_20260615.csv": [
            _snapshot_row("2026-06-15", "000001", "not_executed", reason="entry_not_touched"),
        ],
    }
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots)
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "NOT_EXECUTED"
    assert out["result"] == "NOT_EXECUTED"
    # 손익이 없는 거래이므로 returnPct가 채워지면 안 됨 (승률 계산에 섞이면 안 됨)
    assert out["returnPct"] == ""


def test_true_data_gap_still_expired(tmp_path, monkeypatch):
    """스냅샷도 OHLCV도 전혀 없으면 여전히 EXPIRED(데이터 없음)여야 한다."""
    ledger = [_ledger_row()]
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots={})
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "EXPIRED"
    assert out["result"] == "DATA_PENDING"


# ── 스냅샷이 한 번도 안 잡힌 심볼도 OHLCV로 직접 재구성해 정산 ──────────────

def _ohlcv_row(date: str, low: float, high: float, close: float) -> dict:
    return {"date": date, "market": "kr", "symbol": "000001", "open": "", "high": str(high),
            "low": str(low), "close": str(close), "volume": ""}


def test_ohlcv_fallback_settles_symbol_with_no_snapshot_coverage(tmp_path, monkeypatch):
    """추천 리스트 이탈 등으로 스냅샷이 단 한 번도 안 만들어진 심볼도, OHLCV가 있으면
    스냅샷 없이 직접 정산할 수 있어야 한다 (KR 009150/010950과 같은 케이스)."""
    ledger = [_ledger_row()]  # entry=10000, stop=9000, target=12000, created 06-01, due 06-05
    ohlcv = {
        "kr_000001_daily.csv": [
            _ohlcv_row("2026-06-01", low=9500, high=10500, close=9800),
            _ohlcv_row("2026-06-02", low=8500, high=10200, close=8800),  # entry·stop 둘 다 포함 → stop_hit
        ],
    }
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots={}, ohlcv=ohlcv)
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "LOSS"
    assert out["result"] == "stop_hit"
    assert out["exitPrice"] == "9000.0"


def test_ohlcv_fallback_ignores_touches_outside_window(tmp_path, monkeypatch):
    """검증 창(due_date + horizon 여유일) 밖의 체결은 무시해야 한다."""
    ledger = [_ledger_row()]  # due 2026-06-05, swing -> cutoff은 due+17일
    ohlcv = {
        "kr_000001_daily.csv": [
            _ohlcv_row("2026-07-01", low=8500, high=9900, close=8800),  # cutoff 밖
        ],
    }
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots={}, ohlcv=ohlcv)
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "EXPIRED"


def test_ohlcv_fallback_not_executed_when_entry_never_touched(tmp_path, monkeypatch):
    """OHLCV는 있지만 창 안에서 진입가에 한 번도 안 닿았으면 NOT_EXECUTED여야 한다."""
    ledger = [_ledger_row()]  # entry=10000
    ohlcv = {
        "kr_000001_daily.csv": [
            _ohlcv_row("2026-06-01", low=10500, high=11000, close=10800),  # entry보다 항상 위
        ],
    }
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots={}, ohlcv=ohlcv)
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "NOT_EXECUTED"


def test_exec_result_takes_priority_over_earlier_not_executed_observation(tmp_path, monkeypatch):
    """같은 창 안에 '미체결' 관측과 실제 체결 결과가 둘 다 있으면 체결 결과가 최종이어야 한다."""
    ledger = [_ledger_row()]
    snapshots = {
        "mone_v36_final_trade_validation_kr_balanced_swing_20260601.csv": [
            _snapshot_row("2026-06-01", "000001", "not_executed", reason="entry_not_touched"),
        ],
        "mone_v36_final_trade_validation_kr_balanced_swing_20260610.csv": [
            _snapshot_row(
                "2026-06-10", "000001", "stop_hit",
                executed="true", exitPrice="9000", returnPct="-10.0",
            ),
        ],
    }
    reports = _setup(tmp_path, monkeypatch, ledger, snapshots)
    settle.main()
    out = _read_ledger(reports)[0]
    assert out["status"] == "LOSS"
    assert out["result"] == "stop_hit"


def test_win_rate_calc_excludes_not_executed_rows():
    row = {"mode": "balanced", "horizon": "swing", "result": "NOT_EXECUTED"}
    assert winrates._is_win(row) is None


# ── 추천 리스트에서 빠진 PENDING 예측도 계속 추적 (ledger fallback) ──────────

def test_pending_ledger_fallback_tracks_symbol_dropped_from_recommendations(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    monkeypatch.setattr(gen, "REPORTS", reports)
    ledger = [
        _ledger_row(predictionId="kr|000002|balanced|swing|2026-06-01", symbol="000002", status="PENDING"),
    ]
    _write_csv(reports / "virtual_prediction_ledger.csv", ledger, LEDGER_FIELDS)

    known: set[str] = set()  # 오늘 추천 리스트에는 이 심볼이 없음
    out = gen.load_pending_ledger_fallback("kr", "balanced", "swing", known)

    assert len(out) == 1
    assert out[0]["symbol"] == "000002"
    assert out[0]["entryPrice"] == "10000"
    assert "000002" in known


def test_pending_ledger_fallback_skips_symbol_already_in_recommendations(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    monkeypatch.setattr(gen, "REPORTS", reports)
    ledger = [
        _ledger_row(predictionId="kr|000003|balanced|swing|2026-06-01", symbol="000003", status="PENDING"),
    ]
    _write_csv(reports / "virtual_prediction_ledger.csv", ledger, LEDGER_FIELDS)

    out = gen.load_pending_ledger_fallback("kr", "balanced", "swing", known_symbols={"000003"})
    assert out == []


def test_pending_ledger_fallback_ignores_settled_and_out_of_scope_rows(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    monkeypatch.setattr(gen, "REPORTS", reports)
    ledger = [
        _ledger_row(predictionId="a", symbol="000004", status="WIN"),  # 이미 정산됨
        _ledger_row(predictionId="b", symbol="000005", status="PENDING", market="us"),  # 다른 시장
        _ledger_row(predictionId="c", symbol="000006", status="PENDING", horizon="short"),  # 다른 horizon
    ]
    _write_csv(reports / "virtual_prediction_ledger.csv", ledger, LEDGER_FIELDS)

    out = gen.load_pending_ledger_fallback("kr", "balanced", "swing", known_symbols=set())
    assert out == []
