from __future__ import annotations
import json
from core.v43_operational_engine import run_v43_update

if __name__ == "__main__":
    result = run_v43_update()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    raise SystemExit(0 if result.get("status") == "OK" else 2)
