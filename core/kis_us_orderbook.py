from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from core.kis_us_client import first_num, kis_us_request, payload_outputs
from core.kis_us_quote import kis_us_exchange_candidates, normalize_us_ticker

US_ORDERBOOK_PATH = "/uapi/overseas-price/v1/quotations/inquire-asking-price"
US_ORDERBOOK_TR_ID = "HHDFS76200100"
_DEBUG_SAMPLE_PATH = Path("reports") / "kis_us_orderbook_sample_structure.json"

_BID_PRICE_KEYS = (
    "pbid1", "pbid2", "pbid3", "pbid4", "pbid5",
    "bidp", "bidp1", "bidp2", "bidp3", "bid_price", "bid",
)
_ASK_PRICE_KEYS = (
    "pask1", "pask2", "pask3", "pask4", "pask5",
    "askp", "askp1", "askp2", "askp3", "ask_price", "ask",
)
_BID_VOL_KEYS = (
    "vbid1", "vbid2", "vbid3", "vbid4", "vbid5",
    "bvol", "bid_vol", "bidp_rsqn", "bid_rsqn", "bidp1_rsqn", "bidp_rsqn1",
)
_ASK_VOL_KEYS = (
    "vask1", "vask2", "vask3", "vask4", "vask5",
    "avol", "ask_vol", "askp_rsqn", "ask_rsqn", "askp1_rsqn", "askp_rsqn1",
)


def _row_field_names(row: dict[str, Any]) -> list[str]:
    return sorted(str(k) for k in row.keys())


def _save_debug_sample(payload: dict[str, Any], excd: str, sym: str) -> None:
    """Persist response key layout only (no tokens/secrets)."""
    try:
        sample: dict[str, Any] = {"symbol": sym, "excd": excd, "outputs": {}}
        for key in ("output", "output1", "output2", "output3"):
            block = payload.get(key)
            if isinstance(block, dict):
                sample["outputs"][key] = {"fields": _row_field_names(block)}
            elif isinstance(block, list) and block:
                first = next((item for item in block if isinstance(item, dict)), None)
                if first:
                    sample["outputs"][key] = {"fields": _row_field_names(first), "row_count": len(block)}
        _DEBUG_SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DEBUG_SAMPLE_PATH.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _collect_orderbook_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload_outputs(payload)
    if rows:
        return rows
    for key, block in payload.items():
        if not str(key).lower().startswith("output"):
            continue
        if isinstance(block, dict):
            rows.append(block)
        elif isinstance(block, list):
            rows.extend(item for item in block if isinstance(item, dict))
    return rows


def _level_index(key: str) -> int:
    match = re.search(r"(\d+)$", key)
    return int(match.group(1)) if match else 1


def _parse_orderbook_outputs(rows: list[dict[str, Any]], excd: str) -> dict[str, Any]:
    bid_total = 0.0
    ask_total = 0.0
    best_bid = math.nan
    best_ask = math.nan
    for row in rows:
        if not isinstance(row, dict):
            continue
        bid_prices: list[tuple[int, float]] = []
        ask_prices: list[tuple[int, float]] = []
        for key, value in row.items():
            key_l = str(key).lower()
            num = first_num({key: value})
            if math.isnan(num) or num <= 0:
                continue
            if key_l in _BID_PRICE_KEYS or key_l.startswith("pbid") or key_l.startswith("bidp"):
                bid_prices.append((_level_index(key_l), num))
            elif key_l in _ASK_PRICE_KEYS or key_l.startswith("pask") or key_l.startswith("askp"):
                ask_prices.append((_level_index(key_l), num))
        if bid_prices:
            best_bid = max(p for _, p in bid_prices) if math.isnan(best_bid) else max(best_bid, max(p for _, p in bid_prices))
        if ask_prices:
            best_ask = min(p for _, p in ask_prices) if math.isnan(best_ask) else min(best_ask, min(p for _, p in ask_prices))

        bid_qty = first_num(row, *_BID_VOL_KEYS, default=0.0)
        ask_qty = first_num(row, *_ASK_VOL_KEYS, default=0.0)
        if not math.isnan(bid_qty) and bid_qty > 0:
            bid_total += bid_qty
        if not math.isnan(ask_qty) and ask_qty > 0:
            ask_total += ask_qty

        if math.isnan(best_bid):
            fallback_bid = first_num(row, *_BID_PRICE_KEYS)
            if not math.isnan(fallback_bid) and fallback_bid > 0:
                best_bid = fallback_bid
        if math.isnan(best_ask):
            fallback_ask = first_num(row, *_ASK_PRICE_KEYS)
            if not math.isnan(fallback_ask) and fallback_ask > 0:
                best_ask = fallback_ask

    has_prices = not math.isnan(best_bid) and not math.isnan(best_ask) and best_bid > 0 and best_ask > 0
    has_volumes = bid_total > 0 or ask_total > 0
    if not has_prices and not has_volumes:
        return {
            "ok": False,
            "failure_reason": "no_orderbook_fields",
            "orderbook_data_source": "kis_us_orderbook",
            "kis_exchange": excd,
        }
    total = bid_total + ask_total
    spread = (best_ask - best_bid) if has_prices else math.nan
    ref = (best_bid + best_ask) / 2 if has_prices else math.nan
    return {
        "ok": True,
        "failure_reason": "",
        "orderbook_data_source": "kis_us_orderbook",
        "kis_exchange": excd,
        "bid_total_volume": bid_total,
        "ask_total_volume": ask_total,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_ask_spread": spread,
        "bid_ask_spread_pct": (spread / ref * 100) if has_prices and not math.isnan(ref) and ref > 0 else math.nan,
        "bid_ask_ratio": bid_total / ask_total if ask_total > 0 else (999.0 if bid_total > 0 else math.nan),
        "orderbook_imbalance": (bid_total - ask_total) / total if total > 0 else math.nan,
        "bid_ask_imbalance": (bid_total - ask_total) / total if total > 0 else math.nan,
    }


def _preferred_exchange_only(target_row: dict[str, Any] | None) -> str:
    if not target_row:
        return ""
    for col in ("excd", "exchange", "exchange_code", "market_exchange", "listing_exchange", "ovrs_excg_cd"):
        raw = str(target_row.get(col, "") or "").strip().upper()
        if raw in {"NAS", "NYS", "AMS", "NASDAQ", "NYSE", "AMEX"}:
            from core.kis_us_quote import _EXCHANGE_ALIASES

            return _EXCHANGE_ALIASES.get(raw, raw[:3] if raw in {"NAS", "NYS", "AMS"} else "")
    return ""


def _exchange_attempt_list(sym: str, target_row: dict[str, Any] | None) -> list[str]:
    preferred = _preferred_exchange_only(target_row)
    if preferred:
        return [preferred]
    return kis_us_exchange_candidates(sym, target_row)


def fetch_kis_us_orderbook_api(symbol: str, target_row: dict[str, Any] | None = None) -> dict[str, Any]:
    sym = normalize_us_ticker(symbol)
    if not sym:
        return {"ok": False, "failure_reason": "invalid_symbol", "orderbook_data_source": "kis_us_orderbook"}
    attempt_errors: list[str] = []
    last_excd = ""
    saw_http_ok = False
    for excd in _exchange_attempt_list(sym, target_row):
        last_excd = excd
        result = kis_us_request(
            US_ORDERBOOK_PATH,
            US_ORDERBOOK_TR_ID,
            {"AUTH": "", "EXCD": excd, "SYMB": sym},
        )
        if not result.get("ok"):
            attempt_errors.append(f"EXCD={excd}|{result.get('failure_reason', 'unknown')}")
            continue
        saw_http_ok = True
        payload = result.get("payload") or {}
        if isinstance(payload, dict):
            _save_debug_sample(payload, excd, sym)
        rows = _collect_orderbook_rows(payload if isinstance(payload, dict) else {})
        parsed = _parse_orderbook_outputs(rows, excd)
        if parsed.get("ok"):
            parsed["kis_exchange_code"] = excd
            return parsed
        attempt_errors.append(f"EXCD={excd}|{parsed.get('failure_reason', 'no_orderbook_fields')}")
        if _preferred_exchange_only(target_row):
            break

    if saw_http_ok and any("no_orderbook_fields" in err for err in attempt_errors):
        return {
            "ok": False,
            "failure_reason": "no_orderbook_fields",
            "orderbook_data_source": "kis_us_orderbook",
            "kis_exchange": last_excd,
            "kis_exchange_code": last_excd,
            "kis_quote_error": "; ".join(attempt_errors) if attempt_errors else "no_orderbook_fields",
        }
    return {
        "ok": False,
        "failure_reason": "api_response_empty",
        "orderbook_data_source": "kis_us_orderbook",
        "kis_exchange": last_excd,
        "kis_exchange_code": last_excd,
        "kis_quote_error": "; ".join(attempt_errors) if attempt_errors else "all_exchange_attempts_failed",
    }
