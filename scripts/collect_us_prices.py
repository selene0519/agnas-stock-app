"""
scripts/collect_us_prices.py
----------------------------
로컬 PC에서 미장(US) 현재가를 수집하여 아래 파일을 갱신한다:
  - data/market/snapshots/us_kis_current.json   ← data_quality price_priority_1
  - data/market/intraday/us_intraday_snapshot.csv
  - reports/kis_current_price_us.csv            ← GitHub Actions 기존 형식 호환

실행:
  python scripts/collect_us_prices.py
  python scripts/collect_us_prices.py --max 50
  python scripts/collect_us_prices.py --symbols NVDA,MSFT,AAPL

의존:
  pip install requests python-dotenv
  (선택) pip install yfinance
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# 경로 설정
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
TOKEN_CACHE = REPO_ROOT / "mone-web-app" / "backend" / "cache" / "kis_token_cache.json"
SECTOR_MAP = REPO_ROOT / "data" / "sector_map_us.csv"
SNAPSHOT_DIR = REPO_ROOT / "data" / "market" / "snapshots"
INTRADAY_DIR = REPO_ROOT / "data" / "market" / "intraday"
REPORTS_DIR = REPO_ROOT / "reports"

KST = timezone(timedelta(hours=9))

# ---------------------------------------------------------------------------
# .env 로드 (python-dotenv 없어도 동작)
# ---------------------------------------------------------------------------
def _load_env() -> None:
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv(ENV_FILE, override=False)
        return
    except ImportError:
        pass
    with open(ENV_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _now_label() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST")


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
        return f if f == f else None  # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# KIS 설정 / 토큰
# ---------------------------------------------------------------------------
def _kis_config() -> dict[str, Any]:
    is_mock = _env("KIS_IS_MOCK").lower() in {"1", "true", "yes", "y", "mock"}
    return {
        "app_key": _env("KIS_APP_KEY"),
        "app_secret": _env("KIS_APP_SECRET"),
        "is_mock": is_mock,
        "base_url": (
            "https://openapivts.koreainvestment.com:29443"
            if is_mock
            else "https://openapi.koreainvestment.com:9443"
        ),
    }


def _kis_enabled() -> bool:
    cfg = _kis_config()
    return bool(cfg["app_key"] and cfg["app_secret"])


def _read_json(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _kis_access_token(force_refresh: bool = False) -> str:
    cfg = _kis_config()
    if not _kis_enabled():
        return ""
    if not force_refresh and TOKEN_CACHE.exists():
        try:
            cache = _read_json(TOKEN_CACHE)
            token = str(cache.get("access_token", "") or "")
            expires_at = _safe_float(cache.get("expires_at")) or 0.0
            if token and expires_at > time.time() + 600:
                return token
        except Exception:
            pass
    try:
        resp = requests.post(
            f"{cfg['base_url']}/oauth2/tokenP",
            json={
                "grant_type": "client_credentials",
                "appkey": cfg["app_key"],
                "appsecret": cfg["app_secret"],
            },
            timeout=10,
        )
        payload = resp.json() if resp.text else {}
        token = str(payload.get("access_token", "") or "")
        if resp.status_code == 200 and token:
            expires_in = int(_safe_float(payload.get("expires_in")) or 86400)
            _write_json(
                TOKEN_CACHE,
                {
                    "access_token": token,
                    "expires_at": time.time() + max(60, expires_in - 300),
                    "issued_at": _now_label(),
                    "is_mock": bool(cfg["is_mock"]),
                },
            )
            return token
    except Exception:
        pass
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


# ---------------------------------------------------------------------------
# 심볼 정규화 / 거래소 후보
# ---------------------------------------------------------------------------
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
    "SOXL": ["AMS", "NAS", "NYS"],
    "TQQQ": ["NAS", "AMS", "NYS"],
}


def _clean_symbol(symbol: str) -> str:
    return str(symbol or "").upper().strip().replace("$", "").replace(".US", "")


def _exchange_candidates(symbol: str) -> list[str]:
    clean = _clean_symbol(symbol)
    if not clean or clean.startswith("^") or "=" in clean or "-" in clean or clean.isdigit():
        return []
    base = list(US_EXCHANGE_FALLBACKS.get(clean, []))
    for item in ("NAS", "NYS", "AMS"):
        if item not in base:
            base.append(item)
    return base


# ---------------------------------------------------------------------------
# 가격 수집: KIS → Finnhub → yfinance
# ---------------------------------------------------------------------------
def _fetch_kis_us(symbol: str) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    if not _kis_enabled():
        return {"ok": False, "symbol": clean, "error": "KIS_APP_KEY/KIS_APP_SECRET 미설정", "source": "KIS"}
    candidates = _exchange_candidates(clean)
    if not candidates:
        return {"ok": False, "symbol": clean, "error": "미장 종목 형식 아님", "source": "KIS"}
    cfg = _kis_config()
    url = f"{cfg['base_url']}/uapi/overseas-price/v1/quotations/price-detail"
    last_error = ""
    for exchange in candidates:
        for force in (False, True):
            headers = _kis_headers("HHDFS76200200", force_refresh=force)
            if not headers:
                return {"ok": False, "symbol": clean, "error": "KIS token 발급 실패", "source": "KIS"}
            try:
                resp = requests.get(
                    url,
                    headers=headers,
                    params={"AUTH": "", "EXCD": exchange, "SYMB": clean},
                    timeout=8,
                )
                payload = resp.json() if resp.text else {}
                if resp.status_code == 200 and payload.get("rt_cd") == "0":
                    output = payload.get("output", {}) or {}
                    price = _safe_float(output.get("last"))
                    if price and price > 0:
                        return {
                            "ok": True,
                            "symbol": clean,
                            "currentPrice": price,
                            "current_price": price,
                            "last_price": price,
                            "priceTime": _now_label(),
                            "priceSource": f"KIS 해외 현재가 · {exchange}",
                            "source": "KIS",
                            "exchange": exchange,
                            "priceSourceType": "kis_snapshot",
                            "error": "",
                        }
                    last_error = f"{exchange}: 현재가 응답 비어 있음"
                else:
                    last_error = f"{exchange}:{resp.status_code}/{payload.get('msg_cd','')}/{payload.get('msg1','')}"
            except Exception as exc:
                last_error = f"{exchange}:{str(exc)[:120]}"
    return {"ok": False, "symbol": clean, "error": last_error or "KIS 해외 현재가 실패", "source": "KIS"}


def _fetch_finnhub(symbol: str) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    key = _env("FINNHUB_API_KEY")
    if not key:
        return {"ok": False, "symbol": clean, "error": "FINNHUB_API_KEY 미설정", "source": "Finnhub"}
    if not (clean and clean.replace(".", "").isalpha() and "-" not in clean and "=" not in clean and not clean.startswith("^")):
        return {"ok": False, "symbol": clean, "error": "Finnhub 지원 형식 아님", "source": "Finnhub"}
    try:
        resp = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": clean, "token": key},
            timeout=8,
        )
        payload = resp.json() if resp.text else {}
        price = _safe_float(payload.get("c"))
        if resp.status_code == 200 and price and price > 0:
            price_time = _now_label()
            ts = _safe_float(payload.get("t"))
            if ts and ts > 0:
                price_time = (
                    datetime.fromtimestamp(int(ts), tz=timezone.utc)
                    .astimezone(KST)
                    .strftime("%Y-%m-%d %H:%M:%S KST")
                )
            return {
                "ok": True,
                "symbol": clean,
                "currentPrice": price,
                "current_price": price,
                "last_price": price,
                "priceTime": price_time,
                "priceSource": "Finnhub 현재가",
                "source": "Finnhub",
                "priceSourceType": "finnhub",
                "error": "",
            }
        return {"ok": False, "symbol": clean, "error": f"{resp.status_code}/empty_price", "source": "Finnhub"}
    except Exception as exc:
        return {"ok": False, "symbol": clean, "error": str(exc)[:160], "source": "Finnhub"}


def _fetch_yfinance(symbol: str) -> dict[str, Any]:
    clean = _clean_symbol(symbol)
    try:
        import yfinance as yf  # type: ignore
        ticker = yf.Ticker(clean)
        info = ticker.fast_info
        price = _safe_float(getattr(info, "last_price", None))
        if not price or price <= 0:
            hist = ticker.history(period="1d")
            if not hist.empty:
                price = _safe_float(hist["Close"].iloc[-1])
        if price and price > 0:
            return {
                "ok": True,
                "symbol": clean,
                "currentPrice": price,
                "current_price": price,
                "last_price": price,
                "priceTime": _now_label(),
                "priceSource": "yfinance",
                "source": "yfinance",
                "priceSourceType": "yfinance_fallback",
                "error": "",
            }
        return {"ok": False, "symbol": clean, "error": "yfinance: 가격 없음", "source": "yfinance"}
    except ImportError:
        return {"ok": False, "symbol": clean, "error": "yfinance 미설치", "source": "yfinance"}
    except Exception as exc:
        return {"ok": False, "symbol": clean, "error": str(exc)[:160], "source": "yfinance"}


def fetch_price(symbol: str) -> dict[str, Any]:
    """KIS → Finnhub → yfinance 순서로 현재가 수집."""
    clean = _clean_symbol(symbol)
    kis = _fetch_kis_us(clean)
    if kis.get("ok"):
        return kis
    fh = _fetch_finnhub(clean)
    if fh.get("ok"):
        fh["fallbackFrom"] = kis.get("error", "")
        return fh
    yf_r = _fetch_yfinance(clean)
    if yf_r.get("ok"):
        yf_r["fallbackFrom"] = f"KIS:{kis.get('error','')}; Finnhub:{fh.get('error','')}"
        return yf_r
    fh["fallbackFrom"] = kis.get("error", "")
    return fh


# ---------------------------------------------------------------------------
# 심볼 유니버스 로드
# ---------------------------------------------------------------------------
_SYMBOL_COLS = ("symbol", "ticker", "code", "종목코드")

def _csv_symbols(path: Path, market_filter: str = "") -> list[str]:
    """CSV 파일에서 symbol 컬럼을 읽어 반환. market_filter가 있으면 market 컬럼 검사."""
    if not path.exists():
        return []
    syms: list[str] = []
    try:
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                sym = ""
                for col in _SYMBOL_COLS:
                    v = str(row.get(col, "") or "").strip()
                    if v:
                        sym = _clean_symbol(v)
                        break
                if not sym:
                    continue
                if market_filter:
                    mkt = str(row.get("market", "")).strip().lower()
                    if mkt and mkt != market_filter:
                        continue
                if sym and not sym.isdigit() and len(sym) <= 10:
                    syms.append(sym)
    except Exception:
        pass
    return syms


def load_symbols() -> list[str]:
    """
    전체 US 심볼 유니버스를 아래 소스에서 합산:
      1. data/sector_map_us.csv
      2. data/candidate_universe_us.csv
      3. reports/mone_v36_final_recommendations_us_*.csv  (추천 CSV 전체)
      4. watchlist_us.csv / data/watchlist_us.csv
      5. holdings_us.csv / data/holdings_us.csv
    """
    collected: list[str] = []

    # 1. sector_map
    collected += _csv_symbols(SECTOR_MAP, market_filter="us")

    # 2. candidate_universe
    for p in (
        REPO_ROOT / "data" / "candidate_universe_us.csv",
        REPO_ROOT / "data" / "market" / "candidate_universe_us.csv",
    ):
        collected += _csv_symbols(p, market_filter="us")

    # 3. 추천 CSV 전체 (reports/mone_v36_final_recommendations_us_*.csv)
    for rec_csv in sorted((REPO_ROOT / "reports").glob("mone_v36_final_recommendations_us_*.csv")):
        collected += _csv_symbols(rec_csv)

    # 4. watchlist
    for p in (
        REPO_ROOT / "watchlist_us.csv",
        REPO_ROOT / "data" / "watchlist_us.csv",
        REPO_ROOT / "watchlist_us_growth.csv",
    ):
        collected += _csv_symbols(p, market_filter="us")

    # 5. holdings
    for p in (
        REPO_ROOT / "holdings_us.csv",
        REPO_ROOT / "data" / "holdings_us.csv",
    ):
        collected += _csv_symbols(p)

    # 중복 제거 + 순서 유지 + 최소 fallback
    result = list(dict.fromkeys(s for s in collected if s))
    if not result:
        result = [
            "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO",
            "AMD", "PLTR", "TSM", "QQQ", "SPY", "SMH", "SOXL", "TQQQ",
        ]
    return result


# ---------------------------------------------------------------------------
# 결과 파일 쓰기
# ---------------------------------------------------------------------------
CSV_FIELDS = [
    "symbol", "market", "ok", "currentPrice", "current_price", "last_price",
    "priceTime", "priceSource", "source", "priceSourceType", "priceSourceFile",
    "priceSourceDate", "kis_quote_success", "quote_available", "error", "updated_at",
]


def _result_to_csv_row(r: dict[str, Any]) -> dict[str, Any]:
    ok = bool(r.get("ok"))
    price = r.get("currentPrice") or r.get("current_price") or ""
    return {
        "symbol": r.get("symbol", ""),
        "market": "us",
        "ok": ok,
        "currentPrice": price,
        "current_price": price,
        "last_price": r.get("last_price", price),
        "priceTime": r.get("priceTime", ""),
        "priceSource": r.get("priceSource", ""),
        "source": r.get("source", ""),
        "priceSourceType": r.get("priceSourceType", ""),
        "priceSourceFile": "scripts/collect_us_prices.py",
        "priceSourceDate": datetime.now(KST).strftime("%Y-%m-%d"),
        "kis_quote_success": ok and "KIS" in str(r.get("source", "")),
        "quote_available": ok,
        "error": r.get("error", ""),
        "updated_at": _now_label(),
    }


def write_outputs(results: list[dict[str, Any]]) -> None:
    now_label = _now_label()
    now_iso = datetime.now(KST).isoformat()

    # 1) data/market/snapshots/us_kis_current.json
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snapshot_path = SNAPSHOT_DIR / "us_kis_current.json"
    snapshot_data = {
        "market": "us",
        "collectedAt": now_label,
        "collectedAtIso": now_iso,
        "count": len(results),
        "successCount": sum(1 for r in results if r.get("ok")),
        "quotes": {r["symbol"]: r for r in results},
    }
    _write_json(snapshot_path, snapshot_data)
    print(f"[OK] {snapshot_path.relative_to(REPO_ROOT)}")

    # 2) data/market/intraday/us_intraday_snapshot.csv
    INTRADAY_DIR.mkdir(parents=True, exist_ok=True)
    intraday_path = INTRADAY_DIR / "us_intraday_snapshot.csv"
    with open(intraday_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(_result_to_csv_row(r))
    print(f"[OK] {intraday_path.relative_to(REPO_ROOT)}")

    # 3) reports/kis_current_price_us.csv  (GitHub Actions 기존 형식 호환)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    reports_path = REPORTS_DIR / "kis_current_price_us.csv"
    with open(reports_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for r in results:
            writer.writerow(_result_to_csv_row(r))
    print(f"[OK] {reports_path.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="US 현재가 수집기")
    parser.add_argument("--max", type=int, default=0, help="최대 수집 종목 수 (0=전체)")
    parser.add_argument("--symbols", type=str, default="", help="쉼표 구분 종목 목록 (예: NVDA,MSFT)")
    parser.add_argument("--delay", type=float, default=0.3, help="API 호출 간격(초), 기본 0.3")
    args = parser.parse_args()

    _load_env()

    if args.symbols:
        symbols = [_clean_symbol(s) for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = load_symbols()

    if args.max and args.max > 0:
        symbols = symbols[: args.max]

    print(f"[collect_us_prices] 수집 대상: {len(symbols)}종목 | KIS={'ON' if _kis_enabled() else 'OFF'} | Finnhub={'ON' if _env('FINNHUB_API_KEY') else 'OFF'}")

    results: list[dict[str, Any]] = []
    ok_count = 0
    for i, sym in enumerate(symbols, 1):
        r = fetch_price(sym)
        r["symbol"] = _clean_symbol(sym)
        results.append(r)
        status = "OK" if r.get("ok") else "FAIL"
        price = r.get("currentPrice", "-")
        src = r.get("source", "?")
        print(f"  [{i:>3}/{len(symbols)}] {sym:<8} {status} {price:>10} ({src})")
        if r.get("ok"):
            ok_count += 1
        if i < len(symbols) and args.delay > 0:
            time.sleep(args.delay)

    print(f"\n수집 완료: {ok_count}/{len(symbols)} 성공")
    write_outputs(results)


if __name__ == "__main__":
    main()
