from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "mone-web-app" / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.ai_paper_trader import run_cycle, status  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MONE AI paper trading cycle.")
    parser.add_argument("--market", choices=["kr", "us", "all"], default="all")
    parser.add_argument("--execute", action="store_true", help="Write paper trades and NAV snapshots.")
    parser.add_argument("--status", action="store_true", help="Print current AI paper account status.")
    args = parser.parse_args()

    payload = status(args.market) if args.status else run_cycle(args.market, dry_run=not args.execute)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
