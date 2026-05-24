from core.v73_market_clean_visible_ui_engine import run_v73_update

if __name__ == '__main__':
    import json
    res = run_v73_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
