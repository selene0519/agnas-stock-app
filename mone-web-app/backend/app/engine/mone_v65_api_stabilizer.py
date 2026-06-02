from __future__ import annotations

import csv
import json
import math
import re
import subprocess
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from fastapi import Body, Query
from fastapi.routing import APIRoute


KR_NAME_FALLBACK: dict[str, str] = {
    "005930": "삼성전자",
    "009150": "삼성전기",
    "006340": "대원전선",
    "000660": "SK하이닉스",
    "005380": "현대차",
    "131970": "두산테스나",
    "222800": "심텍",
    "035420": "NAVER",
    "207940": "삼성바이오로직스",
    "000100": "유한양행",
    "058470": "리노공업",
    "006400": "삼성SDI",
    "196170": "알테오젠",
    "055550": "신한지주",
    "375500": "DL이앤씨",
    "086520": "에코프로",
    "214150": "클래시스",
    "267260": "HD현대일렉트릭",
    "001440": "대한전선",
    "003490": "대한항공",
    "373220": "LG에너지솔루션",
    "034020": "두산에너빌리티",
    "009540": "HD한국조선해양",
    "047810": "한국항공우주",
    "015760": "한국전력",
    "247540": "에코프로비엠",
    "090360": "로보스타",
    "403870": "HPSP",
    "005490": "POSCO홀딩스",
    "012330": "현대모비스",
    "042700": "한미반도체",
}

US_NAME_FALLBACK: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "NVIDIA",
    "TSLA": "Tesla",
    "GOOGL": "Alphabet",
    "GOOG": "Alphabet",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "AMD": "AMD",
    "AVGO": "Broadcom",
    "PLTR": "Palantir",
    "INTC": "Intel",
    "MU": "Micron",
    "RKLB": "Rocket Lab",
    "ASTS": "AST SpaceMobile",
    "AAOI": "Applied Optoelectronics",
    "SIMO": "Silicon Motion",
    "BMNR": "BitMine Immersion Technologies",
}

MODE_ALIASES = {
    "conservative": "conservative",
    "balanced": "balanced",
    "aggressive": "aggressive",
    "보수": "conservative",
    "균형": "balanced",
    "공격": "aggressive",
}

HORIZON_ALIASES = {
    "short": "short",
    "day": "short",
    "swing": "swing",
    "mid": "mid",
    "middle": "mid",
    "long": "mid",
    "단기": "short",
    "스윙": "swing",
    "중기": "mid",
}

MODE_LABEL = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
HORIZON_LABEL = {"short": "단기", "swing": "스윙", "mid": "중기"}

SYMBOL_KEYS = [
    "symbol",
    "ticker",
    "code",
    "stock_code",
    "종목코드",
    "종목",
    "Symbol",
    "Ticker",
]

NAME_KEYS = [
    "name",
    "stock_name",
    "company_name",
    "companyName",
    "corp_name",
    "종목명",
    "기업명",
    "Name",
    "Company",
]

PRICE_KEYS = [
    "currentPrice",
    "current_price",
    "last_price",
    "price",
    "close",
    "prev_close",
    "quote_fallback_price",
    "현재가",
    "실시간현재가",
]


def _app_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if parent.name == "mone-web-app" and (parent / "backend").exists() and (parent / "frontend").exists():
            return parent
    for parent in [here.parent, *here.parents]:
        if (parent / "mone-web-app").exists():
            return parent / "mone-web-app"
    return here.parents[3]


def _repo_root() -> Path:
    return _app_root().parent


def _search_roots() -> list[Path]:
    app = _app_root()
    repo = _repo_root()
    candidates = [
        app,
        app / "data",
        app / "reports",
        repo,
        repo / "data",
        repo / "reports",
    ]
    out: list[Path] = []
    for path in candidates:
        if path.exists() and path not in out:
            out.append(path)
    return out


def _safe_rel(path: Path) -> str:
    for root in _search_roots():
        try:
            return str(path.relative_to(root))
        except Exception:
            pass
    return str(path)


def _many(*patterns: str, max_files: int = 300) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in _search_roots():
        for pattern in patterns:
            try:
                for path in root.glob(pattern):
                    if path.is_file() and path.stat().st_size > 0 and path not in seen:
                        seen.add(path)
                        found.append(path)
            except Exception:
                continue
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)[:max_files]


def _read_csv(path: Path | None, limit: int = 50000) -> list[dict[str, Any]]:
    if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            rows: list[dict[str, Any]] = []
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames:
                    return []
                for index, row in enumerate(reader):
                    item = {str(k): v for k, v in row.items() if k is not None}
                    item["_source_file"] = path.name
                    item["_source_path"] = _safe_rel(path)
                    rows.append(item)
                    if index + 1 >= limit:
                        break
            return rows
        except Exception:
            continue
    return []


def _read_json(path: Path | None) -> Any:
    if path is None or not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        return None
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return json.loads(path.read_text(encoding=enc))
        except Exception:
            continue
    return None


def _text(row: dict[str, Any], keys: list[str], default: str = "") -> str:
    lower = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] is not None and str(row[key]).strip():
            return str(row[key]).strip()
        low_key = key.lower()
        if low_key in lower and lower[low_key] is not None and str(lower[low_key]).strip():
            return str(lower[low_key]).strip()
    return default


def _num(value: Any, default: float = 0.0) -> float:
    try:
        raw = str(value if value is not None else "").strip()
        if not raw or raw.lower() in {"nan", "none", "null", "na", "-", "데이터 없음", "연결 필요"}:
            return default
        raw = raw.replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        multiplier = 1.0
        if "조" in raw:
            multiplier = 1_000_000_000_000.0
            raw = raw.replace("조", "")
        elif "억" in raw:
            multiplier = 100_000_000.0
            raw = raw.replace("억", "")
        elif "만" in raw:
            multiplier = 10_000.0
            raw = raw.replace("만", "")
        raw = re.sub(r"[^0-9.\-+]", "", raw)
        if not raw or raw in {"-", "+", "."}:
            return default
        parsed = float(raw) * multiplier
        return default if math.isnan(parsed) else parsed
    except Exception:
        return default


def _symbol_value(value: Any, market: str = "") -> str:
    text = str(value or "").strip().upper()
    if text.endswith(".0"):
        text = text[:-2]
    text = re.sub(r"\.(KS|KQ|KR)$", "", text)
    text = re.sub(r"[^0-9A-Z.\-]", "", text)
    if (market == "kr" or text.isdigit()) and text.isdigit() and len(text) < 6:
        text = text.zfill(6)
    return text


def _symbol(row: dict[str, Any], market: str = "") -> str:
    return _symbol_value(_text(row, SYMBOL_KEYS, ""), market)


def _market_norm(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"all", "전체"}:
        return "all"
    if raw in {"us", "usa", "nyse", "nasdaq", "amex", "미장"}:
        return "us"
    return "kr"


def _mode_norm(value: Any) -> str:
    return MODE_ALIASES.get(str(value or "").strip().lower(), "balanced")


def _horizon_norm(value: Any) -> str:
    return HORIZON_ALIASES.get(str(value or "").strip().lower(), "swing")


def _infer_market(symbol: str, explicit: Any = "") -> str:
    raw = str(explicit or "").strip().lower()
    if raw in {"kr", "kospi", "kosdaq", "korea", "국장"}:
        return "kr"
    if raw in {"us", "usa", "nyse", "nasdaq", "amex", "미장"}:
        return "us"
    return "kr" if re.fullmatch(r"\d{6}", symbol or "") else "us"


def _bad_name(value: Any, symbol: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if text.upper() == symbol.upper():
        return True
    if text in {"-", "N/A", "UNKNOWN", "종목명 없음"}:
        return True
    return bool(re.search(r"[�]|援|蹂댁|誘몄|筌|醫|紐|쨌|\?\?\?", text))


def _fallback_name(symbol: str, market: str) -> str:
    if market == "kr":
        return KR_NAME_FALLBACK.get(symbol, symbol)
    return US_NAME_FALLBACK.get(symbol, symbol)


@lru_cache(maxsize=1)
def _build_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for market in ("kr", "us"):
        for symbol, name in (KR_NAME_FALLBACK if market == "kr" else US_NAME_FALLBACK).items():
            names[f"{market}-{symbol}"] = name

    source_patterns = [
        "watchlist_kr.csv",
        "watchlist_us.csv",
        "watchlist_kr_growth.csv",
        "watchlist_us_growth.csv",
        "**/watchlist_kr.csv",
        "**/watchlist_us.csv",
        "**/watchlist_kr_growth.csv",
        "**/watchlist_us_growth.csv",
        "candidate_universe_kr.csv",
        "candidate_universe_us.csv",
        "symbol_master_kr_full.csv",
        "symbol_master_kr_extra.csv",
        "symbol_master_us_full.csv",
        "symbol_master_us_extra.csv",
        "data/symbol_master_kr_full.csv",
        "data/symbol_master_kr_extra.csv",
        "data/symbol_master_us_full.csv",
        "data/symbol_master_us_extra.csv",
        "**/candidate_universe_kr.csv",
        "**/candidate_universe_us.csv",
        "**/symbol_master_kr_full.csv",
        "**/symbol_master_kr_extra.csv",
        "**/symbol_master_us_full.csv",
        "**/symbol_master_us_extra.csv",
        "**/*symbol_snapshot*.csv",
        "**/*master_investors*.csv",
        "**/*company*.csv",
        "**/*fundamental*.csv",
        "**/*financial*.csv",
    ]
    for path in _many(*source_patterns, max_files=120):
        for row in _read_csv(path, 20000):
            market = _infer_market(_symbol(row), _text(row, ["market", "시장", "_market"], ""))
            symbol = _symbol(row, market)
            if not symbol:
                continue
            raw_name = _text(row, NAME_KEYS, "")
            if not _bad_name(raw_name, symbol):
                names.setdefault(f"{market}-{symbol}", raw_name)
    return names


def _display_name(row: dict[str, Any], symbol: str, market: str, names: dict[str, str]) -> str:
    raw = _text(row, NAME_KEYS, "")
    if not _bad_name(raw, symbol):
        return raw
    return names.get(f"{market}-{symbol}", _fallback_name(symbol, market))


def _normalize_name_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _name_to_symbol_map(names: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, name in names.items():
        try:
            market, symbol = key.split("-", 1)
        except ValueError:
            continue
        normalized = _normalize_name_key(name)
        if normalized:
            out[f"{market}:{normalized}"] = symbol
    return out


def _company_symbol(row: dict[str, Any], market: str, name_to_symbol: dict[str, str]) -> str:
    symbol = _symbol(row, market)
    if symbol:
        return symbol

    for key, value in row.items():
        lowered = str(key or "").lower()
        if any(token in lowered for token in ("symbol", "ticker", "code", "종목코드", "단축코드")):
            symbol = _symbol_value(value, market)
            if symbol:
                return symbol

    for value in list(row.values())[:4]:
        symbol = _symbol_value(value, market)
        if market == "kr" and re.fullmatch(r"\d{6}", symbol):
            return symbol
        if market == "us" and re.fullmatch(r"[A-Z][A-Z.\-]{0,11}", symbol):
            return symbol

    for value in [_text(row, NAME_KEYS, ""), *list(row.values())[:4]]:
        normalized = _normalize_name_key(value)
        if not normalized:
            continue
        symbol = name_to_symbol.get(f"{market}:{normalized}")
        if symbol:
            return symbol
    return ""


def _price_text(value: Any, market: str) -> str:
    price = _num(value)
    if price <= 0:
        return "현재가 산출 필요"
    return f"${price:,.2f}" if market == "us" else f"{round(price):,}원"


def _optional_price_text(value: Any, market: str) -> str:
    price = _num(value)
    if price <= 0:
        return "-"
    return f"${price:,.2f}" if market == "us" else f"{round(price):,}원"


def _pct_text(value: Any) -> str:
    raw = str(value or "").strip()
    if raw.endswith("%"):
        return raw
    n = _num(raw)
    if 0 < n <= 1:
        n *= 100
    return f"{n:.1f}%" if n > 0 else "-"


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _strategy_profile(mode: str) -> dict[str, float]:
    """
    전략별 기본 가격 프로파일.
    보수: 손절 짧고 목표 보수적 / 균형: 기본 / 공격: 손절 넓고 목표 크게
    """
    if mode == "conservative":
        # 손절 -3.0%, 목표 +6.0%, 확률 보정 -2.0
        return {"stop": 0.970, "target": 1.060, "prob": -2.0}
    if mode == "aggressive":
        # 손절 -9.0%, 목표 +20.0%, 확률 보정 +2.0
        return {"stop": 0.910, "target": 1.200, "prob": 2.0}
    # balanced: 손절 -5.5%, 목표 +13.0%
    return {"stop": 0.945, "target": 1.130, "prob": 0.0}


def _prob_number(value: Any, default: float = 58.0) -> float:
    n = _num(value, default)
    if 0 < n <= 1:
        n *= 100
    return _clamp(n)


def _symbol_jitter(symbol: str, scale: float = 0.35) -> float:
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(str(symbol or "")))
    return ((seed % 17) - 8) * scale


def _auto_probability(
    row: dict[str, Any],
    symbol: str,
    mode: str,
    horizon: str,
    current: float,
    entry: float,
    stop: float,
    target: float,
    raw_probability: float,
) -> float:
    raw_anchor = _clamp(raw_probability, 35.0, 72.0)
    base = 50.0 + ((raw_anchor - 50.0) * 0.35)

    rr_adj = 0.0
    if entry > 0 and stop > 0 and target > entry and entry > stop:
        rr = (target - entry) / max(entry - stop, 1e-9)
        rr_adj = _clamp((rr - 1.6) * 3.2, -5.0, 6.0)

    gap_adj = 0.0
    if current > 0 and entry > 0:
        gap_pct = abs(current - entry) / entry * 100.0
        gap_adj = _clamp(3.0 - gap_pct, -4.0, 3.0)

    score_adj = 0.0
    score = _num(_text(row, ["score", "finalScore", "riskScore", "opportunityScore", "confidence"], ""), 0.0)
    if score:
        if 0 < score <= 1:
            score *= 100.0
        score_adj = _clamp((score - 50.0) / 12.0, -4.0, 4.0)

    horizon_adj = {"short": -1.2, "swing": 0.0, "mid": 1.1, "long": 1.5}.get(horizon, 0.0)
    mode_adj = {"conservative": -1.0, "balanced": 0.0, "aggressive": 1.0}.get(mode, 0.0)
    probability = base + rr_adj + gap_adj + score_adj + horizon_adj + mode_adj + _symbol_jitter(symbol)
    return round(_clamp(probability, 45.0, 70.0), 1)


def _computed_append(fields: list[str], name: str) -> None:
    if name not in fields:
        fields.append(name)


def _direct_files(*relative_paths: str) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for root in _search_roots():
        for rel in relative_paths:
            path = root / rel
            if path.is_file() and path.stat().st_size > 0 and path not in seen:
                seen.add(path)
                found.append(path)
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


@lru_cache(maxsize=1)
def _build_name_map() -> dict[str, str]:
    names: dict[str, str] = {}
    for symbol, name in KR_NAME_FALLBACK.items():
        names[f"kr-{symbol}"] = name
    for symbol, name in US_NAME_FALLBACK.items():
        names[f"us-{symbol}"] = name

    for market in ("kr", "us"):
        for path in _direct_files(
            f"holdings_{market}.csv",
            f"watchlist_{market}.csv",
            f"watchlist_{market}_growth.csv",
            f"candidate_universe_{market}.csv",
            f"symbol_master_{market}_full.csv",
            f"symbol_master_{market}_extra.csv",
            f"data/holdings_{market}.csv",
            f"data/watchlist_{market}.csv",
            f"data/watchlist_{market}_growth.csv",
            f"data/candidate_universe_{market}.csv",
            f"data/symbol_master_{market}_full.csv",
            f"data/symbol_master_{market}_extra.csv",
            f"reports/mone_v36_final_recommendations_{market}_balanced_swing.csv",
        ):
            for row in _read_csv(path, 50000):
                sym = _symbol(row, market)
                if not sym:
                    continue
                raw_name = _text(row, NAME_KEYS, "")
                if not _bad_name(raw_name, sym):
                    names.setdefault(f"{market}-{sym}", raw_name)
    return names


def _quote_files(market: str) -> list[Path]:
    return _direct_files(
        f"kis_current_price_{market}.csv",
        f"intraday_quote_snapshot_{market}.csv",
        f"data/kis_current_price_{market}.csv",
        f"data/intraday_quote_snapshot_{market}.csv",
        f"data/stockapp/kis_current_price_{market}.csv",
        f"data/stockapp/intraday_quote_snapshot_{market}.csv",
        f"data/stockapp/intraday_realtime_snapshot_{market}.csv",
        f"reports/kis_current_price_{market}.csv",
        f"reports/intraday_quote_snapshot_{market}.csv",
        f"reports/intraday_realtime_snapshot_{market}.csv",
    )


def _recommendation_paths(market: str, mode: str, horizon: str) -> list[tuple[Path, str]]:
    exact = _direct_files(
        f"reports/mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
    )
    if exact:
        return [(path, "MATCH") for path in exact]

    fallback = _direct_files(
        f"reports/mone_v36_final_recommendations_{market}_balanced_{horizon}.csv",
        f"reports/mone_v36_final_recommendations_{market}_{mode}_swing.csv",
        f"predictions.csv",
        f"reports/predictions.csv",
        f"reports/v93_action_cards_{market}.csv",
        f"v93_action_cards_{market}.csv",
        f"candidate_universe_{market}.csv",
        f"data/candidate_universe_{market}.csv",
    )
    return [(path, "FALLBACK") for path in fallback]


@lru_cache(maxsize=1)
def _watch_symbols() -> set[str]:
    symbols: set[str] = set()
    for path in _direct_files("daily_watch_selection.json", "data/daily_watch_selection.json", "reports/daily_watch_selection.json"):
        payload = _read_json(path)
        values = payload.values() if isinstance(payload, dict) else payload if isinstance(payload, list) else []
        for value in values:
            if isinstance(value, dict):
                value = value.get("symbols") or value.get("items") or value.get("watchlist") or value.get("codes")
            if isinstance(value, list):
                for item in value:
                    symbols.add(_symbol(item) if isinstance(item, dict) else _symbol_value(item))
            elif isinstance(value, str):
                symbols.add(_symbol_value(value))
    for path in _direct_files(
        "watchlist_kr.csv",
        "watchlist_us.csv",
        "watchlist_kr_growth.csv",
        "watchlist_us_growth.csv",
        "data/watchlist_kr.csv",
        "data/watchlist_us.csv",
        "data/watchlist_kr_growth.csv",
        "data/watchlist_us_growth.csv",
    ):
        for row in _read_csv(path, 20000):
            sym = _symbol(row)
            if sym:
                symbols.add(sym)
    return {s for s in symbols if s}


def _rows_from_paths(paths: list[Path], limit_per_file: int = 50000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(_read_csv(path, limit_per_file))
    return rows


def _quote_files(market: str) -> list[Path]:
    return _many(
        f"**/kis_current_price_{market}.csv",
        f"**/kis_current_price_{market}.json",
        f"**/intraday_quote_snapshot_{market}.csv",
        f"**/*quote*{market}*.csv",
        f"**/*price*{market}*.csv",
        max_files=80,
    )


@lru_cache(maxsize=4)
def _quote_index(market: str) -> dict[str, dict[str, Any]]:
    quotes: dict[str, dict[str, Any]] = {}
    for row in _rows_from_paths([p for p in _quote_files(market) if p.suffix.lower() == ".csv"], 50000):
        sym = _symbol(row, market)
        if sym and sym not in quotes:
            quotes[sym] = row
    return quotes


@lru_cache(maxsize=1)
def _all_symbol_rows() -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for market in ("kr", "us"):
        for path in _direct_files(
            f"holdings_{market}.csv",
            f"watchlist_{market}.csv",
            f"watchlist_{market}_growth.csv",
            f"candidate_universe_{market}.csv",
            f"symbol_master_{market}_full.csv",
            f"symbol_master_{market}_extra.csv",
            f"data/holdings_{market}.csv",
            f"data/watchlist_{market}.csv",
            f"data/watchlist_{market}_growth.csv",
            f"data/candidate_universe_{market}.csv",
            f"data/symbol_master_{market}_full.csv",
            f"data/symbol_master_{market}_extra.csv",
            f"data/stockapp/kis_current_price_{market}.csv",
            f"data/stockapp/intraday_quote_snapshot_{market}.csv",
            f"data/stockapp/intraday_realtime_snapshot_{market}.csv",
            f"reports/mone_v36_final_recommendations_{market}_balanced_swing.csv",
            f"reports/mone_v36_final_recommendations_{market}_balanced_short.csv",
            f"reports/mone_v36_final_recommendations_{market}_balanced_mid.csv",
            f"reports/mone_v36_final_recommendations_{market}_conservative_swing.csv",
            f"reports/mone_v36_final_recommendations_{market}_aggressive_swing.csv",
            f"reports/kis_current_price_{market}.csv",
            f"reports/intraday_quote_snapshot_{market}.csv",
            f"reports/intraday_realtime_snapshot_{market}.csv",
            f"reports/watchlist_{market}.csv",
            f"reports/watchlist_{market}_growth.csv",
            f"reports/candidate_universe_{market}.csv",
            f"reports/v93_company_integrated_{market}.csv",
            f"reports/v92_company_integrated_{market}.csv",
            f"reports/v81_company_summary_cards_{market}.csv",
        ):
            for row in _read_csv(path, 50000):
                row["_market"] = market
                rows.append(row)
        for path in _many(
            f"reports/v*_symbol_snapshot_{market}.csv",
            f"reports/v*_master_investors_{market}.csv",
            f"reports/mone_v36_final_recommendations_{market}_*.csv",
            max_files=300,
        ):
            for row in _read_csv(path, 50000):
                row["_market"] = market
                rows.append(row)
        for path in _many(f"data/market/ohlcv/{market}_*_daily.csv", max_files=5000):
            match = re.match(rf"{market}_(.+?)_daily\.csv$", path.name, re.IGNORECASE)
            if not match:
                continue
            symbol = _symbol_value(match.group(1), market)
            if not symbol:
                continue
            rows.append({
                "symbol": symbol,
                "name": _fallback_name(symbol, market),
                "_market": market,
                "_source_file": path.name,
                "_source_path": _safe_rel(path),
            })
    return tuple(rows)


def _extract_source_mode_horizon(path: Path, row: dict[str, Any]) -> tuple[str, str]:
    source = " ".join([
        path.name.lower(),
        _text(row, ["sourceMode", "mode", "strategy", "추천모드"], "").lower(),
        _text(row, ["sourceHorizon", "horizon", "term", "기간"], "").lower(),
    ])

    source_mode = ""
    for mode in ("conservative", "balanced", "aggressive"):
        if mode in source:
            source_mode = mode
            break
    if not source_mode:
        for label, mode in {"보수": "conservative", "균형": "balanced", "공격": "aggressive"}.items():
            if label in source:
                source_mode = mode
                break

    source_horizon = ""
    for horizon in ("short", "swing", "mid", "long"):
        if horizon in source:
            source_horizon = "mid" if horizon == "long" else horizon
            break
    if not source_horizon:
        for label, horizon in {"단기": "short", "스윙": "swing", "중기": "mid"}.items():
            if label in source:
                source_horizon = horizon
                break

    return source_mode, source_horizon


def _recommendation_paths(market: str, mode: str, horizon: str) -> list[tuple[Path, str]]:
    exact_patterns = [
        f"reports/mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        f"**/mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        f"**/*recommend*{market}*{mode}*{horizon}*.csv",
        f"**/*candidate*{market}*{mode}*{horizon}*.csv",
        f"**/*action*{market}*{mode}*{horizon}*.csv",
    ]
    exact = _many(*exact_patterns, max_files=80)
    if exact:
        return [(path, "MATCH") for path in exact]

    fallback_patterns = [
        f"**/*recommend*{market}*{mode}*.csv",
        f"**/*recommend*{market}*{horizon}*.csv",
        f"**/*candidate*{market}*{mode}*.csv",
        f"**/*candidate*{market}*{horizon}*.csv",
        f"**/*action*{market}*{mode}*.csv",
        f"**/*action*{market}*{horizon}*.csv",
        "predictions.csv",
        "**/predictions.csv",
        f"**/v93_action_cards_{market}.csv",
        f"**/candidate_universe_{market}.csv",
        f"candidate_universe_{market}.csv",
    ]
    return [(path, "FALLBACK") for path in _many(*fallback_patterns, max_files=120)]


@lru_cache(maxsize=4)
def _company_paths(market: str) -> tuple[Path, ...]:
    markets = ["kr", "us"] if market == "all" else [market]
    paths: list[Path] = []
    for item_market in markets:
        paths.extend(_many(
            f"**/*company*{item_market}*.csv",
            f"**/*financial*{item_market}*.csv",
            f"**/*fundamental*{item_market}*.csv",
            f"**/*statement*{item_market}*.csv",
            f"**/*kpi*{item_market}*.csv",
            f"**/*valuation*{item_market}*.csv",
            f"**/v81_company_summary_cards_{item_market}.csv",
            f"**/v81_financial_statement_{item_market}.csv",
            max_files=80,
        ))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    return tuple(unique)


def _field_value(row: dict[str, Any], keys: list[str]) -> float | None:
    raw = _text(row, keys, "")
    if not str(raw or "").strip() or str(raw).strip().lower() in {"nan", "none", "null", "na", "-", "데이터 없음", "연결 필요"}:
        return None
    return _num(raw)


def _missing_fields(item: dict[str, Any]) -> list[str]:
    fields = [
        ("EPS", item.get("eps")),
        ("PER", item.get("per")),
        ("PBR", item.get("pbr")),
        ("ROE", item.get("roe")),
        ("매출", item.get("revenue")),
        ("영업이익", item.get("operatingProfit")),
        ("순이익", item.get("netIncome")),
        ("부채비율", item.get("debtRatio")),
    ]
    return [name for name, value in fields if not value]


@lru_cache(maxsize=128)

def _symbols_payload_cached(market: str, q: str, watch_only: bool, limit: int) -> dict[str, Any]:
    market = _market_norm(market)
    limit = max(1, min(int(limit or 300), 10000))
    names = _build_name_map()
    watch = _watch_symbols()
    query_raw = str(q or "").strip()
    query = query_raw.lower()
    query_compact = re.sub(r"\s+", "", query)
    query_digits = re.sub(r"\D", "", query)
    seen: set[str] = set()
    all_items: list[dict[str, Any]] = []
    quote_indexes = {"kr": _quote_index("kr"), "us": _quote_index("us")}

    def _compact(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().lower())

    def _match(symbol: str, name: str) -> bool:
        if not query:
            return True
        sym_lower = symbol.lower()
        name_lower = str(name or "").lower()
        name_compact = _compact(name)
        if query in sym_lower or query in name_lower:
            return True
        if query_compact and query_compact in name_compact:
            return True
        if query_digits and query_digits in re.sub(r"\D", "", symbol):
            return True
        return False

    def _score(item: dict[str, Any]) -> tuple[int, int, int, int, str, str]:
        symbol = str(item.get("symbol") or "")
        name = str(item.get("name") or "")
        symbol_lower = symbol.lower()
        name_lower = name.lower()
        name_compact = _compact(name)
        symbol_digits = re.sub(r"\D", "", symbol)
        exact_symbol = bool(query and symbol_lower == query) or bool(query_digits and symbol_digits == query_digits)
        exact_name = bool(query and name_lower == query) or bool(query_compact and name_compact == query_compact)
        starts_name = bool(query and name_lower.startswith(query)) or bool(query_compact and name_compact.startswith(query_compact))
        has_price = bool(item.get("currentPrice"))
        return (
            0 if exact_symbol else 1,
            0 if exact_name else 1,
            0 if starts_name else 1,
            0 if has_price else 1,
            str(item.get("market") or ""),
            symbol,
        )

    for row in _all_symbol_rows():
        item_market = _infer_market(str(_text(row, ["symbol", "ticker", "code", "종목코드"], "")), _text(row, ["market", "시장", "_market"], ""))
        sym = _symbol(row, item_market)
        item_market = _infer_market(sym, _text(row, ["market", "시장", "_market"], item_market))
        sym = _symbol(row, item_market)
        if not sym:
            continue
        key = f"{item_market}-{sym}"
        if key in seen:
            continue
        if market != "all" and item_market != market:
            continue

        name = _display_name(row, sym, item_market, names)
        if watch_only and sym not in watch:
            continue
        if not _match(sym, name):
            continue

        quote = quote_indexes.get(item_market, {}).get(sym, {})
        current = _num(_text(quote, PRICE_KEYS, ""))
        seen.add(key)

        source_file = _text(row, ["_source_file", "sourceFile", "source"], "")
        price_source = _text(quote, ["priceSource", "source", "price_source", "_source_file"], "")
        price_time = _text(quote, ["priceTime", "priceSourceDate", "updated_at", "timestamp", "quoteTimestamp"], "")
        prev_close = _num(_text(quote, ["prevClose", "previousClose", "basePrice", "stck_prdy_clpr", "전일종가", "기준가"], ""))
        change_pct = _num(_text(quote, ["changePct", "changeRate", "prdy_ctrt", "등락률"], ""))

        if not change_pct and current > 0 and prev_close > 0:
            change_pct = (current - prev_close) / prev_close * 100

        data_status = "NORMAL" if current > 0 else "PRICE_PENDING"

        all_items.append({
            "id": key,
            "symbol": sym,
            "name": name,
            "market": item_market,
            "label": f"{name} {sym}",
            "isWatch": sym in watch,
            "source": source_file,
            "currentPrice": current if current > 0 else None,
            "currentPriceText": _price_text(current, item_market) if current > 0 else "",
            "prevClose": prev_close if prev_close > 0 else None,
            "prevCloseText": _price_text(prev_close, item_market) if prev_close > 0 else "",
            "changePct": change_pct if change_pct else None,
            "changePctText": f"{'+' if change_pct > 0 else ''}{change_pct:.2f}%" if change_pct else "",
            "priceSource": price_source,
            "priceTime": price_time,
            "dataStatus": data_status,
        })

    all_items.sort(key=_score)
    items = all_items[:limit]
    return {
        "status": "OK" if items else "NO_DATA",
        "routeVersion": "symbols-full-master-general-v3",
        "market": market,
        "query": q,
        "count": len(items),
        "totalCount": len(all_items),
        "watchCount": len(watch),
        "items": items,
    }

def _symbols_payload(market: str, q: str, watch_only: bool, limit: int) -> dict[str, Any]:
    market_key = _market_norm(market)
    query_key = str(q or "").strip().lower()
    limit_key = max(1, min(int(limit or 300), 10000))
    payload = _symbols_payload_cached(market_key, query_key, bool(watch_only), limit_key)
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _merge_company_item(base_item: dict[str, Any], row_item: dict[str, Any]) -> dict[str, Any]:
    """Fill missing financial fields from another CSV row for the same market+symbol."""
    out = dict(base_item)
    for key in (
        "eps", "per", "pbr", "roe", "revenue", "operatingProfit",
        "netIncome", "debtRatio", "fundamentalScore", "flowScore",
    ):
        if not out.get(key) and row_item.get(key):
            out[key] = row_item[key]

    sources = list(out.get("sourceFiles") or [])
    source = row_item.get("source")
    if source and source not in sources:
        sources.append(source)
    out["sourceFiles"] = sources
    out["source"] = ", ".join(sources[:3]) if sources else out.get("source", "")
    out["matchedRows"] = int(out.get("matchedRows") or 0) + int(row_item.get("matchedRows") or 0)
    return out


def _company_row_item(row: dict[str, Any], sym: str, name: str, item_market: str, path: Path) -> dict[str, Any]:
    item = {
        "id": f"company-{item_market}-{sym}",
        "symbol": sym,
        "name": name,
        "market": item_market,
        "eps": _field_value(row, ["EPS", "eps", "주당순이익", "earningsPerShare", "basicEps"]),
        "per": _field_value(row, ["PER", "per", "pe", "trailingPE", "forwardPE", "주가수익비율"]),
        "pbr": _field_value(row, ["PBR", "pbr", "pb", "priceToBook", "주가순자산비율"]),
        "roe": _field_value(row, ["ROE", "roe", "returnOnEquity", "자기자본이익률"]),
        "revenue": _field_value(row, ["revenue", "sales", "totalRevenue", "매출", "매출액"]),
        "operatingProfit": _field_value(row, ["operatingProfit", "operating_profit", "operatingIncome", "영업이익"]),
        "netIncome": _field_value(row, ["netIncome", "net_income", "profit", "순이익", "당기순이익"]),
        "debtRatio": _field_value(row, ["debtRatio", "debt_ratio", "debtToEquity", "부채비율"]),
        "fundamentalScore": _field_value(row, ["fundamentalScore", "fundamental_score", "score", "종합점수", "펀더멘털점수"]),
        "flowScore": _field_value(row, ["flowScore", "flow_score", "수급점수"]),
        "source": path.name,
        "sourceFiles": [path.name],
        "matchedRows": 1,
    }
    return item


def _blank_company_item(symbol: str, name: str, market: str, reason: str) -> dict[str, Any]:
    return {
        "id": f"company-{market}-{symbol}",
        "symbol": symbol,
        "name": name,
        "market": market,
        "eps": None,
        "per": None,
        "pbr": None,
        "roe": None,
        "revenue": None,
        "operatingProfit": None,
        "netIncome": None,
        "debtRatio": None,
        "fundamentalScore": None,
        "flowScore": None,
        "source": "",
        "sourceFiles": [],
        "matchedRows": 0,
        "_missingReason": reason,
    }


def _has_financial_value(item: dict[str, Any]) -> bool:
    return any(
        bool(item.get(key))
        for key in ("eps", "per", "pbr", "roe", "revenue", "operatingProfit", "netIncome", "debtRatio")
    )


def _company_finalize(item: dict[str, Any], has_sources: bool) -> dict[str, Any]:
    item = dict(item)
    item["missingFields"] = _missing_fields(item)
    matched_rows = int(item.get("matchedRows") or 0)
    has_values = _has_financial_value(item)

    if not has_sources:
        item["missingReason"] = "기업분석 재무 원본 CSV/API가 없습니다."
        item["dataStatus"] = "NO_DATA"
        item["connectionStatus"] = "재무 원본 없음"
    elif matched_rows <= 0:
        item["missingReason"] = item.get("_missingReason") or "재무 CSV에 종목코드가 없거나 종목명 매핑이 필요합니다."
        item["dataStatus"] = "NO_DATA"
        item["connectionStatus"] = "컬럼 매핑 필요"
    elif item["missingFields"] or not has_values:
        item["missingReason"] = "재무 원본 행은 연결됐지만 일부 항목 값이 비어 있습니다."
        item["dataStatus"] = "PARTIAL"
        item["connectionStatus"] = "값 비어 있음"
    else:
        item["missingReason"] = ""
        item["dataStatus"] = "NORMAL"
        item["connectionStatus"] = "정상"
    item.pop("_missingReason", None)
    return item


def _company_target_items(market: str, names: dict[str, str]) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for row in _all_symbol_rows():
        item_market = _infer_market(_symbol(row), _text(row, ["market", "시장", "_market"], market))
        if market != "all" and item_market != market:
            continue
        symbol = _symbol(row, item_market)
        if not symbol:
            continue
        name = _display_name(row, symbol, item_market, names)
        key = f"{item_market}-{symbol}"
        targets.setdefault(key, {"symbol": symbol, "name": name, "market": item_market})
    return targets


def _write_financial_gap_report(items: list[dict[str, Any]]) -> None:
    gaps = [item for item in items if item.get("connectionStatus") != "정상"]
    if not gaps:
        return
    path = _repo_root() / "reports" / "financial_data_gap_report.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "market",
        "symbol",
        "name",
        "connectionStatus",
        "dataStatus",
        "missingFields",
        "missingReason",
        "source",
        "updated_at",
    ]
    now = datetime.now().isoformat(timespec="seconds")
    try:
        with path.open("w", encoding="utf-8-sig", newline="") as fp:
            writer = csv.DictWriter(fp, fieldnames=fields)
            writer.writeheader()
            for item in gaps:
                writer.writerow({
                    "market": item.get("market", ""),
                    "symbol": item.get("symbol", ""),
                    "name": item.get("name", ""),
                    "connectionStatus": item.get("connectionStatus", ""),
                    "dataStatus": item.get("dataStatus", ""),
                    "missingFields": ", ".join(item.get("missingFields") or []),
                    "missingReason": item.get("missingReason", ""),
                    "source": item.get("source", ""),
                    "updated_at": now,
                })
    except Exception:
        return


def _company_payload(market: str, limit: int, q: str) -> dict[str, Any]:
    market = _market_norm(market)
    names = _build_name_map()
    name_to_symbol = _name_to_symbol_map(names)
    query = str(q or "").strip().lower()
    paths = _company_paths(market)
    has_sources = bool(paths)

    merged: dict[str, dict[str, Any]] = {}
    targets = _company_target_items(market, names)

    for path in paths:
        for row in _read_csv(path, 50000):
            item_market = _infer_market(_symbol(row), _text(row, ["market", "시장", "_market"], market))
            if market != "all" and item_market != market:
                continue

            sym = _company_symbol(row, item_market, name_to_symbol)
            if not sym:
                continue

            name = _display_name(row, sym, item_market, names)
            key = f"{item_market}-{sym}"
            row_item = _company_row_item(row, sym, name, item_market, path)

            if key in merged:
                merged[key] = _merge_company_item(merged[key], row_item)
            else:
                merged[key] = row_item
            targets.setdefault(key, {"symbol": sym, "name": name, "market": item_market})

    for key, target in targets.items():
        if key not in merged:
            merged[key] = _blank_company_item(
                target["symbol"],
                target["name"],
                target["market"],
                "보유/추천/관심 종목에는 포함됐지만 재무 CSV에서 매칭되는 행을 찾지 못했습니다.",
            )

    items = [_company_finalize(item, has_sources) for item in merged.values()]
    if query:
        items = [
            item for item in items
            if query in item.get("symbol", "").lower() or query in item.get("name", "").lower()
        ]
    status_order = {"NORMAL": 0, "PARTIAL": 1, "NO_DATA": 2, "ERROR": 3}
    items.sort(key=lambda item: (status_order.get(item.get("dataStatus"), 9), item["market"], item["name"], item["symbol"]))
    max_limit = max(1, min(limit, 10000))
    _write_financial_gap_report(items)
    items = items[:max_limit]

    normal_count = sum(1 for item in items if item.get("dataStatus") == "NORMAL")
    partial_count = sum(1 for item in items if item.get("dataStatus") == "PARTIAL")
    no_data_count = sum(1 for item in items if item.get("dataStatus") == "NO_DATA")

    return {
        "status": "OK" if items else "NO_DATA",
        "market": market,
        "count": len(items),
        "normalCount": normal_count,
        "partialCount": partial_count,
        "noDataCount": no_data_count,
        "items": items,
        "sourceFiles": [p.name for p in paths[:20]],
        "message": "company financial rows merged from company/clean/cards/kpi/valuation sources by market+symbol and name mapping",
    }

def _quote_files(market: str) -> list[Path]:
    return _direct_files(
        f"kis_current_price_{market}.csv",
        f"intraday_quote_snapshot_{market}.csv",
        f"data/kis_current_price_{market}.csv",
        f"data/intraday_quote_snapshot_{market}.csv",
        f"reports/kis_current_price_{market}.csv",
        f"reports/intraday_quote_snapshot_{market}.csv",
    )


def _recommendation_paths(market: str, mode: str, horizon: str) -> list[tuple[Path, str]]:
    exact = _direct_files(
        f"reports/mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
        f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv",
    )
    if exact:
        return [(path, "MATCH") for path in exact]

    fallback = _direct_files(
        f"reports/mone_v36_final_recommendations_{market}_balanced_{horizon}.csv",
        f"reports/mone_v36_final_recommendations_{market}_{mode}_swing.csv",
        f"reports/predictions.csv",
        f"predictions.csv",
        f"reports/v93_action_cards_{market}.csv",
        f"v93_action_cards_{market}.csv",
        f"candidate_universe_{market}.csv",
        f"data/candidate_universe_{market}.csv",
    )
    return [(path, "FALLBACK") for path in fallback]


def _recommendation_item(
    row: dict[str, Any],
    market: str,
    mode: str,
    horizon: str,
    source_status: str,
    source_mode: str,
    source_horizon: str,
    names: dict[str, str],
    quotes: dict[str, dict[str, Any]],
    watch: set[str],
) -> dict[str, Any] | None:
    sym = _symbol(row, market)
    if not sym:
        return None
    if market == "kr" and not re.fullmatch(r"\d{6}", sym):
        return None
    if market == "us" and not re.fullmatch(r"[A-Z.\-]{1,12}", sym):
        return None

    quote = quotes.get(sym, {})
    current = _num(_text(quote, PRICE_KEYS, "")) or _num(_text(row, PRICE_KEYS, ""))
    entry = _num(_text(row, ["entry", "entry_price", "entryPrice", "preferred_entry", "technical_entry", "support1", "진입가"], ""))
    if entry <= 0:
        entry = current

    # ── 기간별 정량 기준으로 손절/목표가 산출
    # short:  손절 -3~-5%, 목표 +4~+8%
    # swing:  손절 -5~-8%, 목표 +8~+18%
    # mid:    손절 -7~-12%, 목표 +15~+30%
    _horizon_bands = {
        "short": {"stop_mid": 0.961, "target_mid": 1.060},   # -3.9% / +6.0%
        "swing": {"stop_mid": 0.935, "target_mid": 1.130},   # -6.5% / +13.0%
        "mid":   {"stop_mid": 0.905, "target_mid": 1.220},   # -9.5% / +22.0%
    }
    _mode_risk = {"conservative": 0.85, "balanced": 1.0, "aggressive": 1.20}
    _mode_reward = {"conservative": 0.80, "balanced": 1.0, "aggressive": 1.30}

    band = _horizon_bands.get(horizon, _horizon_bands["swing"])
    risk_factor = _mode_risk.get(mode, 1.0)
    reward_factor = _mode_reward.get(mode, 1.0)

    stop = _num(_text(row, ["stop", "stop_loss", "stopLoss", "손절가"], ""))
    if stop <= 0 and entry > 0:
        raw_stop_pct = 1.0 - band["stop_mid"]
        stop = entry * (1.0 - raw_stop_pct * risk_factor)

    target = _num(_text(row, ["target", "target_price", "targetPrice", "take_profit1", "resistance1", "목표가"], ""))
    if target <= 0 and entry > 0:
        raw_target_pct = band["target_mid"] - 1.0
        target = entry * (1.0 + raw_target_pct * reward_factor)

    expected = _num(_text(row, ["expectedPrice", "expected_price", "예상가"], "")) or target

    probability = _text(row, ["probability", "win_probability", "probSwing", "prob_3d", "prob_5d", "확률"], "58")
    price_status = "NORMAL" if current > 0 else "PARTIAL"
    fallback_reason = ""
    if source_status == "FALLBACK":
        fallback_reason = "요청한 투자 성향/기간과 정확히 일치하는 추천 파일이 없어 대체 소스를 사용했습니다."
    if current <= 0:
        fallback_reason = (fallback_reason + " " if fallback_reason else "") + "현재가 매핑 필요."

    return {
        "id": f"{market.upper()}-{sym}",
        "symbol": sym,
        "name": _display_name(row, sym, market, names),
        "market": market,
        "mode": mode,
        "modeLabel": MODE_LABEL[mode],
        "horizon": horizon,
        "horizonLabel": HORIZON_LABEL[horizon],
        "sourceMode": source_mode or mode,
        "sourceHorizon": source_horizon or horizon,
        "sourceStatus": source_status,
        "fallbackReason": fallback_reason,
        "currentPrice": current if current > 0 else None,
        "currentPriceText": _price_text(current, market),
        "entry": entry if entry > 0 else None,
        "entryText": _optional_price_text(entry, market),
        "stop": stop if stop > 0 else None,
        "stopText": _optional_price_text(stop, market),
        "target": target if target > 0 else None,
        "targetText": _optional_price_text(target, market),
        "expectedPrice": expected if expected > 0 else None,
        "expectedPriceText": _optional_price_text(expected, market),
        "probability": _num(probability, 0),
        "probabilityText": _pct_text(probability),
        "prob1d": _pct_text(_text(row, ["prob1d", "prob_1d"], probability)),
        "prob3d": _pct_text(_text(row, ["prob3d", "prob_3d"], probability)),
        "prob5d": _pct_text(_text(row, ["prob5d", "prob_5d"], probability)),
        "priceDataStatus": price_status,
        "dataStatus": price_status,
        "warning_reason": "가격 일부 누락" if price_status == "PARTIAL" else "",
        "priceSource": _text(quote, ["_source_file"], "") or _text(row, ["_source_file", "sourceFile", "source"], ""),
        "source": _text(row, ["_source_file", "sourceFile", "source"], ""),
        "isWatch": sym in watch,
    }
def _recommendation_item(
    row: dict[str, Any],
    market: str,
    mode: str,
    horizon: str,
    source_status: str,
    source_mode: str,
    source_horizon: str,
    names: dict[str, str],
    quotes: dict[str, dict[str, Any]],
    watch: set[str],
) -> dict[str, Any] | None:
    sym = _symbol(row, market)
    if not sym:
        return None
    if market == "kr" and not re.fullmatch(r"\d{6}", sym):
        return None
    if market == "us" and not re.fullmatch(r"[A-Z.\-]{1,12}", sym):
        return None

    quote = quotes.get(sym, {})
    computed_fields: list[str] = []
    profile = _strategy_profile(mode)

    current = _num(_text(quote, PRICE_KEYS, "")) or _num(_text(row, PRICE_KEYS, ""))
    entry = _num(_text(row, ["entry", "entry_price", "entryPrice", "preferred_entry", "technical_entry", "support1"], ""))
    if entry <= 0:
        entry = current
        if entry > 0:
            _computed_append(computed_fields, "entry_from_current_price")
    if current <= 0 and entry > 0:
        current = entry
        _computed_append(computed_fields, "current_price_from_entry")

    stop = _num(_text(row, ["stop", "stop_loss", "stopLoss", "stopPrice"], ""))
    if stop <= 0 and entry > 0:
        stop = entry * profile["stop"]
        _computed_append(computed_fields, "stop_from_strategy")

    target = _num(_text(row, ["target", "target_price", "targetPrice", "take_profit1", "resistance1"], ""))
    if target <= 0 and entry > 0:
        target = entry * profile["target"]
        _computed_append(computed_fields, "target_from_strategy")

    # Strategy x horizon display values must not collapse into the same
    # entry/stop/target set. Some source CSV files have identical raw prices
    # across conservative/balanced/aggressive and short/swing/mid. Keep the
    # same candidate universe, but create transparent strategy-adjusted risk
    # levels from current/entry gap and original risk-reward width.
    # This is marked in computedFields so the UI can explain that values are
    # adjusted for strategy/period comparison rather than raw source prices.
    source_mismatch = bool(source_status == "FALLBACK" and ((source_mode and source_mode != mode) or (source_horizon and source_horizon != horizon)))
    if entry > 0:
        raw_entry = entry
        raw_stop = stop
        raw_target = target
        horizon_factor = {"short": 0.68, "swing": 1.0, "mid": 1.32}.get(horizon, 1.0)
        mode_gap_factor = {"conservative": 0.78, "balanced": 1.0, "aggressive": 1.18}.get(mode, 1.0)
        mode_risk_factor = {"conservative": 0.72, "balanced": 1.0, "aggressive": 1.24}.get(mode, 1.0)
        mode_reward_factor = {"conservative": 0.78, "balanced": 1.0, "aggressive": 1.35}.get(mode, 1.0)

        if current > 0:
            raw_gap_pct = (raw_entry - current) / current
            # For already-below-entry candidates, keep direction but scale width.
            entry = current * (1.0 + raw_gap_pct * mode_gap_factor * horizon_factor)

        if entry > 0:
            raw_risk_pct = abs((raw_entry - raw_stop) / raw_entry) if raw_stop > 0 and raw_entry > 0 else abs(1.0 - profile["stop"])
            raw_reward_pct = abs((raw_target - raw_entry) / raw_entry) if raw_target > 0 and raw_entry > 0 else abs(profile["target"] - 1.0)
            risk_pct = max(0.012, min(0.18, raw_risk_pct * mode_risk_factor * horizon_factor))
            reward_pct = max(0.025, min(0.35, raw_reward_pct * mode_reward_factor * horizon_factor))
            stop = entry * (1.0 - risk_pct)
            target = entry * (1.0 + reward_pct)
            expected = target

        if source_mismatch:
            _computed_append(computed_fields, "strategy_horizon_overlay_from_fallback")
        else:
            _computed_append(computed_fields, "strategy_horizon_adjusted_from_source")

    expected = _num(_text(row, ["expectedPrice", "expected_price"], ""))
    if expected <= 0:
        expected = target if target > 0 else current * (1 + max(profile["target"] - 1, 0.03))
        if expected > 0:
            _computed_append(computed_fields, "expected_price_from_target")

    probability_raw = _text(row, ["probability", "win_probability", "probSwing", "prob_3d", "prob_5d"], "")
    raw_probability = _prob_number(probability_raw, 58.0)
    use_auto_probability = (not probability_raw) or raw_probability < 45.0
    if use_auto_probability:
        probability = _auto_probability(row, sym, mode, horizon, current, entry, stop, target, raw_probability)
        _computed_append(computed_fields, "probability_auto")
        if probability_raw:
            _computed_append(computed_fields, "probability_source_low_confidence")
    else:
        probability = round(_clamp(raw_probability + profile["prob"]), 1)
    prob1d = round(_clamp(probability - 1.0), 1)
    prob3d = round(_clamp(probability + (0.5 if horizon == "short" else 1.0)), 1)
    prob5d = round(_clamp(probability + (1.5 if horizon == "swing" else 0.5)), 1)
    prob10d = round(_clamp(probability + (2.0 if horizon == "mid" else 1.0)), 1)

    # 실제 데이터 품질 기준: KIS 실시간 현재가 있으면 NORMAL, 없으면 PARTIAL
    has_live_quote = bool(_text(quote, PRICE_KEYS, ""))
    price_status = "NORMAL" if has_live_quote else ("PARTIAL" if current > 0 else "PRICE_PENDING")
    fallback_reason = ""
    if source_status == "FALLBACK":
        fallback_reason = "요청한 투자 성향/기간과 정확히 일치하는 추천 파일이 없어 대체 소스를 사용했습니다."
    if "current_price_from_entry" in computed_fields:
        fallback_reason = (fallback_reason + " " if fallback_reason else "") + "현재가는 진입가 기준으로 보강했습니다."

    return {
        "id": f"{market.upper()}-{sym}",
        "symbol": sym,
        "name": _display_name(row, sym, market, names),
        "market": market,
        "mode": mode,
        "modeLabel": MODE_LABEL[mode],
        "horizon": horizon,
        "horizonLabel": HORIZON_LABEL[horizon],
        "sourceMode": source_mode or mode,
        "sourceHorizon": source_horizon or horizon,
        "sourceStatus": source_status,
        "fallbackReason": fallback_reason,
        "currentPrice": current if current > 0 else None,
        "currentPriceText": _price_text(current, market),
        "entry": entry if entry > 0 else None,
        "entryText": _optional_price_text(entry, market),
        "stop": stop if stop > 0 else None,
        "stopText": _optional_price_text(stop, market),
        "target": target if target > 0 else None,
        "targetText": _optional_price_text(target, market),
        "expectedPrice": expected if expected > 0 else None,
        "expectedPriceText": _optional_price_text(expected, market),
        "probability": probability,
        "probabilityText": _pct_text(probability),
        "prob1d": _pct_text(_text(row, ["prob1d", "prob_1d"], prob1d)),
        "prob3d": _pct_text(_text(row, ["prob3d", "prob_3d"], prob3d)),
        "prob5d": _pct_text(_text(row, ["prob5d", "prob_5d"], prob5d)),
        "prob10d": _pct_text(_text(row, ["prob10d", "prob_10d"], prob10d)),
        "priceDataStatus": price_status,
        "dataStatus": price_status,
        "warning_reason": "자동 보강값 포함" if computed_fields else "",
        "priceSource": _text(quote, ["_source_file"], "") or _text(row, ["_source_file", "sourceFile", "source"], ""),
        "source": _text(row, ["_source_file", "sourceFile", "source"], ""),
        "computedFields": computed_fields,
        "isWatch": sym in watch,
    }


def _light_correction_summary(market: str, mode: str, horizon: str) -> dict[str, Any]:
    path = _repo_root() / "reports" / "virtual_validation_results.csv"
    rows = _read_csv(path, 100000)
    filtered = [
        row for row in rows
        if str(row.get("market") or "").lower() == market
        and str(row.get("mode") or "").lower() == mode
        and str(row.get("horizon") or "").lower() == horizon
    ]
    filtered.sort(key=lambda row: str(row.get("validationDueDate") or row.get("createdAt") or row.get("date") or ""), reverse=True)
    evaluated = [
        row for row in filtered
        if str(row.get("result") or "").upper() not in {"", "PENDING", "VALIDATABLE", "DATA_PENDING"}
    ]
    executed = [
        row for row in evaluated
        if str(row.get("isExecuted") or row.get("executed") or "").lower() in {"true", "1", "yes", "executed", "체결"}
    ]
    failures: list[dict[str, Any]] = []
    for row in executed[:3]:
        text = " ".join(str(row.get(key) or "") for key in ("result", "reason", "failureReason", "dataStatus")).lower()
        return_pct = _num(row.get("returnPct"))
        if "stop" in text or "손절" in text or (return_pct < 0):
            failures.append(row)
        else:
            break
    recent_evaluated = evaluated[:5]
    not_executed = [
        row for row in recent_evaluated
        if str(row.get("result") or "").upper() in {"NOT_EXECUTED", "NO_TOUCH", "ENTRY_NOT_TOUCHED"}
        or str(row.get("isExecuted") or "").lower() in {"false", "0", "no"}
    ]
    miss_rate = round(len(not_executed) / len(recent_evaluated) * 100, 2) if recent_evaluated else 0.0
    stop_active = len(failures) >= 3
    miss_active = len(recent_evaluated) >= 5 and miss_rate >= 60
    active = stop_active or miss_active
    penalty = (15.0 if stop_active else 0.0) + (8.0 if miss_active else 0.0)
    reason_parts: list[str] = []
    if stop_active:
        reason_parts.append("최근 3회 연속 체결 손절로 승률 15% 감산")
    if miss_active:
        reason_parts.append(f"최근 검증 미체결률 {miss_rate:.1f}%로 진입 밴드 보정 필요")
    return {
        "status": "OK",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "active": active,
        "penaltyPct": penalty if active else 0.0,
        "priorityDowngrade": active,
        "consecutiveStopFailures": len(failures),
        "recentEvaluatedCount": len(recent_evaluated),
        "recentNotExecutedCount": len(not_executed),
        "recentNotExecutedRate": miss_rate,
        "entryBandAction": "PULL_ENTRY_CLOSER" if miss_active else "KEEP",
        "threshold": 3,
        "source": path.name if path.exists() else "virtual_validation_results_missing",
        "correctionReasons": reason_parts,
        "validationPolicy": "entry_touch_only: low<=entry<=high only, not executed is not a win, same-bar target/stop uses stop-first",
        "reason": "최근 3회 연속 손절 실패로 승률 15% 감산" if active else "자가 보정 비활성",
    }


def _apply_light_correction(item: dict[str, Any], summary: dict[str, Any]) -> dict[str, Any]:
    if not summary.get("active"):
        return item
    penalty = float(summary.get("penaltyPct") or 15.0)
    adjusted = dict(item)
    probability = _num(adjusted.get("probability"))
    if probability > 0:
        adjusted["probability"] = max(0.0, round(probability - penalty, 1))
        adjusted["probabilityText"] = _pct_text(adjusted["probability"])
    for key in ("finalScore", "quantScore"):
        if isinstance(adjusted.get(key), (int, float)):
            adjusted[key] = round(float(adjusted[key]) * 0.85, 1)
    if summary.get("entryBandAction") == "PULL_ENTRY_CLOSER":
        current = _num(adjusted.get("currentPrice"))
        entry = _num(adjusted.get("entry"))
        stop = _num(adjusted.get("stop"))
        target = _num(adjusted.get("target"))
        if current > 0 and entry > 0 and abs(entry - current) / current > 0.03:
            risk_pct = abs(entry - stop) / entry if stop > 0 else 0.04
            reward_pct = abs(target - entry) / entry if target > 0 else max(risk_pct * 2, 0.06)
            risk_pct = min(max(risk_pct, 0.015), 0.12)
            reward_pct = min(max(reward_pct, risk_pct * 1.8), 0.25)
            new_entry = current * 0.98 if entry < current else current * 1.005
            item_market = str(adjusted.get("market") or "kr")
            adjusted["entry"] = round(new_entry, 2)
            adjusted["entryText"] = _optional_price_text(adjusted["entry"], item_market)
            adjusted["stop"] = round(new_entry * (1 - risk_pct), 2)
            adjusted["stopText"] = _optional_price_text(adjusted["stop"], item_market)
            adjusted["target"] = round(new_entry * (1 + reward_pct), 2)
            adjusted["targetText"] = _optional_price_text(adjusted["target"], item_market)
            adjusted.setdefault("computedFields", []).append("self_correction_entry_band_adjusted")
            adjusted["entryBandCorrection"] = "recent no-touch rate was high, entry band pulled closer to current price with original risk width preserved"
    adjusted["selfCorrectionPenaltyPct"] = penalty
    adjusted["priorityDowngraded"] = True
    adjusted["validationPolicy"] = summary.get("validationPolicy")
    adjusted["warning_reason"] = (
        f"{adjusted.get('warning_reason')} · {summary.get('reason')}"
        if adjusted.get("warning_reason")
        else str(summary.get("reason") or "자가 보정 감산 적용")
    )
    return adjusted


def _scan_coverage(market: str) -> dict[str, Any]:
    repo = _repo_root()
    candidate_rows: list[dict[str, Any]] = []
    for path in _direct_files(
        f"candidate_universe_{market}.csv",
        f"data/candidate_universe_{market}.csv",
        f"reports/candidate_universe_{market}.csv",
    ):
        candidate_rows.extend(_read_csv(path, 100000))
    candidate_symbols = {_symbol(row, market) for row in candidate_rows if _symbol(row, market)}
    ohlcv_dir = repo / "data" / "market" / "ohlcv"
    ohlcv_symbols = {
        p.name[len(f"{market}_"):-len("_daily.csv")].upper()
        for p in ohlcv_dir.glob(f"{market}_*_daily.csv")
    } if ohlcv_dir.exists() else set()
    quote_rows = _read_csv(repo / "reports" / "price_collection_coverage_audit.csv", 100000)
    quote_market_rows = [row for row in quote_rows if str(row.get("market") or "").lower() == market]
    quote_ok = [
        row for row in quote_market_rows
        if str(row.get("status") or "").upper() == "NORMAL"
        or str(row.get("hasCurrentPrice") or "").lower() == "true"
        or str(row.get("currentPriceStatus") or "").upper() == "NORMAL"
    ]
    full_threshold = 1500 if market == "kr" else 3000
    universe_count = len(candidate_symbols | ohlcv_symbols)
    is_full_market = universe_count >= full_threshold
    return {
        "market": market,
        "universeScope": "FULL_MARKET_READY" if is_full_market else "CURATED_UNIVERSE",
        "candidateUniverseCount": len(candidate_symbols),
        "ohlcvSymbolCount": len(ohlcv_symbols),
        "localScanUniverseCount": universe_count,
        "fullMarketThreshold": full_threshold,
        "quoteCoverageCount": len(quote_ok),
        "quoteTargetCount": len(quote_market_rows),
        "quoteCoveragePct": round(len(quote_ok) / len(quote_market_rows) * 100, 2) if quote_market_rows else 0.0,
        "isFullMarket": is_full_market,
        "message": (
            "Full market scan ready"
            if is_full_market
            else "Curated universe only: expand symbol master, OHLCV, quote, news/disclosure/fundamental collection before labeling this as full-market scan."
        ),
    }


def _validation_policy_payload() -> dict[str, Any]:
    return {
        "executionRule": "A recommendation is executed only when actual low <= entry <= high during the validation window.",
        "successRule": "Only executed trades that hit target are counted as wins.",
        "lossRule": "Executed trades that hit stop are counted as losses.",
        "sameBarRule": "If target and stop both touch in the same daily bar, stop is assumed first.",
        "notExecutedRule": "Not-executed predictions are excluded from win-rate and return, but feed entry-band correction.",
        "dataRule": "Missing OHLCV remains DATA_PENDING and is never counted as success.",
    }


@lru_cache(maxsize=48)
def _recommendations_payload_cached(market: str, mode: str, horizon: str, limit: int, watch_only: bool) -> dict[str, Any]:
    market = _market_norm(market)
    mode = _mode_norm(mode)
    horizon = _horizon_norm(horizon)

    if market == "all":
        merged: list[dict[str, Any]] = []
        source_files: list[str] = []
        for item_market in ("kr", "us"):
            payload = _recommendations_payload_cached(item_market, mode, horizon, limit, watch_only)
            merged.extend(payload.get("items", []))
            source_files.extend(payload.get("sourceFiles", []))
        deduped: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in merged:
            key = f"{item.get('market')}-{item.get('symbol')}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
            if len(deduped) >= max(1, min(limit, 1000)):
                break
        return {
            "status": "OK" if deduped else "NO_DATA",
            "market": "all",
            "mode": mode,
            "horizon": horizon,
            "count": len(deduped),
            "uniqueCount": len(seen),
            "hiddenCount": 0,
            "scanCoverage": {"kr": _scan_coverage("kr"), "us": _scan_coverage("us")},
            "validationPolicy": _validation_policy_payload(),
            "sourceFiles": source_files[:20],
            "items": deduped,
        }

    names = _build_name_map()
    quotes = _quote_index(market)
    watch = _watch_symbols()
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    source_files: list[str] = []
    correction_state: dict[str, Any] = _light_correction_summary(market, mode, horizon)

    for path, source_status in _recommendation_paths(market, mode, horizon):
        if path.name not in source_files:
            source_files.append(path.name)
        rows = _read_csv(path, 50000)
        for row in rows:
            source_mode, source_horizon = _extract_source_mode_horizon(path, row)
            if source_status == "MATCH":
                source_mode = source_mode or mode
                source_horizon = source_horizon or horizon

            # Matrix/home comparisons should not become empty just because the
            # exact strategy x horizon source file is missing. In FALLBACK mode,
            # keep the nearest available source and mark sourceMode/sourceHorizon
            # on each item so the UI can show "동일 소스 확인" instead of hiding
            # the cell entirely. Exact MATCH rows are still preferred above.
            sym = _symbol(row, market)
            key = f"{market}-{sym}"
            if not sym or key in seen:
                continue
            if watch_only and sym not in watch:
                continue

            item = _recommendation_item(row, market, mode, horizon, source_status, source_mode, source_horizon, names, quotes, watch)
            if not item:
                continue
            try:
                from app.engine.quant_scanner import apply_quant_overlay

                item = apply_quant_overlay(item, _repo_root(), mode, horizon)
            except Exception:
                item.setdefault("computedFields", []).append("quant_scanner_unavailable")
            if correction_state.get("active"):
                item = _apply_light_correction(item, correction_state)
                item.setdefault("computedFields", []).append("self_correction_penalty")
            seen.add(key)
            items.append(item)
            if len(items) >= max(1, min(limit, 1000)):
                break
        if len(items) >= max(1, min(limit, 1000)):
            break

    # ── EV 음수 필터링 및 마켓 레짐 정보 수집
    ev_negative_count = 0
    filtered_items: list[dict[str, Any]] = []
    for item in items:
        ev = item.get("expectedValue")
        ev_val = None
        try:
            ev_val = float(ev) if ev not in (None, "", "nan") else None
        except Exception:
            pass
        ev_negative = ev_val is not None and ev_val < 0
        item["evNegative"] = ev_negative
        if ev_negative:
            ev_negative_count += 1
            # 보수형은 EV 음수 종목 완전 제외
            if mode == "conservative":
                continue
            # 균형/공격은 tradeBlockStatus를 CAUTION으로, 진입 버킷을 기다림으로
            item["tradeBlockStatus"] = "EV_NEGATIVE"
            item["decisionBucket"] = "기다림"
            item.setdefault("strategyTags", [])
            if "CAUTION" not in item["strategyTags"]:
                item["strategyTags"].append("CAUTION")
        filtered_items.append(item)

    hidden_count = len(items) - len(filtered_items)

    # 마켓 레짐 로드
    market_regime: dict[str, Any] = {}
    try:
        from app.engine.quant_scanner import load_market_regime
        market_regime = load_market_regime(_repo_root(), market)
    except Exception:
        pass

    return {
        "status": "OK" if filtered_items else "NO_DATA",
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "count": len(filtered_items),
        "uniqueCount": len(seen),
        "hiddenCount": hidden_count,
        "evNegativeFiltered": ev_negative_count if mode == "conservative" else 0,
        "marketRegime": market_regime,
        "selfCorrection": correction_state,
        "scanCoverage": _scan_coverage(market),
        "validationPolicy": _validation_policy_payload(),
        "sourceFiles": source_files[:20],
        "items": filtered_items,
    }


def _recommendations_payload(market: str, mode: str, horizon: str, cash: float, limit: int, watch_only: bool) -> dict[str, Any]:
    payload = _recommendations_payload_cached(market, mode, horizon, limit, watch_only)
    try:
        _record_virtual_ledger(payload.get("items", []), "api/final/recommendations")
    except Exception:
        pass
    return json.loads(json.dumps(payload, ensure_ascii=False))


def _pct_gap(current: float, level: float) -> float | None:
    if current <= 0 or level <= 0:
        return None
    return round((level - current) / current * 100.0, 2)


def _signed_pct_text(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _intraday_status(item: dict[str, Any]) -> tuple[str, str]:
    current = _num(item.get("currentPrice"))
    entry = _num(item.get("entry"))
    stop = _num(item.get("stop"))
    target = _num(item.get("target"))
    if current <= 0:
        return "현재가 없음", "현재가 수집이 필요합니다."
    if entry > 0 and abs(current - entry) / entry <= 0.02:
        return "진입 임박", "진입가 2% 이내입니다."
    if entry > 0 and current > entry * 1.02:
        if target > 0 and current >= target:
            return "목표 도달", "현재가가 목표가 이상입니다."
        if target > 0 and current >= target * 0.985:
            return "목표 접근", "목표가 1.5% 이내입니다."
        if stop > 0 and current <= stop * 1.015:
            return "손절 접근", "진입 후 기준이라면 손절가 1.5% 이내입니다."
        return "진입가 상회", "추격 매수보다 눌림 확인이 필요합니다."
    if entry > 0 and current < entry * 0.98:
        return "관망", "현재가가 진입가보다 낮아 조건 충족을 기다립니다."
    if stop > 0 and current <= stop * 1.015:
        return "손절 접근", "손절가 1.5% 이내입니다."
    return "관망", "현재가와 기준 가격을 확인 중입니다."


def _intraday_payload(market: str, mode: str, horizon: str, limit: int) -> dict[str, Any]:
    payload = _recommendations_payload(market, mode, horizon, 0, limit, False)
    items: list[dict[str, Any]] = []
    for raw in payload.get("items", []) or []:
        item = dict(raw)
        current = _num(item.get("currentPrice"))
        entry = _num(item.get("entry"))
        stop = _num(item.get("stop"))
        target = _num(item.get("target"))
        entry_gap = _pct_gap(current, entry)
        stop_gap = _pct_gap(current, stop)
        target_gap = _pct_gap(current, target)
        status, reason = _intraday_status(item)
        item.update({
            "intradayStatus": status,
            "intradayReason": reason,
            "entryDistancePct": entry_gap,
            "entryDistanceText": _signed_pct_text(entry_gap),
            "stopDistancePct": stop_gap,
            "stopDistanceText": _signed_pct_text(stop_gap),
            "targetDistancePct": target_gap,
            "targetDistanceText": _signed_pct_text(target_gap),
            "priceGapWarning": bool(entry_gap is not None and abs(entry_gap) >= 20),
            "priceSource": item.get("priceSource") or "",
            "recommendationSource": item.get("source") or "",
        })
        items.append(item)
    payload["items"] = items
    payload["reportType"] = "intraday"
    payload["description"] = "현재가 기준 진입/손절/목표 접근도"
    return payload


def _audit_payload() -> dict[str, Any]:
    specs = {
        "candidateKR": ["candidate_universe_kr.csv", "**/candidate_universe_kr.csv", "**/*candidate*kr*.csv"],
        "candidateUS": ["candidate_universe_us.csv", "**/candidate_universe_us.csv", "**/*candidate*us*.csv"],
        "watchlist": ["daily_watch_selection.json", "**/daily_watch_selection.json", "*watch*.csv", "**/*watch*.csv"],
        "ohlcv": ["**/ohlcv/*.csv", "**/*ohlcv*.csv"],
        "companyKR": ["**/*company*kr*.csv", "**/*financial*kr*.csv", "**/*statement*kr*.csv"],
        "companyUS": ["**/*company*us*.csv", "**/*financial*us*.csv", "**/*statement*us*.csv"],
        "virtual": ["**/*virtual*.csv", "paper_trading*.csv", "**/*backtest*.csv", "**/*trading*.csv"],
        "predictions": ["predictions.csv", "**/predictions.csv", "**/prediction*.csv"],
        "news": ["**/*news*.csv"],
        "disclosures": ["**/*disclosure*.csv", "**/disclosures*.csv"],
    }
    items: list[dict[str, Any]] = []
    for name, patterns in specs.items():
        paths = _many(*patterns, max_files=40)
        records = 0
        for path in paths[:5]:
            records += len(_read_csv(path, 20000)) if path.suffix.lower() == ".csv" else 1
        newest = paths[0] if paths else None
        items.append({
            "name": name,
            "status": "OK" if paths else "NO_DATA",
            "path": _safe_rel(newest) if newest else "",
            "count": records,
            "modified": datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if newest else "",
        })
    return {"status": "OK", "root": str(_app_root()), "searchRoots": [str(path) for path in _search_roots()], "items": items}


def _github_payload() -> dict[str, Any]:
    app_root = _app_root()
    repo = app_root if (app_root / ".git").exists() else app_root.parent
    is_repo = (repo / ".git").exists()
    branch = ""
    remote = ""
    if is_repo:
        try:
            branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            pass
        try:
            remote = subprocess.check_output(["git", "remote", "-v"], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip().splitlines()[0]
        except Exception:
            pass
    return {"status": "OK", "isGitRepo": is_repo, "branch": branch, "remote": remote, "root": str(repo)}


def _safe_payload(fn: Callable[[], dict[str, Any]], endpoint: str) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {
            "status": "ERROR",
            "error": f"{type(exc).__name__}: {exc}",
            "endpoint": endpoint,
            "appRoot": str(_app_root()),
            "searchRoots": [str(path) for path in _search_roots()],
            "items": [],
            "count": 0,
        }


# __HOLDINGS_WATCHLIST_EDITOR_PATCH__
def _editable_csv_path(kind: str, market: str) -> Path:
    market_key = _market_norm(market)
    if market_key == "all":
        market_key = "kr"
    filename = f"{'holdings' if kind == 'holdings' else 'watchlist'}_{market_key}.csv"
    return _repo_root() / filename


def _normalize_edit_symbol(symbol: Any, market: str) -> str:
    value = _symbol_value(symbol)
    market_key = _market_norm(market)
    if market_key == "kr":
        digits = re.sub(r"\D", "", value)
        return digits.zfill(6)[-6:] if digits else ""
    return value.upper()


def _read_edit_rows(kind: str, market: str = "all") -> list[dict[str, Any]]:
    markets = ["kr", "us"] if _market_norm(market) == "all" else [_market_norm(market)]
    names = _build_name_map()
    rows: list[dict[str, Any]] = []
    for mk in markets:
        path = _editable_csv_path(kind, mk)
        for row in _read_csv(path, 20000):
            symbol = _normalize_edit_symbol(_symbol(row, mk), mk)
            if not symbol:
                continue
            name = _display_name(row, symbol, mk, names)
            item: dict[str, Any] = {
                "market": mk,
                "symbol": symbol,
                "name": name,
                "source": path.name,
                "sourcePath": str(path),
            }
            if kind == "holdings":
                item["quantity"] = _num(_text(row, ["quantity", "qty", "?섎웾"], ""), 0)
                item["avgPrice"] = _num(_text(row, ["avgPrice", "avg_price", "averagePrice", "?됯퇏?④?", "留ㅼ엯媛"], ""), 0)
            rows.append(item)
    rows.sort(key=lambda x: (str(x.get("market", "")), str(x.get("symbol", ""))))
    return rows


def _backup_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup_dir = _repo_root() / "_archive_old_files" / "mone_edit_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp_value = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = backup_dir / f"{path.name}.bak_{stamp_value}"
    backup.write_bytes(path.read_bytes())
    return backup


def _write_csv_rows(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _collection_target_path(market: str) -> Path:
    return _repo_root() / "data" / "stockapp" / f"kis_collection_targets_{market}.csv"


def _append_collection_targets(rows: list[dict[str, Any]], default_reason: str) -> dict[str, Any]:
    updated_files: list[str] = []
    updated_count = 0
    by_market: dict[str, list[dict[str, Any]]] = {"kr": [], "us": []}
    for row in rows:
        market = _market_norm(row.get("market", "kr"))
        if market not in {"kr", "us"}:
            continue
        symbol = _normalize_edit_symbol(row.get("symbol", ""), market)
        if not symbol:
            continue
        by_market[market].append({
            "market": market,
            "symbol": symbol,
            "name": str(row.get("name") or _fallback_name(symbol, market)).strip(),
            "reason": str(row.get("targetReason") or row.get("_targetReason") or default_reason).strip() or default_reason,
            "updatedAt": datetime.now().isoformat(timespec="seconds"),
        })

    for market, new_rows in by_market.items():
        if not new_rows:
            continue
        path = _collection_target_path(market)
        existing: dict[str, dict[str, Any]] = {}
        for row in _read_csv(path, 20000):
            symbol = _normalize_edit_symbol(_text(row, ["symbol", "code", "ticker"], ""), market)
            if not symbol:
                continue
            existing[symbol] = {
                "market": market,
                "symbol": symbol,
                "name": _text(row, ["name", "companyName"], _fallback_name(symbol, market)),
                "reason": _text(row, ["reason"], "existing"),
                "updatedAt": _text(row, ["updatedAt"], ""),
            }
        before = len(existing)
        for row in new_rows:
            existing[row["symbol"]] = row
        _write_csv_rows(
            path,
            ["market", "symbol", "name", "reason", "updatedAt"],
            sorted(existing.values(), key=lambda item: item["symbol"]),
        )
        updated_count += max(0, len(existing) - before) + len(new_rows)
        updated_files.append(str(path))

    return {"targetCount": updated_count, "targetFiles": updated_files}


def _horizon_window_days(horizon: str) -> int:
    return {"short": 3, "swing": 5, "mid": 20, "long": 20}.get(str(horizon or "swing"), 5)


def _date_add_days(date_text: str, days: int) -> str:
    try:
        base = datetime.fromisoformat(str(date_text)[:10])
    except Exception:
        base = datetime.now()
    return (base + timedelta(days=days)).date().isoformat()


def _date_add_trading_days(date_text: str, days: int) -> str:
    try:
        current = datetime.fromisoformat(str(date_text)[:10])
    except Exception:
        current = datetime.now()
    remaining = max(0, int(days or 0))
    while remaining > 0:
        current = current + timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current.date().isoformat()


def _ledger_path() -> Path:
    return _repo_root() / "reports" / "virtual_prediction_ledger.csv"


def _validation_path() -> Path:
    return _repo_root() / "reports" / "virtual_validation_results.csv"


def _normalize_ledger_due_dates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changed = False
    for row in rows:
        created = str(row.get("createdAt") or "")[:10]
        if not created:
            continue
        window = int(_num(row.get("validationWindowDays")) or _horizon_window_days(str(row.get("horizon") or "swing")))
        due = _date_add_trading_days(created, window)
        if str(row.get("validationDueDate") or "") != due:
            row["validationWindowDays"] = window
            row["validationDueDate"] = due
            changed = True
    if changed:
        _write_csv_rows(_ledger_path(), [
            "predictionId", "createdAt", "market", "symbol", "name", "mode", "horizon",
            "entryPrice", "stopPrice", "targetPrice", "expectedPrice", "probability",
            "validationWindowDays", "validationDueDate", "status", "source",
        ], rows)
    return rows


def _prediction_id(item: dict[str, Any], created_date: str) -> str:
    return "|".join([
        str(item.get("market") or ""),
        str(item.get("symbol") or ""),
        str(item.get("mode") or ""),
        str(item.get("horizon") or ""),
        created_date,
    ])


def _record_virtual_ledger(items: list[dict[str, Any]], source: str = "recommendations") -> None:
    if not items:
        return
    path = _ledger_path()
    existing = _read_csv(path, 100000)
    keyed = {str(row.get("predictionId") or ""): row for row in existing if row.get("predictionId")}
    today = datetime.now().date().isoformat()
    for item in items:
        entry = _num(item.get("entry"))
        stop = _num(item.get("stop"))
        target = _num(item.get("target"))
        if entry <= 0 or stop <= 0 or target <= 0:
            continue
        horizon = str(item.get("horizon") or "swing")
        window = _horizon_window_days(horizon)
        prediction_id = _prediction_id(item, today)
        record = keyed.setdefault(prediction_id, {
            "predictionId": prediction_id,
            "createdAt": today,
            "market": item.get("market", ""),
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "mode": item.get("mode", ""),
            "horizon": horizon,
            "entryPrice": entry,
            "stopPrice": stop,
            "targetPrice": target,
            "expectedPrice": _num(item.get("expectedPrice")),
            "probability": _num(item.get("probability")),
            "validationWindowDays": window,
            "validationDueDate": _date_add_trading_days(today, window),
            "status": "PENDING",
            "source": source,
        })
        record["validationWindowDays"] = window
        record["validationDueDate"] = _date_add_trading_days(str(record.get("createdAt") or today), window)
    _write_csv_rows(path, [
        "predictionId", "createdAt", "market", "symbol", "name", "mode", "horizon",
        "entryPrice", "stopPrice", "targetPrice", "expectedPrice", "probability",
        "validationWindowDays", "validationDueDate", "status", "source",
    ], list(keyed.values()))


def _ohlcv_rows_for(market: str, symbol: str) -> list[dict[str, Any]]:
    paths = [
        _repo_root() / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv",
        _repo_root() / "data" / "stockapp" / f"{market}_{symbol}_daily.csv",
        _repo_root() / "reports" / f"{market}_{symbol}_daily.csv",
    ]
    for path in paths:
        rows = _read_csv(path, 100000)
        if rows:
            rows.sort(key=lambda row: _text(row, ["date", "Date", "날짜"], ""))
            return rows
    return []


def _validate_virtual_ledger() -> dict[str, Any]:
    ledger = _normalize_ledger_due_dates(_read_csv(_ledger_path(), 100000))
    today = datetime.now().date().isoformat()
    results: list[dict[str, Any]] = []
    wins = 0
    executed = 0
    not_executed_count = 0
    data_pending_count = 0
    for row in ledger:
        due = str(row.get("validationDueDate") or "")
        status = "PENDING" if due > today else "VALIDATABLE"
        market = str(row.get("market") or "kr").lower()
        symbol = str(row.get("symbol") or "")
        entry = _num(row.get("entryPrice"))
        stop = _num(row.get("stopPrice"))
        target = _num(row.get("targetPrice"))
        created = str(row.get("createdAt") or "")
        window_rows = [r for r in _ohlcv_rows_for(market, symbol) if created < _text(r, ["date", "Date", "날짜"], "") <= due]
        result = {
            **row,
            "isExecuted": "false",
            "targetHit": "false",
            "stopHit": "false",
            "exitPrice": "",
            "returnPct": "",
            "result": status,
            "reason": "검증 대기" if status == "PENDING" else "",
            "dataStatus": "NORMAL",
        }
        if status != "PENDING":
            if not window_rows:
                data_pending_count += 1
                result.update({"result": "DATA_PENDING", "reason": "검증 기간 OHLCV 없음", "dataStatus": "DATA_PENDING"})
            else:
                touched = False
                target_hit = False
                stop_hit = False
                close_price = 0.0
                for bar in window_rows:
                    high = _num(_text(bar, ["high", "High", "고가"], ""))
                    low = _num(_text(bar, ["low", "Low", "저가"], ""))
                    close_price = _num(_text(bar, ["close", "Close", "종가"], "")) or close_price
                    if low <= entry <= high:
                        touched = True
                    if touched and high >= target:
                        target_hit = True
                    if touched and low <= stop:
                        stop_hit = True
                if not touched:
                    not_executed_count += 1
                    result.update({"result": "NOT_EXECUTED", "reason": "진입가 미도달"})
                else:
                    executed += 1
                    if stop_hit and target_hit:
                        exit_price = stop
                        result_name = "STOP_FIRST"
                        reason = "목표/손절 동시 터치, 보수적 손절 우선"
                    elif stop_hit:
                        exit_price = stop
                        result_name = "STOP"
                        reason = "손절가 도달"
                    elif target_hit:
                        exit_price = target
                        result_name = "TARGET"
                        reason = "목표가 도달"
                        wins += 1
                    else:
                        exit_price = close_price
                        result_name = "HOLDING_EVAL"
                        reason = "목표/손절 미도달, 종가 평가"
                    return_pct = (exit_price - entry) / entry * 100 if entry > 0 else 0
                    result.update({
                        "isExecuted": "true",
                        "targetHit": "true" if target_hit else "false",
                        "stopHit": "true" if stop_hit else "false",
                        "exitPrice": exit_price,
                        "returnPct": round(return_pct, 4),
                        "result": result_name,
                        "reason": reason,
                        "validationRule": "entry_touch_only",
                    })
        results.append(result)
    _write_csv_rows(_validation_path(), [
        "predictionId", "createdAt", "market", "symbol", "name", "mode", "horizon",
        "entryPrice", "stopPrice", "targetPrice", "expectedPrice", "probability",
        "validationWindowDays", "validationDueDate", "status", "source", "isExecuted",
        "targetHit", "stopHit", "exitPrice", "returnPct", "result", "reason", "dataStatus", "validationRule",
    ], results)
    evaluable_count = len([row for row in results if row.get("dataStatus") != "DATA_PENDING" and row.get("result") != "PENDING"])
    return {
        "status": "OK",
        "count": len(results),
        "executedCount": executed,
        "notExecutedCount": not_executed_count,
        "dataPendingCount": data_pending_count,
        "executionRate": round(executed / max(1, evaluable_count) * 100, 2) if results else 0.0,
        "winRate": round(wins / executed * 100, 2) if executed else 0.0,
        "validationPolicy": _validation_policy_payload(),
        "items": results,
    }


def _quote_map(*args, **kwargs):
    return {}

def _clear_mone_edit_caches() -> None:
    for fn in [
        _build_name_map,
        _watch_symbols,
        _all_symbol_rows,
        _quote_index,
        _symbols_payload_cached,
        _symbols_payload,
        _quote_map,
    ]:
        try:
            fn.cache_clear()  # type: ignore[attr-defined]
        except Exception:
            pass


def _save_edit_rows(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    raw_items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(raw_items, list):
        return {"status": "ERROR", "error": "items must be a list", "items": [], "count": 0}

    grouped: dict[str, list[dict[str, Any]]] = {"kr": [], "us": []}
    errors: list[str] = []

    for idx, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            continue
        market = _market_norm(raw.get("market", "kr"))
        if market not in {"kr", "us"}:
            market = _infer_market(str(raw.get("symbol", "")), market)
        symbol = _normalize_edit_symbol(raw.get("symbol", ""), market)
        name = str(raw.get("name") or _fallback_name(symbol, market)).strip()
        if not symbol:
            errors.append(f"{idx + 1} row symbol missing")
            continue
        if market == "kr" and not re.fullmatch(r"\d{6}", symbol):
            errors.append(f"{idx + 1} row KR symbol must be 6 digits")
            continue

        if kind == "holdings":
            qty = _num(raw.get("quantity"), 0)
            avg = _num(raw.get("avgPrice"), 0)
            if qty <= 0:
                errors.append(f"{symbol} quantity must be greater than 0")
                continue
            if avg <= 0:
                errors.append(f"{symbol} avgPrice must be greater than 0")
                continue
            grouped[market].append({
                "symbol": symbol,
                "name": name,
                "market": market,
                "quantity": qty,
                "avgPrice": avg,
                "_targetReason": str(raw.get("targetReason") or "holding_added").strip(),
            })
        else:
            grouped[market].append({
                "symbol": symbol,
                "name": name,
                "market": market,
                "_targetReason": str(raw.get("targetReason") or "user_added").strip(),
            })

    if errors:
        return {"status": "ERROR", "error": "; ".join(errors[:5]), "items": [], "count": 0}

    backups: list[str] = []
    for market, rows in grouped.items():
        path = _editable_csv_path(kind, market)
        backup = _backup_file(path)
        if backup:
            backups.append(str(backup))
        if kind == "holdings":
            _write_csv_rows(path, ["symbol", "name", "market", "quantity", "avgPrice"], rows)
        else:
            _write_csv_rows(path, ["symbol", "name", "market"], rows)

    target_info = _append_collection_targets(
        [row for rows in grouped.values() for row in rows],
        "holding_added" if kind == "holdings" else "user_added",
    )

    _clear_mone_edit_caches()
    merged = _read_edit_rows(kind, "all")
    return {
        "status": "OK",
        "kind": kind,
        "count": len(merged),
        "items": merged,
        "backupCount": len(backups),
        "backups": backups,
        **target_info,
        "updatedAt": datetime.now().isoformat(),
    }



def register_mone_v65_api_stabilizer(app: Any) -> None:
    paths = {
        "/api/symbols",
        "/api/final/symbols",
        "/api/watchlist",
        "/api/holdings-edit",
        "/api/holdings-edit/save",
        "/api/watchlist-edit",
        "/api/watchlist-edit/save",
        "/api/company-analysis",
        "/api/data/audit",
        "/api/health/github",
        "/api/final/recommendations",
        "/api/v1/candidates",
        "/api/reports/premarket",
        "/api/reports/intraday",
        "/api/predictions/table",
        "/api/virtual/ledger",
        "/api/virtual/validation",
    }
    app.router.routes = [route for route in app.router.routes if not (isinstance(route, APIRoute) and getattr(route, "path", "") in paths)]

    @app.get("/api/symbols")
    def symbols(market: str = Query("all"), q: str = Query(""), watchOnly: bool = Query(False), limit: int = Query(10000)) -> dict[str, Any]:
        return _safe_payload(lambda: _symbols_payload(market, q, watchOnly, limit), "/api/symbols")

    @app.get("/api/final/symbols")
    def final_symbols(market: str = Query("all"), q: str = Query(""), watchOnly: bool = Query(False), limit: int = Query(10000)) -> dict[str, Any]:
        return _safe_payload(lambda: _symbols_payload(market, q, watchOnly, limit), "/api/final/symbols")

    @app.get("/api/watchlist")
    def watchlist(market: str = Query("all"), limit: int = Query(10000)) -> dict[str, Any]:
        return _safe_payload(lambda: _symbols_payload(market, "", True, limit), "/api/watchlist")


    @app.get("/api/holdings-edit")
    def holdings_edit(market: str = Query("all")) -> dict[str, Any]:
        items = _read_edit_rows("holdings", market)
        return _safe_payload(lambda: {"status": "OK", "kind": "holdings", "market": _market_norm(market), "items": items, "count": len(items)}, "/api/holdings-edit")

    @app.post("/api/holdings-edit/save")
    def holdings_edit_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return _safe_payload(lambda: _save_edit_rows("holdings", payload), "/api/holdings-edit/save")

    @app.get("/api/watchlist-edit")
    def watchlist_edit(market: str = Query("all")) -> dict[str, Any]:
        items = _read_edit_rows("watchlist", market)
        return _safe_payload(lambda: {"status": "OK", "kind": "watchlist", "market": _market_norm(market), "items": items, "count": len(items)}, "/api/watchlist-edit")

    @app.post("/api/watchlist-edit/save")
    def watchlist_edit_save(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return _safe_payload(lambda: _save_edit_rows("watchlist", payload), "/api/watchlist-edit/save")

    @app.get("/api/company-analysis")
    def company(market: str = Query("all"), limit: int = Query(500), q: str = Query("")) -> dict[str, Any]:
        return _safe_payload(lambda: _company_payload(market, limit, q), "/api/company-analysis")

    @app.get("/api/data/audit")
    def audit() -> dict[str, Any]:
        return _safe_payload(_audit_payload, "/api/data/audit")

    @app.get("/api/health/github")
    def github() -> dict[str, Any]:
        return _safe_payload(_github_payload, "/api/health/github")

    @app.get("/api/final/recommendations")
    def recommendations(
        market: str = Query("kr"),
        mode: str = Query("balanced"),
        horizon: str = Query("swing"),
        cash: float = Query(0),
        limit: int = Query(300),
        watchOnly: bool = Query(False),
    ) -> dict[str, Any]:
        return _safe_payload(lambda: _recommendations_payload(market, mode, horizon, cash, limit, watchOnly), "/api/final/recommendations")

    @app.get("/api/v1/candidates")
    def candidates(
        market: str = Query("kr"),
        strategy: str = Query("balanced"),
        term: str = Query("swing"),
        cash: float = Query(0),
        limit: int = Query(300),
        watchOnly: bool = Query(False),
    ) -> dict[str, Any]:
        return _safe_payload(lambda: _recommendations_payload(market, strategy, term, cash, limit, watchOnly), "/api/v1/candidates")

    @app.get("/api/reports/premarket")
    def premarket(market: str = Query("kr"), mode: str = Query("balanced"), horizon: str = Query("swing"), limit: int = Query(300)) -> dict[str, Any]:
        payload = _safe_payload(lambda: _recommendations_payload(market, mode, horizon, 0, limit, False), "/api/reports/premarket")
        payload["reportType"] = "premarket"
        return payload

    @app.get("/api/reports/intraday")
    def intraday(market: str = Query("kr"), mode: str = Query("balanced"), horizon: str = Query("swing"), limit: int = Query(300)) -> dict[str, Any]:
        return _safe_payload(lambda: _intraday_payload(market, mode, horizon, limit), "/api/reports/intraday")

    @app.get("/api/predictions/table")
    def predictions(market: str = Query("all"), mode: str = Query("balanced"), horizon: str = Query("swing"), limit: int = Query(300)) -> dict[str, Any]:
        return _safe_payload(lambda: _recommendations_payload(market, mode, horizon, 0, limit, False), "/api/predictions/table")

    @app.get("/api/virtual/ledger")
    def virtual_ledger(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all"), limit: int = Query(300)) -> dict[str, Any]:
        def payload() -> dict[str, Any]:
            rows = _normalize_ledger_due_dates(_read_csv(_ledger_path(), 100000))
            market_key = _market_norm(market)
            mode_key = _mode_norm(mode) if mode != "all" else "all"
            horizon_key = _horizon_norm(horizon) if horizon != "all" else "all"
            filtered: list[dict[str, Any]] = []
            for row in rows:
                if market_key != "all" and str(row.get("market")) != market_key:
                    continue
                if mode_key != "all" and str(row.get("mode")) != mode_key:
                    continue
                if horizon_key != "all" and str(row.get("horizon")) != horizon_key:
                    continue
                filtered.append(row)
            return {"status": "OK", "count": len(filtered[:limit]), "totalCount": len(filtered), "items": filtered[:limit]}
        return _safe_payload(payload, "/api/virtual/ledger")

    @app.get("/api/virtual/validation")
    def virtual_validation(market: str = Query("all"), mode: str = Query("all"), horizon: str = Query("all"), limit: int = Query(300)) -> dict[str, Any]:
        def payload() -> dict[str, Any]:
            result = _validate_virtual_ledger()
            market_key = _market_norm(market)
            mode_key = _mode_norm(mode) if mode != "all" else "all"
            horizon_key = _horizon_norm(horizon) if horizon != "all" else "all"
            filtered: list[dict[str, Any]] = []
            for row in result.get("items", []):
                if market_key != "all" and str(row.get("market")) != market_key:
                    continue
                if mode_key != "all" and str(row.get("mode")) != mode_key:
                    continue
                if horizon_key != "all" and str(row.get("horizon")) != horizon_key:
                    continue
                filtered.append(row)
            return {**result, "count": len(filtered[:limit]), "totalCount": len(filtered), "items": filtered[:limit]}
        return _safe_payload(payload, "/api/virtual/validation")
