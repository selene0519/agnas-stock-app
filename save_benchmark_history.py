from __future__ import annotations

import json

from core.portfolio_history_engine import save_benchmark_daily_history

if __name__ == "__main__":
    df = save_benchmark_daily_history()
    counts = df.groupby("benchmark").size().to_dict() if not df.empty and "benchmark" in df.columns else {}
    print(json.dumps({
        "status": "OK" if counts else "NO_BENCHMARK_DATA",
        "rows": int(len(df)),
        "benchmark_counts": {str(k): int(v) for k, v in counts.items()},
        "path": "data/market/benchmark_daily.csv",
    }, ensure_ascii=False, indent=2))
