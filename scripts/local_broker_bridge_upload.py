#!/usr/bin/env python
"""Upload sanitized broker holdings from a local PC to MONE.

This script is intended for Windows Task Scheduler. Broker API calls should run
locally on the user's PC, then this script uploads only the resulting holdings
snapshot to the backend. Do not put broker App Secret values in the frontend,
URL query strings, localStorage, sessionStorage, Render env vars, or Git.

Examples:
  python scripts/local_broker_bridge_upload.py --broker kis --file holdings.csv --user-token %MONE_USER_TOKEN%
  python scripts/local_broker_bridge_upload.py --broker toss --file toss_holdings.json --backend-url https://your-app.onrender.com

CSV columns accepted:
  symbol,name,market,quantity,avgPrice,currentPrice,evalAmount,profitLoss,profitLossRate,stopPrice,targetPrice
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def read_items(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(str(path))
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        items = payload.get("items") or payload.get("holdings") or []
        return [dict(item) for item in items if isinstance(item, dict)]
    # CSV: KIS 등 증권사 내보내기는 CP949/EUC-KR을 사용하는 경우가 많으므로 순서대로 시도
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with path.open("r", encoding=enc, newline="") as handle:
                rows = [dict(row) for row in csv.DictReader(handle)]
            if rows:
                print(f"[bridge] CSV decoded with {enc} ({len(rows)} rows)", flush=True)
            return rows
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception:
            break
    raise ValueError(f"Cannot decode CSV {path} — tried utf-8-sig, cp949, euc-kr, utf-8")


def post_json(url: str, token: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "MONE-LocalBrokerBridge/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:500]}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload sanitized broker holdings to MONE.")
    parser.add_argument("--broker", required=True, choices=["toss", "kis", "manual", "file"])
    parser.add_argument("--file", required=True, type=Path, help="CSV or JSON holdings snapshot")
    parser.add_argument("--backend-url", default=os.environ.get("MONE_BACKEND_URL", "http://localhost:8050"))
    parser.add_argument("--user-token", default=os.environ.get("MONE_USER_TOKEN", ""))
    parser.add_argument("--account-hint", default="", help="Masked account hint only, e.g. 123****789")
    parser.add_argument("--mode", default="replace_broker", choices=["replace_broker", "replace_all", "merge"])
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.user_token:
        print("ERROR: --user-token or MONE_USER_TOKEN is required.", file=sys.stderr)
        return 2

    items = read_items(args.file)
    payload = {
        "broker": args.broker,
        "source": "local_bridge",
        "accountNoHint": args.account_hint,
        "mode": args.mode,
        "items": items,
    }
    if args.dry_run:
        print(json.dumps({"count": len(items), "payloadPreview": payload}, ensure_ascii=False, indent=2)[:4000])
        return 0

    base = args.backend_url.rstrip("/")
    result = post_json(f"{base}/api/broker/local-bridge/upload", args.user_token, payload, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
