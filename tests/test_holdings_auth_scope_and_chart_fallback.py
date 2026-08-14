from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_holdings_are_user_scoped_and_anonymous_view_never_fetches_private_rows() -> None:
    holdings = read("mone-web-app/frontend/components/pages/HoldingsPage.tsx")
    boot = read("mone-web-app/frontend/lib/bootPreload.ts")

    assert 'return `${LS_HOLDINGS_KEY}:${scope}`' in holdings
    assert "_holdingsCache.userScope !== userScope" in holdings
    load_start = holdings.index("async function load(options")
    auth_guard = holdings.index("if (!hasHoldingsAuth)", load_start)
    request = holdings.index("mone.holdingsClean", load_start)
    assert auth_guard < request
    assert "writeHoldingsCache(market, empty, loadedAt, userScope)" in holdings
    assert 'loadHoldingsFromLocalStorage({ includeLegacy: true })' in holdings
    assert 'scope !== "anonymous"' in holdings
    assert "localStorage.removeItem(LS_HOLDINGS_KEY)" in holdings

    assert 'const BOOT_CACHE_KEY = "mone:boot-preload:v7"' in boot
    assert 'return `${BOOT_CACHE_KEY}:${getAuthenticatedUserId() || "anonymous"}`' in boot


def test_backend_only_exposes_legacy_csv_after_authentication() -> None:
    main = read("mone-web-app/backend/app/main.py")
    legacy_start = main.index("def _legacy_holdings_payload")
    anon_start = main.index("def _anon_or_empty_payload", legacy_start)
    route_start = main.index('@app.get("/api/holdings-clean")', anon_start)
    anon_block = main[anon_start:route_start]
    route_block = main[route_start:main.index('@app.get("/api/final/holdings-clean")', route_start)]

    assert "if _local_dev_bypass():" in anon_block
    assert "return _empty_holdings_payload(market)" in anon_block
    assert "fallback = _legacy_holdings_payload(market, limit)" in route_block


def test_ohlcv_analysis_does_not_require_a_recommendation_score() -> None:
    chart = read("mone-web-app/frontend/components/pages/ChartPage.tsx")

    assert "const analysisReady = rows.length >= 20 && currentPrice > 0;" in chart
    assert "Number(moneConclusion?.score || 0) > 0" not in chart
    assert "기술 분석 표시 중" in chart
    assert "추천 후보가 아닙니다" in chart
    assert "recommendationEntryPrice || atrPlan?.entry || currentPrice" in chart