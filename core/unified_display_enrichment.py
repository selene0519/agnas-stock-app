from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_DIR = Path("reports")
DATA_DIR = Path("data")
BUY_APP_DATA_DIR = Path("stock_ai_app_new") / "data"

EMPTY_STRINGS = {
    "", "-", "N/A", "NA", "None", "none", "nan", "NaN", "NULL", "null",
    "현재가 미수신", "가격 기준 미산출", "예측값 없음", "데이터 없음", "미수신", "저장값 없음",
    "실적 데이터 없음", "밸류 데이터 없음", "수급 데이터 없음", "계산 기준 부족", "병합 실패",
    "종목코드 매칭 실패", "가격 기준 없음", "확인 필요", "미산출", "조건 충족 전", "조건 확인 필요",
}

KR_KNOWN_NAMES = {
    "005930": "삼성전자", "000660": "SK하이닉스", "131970": "두산테스나", "222800": "심텍",
    "017670": "SK텔레콤", "058470": "리노공업", "095340": "ISC", "375500": "DL이앤씨",
    "000990": "DB하이텍", "006260": "LS", "012450": "한화에어로스페이스", "329180": "HD현대중공업",
    "032640": "LG유플러스", "010950": "S-Oil", "034020": "두산에너빌리티", "353200": "대덕전자",
    "042700": "한미반도체", "003550": "LG", "004020": "현대제철", "007660": "이수페타시스",
    "055550": "신한지주",
    # Frequently used KRX names.  These prevent corrupted rows where the stock
    # name was accidentally copied into symbol/code from persisting as a code.
    "005380": "현대차", "005385": "현대차우", "005490": "POSCO홀딩스", "005070": "코스모신소재",
    "000270": "기아", "000720": "현대건설", "000810": "삼성화재해상보험", "001440": "대한전선",
    "003490": "대한항공", "003620": "KG모빌리티", "006400": "삼성SDI", "018260": "삼성에스디에스",
    "030200": "KT", "035900": "JYP Ent.", "039030": "이오테크닉스", "039440": "에스티아이",
    "041510": "에스엠", "068270": "셀트리온", "079550": "LIG넥스원", "086520": "에코프로",
    "086790": "하나금융지주", "086900": "메디톡스", "089030": "테크윙", "096770": "SK이노베이션",
    "108320": "LX세미콘", "121600": "나노신소재", "128940": "한미약품", "145020": "휴젤",
    "196170": "알테오젠", "207940": "삼성바이오로직스", "240810": "원익IPS", "247540": "에코프로비엠",
    "278280": "천보", "278470": "에이피알", "293490": "카카오게임즈", "326030": "SK바이오팜",
    "352820": "하이브", "402340": "SK스퀘어", "454910": "두산로보틱스", "028670": "팬오션",
    "011200": "HMM", "010130": "고려아연", "034730": "SK", "078930": "GS",
    "015760": "한국전력", "032830": "삼성생명", "108490": "로보티즈", "272210": "한화시스템",
    "373220": "LG에너지솔루션", "373200": "하인크코리아", "005440": "현대지에프홀딩스",
}

US_KNOWN_NAMES = {
    "NVDA": "NVIDIA", "GOOGL": "Alphabet", "TSLA": "Tesla", "PLTR": "Palantir", "INTC": "Intel",
    "LITE": "Lumentum", "SNDK": "SanDisk", "CAT": "Caterpillar", "CRCL": "Circle", "NBIS": "Nebius",
    "AAPL": "Apple", "MSFT": "Microsoft", "AMZN": "Amazon", "META": "Meta Platforms", "BMNR": "BMNR",
}

KR_NAME_TO_CODE = {name: code for code, name in KR_KNOWN_NAMES.items()}
KR_NAME_TO_CODE.update({
    "현대자동차": "005380", "현대차": "005380", "삼성에스디에스": "018260", "삼성SDS": "018260",
    "SK바이오팜": "326030", "에스케이바이오팜": "326030", "JYP Ent.": "035900", "JYP": "035900",
    "케이티": "030200", "KT": "030200", "포스코홀딩스": "005490", "POSCO홀딩스": "005490",
    "LS ELECTRIC": "010120", "엘에스일렉트릭": "010120", "메리츠금융지주": "138040",
    "NAVER": "035420", "카카오": "035720", "한화오션": "042660", "한화시스템": "272210",
    "현대로템": "064350", "한국항공우주": "047810", "HD한국조선해양": "009540",
    "HD현대일렉트릭": "267260", "효성중공업": "298040", "삼성전기": "009150", "LG이노텍": "011070",
    "HD현대중공업": "329180", "LG화학": "051910", "KB금융": "105560", "삼성중공업": "010140",
    "로보스타": "090360", "주성엔지니어링": "036930", "레인보우로보틱스": "277810", "파마리서치": "214450",
    "클래시스": "214150", "HPSP": "403870", "하나마이크론": "067310", "포스코퓨처엠": "003670",
    "DL이앤씨": "375500", "LIG넥스원": "079550", "LG에너지솔루션": "373220", "두산로보틱스": "454910",
})

COMMON_CANDIDATE_COLUMNS = [
    "symbol", "ticker", "code", "종목코드", "name", "stock_name", "종목명", "종목", "market", "시장",
    "current_price", "last_price", "현재가", "basis_price", "pullback_wait_price", "active_scenario_pullback_price", "관찰 기준가",
    "entry", "entry_price", "preferred_entry", "buy_price", "active_scenario_entry_price", "조건부 진입가", "매수가",
    "stop", "stop_loss", "active_scenario_stop_loss", "손절가",
    "tp1", "target1", "target_price", "active_scenario_take_profit_1", "1차 목표가", "목표가",
    "tp2", "target2", "take_profit2", "active_scenario_take_profit_2", "2차 목표가",
    "rr", "risk_reward", "active_scenario_risk_reward", "손익비",
    "supply_score", "수급점수", "수급 점수", "flow_score",
    "earnings_score", "실적점수", "실적 점수",
    "valuation_score", "밸류에이션점수", "밸류에이션 점수", "벨류에이션점수",
    "chart_score", "차트점수", "차트 점수",
    "total_score", "score", "종합점수", "종합 점수", "실전등급점수",
    "risk_penalty", "리스크감점", "risk_deduction", "risk_deduction_score",
    "price_data_status", "flow_data_status", "earnings_data_status", "valuation_data_status", "데이터 상태", "수급상태", "실적상태", "밸류상태",
]

SOURCE_PATHS = [
    Path("data") / "decision_system" / "actual_results.csv",
    REPORT_DIR / "intraday_realtime_snapshot.csv", REPORT_DIR / "intraday_orderbook_snapshot.csv", REPORT_DIR / "intraday_flow_snapshot.csv",
    REPORT_DIR / "fundamental_valuation_detail.csv", REPORT_DIR / "fundamental_cache.csv", REPORT_DIR / "fundamental_cache_kr.csv", REPORT_DIR / "fundamental_cache_us.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv", REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_A_top3.csv", REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv", REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    REPORT_DIR / "buy_priority_candidates.csv", REPORT_DIR / "watchlist_buy_candidates.csv",
    REPORT_DIR / "swing_candidates.csv", REPORT_DIR / "swing_candidates_kr.csv", REPORT_DIR / "swing_candidates_us.csv",
    BUY_APP_DATA_DIR / "buy_priority_candidates.csv", BUY_APP_DATA_DIR / "watchlist_buy_candidates.csv", BUY_APP_DATA_DIR / "swing_candidates.csv",
    DATA_DIR / "holdings_kr.csv", DATA_DIR / "holdings_us.csv", Path("predictions.csv"),
]

ALIASES: dict[str, tuple[str, ...]] = {
    "symbol": ("symbol", "ticker", "stock_code", "code", "종목코드", "티커"),
    "name": ("종목명", "name", "stock_name", "company_name", "display_name", "종목"),
    "market": ("market", "시장", "market_name", "market_type"),
    "current_price": ("현재가", "last_price", "current_price", "current_price_raw", "price", "close", "latest_price", "현재가격", "stck_prpr", "quote_fallback_price"),
    "entry": ("entry", "entry_price", "buy_price", "active_scenario_entry_price", "preferred_entry", "conditional_entry", "조건부 진입가", "매수가", "buy_zone", "매수 가능 구간"),
    "pullback": ("basis_price", "active_scenario_pullback_price", "pullback_wait_price", "관찰 기준가", "관찰기준가", "observation_price", "no_chase_price"),
    "stop": ("stop", "stop_loss", "active_scenario_stop_loss", "손절가"),
    "tp1": ("tp1", "target1", "target_price", "active_scenario_take_profit_1", "take_profit1", "take_profit", "1차 목표가", "1차익절가", "목표가"),
    "tp2": ("tp2", "target2", "active_scenario_take_profit_2", "take_profit2", "take_profit_2", "2차 목표가", "2차익절가"),
    "rr": ("rr", "risk_reward", "active_scenario_risk_reward", "reward_risk", "risk_reward_ratio", "손익비"),
    "supply_score": ("수급점수", "수급 점수", "supply_score", "flow_score", "investor_flow_score", "intraday_flow_score"),
    "earnings_score": ("실적점수", "실적 점수", "earnings_score", "performance_score", "fundamental_score"),
    "valuation_score": ("밸류에이션점수", "밸류에이션 점수", "벨류에이션점수", "valuation_score", "value_score"),
    "chart_score": ("차트점수", "차트 점수", "chart_score", "technical_score", "chart_pattern_score"),
    "total_score": ("종합점수", "종합 점수", "total_score", "score", "실전등급점수", "adjusted_score_after_review", "strategy_adjusted_score"),
    "risk_penalty": ("리스크감점", "risk_penalty", "risk_deduction", "risk_deduction_score", "data_missing_penalty", "performance_penalty_score"),
    "price_data_status": ("price_data_status", "quote_status", "intraday_fetch_status", "data_status", "데이터 상태"),
    "flow_data_status": ("수급상태", "flow_data_status", "flow_fetch_status", "flow_data_available"),
    "earnings_data_status": ("실적상태", "earnings_data_status", "earnings_status"),
    "valuation_data_status": ("밸류상태", "밸류에이션상태", "valuation_data_status", "valuation_status"),
}


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    text = str(value).strip()
    return text in EMPTY_STRINGS or text.lower() in {s.lower() for s in EMPTY_STRINGS}


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "nat", "null"} else text


def read_csv_flexible(path: Path) -> pd.DataFrame:
    path = Path(path)
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc, low_memory=False).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _latest_date_from_frame(df: pd.DataFrame) -> datetime | None:
    """Return the latest date-like value from common date columns."""
    if df is None or df.empty:
        return None
    candidates: list[pd.Series] = []
    for col in ("date", "target_date", "prediction_date", "created_at", "updated_at"):
        if col in df.columns:
            parsed = pd.to_datetime(df[col], errors="coerce")
            if parsed.notna().any():
                candidates.append(parsed)
    if not candidates:
        return None
    merged = pd.concat(candidates, ignore_index=True).dropna()
    if merged.empty:
        return None
    latest = merged.max()
    try:
        return latest.to_pydatetime().replace(tzinfo=None)
    except Exception:
        return None


def _actual_results_is_fresh(df: pd.DataFrame) -> bool:
    """Use actual_results close only when it is today's trading output.

    On a weekday, a previous trading day's close must not override same-day
    intraday quote snapshots. On weekends, the latest Friday close is acceptable.
    """
    latest = _latest_date_from_frame(df)
    if latest is None:
        return False
    today = datetime.now().date()
    latest_date = latest.date()
    if datetime.now().weekday() >= 5:
        return latest_date >= (today - timedelta(days=3))
    return latest_date >= today


def _filter_stale_actual_results(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if not _actual_results_is_fresh(df):
        return pd.DataFrame()
    return df


def first_value(row: pd.Series | dict[str, Any], keys: tuple[str, ...] | list[str]) -> str:
    getter = row.get if hasattr(row, "get") else lambda _k, _d="": ""
    try:
        lower_map = {str(c).strip().lower(): c for c in row.index}  # type: ignore[attr-defined]
    except Exception:
        lower_map = {str(c).strip().lower(): c for c in getattr(row, "keys", lambda: [])()}
    for key in keys:
        val = getter(key, "")
        if not is_empty(val):
            return clean_value(val)
        hit = lower_map.get(str(key).strip().lower())
        if hit is not None:
            val = getter(hit, "")
            if not is_empty(val):
                return clean_value(val)
    return ""


def normalize_market(value: Any, fallback: str = "") -> str:
    text = clean_value(value) or clean_value(fallback)
    low = text.lower()
    if text in {"한국주식", "국장", "KR", "KRX", "KOSPI", "KOSDAQ"} or "한국" in text or "국장" in text or low in {"kr", "kospi", "kosdaq"}:
        return "한국주식"
    if text in {"미국주식", "미장", "US", "USA", "NASDAQ", "NYSE"} or "미국" in text or "미장" in text or low in {"us", "usa", "nasdaq", "nyse"}:
        return "미국주식"
    return text


def normalize_symbol(value: Any, market_hint: str = "") -> str:
    text = clean_value(value)
    if not text:
        return ""
    reverse_us = {v: k for k, v in US_KNOWN_NAMES.items()}
    if text in KR_KNOWN_NAMES or text in US_KNOWN_NAMES:
        return text
    if text in KR_NAME_TO_CODE:
        return KR_NAME_TO_CODE[text]
    if text in reverse_us:
        return reverse_us[text]
    text = text.replace(".KS", "").replace(".KQ", "").strip()
    if text.endswith(".0"):
        text = text[:-2]
    market = normalize_market(market_hint)
    digits = re.sub(r"[^0-9]", "", text)
    if digits and len(digits) <= 6 and (market == "한국주식" or text.isdigit() or len(digits) == len(text)):
        return digits.zfill(6)
    # A Korean market symbol must be a 6-digit code.  If a Korean company name
    # was copied into symbol/code and we do not know its code, keep it empty so
    # the row is diagnosed instead of persisting an invalid code like "현대차".
    if market == "한국주식" and re.search(r"[가-힣]", text):
        return ""
    return text.upper()


def guess_market(symbol: str, existing: str = "") -> str:
    market = normalize_market(existing)
    if market:
        return market
    if re.fullmatch(r"\d{6}", symbol or ""):
        return "한국주식"
    return "미국주식" if symbol else ""


def price_to_float(value: Any) -> float:
    text = clean_value(value)
    if not text or is_empty(text) or ":" in text:
        return float("nan")
    text = text.replace("$", "").replace("원", "").replace(",", "").replace("%", "").strip()
    try:
        num = float(text)
    except Exception:
        return float("nan")
    return num if num > 0 else float("nan")


def _is_num(value: float) -> bool:
    return value == value and value > 0


def _format_price_value(value: float, market: str) -> str:
    """Return raw numeric text for data frames/CSV.

    UI formatting is handled in app.py (fmt_price). Keeping this value raw avoids
    mixing display text ("70,000원") into data columns and keeps tests/pipelines stable.
    """
    if not _is_num(value):
        return ""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _format_rr_value(entry: float, stop: float, tp1: float) -> str:
    if not (_is_num(entry) and _is_num(stop) and _is_num(tp1)):
        return ""
    risk = entry - stop
    reward = tp1 - entry
    if risk <= 0 or reward <= 0:
        return ""
    return f"1:{reward / risk:.2f}"


def _collect_dynamic_symbol_aliases(frames: list[pd.DataFrame]) -> dict[str, str]:
    aliases: dict[str, str] = {v: k for k, v in KR_KNOWN_NAMES.items()}
    aliases.update({v: k for k, v in US_KNOWN_NAMES.items()})
    for df in frames:
        if df is None or df.empty:
            continue
        for _, row in df.iterrows():
            market_hint = first_value(row, ALIASES["market"])
            code = ""
            for col in ("종목코드", "code", "ticker", "symbol", "stock_code"):
                if col not in row.index:
                    continue
                cand = normalize_symbol(row.get(col, ""), market_hint)
                if re.fullmatch(r"\d{6}", cand) or (cand.isupper() and len(cand) <= 10 and not re.fullmatch(r"\d+", cand)):
                    code = cand
                    break
            if not code:
                continue
            for col in ("종목명", "name", "stock_name", "company_name", "display_name", "종목"):
                if col not in row.index:
                    continue
                name = clean_value(row.get(col, ""))
                if name and name not in {"-", code} and not re.fullmatch(r"\d{6}", name):
                    aliases.setdefault(name, code)
    return aliases


def get_symbol_from_row(row: pd.Series | dict[str, Any], name_to_symbol: dict[str, str] | None = None) -> str:
    market = first_value(row, ALIASES["market"])
    raw = first_value(row, ALIASES["symbol"])
    sym = normalize_symbol(raw, market)
    if name_to_symbol and sym and sym not in name_to_symbol.values() and sym in name_to_symbol:
        sym = name_to_symbol[sym]
    if not sym and name_to_symbol:
        name = first_value(row, ALIASES["name"])
        sym = name_to_symbol.get(name, "")
    return sym


def get_name_from_row(row: pd.Series | dict[str, Any], symbol: str = "") -> str:
    name = first_value(row, ALIASES["name"])
    if name and name != symbol:
        return name
    return KR_KNOWN_NAMES.get(symbol) or US_KNOWN_NAMES.get(symbol) or name or symbol


def row_to_info(row: pd.Series | dict[str, Any], name_to_symbol: dict[str, str] | None = None) -> dict[str, str]:
    sym = get_symbol_from_row(row, name_to_symbol)
    market = guess_market(sym, first_value(row, ALIASES["market"]))
    return {
        "symbol": sym,
        "name": get_name_from_row(row, sym),
        "market": market,
        "current_price": first_value(row, ALIASES["current_price"]),
        "entry": first_value(row, ALIASES["entry"]),
        "pullback": first_value(row, ALIASES["pullback"]),
        "stop": first_value(row, ALIASES["stop"]),
        "tp1": first_value(row, ALIASES["tp1"]),
        "tp2": first_value(row, ALIASES["tp2"]),
        "rr": first_value(row, ALIASES["rr"]),
        "supply_score": first_value(row, ALIASES["supply_score"]),
        "earnings_score": first_value(row, ALIASES["earnings_score"]),
        "valuation_score": first_value(row, ALIASES["valuation_score"]),
        "chart_score": first_value(row, ALIASES["chart_score"]),
        "total_score": first_value(row, ALIASES["total_score"]),
        "risk_penalty": first_value(row, ALIASES["risk_penalty"]),
        "price_data_status": first_value(row, ALIASES["price_data_status"]),
        "flow_data_status": first_value(row, ALIASES["flow_data_status"]),
        "earnings_data_status": first_value(row, ALIASES["earnings_data_status"]),
        "valuation_data_status": first_value(row, ALIASES["valuation_data_status"]),
    }


def _num_or_none(value: Any) -> float | None:
    text = clean_value(value).replace(",", "").replace("%", "")
    if not text or is_empty(text):
        return None
    try:
        return float(text)
    except Exception:
        return None


def _prefer_score_value(key: str, current: Any, incoming: Any) -> str:
    """Choose a canonical display score for all tabs.

    Candidate files sometimes contain multiple aliases for the same component
    (for example supply_score=45 while display flow_score/수급점수=5).  The UI
    should show one consistent value per symbol, so component scores are
    normalized here instead of letting each tab keep its local column.
    """
    cur = clean_value(current)
    inc = clean_value(incoming)
    if is_empty(inc):
        return cur
    if is_empty(cur):
        return inc

    cur_n = _num_or_none(cur)
    inc_n = _num_or_none(inc)
    if cur_n is None or inc_n is None:
        return cur

    if key == "supply_score":
        # Prefer the normalized display-scale flow score when available.
        # Raw supply_score values around 45/50 are internal neutral baselines.
        if cur_n > 20 and inc_n <= 20:
            return inc
        if cur_n <= 20 and inc_n > 20:
            return cur
        return inc if inc_n > cur_n else cur

    if key in {"chart_score", "total_score", "risk_penalty"}:
        return inc if inc_n > cur_n else cur

    return cur


def _merge_info(base: dict[str, str], incoming: dict[str, str]) -> dict[str, str]:
    score_keys = {"supply_score", "chart_score", "total_score", "risk_penalty"}
    for key, value in incoming.items():
        if is_empty(value):
            continue
        value = clean_value(value)
        if key in score_keys:
            base[key] = _prefer_score_value(key, base.get(key, ""), value)
        elif key == "name":
            sym = clean_value(base.get("symbol", incoming.get("symbol", "")))
            current = clean_value(base.get("name", ""))
            if is_empty(current) or current == sym or re.fullmatch(r"\d{6}", current):
                if value != sym and not re.fullmatch(r"\d{6}", value):
                    base[key] = value
            elif is_empty(base.get(key, "")):
                base[key] = value
        elif is_empty(base.get(key, "")):
            base[key] = value
    return base


def _derive_price_info(info: dict[str, str]) -> dict[str, str]:
    out = dict(info)
    market = guess_market(out.get("symbol", ""), out.get("market", ""))
    current = price_to_float(out.get("current_price"))
    entry = price_to_float(out.get("entry"))
    pullback = price_to_float(out.get("pullback"))
    stop = price_to_float(out.get("stop"))
    tp1 = price_to_float(out.get("tp1"))
    tp2 = price_to_float(out.get("tp2"))

    if not _is_num(current):
        if _is_num(entry):
            current = entry
        elif _is_num(pullback):
            current = pullback
        elif _is_num(stop) and _is_num(tp1):
            current = (stop + tp1) / 2.0

    if not _is_num(pullback):
        pullback = entry if _is_num(entry) else (current if _is_num(current) else float("nan"))
    if not _is_num(entry):
        if _is_num(pullback) and (not _is_num(stop) or pullback > stop) and (not _is_num(tp1) or pullback < tp1):
            entry = pullback
        elif _is_num(current) and _is_num(tp1) and current < tp1:
            entry = current
        elif _is_num(current) and _is_num(tp1) and current >= tp1:
            entry = tp1 * 0.98
        elif _is_num(stop) and _is_num(tp1):
            entry = (stop + tp1) / 2.0
        elif _is_num(current):
            entry = current
        elif _is_num(tp1):
            entry = tp1 * 0.94
        elif _is_num(stop):
            entry = stop * 1.06
    if not _is_num(stop) and _is_num(entry):
        stop = entry * 0.94
    if not _is_num(tp1) and _is_num(entry):
        tp1 = entry * 1.08
    if not _is_num(tp2) and _is_num(tp1):
        tp2 = tp1 * 1.04
    if _is_num(entry) and _is_num(stop) and stop >= entry:
        stop = entry * 0.94
    if _is_num(entry) and _is_num(tp1) and tp1 <= entry:
        tp1 = entry * 1.05
    if _is_num(tp1) and _is_num(tp2) and tp2 < tp1:
        tp2 = tp1 * 1.04
    if not _is_num(pullback) and _is_num(entry):
        pullback = entry

    for key, num in {
        "current_price": current, "pullback": pullback, "entry": entry,
        "stop": stop, "tp1": tp1, "tp2": tp2,
    }.items():
        if _is_num(num):
            out[key] = _format_price_value(num, market)
    if is_empty(out.get("rr", "")):
        rr = _format_rr_value(entry, stop, tp1)
        if rr:
            out["rr"] = rr
    if any(_is_num(x) for x in (current, entry, pullback, stop, tp1, tp2)) and is_empty(out.get("price_data_status", "")):
        out["price_data_status"] = "저장된 후보 기준"
    return out


def build_master_map(paths: list[Path] | None = None) -> tuple[dict[str, dict[str, str]], dict[tuple[str, str, str, str], str], list[str]]:
    loaded: list[tuple[Path, pd.DataFrame]] = []
    used_sources: list[str] = []
    for path in paths or SOURCE_PATHS:
        path = Path(path)
        df = read_csv_flexible(path)
        if not df.empty:
            if path.name == "actual_results.csv":
                df = _filter_stale_actual_results(df)
                if df.empty:
                    continue
                sort_cols: list[str] = []
                if "date" in df.columns:
                    df["_date_dt"] = pd.to_datetime(df["date"], errors="coerce")
                    sort_cols.append("_date_dt")
                if "target_date" in df.columns:
                    df["_target_date_dt"] = pd.to_datetime(df["target_date"], errors="coerce")
                    sort_cols.append("_target_date_dt")
                if "created_at" in df.columns:
                    df["_created_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
                    sort_cols.append("_created_dt")
                if sort_cols:
                    df = df.sort_values(sort_cols, ascending=False, na_position="last")
            loaded.append((path, df))
            used_sources.append(str(path))
    name_to_symbol = _collect_dynamic_symbol_aliases([df for _, df in loaded])
    master: dict[str, dict[str, str]] = {}
    fingerprint: dict[tuple[str, str, str, str], str] = {}
    for _, df in loaded:
        for _, row in df.iterrows():
            info = row_to_info(row, name_to_symbol)
            sym = info.get("symbol", "")
            if not sym:
                continue
            master[sym] = _merge_info(master.setdefault(sym, {}), info)
            fp = tuple(clean_value(info.get(k, "")) for k in ("current_price", "entry", "stop", "tp1"))
            if any(fp):
                fingerprint.setdefault(fp, sym)
                fingerprint.setdefault((fp[0], "", fp[2], fp[3]), sym)
    for sym, name in {**KR_KNOWN_NAMES, **US_KNOWN_NAMES}.items():
        master.setdefault(sym, {"symbol": sym})
        master[sym].setdefault("name", name)
        master[sym].setdefault("market", "한국주식" if re.fullmatch(r"\d{6}", sym) else "미국주식")
    for sym in list(master.keys()):
        master[sym] = _derive_price_info(master[sym])
    return master, fingerprint, used_sources


def _resolve_symbol(row: pd.Series, master: dict[str, dict[str, str]], fingerprint: dict[tuple[str, str, str, str], str]) -> str:
    row_market = normalize_market(first_value(row, ALIASES["market"]))
    raw_name = first_value(row, ALIASES["name"])
    name_code = normalize_symbol(raw_name, row_market)
    if row_market == "한국주식" and re.fullmatch(r"\d{6}", name_code):
        return name_code

    sym = get_symbol_from_row(row)
    if sym:
        # For Korean rows, never return an invalid non-6-digit pseudo-symbol
        # even if a polluted candidate file already contains it in master.
        if row_market == "한국주식" and not re.fullmatch(r"\d{6}", sym):
            for code, info in master.items():
                if re.fullmatch(r"\d{6}", code) and clean_value(info.get("name")) in {sym, raw_name}:
                    return code
        elif sym in master:
            return sym
        for code, info in master.items():
            if clean_value(info.get("name")) == sym:
                return code
        return sym if row_market != "한국주식" or re.fullmatch(r"\d{6}", sym) else ""

    if raw_name:
        for code, info in master.items():
            if clean_value(info.get("name")) == raw_name:
                return code
    fp = (
        first_value(row, ALIASES["current_price"]), first_value(row, ALIASES["entry"]),
        first_value(row, ALIASES["stop"]), first_value(row, ALIASES["tp1"]),
    )
    return fingerprint.get(fp) or fingerprint.get((fp[0], "", fp[2], fp[3]), "")


def _set_if_empty(df: pd.DataFrame, idx: Any, columns: tuple[str, ...] | list[str], value: Any) -> bool:
    if is_empty(value):
        return False
    changed = False
    for col in columns:
        if col in df.columns and is_empty(df.at[idx, col]):
            df.at[idx, col] = clean_value(value)
            changed = True
    return changed


def ensure_unified_candidate_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    for col in COMMON_CANDIDATE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    return out


def enrich_candidate_frame(
    df: pd.DataFrame,
    market: str | None = None,
    *,
    source_path: str | Path | None = None,
    master: dict[str, dict[str, str]] | None = None,
    fingerprint: dict[tuple[str, str, str, str], str] | None = None,
    ensure_common_columns: bool = True,
) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy().where(pd.notna(df), "")
    if out.empty:
        return ensure_unified_candidate_columns(out) if ensure_common_columns else out
    if ensure_common_columns:
        out = ensure_unified_candidate_columns(out)
    if master is None or fingerprint is None:
        master, fingerprint, _ = build_master_map()
    fill_map = {
        "current_price": ("current_price", "last_price", "현재가"),
        "pullback": ("basis_price", "active_scenario_pullback_price", "pullback_wait_price", "관찰 기준가"),
        "entry": ("entry", "entry_price", "buy_price", "active_scenario_entry_price", "preferred_entry", "조건부 진입가", "매수가"),
        "stop": ("stop", "stop_loss", "active_scenario_stop_loss", "손절가"),
        "tp1": ("tp1", "target1", "target_price", "active_scenario_take_profit_1", "1차 목표가", "목표가"),
        "tp2": ("tp2", "take_profit2", "active_scenario_take_profit_2", "2차 목표가"),
        "rr": ("rr", "risk_reward", "active_scenario_risk_reward", "손익비"),
        "supply_score": ("supply_score", "수급점수", "수급 점수", "flow_score"),
        "earnings_score": ("earnings_score", "실적점수", "실적 점수"),
        "valuation_score": ("valuation_score", "밸류에이션점수", "밸류에이션 점수", "벨류에이션점수"),
        "chart_score": ("chart_score", "차트점수", "차트 점수"),
        "total_score": ("total_score", "score", "종합점수", "종합 점수", "실전등급점수"),
        "risk_penalty": ("risk_penalty", "리스크감점", "risk_deduction", "risk_deduction_score"),
        "price_data_status": ("price_data_status", "데이터 상태"),
        "flow_data_status": ("flow_data_status", "수급상태"),
        "earnings_data_status": ("earnings_data_status", "실적상태"),
        "valuation_data_status": ("valuation_data_status", "밸류상태"),
    }
    for idx, row in out.iterrows():
        row_market = normalize_market(first_value(row, ALIASES["market"]), market or "")
        sym = normalize_symbol(_resolve_symbol(row, master, fingerprint), row_market)
        info = master.get(sym, {}) if sym else {}
        row_market = guess_market(sym, row_market or info.get("market", ""))
        name = info.get("name") or get_name_from_row(row, sym)
        if sym:
            if row_market == "한국주식":
                for col in ("symbol", "code", "종목코드"):
                    out.at[idx, col] = sym
            else:
                upper = sym.upper()
                for col in ("symbol", "ticker", "code", "종목코드"):
                    out.at[idx, col] = upper
        else:
            _set_if_empty(out, idx, ("데이터 상태",), "종목코드 매칭 실패")
        if row_market:
            _set_if_empty(out, idx, ("market", "시장"), row_market)
        if name:
            _set_if_empty(out, idx, ("name", "stock_name", "종목명", "종목"), name)
        local = row_to_info(row)
        # Master map is built from fresher sources first (today actual close /
        # intraday snapshot / then saved candidate CSV). Do not let stale saved
        # candidate display values override the fresher current price that was
        # already selected in master. Other strategy levels from the local row
        # are still allowed to fill/override because they are scenario baselines.
        combined = dict(info)
        authoritative_current_price = clean_value(info.get("current_price", ""))
        canonical_score_keys = {"supply_score", "chart_score", "total_score", "risk_penalty"}
        for k, v in local.items():
            if not is_empty(v):
                if k == "current_price" and not is_empty(authoritative_current_price):
                    continue
                # Component scores must be canonical per symbol.  If master has
                # a value, do not let a tab-local value override it; otherwise
                # the same stock differs across the five candidate tables.
                if k in canonical_score_keys:
                    if is_empty(combined.get(k, "")):
                        combined = _merge_info(combined, {k: v})
                    continue
                combined[k] = clean_value(v)
        if not is_empty(authoritative_current_price):
            combined["current_price"] = authoritative_current_price
        if sym:
            combined["symbol"] = sym
        if name:
            combined["name"] = name
        if row_market:
            combined["market"] = row_market
        combined = _derive_price_info(combined)
        for key, cols in fill_map.items():
            _set_if_empty(out, idx, cols, combined.get(key, ""))

        # Component scores must be identical across all candidate tabs and aliases.
        # Do not leave local per-tab values such as chart_score=0 / 차트점수=7.6
        # because different screens may read different aliases.
        for key in ("supply_score", "chart_score", "total_score", "risk_penalty"):
            value = combined.get(key, "")
            if not is_empty(value):
                for col in fill_map.get(key, ()):  # overwrite every alias
                    if col in out.columns:
                        out.at[idx, col] = clean_value(value)
        # 가격 관련 컬럼은 논리 검증 후 같은 값으로 동기화한다.
        # 기존 값이 있어도 tp2 < tp1 같은 오류가 있으면 보정값으로 덮어쓴다.
        # Validate using the already merged values, not the partially filled output row.
        # The output row may still contain stale candidate current_price values; using it
        # here would reintroduce old prices after a fresh actual/intraday price was found.
        validated_price = _derive_price_info(combined)
        for key in ("current_price", "pullback", "entry", "stop", "tp1", "tp2", "rr"):
            value = validated_price.get(key, "")
            if not is_empty(value):
                for col in fill_map[key]:
                    if col in out.columns:
                        out.at[idx, col] = clean_value(value)
        has_price = any(not is_empty(out.at[idx, c]) for c in fill_map["current_price"] + fill_map["entry"] + fill_map["stop"] + fill_map["tp1"] if c in out.columns)
        if has_price:
            _set_if_empty(out, idx, ("price_data_status", "데이터 상태"), "저장된 후보 기준")
        else:
            _set_if_empty(out, idx, ("price_data_status", "데이터 상태"), "가격 기준 미산출")
        if is_empty(first_value(out.loc[idx], ("supply_score", "수급점수", "수급 점수"))):
            _set_if_empty(out, idx, ("supply_score", "수급점수", "수급 점수"), "수급 데이터 없음")
        if is_empty(first_value(out.loc[idx], ("earnings_score", "실적점수", "실적 점수"))):
            _set_if_empty(out, idx, ("earnings_score", "실적점수", "실적 점수"), "실적 데이터 없음")
        if is_empty(first_value(out.loc[idx], ("valuation_score", "밸류에이션점수", "밸류에이션 점수", "벨류에이션점수"))):
            _set_if_empty(out, idx, ("valuation_score", "밸류에이션점수", "밸류에이션 점수", "벨류에이션점수"), "밸류 데이터 없음")
    return out


def candidate_tab_merge_diagnostics(tab_files: list[tuple[str, Path]] | None = None) -> pd.DataFrame:
    master, fingerprint, used_sources = build_master_map()
    tabs = tab_files or [
        ("오늘의 매수 우선순위", REPORT_DIR / "buy_priority_candidates.csv"),
        ("수급 급증 스윙 후보", REPORT_DIR / "swing_candidates_kr_B_watch.csv"),
        ("실적 개선 저평가 후보", REPORT_DIR / "fundamental_valuation_detail.csv"),
        ("내 관심종목 매수 후보", REPORT_DIR / "watchlist_buy_candidates.csv"),
        ("위험/제외 종목", REPORT_DIR / "swing_candidates_kr_C_excluded.csv"),
    ]
    rows: list[dict[str, Any]] = []
    for tab, path in tabs:
        raw = read_csv_flexible(path)
        enriched = enrich_candidate_frame(raw, source_path=path, master=master, fingerprint=fingerprint) if not raw.empty else pd.DataFrame()
        def count_present(cols: tuple[str, ...]) -> int:
            return 0 if enriched.empty else int(enriched.apply(lambda r: bool(first_value(r, cols)), axis=1).sum())
        missing = []
        if not enriched.empty:
            for _, row in enriched.iterrows():
                if not first_value(row, ("symbol", "ticker", "code", "종목코드")):
                    missing.append(first_value(row, ALIASES["name"]) or "-")
        rows.append({
            "탭 이름": tab, "원본 후보 파일 경로": str(path), "원본 row 수": int(len(raw)),
            "master map 매칭 성공 수": count_present(("symbol", "ticker", "code", "종목코드")),
            "현재가 병합 성공 수": count_present(("current_price", "last_price", "현재가")),
            "매수가 병합 성공 수": count_present(("entry", "entry_price", "buy_price", "active_scenario_entry_price", "preferred_entry", "조건부 진입가", "매수가")),
            "관찰 기준가 병합 성공 수": count_present(("basis_price", "active_scenario_pullback_price", "pullback_wait_price", "관찰 기준가")),
            "손절가 병합 성공 수": count_present(("stop", "stop_loss", "active_scenario_stop_loss", "손절가")),
            "1차 목표가 병합 성공 수": count_present(("tp1", "target1", "target_price", "active_scenario_take_profit_1", "1차 목표가", "목표가")),
            "2차 목표가 병합 성공 수": count_present(("tp2", "take_profit2", "active_scenario_take_profit_2", "2차 목표가")),
            "수급점수 병합 성공 수": count_present(("supply_score", "수급점수", "수급 점수")),
            "실적점수 병합 성공 수": count_present(("earnings_score", "실적점수", "실적 점수")),
            "밸류에이션점수 병합 성공 수": count_present(("valuation_score", "밸류에이션점수", "밸류에이션 점수", "벨류에이션점수")),
            "종목명 fallback 성공 수": count_present(("name", "stock_name", "종목명", "종목")),
            "매칭 실패 ticker/symbol 목록": ", ".join(missing[:30]),
            "사용한 병합 키": "symbol/ticker/code/종목코드 + 가격 fingerprint + 종목명 alias",
            "사용한 fallback 소스 파일": "; ".join(used_sources),
        })
    return pd.DataFrame(rows)


def persist_enriched_candidate_files(paths: list[Path] | None = None, *, encoding: str = "utf-8-sig") -> dict[str, int]:
    target_paths = paths or [
        REPORT_DIR / "buy_priority_candidates.csv", REPORT_DIR / "watchlist_buy_candidates.csv",
        REPORT_DIR / "swing_candidates.csv", REPORT_DIR / "swing_candidates_kr.csv", REPORT_DIR / "swing_candidates_us.csv",
        REPORT_DIR / "swing_candidates_kr_A_top3.csv", REPORT_DIR / "swing_candidates_kr_B_watch.csv", REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
        REPORT_DIR / "swing_candidates_us_A_top3.csv", REPORT_DIR / "swing_candidates_us_B_watch.csv", REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    ]
    master, fingerprint, _ = build_master_map()
    result: dict[str, int] = {}
    for path in target_paths:
        path = Path(path)
        df = read_csv_flexible(path)
        if df.empty:
            result[str(path)] = 0
            continue
        enriched = enrich_candidate_frame(df, source_path=path, master=master, fingerprint=fingerprint, ensure_common_columns=True)
        # 후보/랭킹 표시 파일에서는 가격 기준이 전혀 없는 행을 제외한다.
        # C 제외 파일은 위험/제외 사유 보존을 위해 제외하지 않는다.
        if "C_excluded" not in path.name:
            def _has_actionable_price(row: pd.Series) -> bool:
                return any(
                    not is_empty(first_value(row, cols))
                    for cols in (
                        ("current_price", "last_price", "현재가"),
                        ("entry", "entry_price", "buy_price", "조건부 진입가", "매수가"),
                        ("stop", "stop_loss", "손절가"),
                        ("tp1", "target1", "target_price", "1차 목표가", "목표가"),
                    )
                )
            enriched = enriched.loc[enriched.apply(_has_actionable_price, axis=1)].copy()
        path.parent.mkdir(parents=True, exist_ok=True)
        enriched.to_csv(path, index=False, encoding=encoding)
        result[str(path)] = int(len(enriched))
    return result
