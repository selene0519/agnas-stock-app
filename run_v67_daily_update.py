from __future__ import annotations

import json


def main() -> int:
    try:
        from core.v67_previous_close_engine import run_v67_update
        res = run_v67_update(fetch_news=True, fetch_missing_prices=True)
    except Exception as exc:
        res = {"status":"ERROR", "error":f"{type(exc).__name__}: {exc}"}
    print(json.dumps(res, ensure_ascii=False, indent=2, default=str))
    return 0 if res.get("status") != "ERROR" else 2


if __name__ == "__main__":
    raise SystemExit(main())
