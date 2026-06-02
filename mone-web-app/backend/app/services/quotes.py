from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

from app.services import data_loader as data


KST = timezone(timedelta(hours=9))
KIS_TOKEN_CACHE_FILE = data.CACHE_DIR / "kis_token_cache.json"

US_EXCHANGE_FALLBACKS: dict[str, list[str]] = {
    "AAPL": ["NAS", "NYS", "AMS"],
    "MSFT": ["NAS", "NYS", "AMS"],
    "NVDA": ["NAS", "NYS", "AMS"],
    "AMD": ["NAS", "NYS", "AMS"],
    "AVGO": ["NAS", "NYS", "AMS"],
    "META": ["NAS", "NYS", "AMS"],
    "GOOGL": ["NAS", "NYS", "AMS"],
    "GOOG": ["NAS", "NYS", "AMS"],
    "AMZN": ["NAS", "NYS", "AMS"],
    "TSLA": ["NAS", "NYS", "AMS"],
    "PLTR": ["NYS", "NAS", "AMS"],
    "TSM": ["NYS", "NAS", "AMS"],
    "QQQ": ["NAS", "AMS", "NYS"],
    "SPY": ["AMS", "NYS", "NAS"],
    "SMH": ["AMS", "NAS", "NYS"],
}


def _now_label() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _safe_float(value: Any) -> float | None:
    return data._safe_float(value)


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _kis_config() -> dict[str, Any]:
    is_mock = _env("KIS_IS_MOCK").lower() in {"1", "true", "yes", "y", "mock", "모의"}
    return {
        "app_key": _env("KIS_APP_KEY"),
        "app_secret": _env("KIS_APP_SECRET"),
        "is_mock": is_mock,
        "base_url": "https://openapivts.koreainvestment.com:29443" if is_mock else "https://openapi.koreainvestment.com:9443",
    }


def _kis_enabled() -> bool:
    cfg = _kis_config()
    return bool(cfg["app_key"] and cfg["app_secret"])


def _kis_access_token(force_refresh: bool = False) -> str:
    cfg = _kis_config()
    if not _kis_enabled():
        return ""
    try:
        if not force_refresh and KIS_TOKEN_CACHE_FILE.exists():
            cache = data.read_json(KIS_TOKEN_CACHE_FILE)
            token = str(cache.get("access_token", "") or "")
            expires_at = _safe_float(cache.get("expires_at")) or 0
            if token and expires_at > time.time() + 180:
                return token
    except Exception:
        pass

    try:
        response = requests.post(
            f"{cfg['base_url']}/oauth2/tokenP",
            json={"grant_type": "client_credentials", "appkey": cfg["app_key"], "appsecret": cfg["app_secret"]},
            timeout=10,
        )
        payload = response.json() if response.text else {}
        token = str(payload.get("access_token", "") or "")
        if response.status_code == 200 and token:
            expires_in = int(_safe_float(payload.get("expires_in")) or 86400)
            data.write_json(
                KIS_TOKEN_CACHE_FILE,
                {
                    "access_token": token,
                    "expires_at": time.time() + max(60, expires_in - 300),
                    "issued_at": _now_label(),
                    "is_mock": bool(cfg["is_mock"]),
                },
            )
            return token
    except Exception:
        return ""
    return ""


def _kis_headers(tr_id: str, force_refresh: bool = False) -> dict[str, str]:
    cfg = _kis_config()
    token = _kis_access_token(force_refresh=force_refresh)
    if not token:
        return {}
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": cfg["app_key"],
        "appsecret": cfg["app_secret"],
        "tr_id": tr_id,
        "custtype": "P",
    }


def _quote_result(symbol: str, market: str, ok: bool, source: str, error: str = "", price: float | None = None) -> dict[str, Any]:
    return {
        "symbol": data.normalize_symbol(symbol, market),
        "market": market,
        "ok": ok,
        "currentPrice": price,
        "priceTime": _now_label() if ok else "",
        "priceSource": source if ok else "가격출처 없음",
        "source": source,
        "error": error,
    }


def _fetch_kis_kr(symbol: str) -> dict[str, Any]:
    normalized = data.normalize_symbol(symbol, "kr")
    if not _kis_enabled():
        return _quote_result(normalized, "kr", False, "KIS 현재가", "KIS_APP_KEY/KIS_APP_SECRET 미설정")
    if not normalized.isdigit():
        return _quote_result(normalized, "kr", False, "KIS 현재가", "국장 종목코드 형식 아님")

    cfg = _kis_config()
    url = f"{cfg['base_url']}/uapi/domestic-stock/v1/quotations/inquire-price"
    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": normalized.zfill(6)}
    last_error = ""
    for force in (False, True):
        headers = _kis_headers("FHKST01010100", force_refresh=force)
        if not headers:
            return _quote_result(normalized, "kr", False, "KIS 현재가", "KIS token 발급 실패")
        try:
            response = requests.get(url, headers=headers, params=params, timeout=8)
            payload = response.json() if response.text else {}
            if response.status_code == 200 and payload.get("rt_cd") == "0":
                output = payload.get("output", {}) or {}
                price = _safe_float(output.get("stck_prpr"))
                if price and price > 0:
                    return _quote_result(normalized, "kr", True, "KIS 현재가", price=price)
                last_error = "현재가 응답 비어 있음"
            else:
                last_error = f"{response.status_code}/{payload.get('msg_cd','')}/{payload.get('msg1','')}"
        except Exception as exc:
            last_error = str(exc)[:160]
    return _quote_result(normalized, "kr", False, "KIS 현재가", last_error or "KIS 현재가 실패")


def _us_symbol(symbol: str) -> str:
    return str(symbol or "").upper().strip().replace("$", "").replace(".US", "")


def _us_exchange_candidates(symbol: str) -> list[str]:
    clean = _us_symbol(symbol)
    if not clean or clean.startswith("^") or "=" in clean or "-" in clean or clean.isdigit():
        return []
    base = list(US_EXCHANGE_FALLBACKS.get(clean, []))
    for item in ("NAS", "NYS", "AMS"):
        if item not in base:
            base.append(item)
    return base


def _fetch_kis_us(symbol: str) -> dict[str, Any]:
    clean = _us_symbol(symbol)
    if not _kis_enabled():
        return _quote_result(clean, "us", False, "KIS 해외 현재가", "KIS_APP_KEY/KIS_APP_SECRET 미설정")
    candidates = _us_exchange_candidates(clean)
    if not candidates:
        return _quote_result(clean, "us", False, "KIS 해외 현재가", "미장 종목 형식 아님")
    cfg = _kis_config()
    url = f"{cfg['base_url']}/uapi/overseas-price/v1/quotations/price-detail"
    last_error = ""
    for exchange in candidates:
        for force in (False, True):
            headers = _kis_headers("HHDFS76200200", force_refresh=force)
            if not headers:
                return _quote_result(clean, "us", False, "KIS 해외 현재가", "KIS token 발급 실패")
            try:
                response = requests.get(url, headers=headers, params={"AUTH": "", "EXCD": exchange, "SYMB": clean}, timeout=8)
                payload = response.json() if response.text else {}
                if response.status_code == 200 and payload.get("rt_cd") == "0":
                    output = payload.get("output", {}) or {}
                    price = _safe_float(output.get("last"))
                    if price and price > 0:
                        result = _quote_result(clean, "us", True, f"KIS 해외 현재가 · {exchange}", price=price)
                        result["exchange"] = exchange
                        return result
                    last_error = f"{exchange}: 현재가 응답 비어 있음"
                else:
                    last_error = f"{exchange}:{response.status_code}/{payload.get('msg_cd','')}/{payload.get('msg1','')}"
            except Exception as exc:
                last_error = f"{exchange}:{str(exc)[:120]}"
    return _quote_result(clean, "us", False, "KIS 해외 현재가", last_error or "KIS 해외 현재가 실패")


def _is_finnhub_symbol(symbol: str) -> bool:
    clean = _us_symbol(symbol)
    return bool(clean and clean.replace(".", "").isalpha() and "-" not in clean and "=" not in clean and not clean.startswith("^"))


def _fetch_finnhub(symbol: str) -> dict[str, Any]:
    clean = _us_symbol(symbol)
    key = _env("FINNHUB_API_KEY")
    if not key:
        return _quote_result(clean, "us", False, "Finnhub", "FINNHUB_API_KEY 미설정")
    if not _is_finnhub_symbol(clean):
        return _quote_result(clean, "us", False, "Finnhub", "Finnhub 지원 종목 형식 아님")
    try:
        response = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": clean, "token": key}, timeout=8)
        payload = response.json() if response.text else {}
        price = _safe_float(payload.get("c"))
        if response.status_code == 200 and price and price > 0:
            result = _quote_result(clean, "us", True, "Finnhub 현재가", price=price)
            timestamp = _safe_float(payload.get("t"))
            if timestamp and timestamp > 0:
                result["priceTime"] = datetime.fromtimestamp(int(timestamp), tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S KST")
            return result
        return _quote_result(clean, "us", False, "Finnhub", f"{response.status_code}/empty_price")
    except Exception as exc:
        return _quote_result(clean, "us", False, "Finnhub", str(exc)[:160])


def _fetch_quote(symbol: str, market: str) -> dict[str, Any]:
    if market == "kr":
        return _fetch_kis_kr(symbol)
    kis = _fetch_kis_us(symbol)
    if kis.get("ok"):
        return kis
    finnhub = _fetch_finnhub(symbol)
    if finnhub.get("ok"):
        finnhub["fallbackFrom"] = kis.get("error", "")
        return finnhub
    finnhub["fallbackFrom"] = kis.get("error", "")
    return finnhub


def _refresh_targets(market: str, symbols: str | None, max_symbols: int) -> list[str]:
    if symbols:
        raw = [item.strip() for item in symbols.split(",") if item.strip()]
        return [data.normalize_symbol(item, market) for item in raw][:max_symbols]
    target_symbols: list[str] = []
    target_files = [
        data.REPO_ROOT / "data" / "stockapp" / f"price_collection_universe_{market}.csv",
        data.REPO_ROOT / "data" / "stockapp" / f"kis_collection_targets_{market}.csv",
    ]
    for path in target_files:
        for item in data.dataframe_records(data.read_csv(path)):
            symbol = data.normalize_symbol(item.get("symbol"), market)
            if symbol and symbol not in target_symbols:
                target_symbols.append(symbol)
            if len(target_symbols) >= max_symbols:
                return target_symbols
    for collection in (data.positions(market).get("items", []), data.symbols(market).get("items", [])):
        for item in collection:
            symbol = data.normalize_symbol(item.get("symbol"), market)
            if symbol and symbol not in target_symbols:
                target_symbols.append(symbol)
            if len(target_symbols) >= max_symbols:
                return target_symbols
    return target_symbols


def refresh_quotes(market: str = "all", symbols: str | None = None, max_symbols: int = 80) -> dict[str, Any]:
    markets = ["kr", "us"] if market == "all" else [market]
    cache = data.quote_cache()
    cache.setdefault("markets", {}).setdefault("kr", {})
    cache.setdefault("markets", {}).setdefault("us", {})

    refreshed: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for current_market in markets:
        for symbol in _refresh_targets(current_market, symbols, max_symbols):
            quote = _fetch_quote(symbol, current_market)
            if quote.get("ok"):
                normalized = data.normalize_symbol(symbol, current_market)
                cache["markets"][current_market][normalized] = quote
                refreshed.append(quote)
            else:
                cached = data.cached_quote_for(symbol, current_market)
                quote["fallbackKept"] = bool(cached and cached.get("ok"))
                failed.append(quote)

    updated_at = _now_label()
    cache["updatedAt"] = updated_at
    cache["lastRefresh"] = {
        "market": market,
        "requestedSymbols": symbols or "",
        "refreshed": len(refreshed),
        "failed": len(failed),
        "updatedAt": updated_at,
    }
    data.save_quote_cache(cache)

    if refreshed and failed:
        status = "PARTIAL"
    elif refreshed:
        status = "OK"
    else:
        status = "NO_REFRESH"
    return {
        "status": status,
        "market": market,
        "updatedAt": updated_at,
        "cachePath": data.QUOTE_CACHE_FILE.relative_to(data.APP_DIR).as_posix(),
        "refreshed": len(refreshed),
        "failed": len(failed),
        "items": refreshed[:50],
        "failedItems": failed[:50],
        "providers": {
            "kis": "OK" if _kis_enabled() else "MISSING",
            "finnhub": "OK" if bool(_env("FINNHUB_API_KEY")) else "MISSING",
        },
    }
