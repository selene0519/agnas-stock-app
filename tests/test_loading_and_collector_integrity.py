"""Regression checks for collector authority and launch-loading readiness."""
from __future__ import annotations

import importlib.util
import json
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


def test_launch_overlay_waits_for_supporting_snapshots_and_seeds_home() -> None:
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
    assert "const showLaunchLoading = true;" in page
    assert "void Promise.allSettled" not in preload
    assert "await preloadSupportingSnapshots" in preload
    assert "const [krAuxiliary, usAuxiliary, krChart, usChart] = await Promise.all" in preload
    assert 'const BOOT_CACHE_KEY = "mone:boot-preload:v6";' in preload
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
