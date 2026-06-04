from __future__ import annotations

import os
import csv
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


def _ohlcv_path(symbol: str, market: str) -> Path:
    normalized = data.normalize_symbol(symbol, market)
    return data.REPO_ROOT / "data" / "market" / "ohlcv" / f"{market}_{normalized}_daily.csv"


def _write_ohlcv(symbol: str, market: str, rows: list[dict[str, Any]], source: str) -> dict[str, Any]:
    normalized = data.normalize_symbol(symbol, market)
    cleaned: dict[str, dict[str, Any]] = {}
    for row in rows:
        date_text = str(row.get("date") or "").strip()
        close = _safe_float(row.get("close"))
        if not date_text or not close or close <= 0:
            continue
        cleaned[date_text] = {
            "date": date_text,
            "open": row.get("open") or close,
            "high": row.get("high") or close,
            "low": row.get("low") or close,
            "close": close,
            "volume": row.get("volume") or "",
            "source": source,
            "updated_at": _now_label(),
        }
    ordered = [cleaned[key] for key in sorted(cleaned.keys())]
    if not ordered:
        return {"status": "NO_DATA", "market": market, "symbol": normalized, "count": 0, "error": "empty OHLCV rows"}

    path = _ohlcv_path(normalized, market)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["date", "open", "high", "low", "close", "volume", "source", "updated_at"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in ordered:
            writer.writerow({key: row.get(key, "") for key in fields})
    return {
        "status": "OK",
        "market": market,
        "symbol": normalized,
        "count": len(ordered),
        "path": path.relative_to(data.REPO_ROOT).as_posix(),
        "source": source,
        "latestDate": ordered[-1]["date"],
    }


def _fetch_kis_kr_daily_ohlcv(symbol: str, days: int = 120) -> dict[str, Any]:
    normalized = data.normalize_symbol(symbol, "kr")
    if not _kis_enabled():
        return {"status": "ERROR", "market": "kr", "symbol": normalized, "error": "KIS_APP_KEY/KIS_APP_SECRET 미설정"}
    if not normalized.isdigit():
        return {"status": "ERROR", "market": "kr", "symbol": normalized, "error": "국장 종목코드 형식 아님"}

    cfg = _kis_config()
    end = datetime.now(KST).strftime("%Y%m%d")
    start = (datetime.now(KST) - timedelta(days=max(20, days * 2))).strftime("%Y%m%d")
    url = f"{cfg['base_url']}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": normalized.zfill(6),
        "FID_INPUT_DATE_1": start,
        "FID_INPUT_DATE_2": end,
        "FID_PERIOD_DIV_CODE": "D",
        "FID_ORG_ADJ_PRC": "1",
    }
    last_error = ""
    for force in (False, True):
        headers = _kis_headers("FHKST03010100", force_refresh=force)
        if not headers:
            return {"status": "ERROR", "market": "kr", "symbol": normalized, "error": "KIS token 발급 실패"}
        try:
            response = requests.get(url, headers=headers, params=params, timeout=12)
            payload = response.json() if response.text else {}
            if response.status_code == 200 and payload.get("rt_cd") == "0":
                rows = []
                for item in payload.get("output2", []) or []:
                    rows.append({
                        "date": str(item.get("stck_bsop_date") or "").strip(),
                        "open": _safe_float(item.get("stck_oprc")),
                        "high": _safe_float(item.get("stck_hgpr")),
                        "low": _safe_float(item.get("stck_lwpr")),
                        "close": _safe_float(item.get("stck_clpr")),
                        "volume": _safe_float(item.get("acml_vol")),
                    })
                return _write_ohlcv(normalized, "kr", rows[-days:], "KIS 국내주식기간별시세")
            last_error = f"{response.status_code}/{payload.get('msg_cd','')}/{payload.get('msg1','')}"
        except Exception as exc:
            last_error = str(exc)[:160]
    return {"status": "ERROR", "market": "kr", "symbol": normalized, "error": last_error or "KIS 국내 OHLCV 실패"}


def _fetch_kis_us_daily_ohlcv(symbol: str, days: int = 120) -> dict[str, Any]:
    clean = _us_symbol(symbol)
    if not _kis_enabled():
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": "KIS_APP_KEY/KIS_APP_SECRET 미설정"}
    candidates = _us_exchange_candidates(clean)
    if not candidates:
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": "미장 종목 형식 아님"}

    cfg = _kis_config()
    bymd = datetime.now(KST).strftime("%Y%m%d")
    url = f"{cfg['base_url']}/uapi/overseas-price/v1/quotations/dailyprice"
    last_error = ""
    for exchange in candidates:
        params = {"AUTH": "", "EXCD": exchange, "SYMB": clean, "GUBN": "0", "BYMD": bymd, "MODP": "1"}
        for force in (False, True):
            headers = _kis_headers("HHDFS76240000", force_refresh=force)
            if not headers:
                return {"status": "ERROR", "market": "us", "symbol": clean, "error": "KIS token 발급 실패"}
            try:
                response = requests.get(url, headers=headers, params=params, timeout=12)
                payload = response.json() if response.text else {}
                if response.status_code == 200 and payload.get("rt_cd") == "0":
                    rows = []
                    for item in payload.get("output2", []) or []:
                        rows.append({
                            "date": str(item.get("xymd") or item.get("date") or "").strip(),
                            "open": _safe_float(item.get("open")),
                            "high": _safe_float(item.get("high")),
                            "low": _safe_float(item.get("low")),
                            "close": _safe_float(item.get("clos") or item.get("last")),
                            "volume": _safe_float(item.get("tvol") or item.get("evol")),
                        })
                    result = _write_ohlcv(clean, "us", rows[-days:], f"KIS 해외주식기간별시세 · {exchange}")
                    if result.get("status") == "OK":
                        result["exchange"] = exchange
                        return result
                    last_error = f"{exchange}: empty OHLCV rows"
                else:
                    last_error = f"{exchange}:{response.status_code}/{payload.get('msg_cd','')}/{payload.get('msg1','')}"
            except Exception as exc:
                last_error = f"{exchange}:{str(exc)[:120]}"
    return {"status": "ERROR", "market": "us", "symbol": clean, "error": last_error or "KIS 해외 OHLCV 실패"}


def _fetch_finnhub_daily_ohlcv(symbol: str, days: int = 120) -> dict[str, Any]:
    clean = _us_symbol(symbol)
    key = _env("FINNHUB_API_KEY")
    if not key:
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": "FINNHUB_API_KEY 미설정"}
    if not _is_finnhub_symbol(clean):
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": "Finnhub 지원 종목 형식 아님"}
    now = int(datetime.now(timezone.utc).timestamp())
    start = now - max(30, days * 3) * 86400
    try:
        response = requests.get(
            "https://finnhub.io/api/v1/stock/candle",
            params={"symbol": clean, "resolution": "D", "from": start, "to": now, "token": key},
            timeout=12,
        )
        payload = response.json() if response.text else {}
        if response.status_code != 200 or payload.get("s") != "ok":
            return {"status": "ERROR", "market": "us", "symbol": clean, "error": f"Finnhub candle {response.status_code}/{payload.get('s', '')}"}
        rows = []
        closes = payload.get("c") or []
        for idx, close in enumerate(closes):
            ts = (payload.get("t") or [])[idx] if idx < len(payload.get("t") or []) else 0
            date_text = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y%m%d") if ts else ""
            rows.append({
                "date": date_text,
                "open": (payload.get("o") or [])[idx] if idx < len(payload.get("o") or []) else close,
                "high": (payload.get("h") or [])[idx] if idx < len(payload.get("h") or []) else close,
                "low": (payload.get("l") or [])[idx] if idx < len(payload.get("l") or []) else close,
                "close": close,
                "volume": (payload.get("v") or [])[idx] if idx < len(payload.get("v") or []) else "",
            })
        return _write_ohlcv(clean, "us", rows[-days:], "Finnhub daily candle")
    except Exception as exc:
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": str(exc)[:160]}


def _fetch_yahoo_daily_ohlcv(symbol: str, days: int = 120) -> dict[str, Any]:
    clean = _us_symbol(symbol)
    if not _is_finnhub_symbol(clean):
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": "Yahoo 지원 종목 형식 아님"}
    try:
        response = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{clean}",
            params={"range": "6mo", "interval": "1d", "includePrePost": "false"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=12,
        )
        payload = response.json() if response.text else {}
        result = ((payload.get("chart") or {}).get("result") or [None])[0] or {}
        timestamps = result.get("timestamp") or []
        quote = (((result.get("indicators") or {}).get("quote") or [None])[0]) or {}
        closes = quote.get("close") or []
        rows = []
        for idx, close in enumerate(closes):
            if close is None:
                continue
            ts = timestamps[idx] if idx < len(timestamps) else 0
            date_text = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y%m%d") if ts else ""
            rows.append({
                "date": date_text,
                "open": (quote.get("open") or [])[idx] if idx < len(quote.get("open") or []) else close,
                "high": (quote.get("high") or [])[idx] if idx < len(quote.get("high") or []) else close,
                "low": (quote.get("low") or [])[idx] if idx < len(quote.get("low") or []) else close,
                "close": close,
                "volume": (quote.get("volume") or [])[idx] if idx < len(quote.get("volume") or []) else "",
            })
        return _write_ohlcv(clean, "us", rows[-days:], "Yahoo daily chart")
    except Exception as exc:
        return {"status": "ERROR", "market": "us", "symbol": clean, "error": str(exc)[:160]}


def backfill_daily_ohlcv(symbol: str, market: str, days: int = 120) -> dict[str, Any]:
    normalized_market = "us" if str(market).lower() == "us" else "kr"
    if normalized_market == "kr":
        return _fetch_kis_kr_daily_ohlcv(symbol, days=days)
    kis = _fetch_kis_us_daily_ohlcv(symbol, days=days)
    if str(kis.get("status", "")).upper() == "OK":
        return kis
    fallback = _fetch_finnhub_daily_ohlcv(symbol, days=days)
    if str(fallback.get("status", "")).upper() == "OK":
        fallback["fallbackFrom"] = kis.get("error", "")
        return fallback
    yahoo = _fetch_yahoo_daily_ohlcv(symbol, days=days)
    if str(yahoo.get("status", "")).upper() == "OK":
        yahoo["fallbackFrom"] = f"KIS: {kis.get('error', '')}; Finnhub: {fallback.get('error', '')}"
        return yahoo
    yahoo["fallbackFrom"] = f"KIS: {kis.get('error', '')}; Finnhub: {fallback.get('error', '')}"
    return yahoo


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
