from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_render_startup_sync_is_non_blocking() -> None:
    main = read("mone-web-app/backend/app/main.py")
    auto_sync = read("mone-web-app/backend/app/engine/auto_sync.py")
    assert "start_startup_sync()" in main
    assert "startup_sync()           #" not in main
    assert 'name="mone-startup-sync"' in auto_sync
    assert '@app.get("/health/bootstrap")' in main


def test_secondary_pages_reuse_boot_snapshots_and_prefetch_chunks() -> None:
    stocks = read("mone-web-app/frontend/components/pages/StocksPage.tsx")
    chart = read("mone-web-app/frontend/components/pages/ChartPage.tsx")
    page = read("mone-web-app/frontend/app/page.tsx")
    assert "homeSummary({ market: resolvedMarket, limit: 12 })" in stocks
    assert "homeSummary({ market: gateMarket, limit: 12 })" in chart
    assert "loadStocksPage(), loadHoldingsPage()" in page
    assert "loadChartPage(), loadAdvancedPage(), loadPaperTradingPage()" in page


def test_analysis_core_does_not_wait_for_supporting_feeds() -> None:
    chart = read("mone-web-app/frontend/components/pages/ChartPage.tsx")
    effect = chart.index("const hasCoreSnapshot")
    support = chart.index("Promise.allSettled([", effect)
    core_block = chart[effect:support]
    ohlcv = core_block.index("mone.ohlcv")
    recommendation = core_block.index("mone.recommendationDetail")
    assert "setLoading(false)" in core_block[ohlcv:recommendation]
    assert "mone.news" not in core_block


def test_more_and_holdings_do_not_block_on_unrelated_work() -> None:
    advanced = read("mone-web-app/frontend/components/pages/AdvancedPage.tsx")
    holdings = read("mone-web-app/frontend/components/pages/HoldingsPage.tsx")
    assert 'if (tab !== "calculator") return;' in advanced
    assert "dynamicImport(() => import" in advanced
    assert "const HOLDINGS_API_TIMEOUT_MS = 15000;" in holdings
    assert 'emptyHoldingsPayload("all", true)' in holdings


def test_no_data_and_default_chart_paths_are_fast_by_construction() -> None:
    stabilizer = read("mone-web-app/backend/app/engine/mone_v65_api_stabilizer.py")
    final_engine = read("mone-web-app/backend/app/services/final_engine.py")
    chart = read("mone-web-app/frontend/components/pages/ChartPage.tsx")
    no_data = stabilizer.index('if not payload.get("items")')
    expensive = stabilizer.index('_record_virtual_ledger(payload.get("items", [])', no_data)
    assert "return payload" in stabilizer[no_data:expensive]
    assert "enrichedItemCount" in final_engine
    assert "rows[1:9]" in final_engine
    assert 'selected.id.startsWith("fallback-")' in chart


def test_no_data_payload_does_not_run_expensive_safety_stack(monkeypatch) -> None:
    from app.engine import mone_v65_api_stabilizer as stabilizer

    monkeypatch.setattr(
        stabilizer,
        "_recommendations_payload_cached",
        lambda *args, **kwargs: {
            "status": "NO_DATA",
            "market": "kr",
            "mode": "balanced",
            "horizon": "swing",
            "count": 0,
            "items": [],
        },
    )
    monkeypatch.setattr(
        stabilizer,
        "_record_virtual_ledger",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("expensive stack ran")),
    )

    result = stabilizer._recommendations_payload("kr", "balanced", "swing", 0, 50, False)

    assert result["status"] == "NO_DATA"
    assert result["reviewOnly"] is True
    assert result["tradeSafety"]["isTradeBlocked"] is True
    assert result["noDataReason"] == "MARKET_OR_EXPECTED_VALUE_GATE"


def test_recommendation_detail_enriches_only_primary_row(monkeypatch) -> None:
    from app.services import final_engine

    rows = [
        {"symbol": "005930", "market": "kr", "mode": "balanced", "horizon": "swing", "detailScore": 100 - index}
        for index in range(12)
    ]
    calls: list[int] = []
    monkeypatch.setattr(final_engine, "_recommendation_detail_rows", lambda market, symbol: rows)

    def enrich(row, market, symbol):
        calls.append(int(row["detailScore"]))
        return {**row, "enriched": True}

    monkeypatch.setattr(final_engine, "_enrich_recommendation_detail_item", enrich)

    result = final_engine.recommendation_detail("kr", "005930")

    assert calls == [100]
    assert result["count"] == 12
    assert result["enrichedItemCount"] == 1
    assert len(result["items"]) == 9
    assert result["item"]["enriched"] is True
    assert "enriched" not in result["items"][1]


def test_health_bootstrap_proxy_keeps_root_health_path() -> None:
    route = read("mone-web-app/frontend/app/mone-api/[...path]/route.ts")
    assert 'joinedPath.startsWith("health/")' in route
    assert '? `/${joinedPath}`' in route
