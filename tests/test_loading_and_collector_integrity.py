"""Regression checks for collector authority and launch-loading readiness."""
from __future__ import annotations

import csv
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_healthcheck():
    spec = importlib.util.spec_from_file_location(
        "data_freshness_healthcheck_collector_test",
        ROOT / "scripts" / "data_freshness_healthcheck.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_fresh_cloud_collector_outranks_stale_optional_local_runner(tmp_path, monkeypatch) -> None:
    hc = _load_healthcheck()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    monkeypatch.setattr(hc, "NOW", datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc))

    _write_json(
        tmp_path / "reports" / "kis_live_refresh_status.json",
        {
            "updatedAt": "2026-08-05 16:04:36 KST",
            "markets": {
                "kr": {"status": "OK", "updatedAt": "2026-08-05 16:05:40 KST"},
                "us": {"status": "PARTIAL", "updatedAt": "2026-08-05 16:07:19 KST"},
            },
        },
    )
    _write_json(
        tmp_path / "reports" / "local_collector_status.json",
        {"startedAt": "2026-07-28T16:40:00", "steps": {"ohlcv_kr": {"ok": 100, "fail": 0}}},
    )

    result = hc.run(max_stale_days=3.0)
    checks = {row["name"]: row for row in result["checks"]}

    assert checks["collector_steps"]["status"] == "OK"
    assert checks["collector_steps"]["critical"] is True
    assert checks["collector_run"]["status"] == "OK"
    assert "source=cloud:kis_live" in checks["collector_run"]["detail"]
    assert checks["local_collector_run"]["status"] == "STALE"
    assert checks["local_collector_run"]["critical"] is False
    assert hc._parse_collector_dt("2026-08-05T16:15:00").utcoffset() == timedelta(hours=9)


def test_cloud_collector_error_remains_critical(tmp_path, monkeypatch) -> None:
    hc = _load_healthcheck()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    monkeypatch.setattr(hc, "NOW", datetime(2026, 8, 5, 8, 0, tzinfo=timezone.utc))
    _write_json(
        tmp_path / "reports" / "kr_close_ohlcv_refresh_status.json",
        {"status": "ERROR", "updatedAt": "2026-08-05T16:00:00"},
    )

    checks = {row["name"]: row for row in hc.run(3.0)["checks"]}
    assert checks["collector_steps"]["status"] == "ERROR"
    assert checks["collector_steps"]["critical"] is True


def test_cloud_collector_partial_failure_is_visible_warning(tmp_path, monkeypatch) -> None:
    hc = _load_healthcheck()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    monkeypatch.setattr(hc, "NOW", datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc))
    _write_json(
        tmp_path / "reports" / "us_close_ohlcv_refresh_status.json",
        {
            "status": "WARN",
            "updatedAt": "2026-08-31T20:00:00",
            "failedCount": 1,
            "failedItems": [{"symbol": "ELF", "status": "NO_DATA"}],
        },
    )

    result = hc.run(3.0)
    checks = {row["name"]: row for row in result["checks"]}
    assert checks["collector_steps"]["status"] == "OK"
    assert checks["collector_partial_failures"]["status"] == "WARN"
    assert checks["collector_partial_failures"]["critical"] is False
    assert "ELF" in checks["collector_partial_failures"]["detail"]
    assert result["overall"] == "ERROR"  # required fixtures are intentionally absent


def test_us_close_refresh_normalizes_dates_and_uses_latest_completed_session(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "us_close_refresh", ROOT / "scripts" / "refresh_us_close_ohlcv.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module._normalize_date("20260603") == "2026-06-03"
    assert module._normalize_date("not-a-date") == ""
    sunday = datetime(2026, 8, 30, 18, 0, tzinfo=timezone.utc)
    assert module._latest_completed_us_session(sunday) == "2026-08-28"
    good_friday = datetime(2026, 4, 3, 22, 0, tzinfo=timezone.utc)
    assert module._latest_completed_us_session(good_friday) == "2026-04-02"

    monkeypatch.setattr(module, "OHLCV_DIR", tmp_path)
    with (tmp_path / "us_DRAM_daily.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "close"])
        writer.writeheader()
        writer.writerow({"date": "20260603", "close": "10"})
    assert module._existing_latest_date("DRAM") == "2026-06-03"

    monkeypatch.setattr(module, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(module, "TARGET_DATE", "2026-08-28")
    monkeypatch.setattr(module, "_ensure_pkg", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(module, "_target_symbols", lambda limit: ["AAPL", "ELF"])
    monkeypatch.setattr(
        module,
        "_process_symbol",
        lambda symbol: {"symbol": symbol, "status": "OK", "latestDate": "2026-08-28"}
        if symbol == "AAPL"
        else {"symbol": symbol, "status": "NO_CURRENT_BAR", "latestDate": "2026-08-27"},
    )
    module.main()
    status = json.loads(
        (tmp_path / "reports" / "us_close_ohlcv_refresh_status.json").read_text(encoding="utf-8")
    )
    assert status["status"] == "WARN"
    assert status["failedCount"] == 1
    assert status["failedItems"][0]["symbol"] == "ELF"


def test_app_session_treats_good_friday_as_us_market_holiday() -> None:
    backend = ROOT / "mone-web-app" / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.engine import session

    assert session.is_market_holiday(
        "us", datetime(2026, 4, 3, 12, 0, tzinfo=timezone.utc)
    ) is True


def test_us_close_refresh_uses_chart_fallback_when_yfinance_fails(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location(
        "us_close_refresh_fallback", ROOT / "scripts" / "refresh_us_close_ohlcv.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "OHLCV_DIR", tmp_path)
    monkeypatch.setattr(module, "TARGET_DATE", "2026-08-28")
    monkeypatch.setattr(module, "HISTORY_START", "")
    monkeypatch.setattr(module, "_fetch_yfinance", lambda *_args: None)
    monkeypatch.setattr(
        module,
        "_fetch_yahoo_chart",
        lambda *_args: [{"date": "2026-08-28", "close": 100, "source": "Yahoo Chart ELF"}],
    )

    result = module._process_symbol("ELF")

    assert result == {"symbol": "ELF", "status": "OK", "latestDate": "2026-08-28"}
    assert module._existing_latest_date("ELF") == "2026-08-28"


def test_regime_benchmark_invalid_trailing_bar_is_critical(tmp_path, monkeypatch) -> None:
    hc = _load_healthcheck()
    monkeypatch.setattr(hc, "ROOT", tmp_path)
    monkeypatch.setattr(hc, "NOW", datetime(2026, 8, 8, 0, 0, tzinfo=timezone.utc))
    directory = tmp_path / "data" / "market" / "ohlcv"
    directory.mkdir(parents=True)
    (tmp_path / "reports").mkdir()
    fields = ["date", "open", "high", "low", "close"]
    for symbol, close in (("KOSPI", "4000"), ("KOSDAQ", "nan")):
        with (directory / f"kr_{symbol}_daily.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerow({"date": "2026-08-07", "open": "3900", "high": "4050", "low": "3850", "close": close})

    checks = {row["name"]: row for row in hc.run(3.0)["checks"]}

    assert checks["kr_kospi_ohlcv"]["status"] == "OK"
    assert checks["kr_kosdaq_ohlcv"]["status"] == "ERROR"
    assert checks["kr_kosdaq_ohlcv"]["critical"] is True


def test_weekend_kr_close_refresh_is_clean_skip(tmp_path, monkeypatch) -> None:
    spec = importlib.util.spec_from_file_location("kr_weekend_refresh", ROOT / "scripts" / "refresh_kr_close_ohlcv.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "TARGET_DATE", "2026-08-08")
    monkeypatch.setattr(module, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(module, "OHLCV_DIR", tmp_path / "ohlcv")

    module.main()
    status = json.loads((tmp_path / "reports" / "kr_close_ohlcv_refresh_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "SKIP"
    assert status["reason"] == "SKIPPED_MARKET_CLOSED"
    assert status["failedCount"] == 0


def test_launch_overlay_waits_for_home_and_light_supporting_snapshots() -> None:
    page = (ROOT / "mone-web-app" / "frontend" / "app" / "page.tsx").read_text(encoding="utf-8")
    preload = (ROOT / "mone-web-app" / "frontend" / "lib" / "bootPreload.ts").read_text(encoding="utf-8")
    api = (ROOT / "mone-web-app" / "frontend" / "lib" / "api.ts").read_text(encoding="utf-8")
    home = (
        ROOT / "mone-web-app" / "frontend" / "components" / "pages" / "HomePage.tsx"
    ).read_text(encoding="utf-8")
    launch = (
        ROOT / "mone-web-app" / "frontend" / "components" / "AppLaunchLoading.tsx"
    ).read_text(encoding="utf-8")

    assert "APP_SHELL_TIMEOUT_MS" not in page
    assert "const showLaunchLoading = !cachedBoot.hasBootData;" in page
    assert "void preloadSupportingSnapshots()" in preload
    assert "const [krHome, usHome, supportErrors] = await Promise.all" in preload
    assert "await preloadSupportingSnapshots" not in preload
    assert "fetchChartSnapshot" not in preload
    assert 'fetchApiSnapshot("/api/final/operation-summary"' not in preload
    assert 'fetchApiSnapshot("/api/risk/near-alerts"' not in preload
    assert 'const BOOT_CACHE_KEY = "mone:boot-preload:v7";' in preload
    assert 'scopedBootCacheKey()' in preload
    assert "headers: bootRequestHeaders()" in preload
    assert 'fetchApiSnapshot("/api/holdings-clean", { market, limit: 500 }' in preload
    assert 'const API_SNAPSHOT_PREFIX = "mone:api-snapshot:v6:";' in api
    assert "apiSnapshotScope(path)" in api
    assert 'getAuthenticatedUserId() || "anonymous"' in api

    seed_position = home.index("setHoldings(homeHoldings.items);")
    personal_position = home.index("await fetchPersonalHomeHoldings(market);", seed_position)
    assert seed_position < personal_position
    assert "if (!active || booting) return;" in home
    assert "[applyCachedOrBootState, clientReady, selectedMarket, booting]" in home
    assert 'bootStatus === "degraded"' in home

    assert "transition-all duration-500" not in launch
    assert "transition-[width] duration-500" in launch
