import os
import json
import traceback
from pathlib import Path

print("=== ENV CHECK ===")
for k in [
    "KIS_APP_KEY",
    "KIS_APP_SECRET",
    "FINNHUB_API_KEY",
    "DART_API_KEY",
    "SEC_API_KEY",
    "GNEWS_API_KEY",
    "APIFY_TOKEN",
]:
    v = os.environ.get(k, "")
    print(f"{k}: {'OK' if v else 'MISSING'}")

print("\n=== IMPORT APP ===")
try:
    import app
    print("app import: OK")
except Exception as e:
    print("app import: FAIL")
    print(type(e).__name__, str(e))
    traceback.print_exc()
    raise SystemExit(1)

print("\n=== KIS CONFIG ===")
try:
    if hasattr(app, "kis_config_v9960"):
        cfg = app.kis_config_v9960()
        print("kis enabled:", cfg.get("enabled"))
        print("kis base_url:", cfg.get("base_url"))
        print("app_key exists:", bool(cfg.get("app_key")))
        print("app_secret exists:", bool(cfg.get("app_secret")))
    else:
        print("kis_config_v9960: MISSING")
except Exception as e:
    print("kis config error:", type(e).__name__, str(e))

print("\n=== KIS DOMESTIC PRICE TEST: 005930 ===")
try:
    if hasattr(app, "fetch_kis_domestic_price_v9960"):
        r = app.fetch_kis_domestic_price_v9960("005930")
        safe = {k: r.get(k) for k in ["ok", "symbol", "last_price", "change_rate", "last_time", "source", "error"]}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
    else:
        print("fetch_kis_domestic_price_v9960: MISSING")
except Exception as e:
    print("domestic price error:", type(e).__name__, str(e))
    traceback.print_exc()

print("\n=== KIS US PRICE TEST: AAPL ===")
try:
    if hasattr(app, "fetch_kis_overseas_price_v9962"):
        r = app.fetch_kis_overseas_price_v9962("AAPL")
        safe = {k: r.get(k) for k in ["ok", "symbol", "last_price", "change_rate", "last_time", "source", "error"]}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
    else:
        print("fetch_kis_overseas_price_v9962: MISSING")
except Exception as e:
    print("us price error:", type(e).__name__, str(e))
    traceback.print_exc()

print("\n=== FINNHUB PRICE TEST: AAPL ===")
try:
    if hasattr(app, "fetch_finnhub_quote_snapshot"):
        key = os.environ.get("FINNHUB_API_KEY", "")
        r = app.fetch_finnhub_quote_snapshot("AAPL", key)
        safe = {k: r.get(k) for k in ["ok", "symbol", "last_price", "change_rate", "source", "error"]}
        print(json.dumps(safe, ensure_ascii=False, indent=2))
    else:
        print("fetch_finnhub_quote_snapshot: MISSING")
except Exception as e:
    print("finnhub error:", type(e).__name__, str(e))
    traceback.print_exc()

print("\n=== FILE DATA CHECK ===")
for f in [
    "reports/v92_news_summary_kr.csv",
    "reports/v92_news_summary_us.csv",
    "daily_watch_selection.json",
    "data/holdings_kr.csv",
    "data/holdings_us.csv",
]:
    p = Path(f)
    print(f"{f}: {'OK' if p.exists() else 'MISSING'} / {p.stat().st_size if p.exists() else 0} bytes")
