from __future__ import annotations

import json


def main() -> int:
    try:
        from core.v65_maximum_ux_engine import run_v65_update
        res = run_v65_update(fetch_news=True, fetch_missing_prices=True)
    except Exception as exc:
        res = {"status":"ERROR", "error":f"{type(exc).__name__}: {exc}"}
    print(json.dumps({"status":"OK" if res.get("status") != "ERROR" else "ERROR", "app":"MONE", "v66":"mone_ux_cleanup", "result":res}, ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("status") != "ERROR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
