from core.v74_mone_complete_integration_engine import run_v74_update

if __name__ == '__main__':
    import json
    res = run_v74_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
