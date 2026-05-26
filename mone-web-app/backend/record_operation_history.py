from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services import operation_history


def main() -> None:
    parser = argparse.ArgumentParser(description="Record MONE prediction and virtual operation history snapshots.")
    parser.add_argument("--market", default="all", choices=["all", "kr", "us"])
    parser.add_argument("--modes", default="all", help="all or comma-separated conservative,balanced,aggressive")
    parser.add_argument("--source", default=os.environ.get("MONE_HISTORY_SOURCE", "scheduled"))
    parser.add_argument("--backfill-existing", action="store_true")
    args = parser.parse_args()

    result = operation_history.save_current_snapshot(
        market=args.market,
        modes=args.modes,
        source=args.source,
        include_backfill=args.backfill_existing,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
