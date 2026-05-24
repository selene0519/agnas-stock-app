from core.v75_donhyun_quant_complete_engine import run_v75_update

if __name__ == '__main__':
    import json
    res = run_v75_update(fetch_news=True, fetch_fundamentals=True, fetch_macro=True)
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
