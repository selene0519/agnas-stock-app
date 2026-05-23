from core.v65_maximum_ux_engine import run_v65_update
import json
if __name__ == "__main__":
    print(json.dumps(run_v65_update(fetch_news=True, fetch_missing_prices=True), ensure_ascii=False, indent=2, default=str))
