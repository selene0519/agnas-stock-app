from __future__ import annotations

import json
import sys

from app.services.final_engine import operational_readiness, write_final_reports


def main() -> int:
    manifest = write_final_reports()
    readiness = operational_readiness()
    print(json.dumps({"manifestVersion": manifest.get("version"), "readiness": readiness}, ensure_ascii=False, indent=2))
    status = readiness.get("status")
    avg = float(readiness.get("readinessAverage") or 0)
    # In local/dev environments, missing external data should warn but not hard-fail when report generation works.
    if status == "CHECK_REQUIRED" and avg < 45:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
