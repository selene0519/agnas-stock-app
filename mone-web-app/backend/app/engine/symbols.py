from __future__ import annotations

import re
from typing import Any

KR_SYMBOL_NAMES = {
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "035420": "NAVER",
    "035720": "카카오",
    "005380": "현대차",
    "000270": "기아",
    "051910": "LG화학",
    "006400": "삼성SDI",
    "068270": "셀트리온",
    "207940": "삼성바이오로직스",
    "042660": "한화오션",
    "058470": "리노공업",
    "196170": "알테오젠",
    "214150": "클래시스",
    "375500": "DL이앤씨",
    "006260": "LS",
    "001440": "대한전선",
    "055550": "신한지주",
    "086520": "에코프로",
    "000100": "유한양행",
    "373220": "LG에너지솔루션",
    "000720": "현대건설",
    "267260": "HD현대일렉트릭",
    "105560": "KB금융",
    "012450": "한화에어로스페이스",
    "086790": "하나금융지주",
    "138040": "메리츠금융지주",
    "018260": "삼성에스디에스",
    "095340": "ISC",
    "329180": "HD현대중공업",
    "214450": "파마리서치",
    "066970": "엘앤에프",
    "015760": "한국전력",
    "009540": "HD한국조선해양",
    "003670": "포스코퓨처엠",
    "005490": "POSCO홀딩스",
    "012330": "현대모비스",
    "042700": "한미반도체",
}

US_SYMBOL_NAMES = {
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
}


def normalize_market(value: Any = "kr") -> str:
    text = str(value or "kr").strip().lower()
    if text in {"us", "usa", "nasdaq", "nyse", "미장"}:
        return "us"
    return "kr"


def normalize_symbol(symbol: Any, market: str = "kr") -> str:
    text = str(symbol or "").strip().upper()
    text = re.sub(r"\.(KS|KQ|KR)$", "", text)
    if normalize_market(market) == "kr" and text.isdigit():
        return text.zfill(6)
    return text


def is_missing_name(name: Any, symbol: Any) -> bool:
    text = str(name or "").strip()
    code = str(symbol or "").strip()
    if not text:
        return True
    return text.upper() == code.upper() or text in {"-", "N/A", "UNKNOWN", "종목명 없음"}


def display_name(symbol: Any, name: Any = "", market: str = "kr") -> str:
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    if not is_missing_name(name, normalized_symbol):
        return str(name).strip()
    if normalized_market == "kr":
        return KR_SYMBOL_NAMES.get(normalized_symbol, normalized_symbol)
    return US_SYMBOL_NAMES.get(normalized_symbol, normalized_symbol)


def market_matches(symbol: Any, market: str) -> bool:
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    if normalized_market == "kr":
        return bool(re.fullmatch(r"\d{6}", normalized_symbol))
    return bool(normalized_symbol) and not normalized_symbol.isdigit()


def stock_label(symbol: Any, name: Any = "", market: str = "kr") -> str:
    normalized_market = normalize_market(market)
    normalized_symbol = normalize_symbol(symbol, normalized_market)
    visible_name = display_name(normalized_symbol, name, normalized_market)
    if normalized_market == "kr":
        return f"{visible_name} ({normalized_symbol})"
    return f"{visible_name} · {normalized_symbol}"
