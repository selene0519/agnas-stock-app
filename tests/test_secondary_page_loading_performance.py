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
