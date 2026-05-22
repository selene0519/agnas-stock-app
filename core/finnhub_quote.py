from __future__ import annotations

import json
import math
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

FINNHUB_CONFIG_FILE = Path("finnhub_config.json")


def load_finnhub_api_key() -> str:
    import os

    key = os.environ.get("FINNHUB_API_KEY", "").strip()
    if key:
        return key
    try:
        if FINNHUB_CONFIG_FILE.exists():
            cfg = json.loads(FINNHUB_CONFIG_FILE.read_text(encoding="utf-8"))
            if bool(cfg.get("enabled", True)):
                return str(cfg.get("api_key", "")).strip()
    except Exception:
        return ""
    return ""


def is_finnhub_quote_symbol(symbol: str) -> bool:
    s = str(symbol or "").strip().upper()
    if not s:
        return False
    if s.startswith("^") or "=" in s or s.endswith(".KS") or s.endswith(".KQ"):
        return False
    if "-" in s:
        return False
    if s.isdigit():
        return False
    return bool(re.fullmatch(r"[A-Z]{1,6}(\.[A-Z])?", s))


def fetch_finnhub_intraday_quote(symbol: str, api_key: str | None = None) -> dict[str, Any]:
    """Finnhub /quote for US symbols. No volume fabrication when missing."""
    sym = str(symbol or "").strip().upper()
    key = (api_key or load_finnhub_api_key()).strip()
    if not key or not is_finnhub_quote_symbol(sym):
        return {"ok": False, "failure_reason": "endpoint_not_configured", "quote_source": "finnhub"}
    params = urllib.parse.urlencode({"symbol": sym, "token": key})
    url = f"https://finnhub.io/api/v1/quote?{params}"
    try:
        with urllib.request.urlopen(url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return {"ok": False, "failure_reason": "api_response_empty", "quote_source": "finnhub"}

    try:
        last = float(payload.get("c") or 0)
    except (TypeError, ValueError):
        last = 0.0
    if not last or last <= 0 or math.isnan(last):
        return {"ok": False, "failure_reason": "api_response_empty", "quote_source": "finnhub"}

    change_pct = 0.0
    try:
        change_pct = float(payload.get("dp") or 0)
    except (TypeError, ValueError):
        change_pct = 0.0
    return {
        "ok": True,
        "failure_reason": "",
        "last_price": last,
        "intraday_change_pct": change_pct,
        "intraday_volume": 0.0,
        "intraday_trading_value": 0.0,
        "quote_full_available": False,
        "quote_partial_available": True,
        "quote_source": "finnhub_quote",
    }
