from __future__ import annotations

import json
from core.backtest_beta_engine import save_backtest_beta_summary

if __name__ == "__main__":
    print(json.dumps(save_backtest_beta_summary(), ensure_ascii=False, indent=2, default=str))
