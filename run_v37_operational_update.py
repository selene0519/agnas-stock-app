from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

from core.operational_plus_engine import (
    build_buy_budget_table,
    build_sell_budget_table,
    build_news_narrative_table,
    build_financial_kpi_table,
    build_macro_table,
)

REPORT_DIR = Path("reports")
REPORT_DIR.mkdir(exist_ok=True)

status = {"updated_at": datetime.now().isoformat(timespec="seconds"), "reports": {}}
for market in ["한국주식", "미국주식"]:
    slug = "kr" if market == "한국주식" else "us"
    jobs = [
        (f"operational_buy_budget_{slug}.csv", build_buy_budget_table(market)),
        (f"operational_sell_budget_{slug}.csv", build_sell_budget_table(market)),
        (f"operational_news_narrative_{slug}.csv", build_news_narrative_table(market)),
        (f"operational_financial_kpi_{slug}.csv", build_financial_kpi_table(market)),
        (f"operational_macro_{slug}.csv", build_macro_table(market)),
    ]
    for name, df in jobs:
        path = REPORT_DIR / name
        try:
            df.to_csv(path, index=False, encoding="utf-8-sig")
            status["reports"][name] = {"rows": int(len(df)), "status": "OK"}
        except Exception as exc:
            status["reports"][name] = {"rows": 0, "status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}

(REPORT_DIR / "v37_operational_update_status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(status, ensure_ascii=False, indent=2))
