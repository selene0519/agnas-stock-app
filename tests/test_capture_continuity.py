"""캡처 **연속성** 검사 회귀 테스트.

`prediction_capture`는 최신 캡처가 며칠 전인지만 본다. 그래서 어제 22건이
들어왔으면 그 앞 9일이 통째로 비어도 OK를 찍는다. 2026-07-28에 배운 교훈
("정산이 매일 돌아 파일 mtime은 새것이었다")과 같은 함정을 감시 장치 쪽에서
반복한 것으로, 표본 축적 속도가 엣지 판정의 분모라 결손일은 지연이 아니라 손실이다.

거래일 달력은 공휴일 표를 하드코딩하지 않고 OHLCV 봉에서 역산하므로,
여기서도 봉 파일을 만들어 장이 열린 날을 정의한다.
"""
from __future__ import annotations

import csv
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEDGER_FIELDS = ["predictionId", "createdAt", "market", "symbol", "status"]


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


def _setup(tmp_path: Path, monkeypatch, trading_days: list[str], captured_days: list[str]):
    """장이 열린 날 `trading_days`, 실제 캡처된 날 `captured_days`로 환경을 만든다."""
    hc = _load_module()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    # epoch을 창 밖으로 밀어 테스트가 실제 배포 날짜에 묶이지 않게 한다.
    monkeypatch.setattr(hc, "CAPTURE_CI_EPOCH", "2000-01-01")
    monkeypatch.setattr(hc, "NOW", datetime.now(timezone.utc))

    _write_csv(
        tmp_path / "data" / "market" / "ohlcv" / "kr_005930_daily.csv",
        ["date", "close"],
        [{"date": d, "close": "70000"} for d in trading_days],
    )
    _write_csv(
        tmp_path / "reports" / "virtual_prediction_ledger.csv",
        LEDGER_FIELDS,
        [{"predictionId": f"p{i}", "createdAt": d, "market": "kr",
          "symbol": "005930", "status": "PENDING"}
         for i, d in enumerate(captured_days)],
    )
    return hc


def _recent_days(n: int) -> list[str]:
    """최근 n일(오늘 포함)을 날짜 문자열로. 창(21일) 안에 들어가게 최근을 쓴다."""
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def test_every_trading_day_captured_is_ok(tmp_path, monkeypatch) -> None:
    days = _recent_days(5)
    hc = _setup(tmp_path, monkeypatch, trading_days=days, captured_days=days)
    name, status, detail, critical = hc._capture_continuity_check()
    assert name == "capture_continuity"
    assert status == "OK", detail
    assert critical is True


def test_gap_in_middle_is_caught_even_when_latest_is_fresh(tmp_path, monkeypatch) -> None:
    """핵심 회귀: 최신 캡처가 오늘이어도 중간 결손은 잡혀야 한다.

    이게 `prediction_capture`(최신성만 검사)가 못 보던 바로 그 구멍이다.
    """
    days = _recent_days(6)
    # 중간 3일을 통째로 비우고, 가장 최근 날은 캡처된 상태로 둔다.
    captured = [days[0], days[1], days[5]]
    hc = _setup(tmp_path, monkeypatch, trading_days=days, captured_days=captured)
    name, status, detail, critical = hc._capture_continuity_check()
    assert status == "ERROR", detail
    assert critical is True
    # 최신 거래일은 경합 유예로 기대집합에서 빠지므로 결손은 days[2:5] 3일.
    for d in days[2:5]:
        assert d in detail
    # 최신성 검사는 같은 상황에서 여전히 OK를 찍는다 — 두 검사가 서로 다른
    # 실패를 본다는 것이 이 검사를 따로 두는 이유다.
    assert hc._learning_loop_stats()["newestCapture"] == days[5]


def test_single_missing_day_is_warn_not_error(tmp_path, monkeypatch) -> None:
    """1일 결손은 CI 지연으로도 생긴다. 2일부터 '멈춤'으로 본다."""
    days = _recent_days(5)
    captured = [d for d in days if d != days[1]]
    hc = _setup(tmp_path, monkeypatch, trading_days=days, captured_days=captured)
    _, status, detail, _ = hc._capture_continuity_check()
    assert status == "WARN", detail
    assert days[1] in detail


def test_latest_trading_day_gets_one_day_grace(tmp_path, monkeypatch) -> None:
    """장마감 수집과 캡처의 경합으로 최신 거래일이 비는 건 결손이 아니다."""
    days = _recent_days(4)
    hc = _setup(tmp_path, monkeypatch, trading_days=days, captured_days=days[:-1])
    _, status, detail, _ = hc._capture_continuity_check()
    assert status == "OK", detail


def test_holidays_are_not_counted_as_missing(tmp_path, monkeypatch) -> None:
    """공휴일엔 봉이 없다. 달력을 OHLCV에서 역산하므로 결손으로 세면 안 된다."""
    days = _recent_days(6)
    trading = [days[0], days[1], days[4], days[5]]  # days[2], days[3] 휴장
    hc = _setup(tmp_path, monkeypatch, trading_days=trading, captured_days=trading)
    _, status, detail, _ = hc._capture_continuity_check()
    assert status == "OK", detail


def test_pre_epoch_history_is_not_penalized(tmp_path, monkeypatch) -> None:
    """CI 캡처가 존재하지도 않던 구간을 결손으로 세면 영영 빨간불이 된다.

    2026-07-10~25가 그 구간이었다(스크립트 생성 7/26, 셰도잉 수정 7/28).
    """
    days = _recent_days(5)
    hc = _setup(tmp_path, monkeypatch, trading_days=days, captured_days=[])
    # epoch을 가장 최근 날로 올리면 판정할 확정 거래일이 사라진다.
    monkeypatch.setattr(hc, "CAPTURE_CI_EPOCH", days[-1])
    _, status, detail, _ = hc._capture_continuity_check()
    assert status == "OK", detail
    assert "판정 구간 없음" in detail
