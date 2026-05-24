# -*- coding: utf-8 -*-
"""
Donhyun Stock Guard v2.0
- Purpose: Stock trading decision assistant, not an automatic trading or guaranteed-profit system.
- Core principle: reduce bad entries first, then find favorable risk/reward opportunities.
"""

from __future__ import annotations

import json
import math
import os
import sys
import traceback
from urllib.parse import quote_plus
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz
import yfinance as yf
import requests

try:
    import feedparser
except Exception:
    feedparser = None

try:
    import streamlit as st
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except Exception:
    st = None
    go = None
    make_subplots = None

APP_VERSION = "Donhyun Stock Guard v2.0.2 MARKET"
KST = pytz.timezone("Asia/Seoul")
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
for _d in [DATA_DIR, REPORTS_DIR, LOGS_DIR, CONFIG_DIR]:
    _d.mkdir(exist_ok=True)

# 화면에 데이터 최신화 시각을 표시하기 위한 상태 저장소입니다.
# v1.8.5: Streamlit rerun 이후에도 최신화 시간이 유지되도록 session_state와 동기화합니다.
DATA_STATUS: dict = {}
MARKET_INTERNALS_CACHE: dict = {}
YF_DATA_CACHE: dict = {}
YF_PREFETCH_LOG: dict = {}

# v2.0.1 SPEED: 분석 항목은 줄이지 않고, 같은 데이터를 반복 다운로드하지 않기 위한 캐시입니다.
# 차트/재무/뉴스 화면 렌더링은 사용자가 열 때만 수행하되, 점수 계산용 데이터는 그대로 유지합니다.
def _yf_cache_ttl_seconds(period: str = "1y", interval: str = "1d") -> int:
    period = str(period)
    interval = str(interval)
    if interval not in ["1d", "1wk", "1mo"]:
        return 60
    if period in ["1d", "5d"]:
        return 60
    if period in ["1mo", "3mo"]:
        return 300
    return 1200


def _yf_cache_key(symbol: str, period: str, interval: str) -> tuple:
    return (str(symbol).strip().upper(), str(period), str(interval))


def _normalize_yf_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        out.columns = [c[0] for c in out.columns]
    out = out.reset_index()
    if "Date" not in out.columns and "Datetime" in out.columns:
        out = out.rename(columns={"Datetime": "Date"})
    if "Date" not in out.columns:
        out.insert(0, "Date", pd.date_range(end=pd.Timestamp.today(), periods=len(out)))
    for c in ["Open", "High", "Low", "Close", "Volume"]:
        if c not in out.columns:
            out[c] = np.nan
    out = out.dropna(subset=["Close"]).copy()
    return out


def prefetch_yf_cache(symbols, period: str = "1y", interval: str = "1d") -> dict:
    """여러 종목 데이터를 한 번에 받아 개별 종목 캐시에 저장합니다.
    분석 항목을 줄이지 않고 네트워크 왕복 횟수만 줄이는 속도 최적화입니다.
    """
    try:
        syms = []
        for x in symbols:
            sx = str(x or "").strip()
            if sx and sx not in syms:
                syms.append(sx)
        if not syms:
            return {"requested": 0, "downloaded": 0, "skipped": 0}
        ttl = _yf_cache_ttl_seconds(period, interval)
        now_ts = datetime.now().timestamp()
        missing = []
        skipped = 0
        for sym in syms:
            key = _yf_cache_key(sym, period, interval)
            hit = YF_DATA_CACHE.get(key)
            if hit and now_ts - hit.get("ts", 0) < ttl and isinstance(hit.get("df"), pd.DataFrame):
                skipped += 1
            else:
                missing.append(sym)
        if not missing:
            return {"requested": len(syms), "downloaded": 0, "skipped": skipped}
        data = yf.download(missing, period=period, interval=interval, auto_adjust=False, progress=False, threads=True, group_by="ticker")
        downloaded = 0
        if isinstance(data, pd.DataFrame) and not data.empty:
            if len(missing) == 1:
                sym = missing[0]
                one = _normalize_yf_frame(data)
                if not one.empty:
                    YF_DATA_CACHE[_yf_cache_key(sym, period, interval)] = {"ts": now_ts, "df": one}
                    downloaded += 1
            elif isinstance(data.columns, pd.MultiIndex):
                level0 = list(dict.fromkeys([str(c[0]) for c in data.columns]))
                for sym in missing:
                    try:
                        if sym in level0:
                            one_raw = data[sym]
                        else:
                            continue
                        one = _normalize_yf_frame(one_raw)
                        if not one.empty:
                            YF_DATA_CACHE[_yf_cache_key(sym, period, interval)] = {"ts": now_ts, "df": one}
                            downloaded += 1
                    except Exception:
                        continue
            else:
                # yfinance가 단일 프레임으로 반환한 예외 케이스
                one = _normalize_yf_frame(data)
                if len(missing) == 1 and not one.empty:
                    YF_DATA_CACHE[_yf_cache_key(missing[0], period, interval)] = {"ts": now_ts, "df": one}
                    downloaded += 1
        YF_PREFETCH_LOG[f"{period}_{interval}"] = {"requested": len(syms), "downloaded": downloaded, "skipped": skipped, "at": now_kst().strftime("%Y-%m-%d %H:%M:%S KST")}
        return {"requested": len(syms), "downloaded": downloaded, "skipped": skipped}
    except Exception as e:
        log_error(f"prefetch_yf_cache {period} {interval}", e)
        return {"requested": len(symbols) if hasattr(symbols, "__len__") else 0, "downloaded": 0, "skipped": 0, "error": str(e)}

STATUS_RENDER_TARGET = None
CURRENT_MARKET_FOR_STATUS = None


def init_data_status_state():
    if st is None:
        return
    if "data_status" not in st.session_state:
        st.session_state["data_status"] = {}
    DATA_STATUS.update(st.session_state.get("data_status", {}))


def set_data_status(key: str, value: str):
    DATA_STATUS[key] = value
    if st is not None:
        if "data_status" not in st.session_state:
            st.session_state["data_status"] = {}
        st.session_state["data_status"][key] = value


def get_data_status(key: str, default: str):
    if st is not None and "data_status" in st.session_state:
        return st.session_state["data_status"].get(key, DATA_STATUS.get(key, default))
    return DATA_STATUS.get(key, default)


def refresh_data_status_board(market: Optional[str] = None):
    if st is None:
        return
    target = globals().get("STATUS_RENDER_TARGET")
    m = market or globals().get("CURRENT_MARKET_FOR_STATUS") or "KR"
    if target is not None:
        render_data_status_board(m, target=target)


def data_limit_text(v: str) -> str:
    return "무료 데이터 제한" if v in [None, "", "-", "nan", "NaN"] else str(v)


DEFAULT_SETTINGS = {
    "total_assets": 150_000_000,
    "stock_value": 100_000_000,
    "cash_krw": 50_000_000,
    "risk_per_trade_pct": 0.5,
    "max_single_position_pct": 10.0,
    "min_cash_reserve_pct": 20.0,
    "top_n": 10,
    "analysis_limit": 30,
    "learning_auto_apply": False,
    "min_learning_samples": 80,
    "manual_event_risk": "없음",
    "manual_event_note": "",
}

MARKET_SYMBOLS = {
    "KR": {
        "KOSPI": "^KS11",
        "KOSDAQ": "^KQ11",
        "USD/KRW": "KRW=X",
        "NASDAQ": "^IXIC",
        "NASDAQ_FUT": "NQ=F",
        "S&P500_FUT": "ES=F",
        "Semiconductor ETF": "SMH",
        "WTI": "CL=F",
        "US10Y": "^TNX",
        "VIX": "^VIX",
        "DOLLAR": "DX-Y.NYB",
    },
    "US": {
        "NASDAQ": "^IXIC",
        "S&P500": "^GSPC",
        "RUSSELL2000": "^RUT",
        "NASDAQ_FUT": "NQ=F",
        "S&P500_FUT": "ES=F",
        "BTC": "BTC-USD",
        "WTI": "CL=F",
        "US10Y": "^TNX",
        "VIX": "^VIX",
        "DOLLAR": "DX-Y.NYB",
    },
}

MARKET_INDICATOR_META = {
    "KR": {
        "KOSPI": {"weight": 1.3, "kind": "risk", "role": "국내 대형주 흐름"},
        "KOSDAQ": {"weight": 1.5, "kind": "risk", "role": "국내 성장주/중소형주 흐름"},
        "USD/KRW": {"weight": 1.2, "kind": "burden", "role": "환율 부담"},
        "NASDAQ": {"weight": 1.1, "kind": "risk", "role": "전일 미국 기술주 심리"},
        "NASDAQ_FUT": {"weight": 1.4, "kind": "risk", "role": "장전 미국 선물"},
        "S&P500_FUT": {"weight": 0.8, "kind": "risk", "role": "미국 대형주 선물"},
        "Semiconductor ETF": {"weight": 1.2, "kind": "risk", "role": "반도체 업종 심리"},
        "WTI": {"weight": 0.8, "kind": "burden", "role": "유가 부담"},
        "US10Y": {"weight": 1.4, "kind": "burden", "role": "금리 부담"},
        "VIX": {"weight": 1.5, "kind": "burden", "role": "공포/변동성"},
        "DOLLAR": {"weight": 0.9, "kind": "burden", "role": "달러 강세 부담"},
    },
    "US": {
        "NASDAQ": {"weight": 1.4, "kind": "risk", "role": "기술주 심리"},
        "S&P500": {"weight": 1.2, "kind": "risk", "role": "미국 대형주 흐름"},
        "RUSSELL2000": {"weight": 1.0, "kind": "risk", "role": "중소형주/위험선호"},
        "NASDAQ_FUT": {"weight": 1.2, "kind": "risk", "role": "나스닥 선물"},
        "S&P500_FUT": {"weight": 0.8, "kind": "risk", "role": "S&P500 선물"},
        "BTC": {"weight": 0.7, "kind": "risk", "role": "위험자산 심리"},
        "WTI": {"weight": 0.7, "kind": "burden", "role": "유가 부담"},
        "US10Y": {"weight": 1.4, "kind": "burden", "role": "금리 부담"},
        "VIX": {"weight": 1.6, "kind": "burden", "role": "공포/변동성"},
        "DOLLAR": {"weight": 1.0, "kind": "burden", "role": "달러 강세 부담"},
    },
}


SECTOR_REPS = {
    "KR": {
        "Semiconductor": ["005930.KS", "000660.KS"],
        "Defense/Aerospace": ["047810.KS", "012450.KS", "079550.KS"],
        "Shipbuilding": ["009540.KS", "010140.KS", "329180.KS"],
        "Airline": ["003490.KS", "020560.KS"],
        "Battery/EV": ["373220.KS", "005380.KS", "051910.KS"],
        "Power/Utility": ["015760.KS", "006260.KS"],
        "Construction": ["375500.KS", "000720.KS"],
    },
    "US": {
        "AI/Semiconductor": ["NVDA", "AMD", "AVGO", "MU", "SMH"],
        "Mega Tech": ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
        "Software/Growth": ["PLTR", "NET", "DDOG", "SNOW"],
        "EV/Auto": ["TSLA", "RIVN", "GM"],
        "Energy": ["XOM", "CVX", "SLB"],
        "Finance": ["JPM", "BAC", "GS"],
    },
}

DEFAULT_UNIVERSE_KR = [
    {"symbol": "005930.KS", "name": "Samsung Electronics", "name_kr": "삼성전자", "sector": "Semiconductor"},
    {"symbol": "000660.KS", "name": "SK Hynix", "name_kr": "SK하이닉스", "sector": "Semiconductor"},
    {"symbol": "003490.KS", "name": "Korean Air", "name_kr": "대한항공", "sector": "Airline"},
    {"symbol": "373220.KS", "name": "LG Energy Solution", "name_kr": "LG에너지솔루션", "sector": "Battery/EV"},
    {"symbol": "375500.KS", "name": "DL E&C", "name_kr": "DL이앤씨", "sector": "Construction"},
    {"symbol": "047810.KS", "name": "Korea Aerospace", "name_kr": "한국항공우주", "sector": "Defense/Aerospace"},
    {"symbol": "015760.KS", "name": "KEPCO", "name_kr": "한국전력", "sector": "Power/Utility"},
    {"symbol": "005380.KS", "name": "Hyundai Motor", "name_kr": "현대차", "sector": "Battery/EV"},
    {"symbol": "009540.KS", "name": "HD Korea Shipbuilding", "name_kr": "HD한국조선해양", "sector": "Shipbuilding"},
    {"symbol": "012450.KS", "name": "Hanwha Aerospace", "name_kr": "한화에어로스페이스", "sector": "Defense/Aerospace"},
    {"symbol": "079550.KS", "name": "LIG Nex1", "name_kr": "LIG넥스원", "sector": "Defense/Aerospace"},
    {"symbol": "010140.KS", "name": "Samsung Heavy", "name_kr": "삼성중공업", "sector": "Shipbuilding"},
    {"symbol": "329180.KS", "name": "HD Hyundai Heavy", "name_kr": "HD현대중공업", "sector": "Shipbuilding"},
    {"symbol": "006260.KS", "name": "LS", "name_kr": "LS", "sector": "Power/Utility"},
    {"symbol": "000720.KS", "name": "Hyundai E&C", "name_kr": "현대건설", "sector": "Construction"},
]

DEFAULT_UNIVERSE_US = [
    {"symbol": "NVDA", "name": "NVIDIA", "name_kr": "엔비디아", "sector": "AI/Semiconductor"},
    {"symbol": "AMD", "name": "AMD", "name_kr": "AMD", "sector": "AI/Semiconductor"},
    {"symbol": "AVGO", "name": "Broadcom", "name_kr": "브로드컴", "sector": "AI/Semiconductor"},
    {"symbol": "MU", "name": "Micron", "name_kr": "마이크론", "sector": "AI/Semiconductor"},
    {"symbol": "SMH", "name": "VanEck Semiconductor ETF", "name_kr": "반도체 ETF", "sector": "AI/Semiconductor"},
    {"symbol": "AAPL", "name": "Apple", "name_kr": "애플", "sector": "Mega Tech"},
    {"symbol": "MSFT", "name": "Microsoft", "name_kr": "마이크로소프트", "sector": "Mega Tech"},
    {"symbol": "GOOGL", "name": "Alphabet", "name_kr": "알파벳", "sector": "Mega Tech"},
    {"symbol": "META", "name": "Meta", "name_kr": "메타", "sector": "Mega Tech"},
    {"symbol": "AMZN", "name": "Amazon", "name_kr": "아마존", "sector": "Mega Tech"},
    {"symbol": "PLTR", "name": "Palantir", "name_kr": "팔란티어", "sector": "Software/Growth"},
    {"symbol": "NET", "name": "Cloudflare", "name_kr": "클라우드플레어", "sector": "Software/Growth"},
    {"symbol": "DDOG", "name": "Datadog", "name_kr": "데이터독", "sector": "Software/Growth"},
    {"symbol": "TSLA", "name": "Tesla", "name_kr": "테슬라", "sector": "EV/Auto"},
    {"symbol": "XOM", "name": "Exxon Mobil", "name_kr": "엑슨모빌", "sector": "Energy"},
    {"symbol": "JPM", "name": "JPMorgan", "name_kr": "제이피모건", "sector": "Finance"},
]


# v1.9.1: 기본 후보군 확장
# - 전체 상장종목 전수분석은 아니지만, 기존 KR 15개 / US 16개보다 넓은 1차 유니버스로 확장합니다.
# - 앱은 이 후보군에서 1차 필터/섹터 필터를 거친 뒤, 사용자가 지정한 15/30/50개만 정밀분석합니다.
EXTRA_UNIVERSE_KR = [
    # Semiconductor
    {"symbol":"042700.KS","name":"Hanmi Semiconductor","name_kr":"한미반도체","sector":"Semiconductor"},
    {"symbol":"058470.KS","name":"LEENO Industrial","name_kr":"리노공업","sector":"Semiconductor"},
    {"symbol":"039030.KQ","name":"EO Technics","name_kr":"이오테크닉스","sector":"Semiconductor"},
    {"symbol":"036930.KQ","name":"JUSUNG Engineering","name_kr":"주성엔지니어링","sector":"Semiconductor"},
    {"symbol":"240810.KQ","name":"Wonik IPS","name_kr":"원익IPS","sector":"Semiconductor"},
    {"symbol":"108320.KQ","name":"LX Semicon","name_kr":"LX세미콘","sector":"Semiconductor"},
    {"symbol":"214150.KQ","name":"CLASSYS","name_kr":"클래시스","sector":"Semiconductor"},
    {"symbol":"064760.KQ","name":"TOKAI Carbon Korea","name_kr":"티씨케이","sector":"Semiconductor"},
    {"symbol":"084370.KQ","name":"YMT","name_kr":"유진테크","sector":"Semiconductor"},
    {"symbol":"095340.KQ","name":"ISC","name_kr":"ISC","sector":"Semiconductor"},
    # Defense/Aerospace
    {"symbol":"064350.KS","name":"Hyundai Rotem","name_kr":"현대로템","sector":"Defense/Aerospace"},
    {"symbol":"272210.KS","name":"Hanwha Systems","name_kr":"한화시스템","sector":"Defense/Aerospace"},
    {"symbol":"011210.KS","name":"Hyundai Wia","name_kr":"현대위아","sector":"Defense/Aerospace"},
    {"symbol":"103140.KS","name":"Poongsan","name_kr":"풍산","sector":"Defense/Aerospace"},
    {"symbol":"079550.KS","name":"LIG Nex1","name_kr":"LIG넥스원","sector":"Defense/Aerospace"},
    # Shipbuilding
    {"symbol":"010060.KS","name":"OCI Holdings","name_kr":"OCI홀딩스","sector":"Shipbuilding"},
    {"symbol":"042660.KS","name":"Hanwha Ocean","name_kr":"한화오션","sector":"Shipbuilding"},
    {"symbol":"329180.KS","name":"HD Hyundai Heavy Industries","name_kr":"HD현대중공업","sector":"Shipbuilding"},
    {"symbol":"010140.KS","name":"Samsung Heavy Industries","name_kr":"삼성중공업","sector":"Shipbuilding"},
    {"symbol":"071970.KS","name":"STX Heavy Industries","name_kr":"STX중공업","sector":"Shipbuilding"},
    {"symbol":"082740.KS","name":"Hanwha Engine","name_kr":"한화엔진","sector":"Shipbuilding"},
    # Airline
    {"symbol":"020560.KS","name":"Asiana Airlines","name_kr":"아시아나항공","sector":"Airline"},
    {"symbol":"089590.KS","name":"Jeju Air","name_kr":"제주항공","sector":"Airline"},
    {"symbol":"091810.KS","name":"T'way Air","name_kr":"티웨이항공","sector":"Airline"},
    # Battery/EV
    {"symbol":"051910.KS","name":"LG Chem","name_kr":"LG화학","sector":"Battery/EV"},
    {"symbol":"006400.KS","name":"Samsung SDI","name_kr":"삼성SDI","sector":"Battery/EV"},
    {"symbol":"247540.KQ","name":"EcoPro BM","name_kr":"에코프로비엠","sector":"Battery/EV"},
    {"symbol":"086520.KQ","name":"EcoPro","name_kr":"에코프로","sector":"Battery/EV"},
    {"symbol":"003670.KS","name":"POSCO Future M","name_kr":"포스코퓨처엠","sector":"Battery/EV"},
    {"symbol":"096770.KS","name":"SK Innovation","name_kr":"SK이노베이션","sector":"Battery/EV"},
    {"symbol":"000270.KS","name":"Kia","name_kr":"기아","sector":"Battery/EV"},
    {"symbol":"012330.KS","name":"Hyundai Mobis","name_kr":"현대모비스","sector":"Battery/EV"},
    # Power/Utility
    {"symbol":"267260.KS","name":"HD Hyundai Electric","name_kr":"HD현대일렉트릭","sector":"Power/Utility"},
    {"symbol":"010120.KS","name":"LS Electric","name_kr":"LS ELECTRIC","sector":"Power/Utility"},
    {"symbol":"103590.KS","name":"Iljin Electric","name_kr":"일진전기","sector":"Power/Utility"},
    {"symbol":"298040.KS","name":"Hyosung Heavy Industries","name_kr":"효성중공업","sector":"Power/Utility"},
    {"symbol":"017960.KS","name":"Hankuk Carbon","name_kr":"한국카본","sector":"Power/Utility"},
    # Construction
    {"symbol":"006360.KS","name":"GS Engineering & Construction","name_kr":"GS건설","sector":"Construction"},
    {"symbol":"047040.KS","name":"Daewoo E&C","name_kr":"대우건설","sector":"Construction"},
    {"symbol":"028050.KS","name":"Samsung E&A","name_kr":"삼성E&A","sector":"Construction"},
    {"symbol":"294870.KS","name":"HDC Hyundai Development","name_kr":"HDC현대산업개발","sector":"Construction"},
    {"symbol":"028670.KS","name":"Pan Ocean","name_kr":"팬오션","sector":"Airline"},
]

EXTRA_UNIVERSE_US = [
    # AI/Semiconductor
    {"symbol":"TSM","name":"TSMC","name_kr":"TSMC","sector":"AI/Semiconductor"},
    {"symbol":"ASML","name":"ASML","name_kr":"ASML","sector":"AI/Semiconductor"},
    {"symbol":"AMAT","name":"Applied Materials","name_kr":"어플라이드머티리얼즈","sector":"AI/Semiconductor"},
    {"symbol":"LRCX","name":"Lam Research","name_kr":"램리서치","sector":"AI/Semiconductor"},
    {"symbol":"KLAC","name":"KLA","name_kr":"KLA","sector":"AI/Semiconductor"},
    {"symbol":"ARM","name":"Arm Holdings","name_kr":"ARM","sector":"AI/Semiconductor"},
    {"symbol":"MRVL","name":"Marvell","name_kr":"마벨","sector":"AI/Semiconductor"},
    {"symbol":"QCOM","name":"Qualcomm","name_kr":"퀄컴","sector":"AI/Semiconductor"},
    {"symbol":"INTC","name":"Intel","name_kr":"인텔","sector":"AI/Semiconductor"},
    {"symbol":"SOXX","name":"iShares Semiconductor ETF","name_kr":"SOXX","sector":"AI/Semiconductor"},
    # Mega Tech
    {"symbol":"ORCL","name":"Oracle","name_kr":"오라클","sector":"Mega Tech"},
    {"symbol":"CRM","name":"Salesforce","name_kr":"세일즈포스","sector":"Mega Tech"},
    {"symbol":"ADBE","name":"Adobe","name_kr":"어도비","sector":"Mega Tech"},
    {"symbol":"NFLX","name":"Netflix","name_kr":"넷플릭스","sector":"Mega Tech"},
    {"symbol":"NOW","name":"ServiceNow","name_kr":"서비스나우","sector":"Mega Tech"},
    # Software/Growth
    {"symbol":"SNOW","name":"Snowflake","name_kr":"스노우플레이크","sector":"Software/Growth"},
    {"symbol":"CRWD","name":"CrowdStrike","name_kr":"크라우드스트라이크","sector":"Software/Growth"},
    {"symbol":"MDB","name":"MongoDB","name_kr":"몽고DB","sector":"Software/Growth"},
    {"symbol":"ZS","name":"Zscaler","name_kr":"지스케일러","sector":"Software/Growth"},
    {"symbol":"PANW","name":"Palo Alto Networks","name_kr":"팔로알토네트웍스","sector":"Software/Growth"},
    {"symbol":"SHOP","name":"Shopify","name_kr":"쇼피파이","sector":"Software/Growth"},
    {"symbol":"UBER","name":"Uber","name_kr":"우버","sector":"Software/Growth"},
    {"symbol":"RDDT","name":"Reddit","name_kr":"레딧","sector":"Software/Growth"},
    # EV/Auto
    {"symbol":"RIVN","name":"Rivian","name_kr":"리비안","sector":"EV/Auto"},
    {"symbol":"GM","name":"General Motors","name_kr":"GM","sector":"EV/Auto"},
    {"symbol":"F","name":"Ford","name_kr":"포드","sector":"EV/Auto"},
    {"symbol":"LI","name":"Li Auto","name_kr":"리오토","sector":"EV/Auto"},
    # Energy
    {"symbol":"CVX","name":"Chevron","name_kr":"셰브론","sector":"Energy"},
    {"symbol":"SLB","name":"Schlumberger","name_kr":"SLB","sector":"Energy"},
    {"symbol":"COP","name":"ConocoPhillips","name_kr":"코노코필립스","sector":"Energy"},
    {"symbol":"OXY","name":"Occidental Petroleum","name_kr":"옥시덴탈","sector":"Energy"},
    # Finance
    {"symbol":"BAC","name":"Bank of America","name_kr":"뱅크오브아메리카","sector":"Finance"},
    {"symbol":"GS","name":"Goldman Sachs","name_kr":"골드만삭스","sector":"Finance"},
    {"symbol":"MS","name":"Morgan Stanley","name_kr":"모건스탠리","sector":"Finance"},
    {"symbol":"V","name":"Visa","name_kr":"비자","sector":"Finance"},
    {"symbol":"MA","name":"Mastercard","name_kr":"마스터카드","sector":"Finance"},
]


def _extend_universe(base_rows: list, extra_rows: list) -> list:
    out = []
    seen = set()
    for r in list(base_rows) + list(extra_rows):
        sym = str(r.get("symbol", "")).strip().upper()
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(r)
    return out

DEFAULT_UNIVERSE_KR = _extend_universe(DEFAULT_UNIVERSE_KR, EXTRA_UNIVERSE_KR)
DEFAULT_UNIVERSE_US = _extend_universe(DEFAULT_UNIVERSE_US, EXTRA_UNIVERSE_US)


SECTOR_KR_NAME = {
    "Semiconductor": "반도체",
    "Defense/Aerospace": "방산/항공우주",
    "Shipbuilding": "조선",
    "Airline": "항공",
    "Battery/EV": "2차전지/전기차",
    "Power/Utility": "전력/유틸리티",
    "Construction": "건설",
    "AI/Semiconductor": "AI/반도체",
    "Mega Tech": "빅테크",
    "Software/Growth": "소프트웨어/성장주",
    "EV/Auto": "전기차/자동차",
    "Energy": "에너지",
    "Finance": "금융",
}

DIRECTION_KR = {"favorable": "우호", "neutral": "중립", "burden": "부담"}
MARKET_CODE_KR = {"KR": "한국주식", "US": "미국주식"}


def sector_kr(sector: str) -> str:
    return SECTOR_KR_NAME.get(str(sector), str(sector))


def build_symbol_alias_map(market: str) -> dict:
    df = load_universe(market) if 'load_universe' in globals() else pd.DataFrame(DEFAULT_UNIVERSE_KR if market == 'KR' else DEFAULT_UNIVERSE_US)
    alias = {}
    for _, r in df.iterrows():
        sym = str(r.get('symbol', '')).strip()
        if not sym:
            continue
        keys = [sym, sym.replace('.KS',''), str(r.get('name','')), str(r.get('name_kr',''))]
        for k in keys:
            k = str(k).strip()
            if k:
                alias[k.upper()] = sym
                alias[k.replace(' ', '').upper()] = sym
    # 자주 쓰는 별칭 보강
    manual = {
        '삼전': '005930.KS', '삼성전자': '005930.KS', '005930': '005930.KS',
        '하이닉스': '000660.KS', 'SK하이닉스': '000660.KS', '000660': '000660.KS',
        '대한항공': '003490.KS', '003490': '003490.KS',
        '엘지에너지솔루션': '373220.KS', 'LG에너지솔루션': '373220.KS', '373220': '373220.KS',
        'DL이앤씨': '375500.KS', '디엘이앤씨': '375500.KS', '375500': '375500.KS',
        '한국항공우주': '047810.KS', 'KAI': '047810.KS', '047810': '047810.KS',
        '한국전력': '015760.KS', '한전': '015760.KS', '015760': '015760.KS',
        '현대차': '005380.KS', '현대자동차': '005380.KS', '005380': '005380.KS',
        'HD한국조선해양': '009540.KS', '한국조선해양': '009540.KS', '009540': '009540.KS',
    }
    if market == 'KR':
        for k, v in manual.items():
            alias[k.upper()] = v
            alias[k.replace(' ', '').upper()] = v
    return alias


def resolve_symbol(user_input: str, market: str) -> Tuple[str, dict]:
    text = str(user_input or '').strip()
    if not text:
        return '', {}
    alias = build_symbol_alias_map(market)
    key = text.upper()
    key2 = text.replace(' ', '').upper()
    sym = alias.get(key) or alias.get(key2)
    if not sym:
        if market == 'KR' and text.isdigit() and len(text) == 6:
            sym = f'{text}.KS'
        else:
            sym = text.upper()
    uni = load_universe(market)
    m = uni[uni['symbol'].astype(str).str.upper() == sym.upper()]
    if not m.empty:
        return sym, m.iloc[0].to_dict()
    return sym, {'symbol': sym, 'name': sym, 'name_kr': text, 'sector': 'Custom'}


def now_kst() -> datetime:
    return datetime.now(KST)


def log_error(where: str, exc: Exception):
    LOGS_DIR.mkdir(exist_ok=True)
    with open(REPORTS_DIR / "app_error_log.txt", "a", encoding="utf-8") as f:
        f.write(f"\n[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {where}\n")
        f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
        f.write("\n")


def read_settings() -> dict:
    path = CONFIG_DIR / "settings.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out = DEFAULT_SETTINGS.copy()
            out.update(data)
            return out
        except Exception:
            return DEFAULT_SETTINGS.copy()
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    (CONFIG_DIR / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


# -------------------------------
# v2.0 한국투자 Open API 데이터 조회 모듈
# 주문 기능은 의도적으로 포함하지 않습니다. 현재가/호가/체결 정보 조회용입니다.
# -------------------------------
KIS_CONFIG_PATH = CONFIG_DIR / "kis_api_config.json"
KIS_TOKEN_PATH = CONFIG_DIR / "kis_access_token.json"


def mask_secret(v: str, left: int = 4, right: int = 4) -> str:
    s = str(v or "")
    if len(s) <= left + right:
        return "*" * len(s)
    return s[:left] + "*" * (len(s) - left - right) + s[-right:]


def load_kis_config() -> dict:
    default = {
        "enabled": False,
        "mode": "mock",  # mock 또는 real
        "app_key": "",
        "app_secret": "",
        "account_no": "",
        "product_code": "01",
    }
    if KIS_CONFIG_PATH.exists():
        try:
            data = json.loads(KIS_CONFIG_PATH.read_text(encoding="utf-8"))
            default.update(data if isinstance(data, dict) else {})
        except Exception as e:
            log_error("load_kis_config", e)
    return default


def save_kis_config(cfg: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    safe_cfg = dict(cfg or {})
    KIS_CONFIG_PATH.write_text(json.dumps(safe_cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def kis_base_url(cfg: dict) -> str:
    mode = str((cfg or {}).get("mode", "mock"))
    if mode == "real":
        return "https://openapi.koreainvestment.com:9443"
    return "https://openapivts.koreainvestment.com:29443"


def load_kis_token() -> dict:
    if KIS_TOKEN_PATH.exists():
        try:
            return json.loads(KIS_TOKEN_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_kis_token(data: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    KIS_TOKEN_PATH.write_text(json.dumps(data or {}, ensure_ascii=False, indent=2), encoding="utf-8")


def kis_token_valid(token_data: dict) -> bool:
    try:
        token = str(token_data.get("access_token", ""))
        exp = str(token_data.get("expires_at", ""))
        if not token or not exp:
            return False
        return datetime.fromisoformat(exp) > now_kst() + timedelta(minutes=5)
    except Exception:
        return False


def kis_get_access_token(force: bool = False) -> tuple:
    """한국투자 접근토큰을 발급/재사용합니다. 성공 시 (token, message), 실패 시 ('', message)."""
    cfg = load_kis_config()
    if not cfg.get("enabled"):
        return "", "한국투자 API 사용이 꺼져 있습니다."
    if not cfg.get("app_key") or not cfg.get("app_secret"):
        return "", "APP KEY / APP SECRET이 비어 있습니다."
    cached = load_kis_token()
    if not force and kis_token_valid(cached):
        return str(cached.get("access_token")), "기존 토큰 사용"
    try:
        url = kis_base_url(cfg) + "/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": cfg.get("app_key"),
            "appsecret": cfg.get("app_secret"),
        }
        res = requests.post(url, json=payload, timeout=12)
        if res.status_code >= 400:
            return "", f"토큰 발급 실패 HTTP {res.status_code}: {res.text[:200]}"
        data = res.json()
        token = data.get("access_token", "")
        if not token:
            return "", f"토큰 응답에 access_token이 없습니다: {str(data)[:200]}"
        expires_in = int(data.get("expires_in", 60*60*24))
        token_data = {
            "access_token": token,
            "token_type": data.get("token_type", "Bearer"),
            "issued_at": now_kst().isoformat(),
            "expires_at": (now_kst() + timedelta(seconds=max(60, expires_in-60))).isoformat(),
            "mode": cfg.get("mode", "mock"),
        }
        save_kis_token(token_data)
        return token, "토큰 발급 완료"
    except Exception as e:
        log_error("kis_get_access_token", e)
        return "", f"토큰 발급 오류: {e}"


def kis_headers(tr_id: str, token: str, cfg: dict) -> dict:
    return {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": str(cfg.get("app_key", "")),
        "appsecret": str(cfg.get("app_secret", "")),
        "tr_id": tr_id,
        "custtype": "P",
    }


def normalize_kr_code(symbol: str) -> str:
    s = str(symbol or "").strip().upper()
    if s.endswith(".KS") or s.endswith(".KQ"):
        s = s[:-3]
    return ''.join(ch for ch in s if ch.isdigit())[:6]


def kis_inquire_price(symbol: str) -> dict:
    """국내주식 현재가 조회. 반환값은 표준화된 dict. 실패 시 available=False."""
    cfg = load_kis_config()
    token, msg = kis_get_access_token(False)
    code = normalize_kr_code(symbol)
    if not token or not code:
        return {"available": False, "message": msg if not token else "종목코드가 올바르지 않습니다.", "symbol": symbol}
    try:
        url = kis_base_url(cfg) + "/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=kis_headers("FHKST01010100", token, cfg), params=params, timeout=10)
        if res.status_code >= 400:
            return {"available": False, "message": f"HTTP {res.status_code}: {res.text[:200]}", "symbol": symbol}
        data = res.json()
        out = data.get("output", {}) or {}
        if not out:
            return {"available": False, "message": f"응답 데이터 없음: {str(data)[:200]}", "symbol": symbol}
        def f(key):
            return safe_float(str(out.get(key, "")).replace(',', ''), np.nan)
        now_text = now_kst().strftime("%Y-%m-%d %H:%M:%S KST")
        return {
            "available": True,
            "source": "한국투자 Open API",
            "symbol": f"{code}.KS",
            "code": code,
            "name": out.get("hts_kor_isnm", ""),
            "price": f("stck_prpr"),
            "open": f("stck_oprc"),
            "high": f("stck_hgpr"),
            "low": f("stck_lwpr"),
            "change": f("prdy_vrss"),
            "change_pct": f("prdy_ctrt"),
            "volume": f("acml_vol"),
            "trading_value": f("acml_tr_pbmn"),
            "query_time": now_text,
            "raw_rt_cd": data.get("rt_cd"),
            "message": data.get("msg1", "조회 완료"),
        }
    except Exception as e:
        log_error("kis_inquire_price", e)
        return {"available": False, "message": f"현재가 조회 오류: {e}", "symbol": symbol}


def kis_inquire_orderbook(symbol: str) -> dict:
    """국내주식 호가 조회. 실패해도 앱 전체가 멈추지 않도록 방어합니다."""
    cfg = load_kis_config()
    token, msg = kis_get_access_token(False)
    code = normalize_kr_code(symbol)
    if not token or not code:
        return {"available": False, "message": msg if not token else "종목코드가 올바르지 않습니다.", "symbol": symbol}
    try:
        url = kis_base_url(cfg) + "/uapi/domestic-stock/v1/quotations/inquire-asking-price-exp-ccn"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
        res = requests.get(url, headers=kis_headers("FHKST01010200", token, cfg), params=params, timeout=10)
        if res.status_code >= 400:
            return {"available": False, "message": f"HTTP {res.status_code}: {res.text[:200]}", "symbol": symbol}
        data = res.json()
        out = data.get("output1", {}) or data.get("output", {}) or {}
        rows = []
        for i in range(1, 6):
            ask = safe_float(str(out.get(f"askp{i}", "")).replace(',', ''), np.nan)
            bid = safe_float(str(out.get(f"bidp{i}", "")).replace(',', ''), np.nan)
            askq = safe_float(str(out.get(f"askp_rsqn{i}", "")).replace(',', ''), np.nan)
            bidq = safe_float(str(out.get(f"bidp_rsqn{i}", "")).replace(',', ''), np.nan)
            rows.append({"호가단계": i, "매도호가": ask, "매도잔량": askq, "매수호가": bid, "매수잔량": bidq})
        return {"available": True, "source": "한국투자 Open API", "symbol": f"{code}.KS", "rows": rows, "message": data.get("msg1", "호가 조회 완료")}
    except Exception as e:
        log_error("kis_inquire_orderbook", e)
        return {"available": False, "message": f"호가 조회 오류: {e}", "symbol": symbol}


def apply_kis_price_to_recommendations(market: str) -> tuple:
    """v2.0: 한국투자 API 현재가를 추천 결과 CSV에 반영합니다. 한국주식 전용."""
    if market != "KR":
        return load_latest_recommendations(market), "한국투자 API 현재가 반영은 한국주식에서만 사용합니다."
    rec = load_latest_recommendations(market)
    if rec.empty:
        return rec, "저장된 추천 결과가 없습니다. 먼저 TOP 추천 새로 계산을 실행하세요."
    settings = read_settings()
    status_path = DATA_DIR / f"today_status_{market}.json"
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
            market_info = status.get("current_market_info") or status.get("market_info") or calculate_market_state(market)
        except Exception:
            market_info = calculate_market_state(market)
    else:
        market_info = calculate_market_state(market)
    if "recommendation_close" not in rec.columns:
        rec["recommendation_close"] = rec.get("close", np.nan)
    if "premarket_decision" not in rec.columns:
        rec["premarket_decision"] = rec.get("decision", "")
    rec = ensure_string_columns(rec)
    updated, failed = 0, 0
    now_text = now_kst().strftime("%Y-%m-%d %H:%M:%S KST")
    for idx, row in rec.iterrows():
        sym = str(row.get("symbol", ""))
        q = kis_inquire_price(sym)
        if not q.get("available"):
            failed += 1
            safe_set_cell(rec, idx, "api_message", q.get("message", "조회 실패"))
            continue
        new_close = safe_float(q.get("price"), np.nan)
        if not np.isfinite(new_close) or new_close <= 0:
            failed += 1
            continue
        old_close = safe_float(rec.at[idx, "close"], np.nan)
        rec.at[idx, "close"] = new_close
        if np.isfinite(old_close) and old_close > 0:
            rec.at[idx, "price_change_from_prev_pct"] = round((new_close / old_close - 1) * 100, 2)
        base_close = safe_float(rec.at[idx, "recommendation_close"], np.nan)
        if np.isfinite(base_close) and base_close > 0:
            rec.at[idx, "price_change_from_recommendation_pct"] = round((new_close / base_close - 1) * 100, 2)
        safe_set_cell(rec, idx, "current_price_time", q.get("query_time", now_text))
        safe_set_cell(rec, idx, "current_price_source", "한국투자 Open API")
        safe_set_cell(rec, idx, "api_message", q.get("message", "조회 완료"))
        recalced = recalculate_decision_after_price(rec.loc[idx], market_info, settings)
        for k, v in recalced.items():
            safe_set_cell(rec, idx, k, v)
        updated += 1
    rec["api_price_refresh_at"] = now_text
    rec.to_csv(DATA_DIR / f"latest_recommendations_{market}.csv", index=False, encoding="utf-8-sig")
    log = pd.DataFrame([{"created_at": now_text, "market": market, "updated": updated, "failed": failed, "source": "KIS_API"}])
    log_path = DATA_DIR / "kis_price_refresh_log_KR.csv"
    if log_path.exists():
        try:
            old = pd.read_csv(log_path, encoding="utf-8-sig")
            log = pd.concat([old, log], ignore_index=True)
        except Exception:
            pass
    log.to_csv(log_path, index=False, encoding="utf-8-sig")
    set_data_status("last_current_price_refresh_time", now_text)
    set_data_status("last_price_query_time", now_text)
    return rec, f"한국투자 API 현재가 반영 완료: 성공 {updated}개 / 실패 {failed}개"


def render_kis_api_tab(market: str):
    st.subheader("한국투자 API")
    st.caption("v2.0은 주문 기능 없이 국내주식 현재가·호가 조회와 추천 결과 현재가 반영만 제공합니다. 실제 주문은 반드시 증권사 앱에서 직접 확인 후 실행하세요.")
    cfg = load_kis_config()
    col1, col2 = st.columns([1, 1])
    with col1:
        st.markdown("#### API 설정")
        enabled = st.checkbox("한국투자 API 사용", value=bool(cfg.get("enabled", False)))
        mode_label = "모의투자" if cfg.get("mode", "mock") == "mock" else "실전"
        mode = st.radio("접속 환경", ["mock", "real"], index=0 if cfg.get("mode", "mock") == "mock" else 1, format_func=lambda x: "모의투자" if x == "mock" else "실전")
        app_key = st.text_input("APP KEY", value=str(cfg.get("app_key", "")), type="password")
        app_secret = st.text_input("APP SECRET", value=str(cfg.get("app_secret", "")), type="password")
        account_no = st.text_input("계좌번호 앞 8자리 선택입력", value=str(cfg.get("account_no", "")), placeholder="조회 기능만 쓸 때는 비워도 됩니다")
        product_code = st.text_input("상품코드 선택입력", value=str(cfg.get("product_code", "01")), placeholder="보통 01")
        csave, ctoken = st.columns(2)
        with csave:
            if st.button("API 설정 저장", type="primary"):
                save_kis_config({"enabled": enabled, "mode": mode, "app_key": app_key.strip(), "app_secret": app_secret.strip(), "account_no": account_no.strip(), "product_code": product_code.strip() or "01"})
                st.success("저장 완료")
                st.rerun()
        with ctoken:
            if st.button("토큰 발급/연결 테스트"):
                save_kis_config({"enabled": enabled, "mode": mode, "app_key": app_key.strip(), "app_secret": app_secret.strip(), "account_no": account_no.strip(), "product_code": product_code.strip() or "01"})
                token, msg = kis_get_access_token(force=True)
                if token:
                    st.success(msg + f" / {mask_secret(token, 6, 4)}")
                else:
                    st.error(msg)
        token_data = load_kis_token()
        if kis_token_valid(token_data):
            st.success(f"토큰 상태: 유효 / 만료예정 {token_data.get('expires_at', '-')}")
        else:
            st.warning("토큰 상태: 없음 또는 만료")
        st.caption("API 키는 이 PC의 config/kis_api_config.json에 저장됩니다. 외부 공유 금지.")
    with col2:
        st.markdown("#### 현재가/호가 조회 테스트")
        default_symbol = "005930" if market == "KR" else "005930"
        test_symbol = st.text_input("국내 종목코드 또는 종목명", value=default_symbol, placeholder="예: 005930 또는 삼성전자")
        resolved = test_symbol
        try:
            resolved, _ = resolve_symbol(test_symbol, "KR")
        except Exception:
            resolved = test_symbol
        cprice, cbook = st.columns(2)
        with cprice:
            if st.button("현재가 조회"):
                q = kis_inquire_price(resolved)
                if q.get("available"):
                    st.success(q.get("message", "조회 완료"))
                    st.metric("현재가", _format_price(q.get("price")), f"{format_ratio(q.get('change_pct'), '%')}")
                    st.dataframe(pd.DataFrame([{
                        "종목": q.get("name", ""), "코드": q.get("code", ""), "시가": q.get("open"), "고가": q.get("high"), "저가": q.get("low"), "거래량": q.get("volume"), "거래대금": q.get("trading_value"), "조회시각": q.get("query_time")
                    }]), use_container_width=True, hide_index=True)
                else:
                    st.error(q.get("message", "조회 실패"))
        with cbook:
            if st.button("호가 조회"):
                ob = kis_inquire_orderbook(resolved)
                if ob.get("available"):
                    st.success(ob.get("message", "호가 조회 완료"))
                    st.dataframe(pd.DataFrame(ob.get("rows", [])), use_container_width=True, hide_index=True)
                else:
                    st.error(ob.get("message", "호가 조회 실패"))
    st.divider()
    st.markdown("#### 추천 결과에 API 현재가 반영")
    st.caption("한국주식 추천 결과가 있을 때, yfinance 기준 현재가 대신 한국투자 API 현재가를 반영해 이격률·권장금액·판정을 다시 계산합니다.")
    if market != "KR":
        st.info("이 기능은 한국주식 모드에서만 사용합니다.")
    else:
        if st.button("한국투자 현재가로 추천 결과 재계산", type="secondary"):
            with st.spinner("한국투자 API 현재가를 추천 종목에 반영 중입니다."):
                _, msg = apply_kis_price_to_recommendations("KR")
            st.success(msg)
            st.rerun()
        log_path = DATA_DIR / "kis_price_refresh_log_KR.csv"
        if log_path.exists():
            try:
                st.write("최근 API 반영 로그")
                st.dataframe(pd.read_csv(log_path, encoding="utf-8-sig").tail(10), use_container_width=True, hide_index=True)
            except Exception:
                pass


def ensure_base_files():
    DATA_DIR.mkdir(exist_ok=True)
    for name, rows in [("candidate_universe_kr.csv", DEFAULT_UNIVERSE_KR), ("candidate_universe_us.csv", DEFAULT_UNIVERSE_US)]:
        path = DATA_DIR / name
        if not path.exists():
            pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")
    for name, rows in [("watchlist_kr.csv", DEFAULT_UNIVERSE_KR[:9]), ("watchlist_us.csv", DEFAULT_UNIVERSE_US[:10])]:
        path = DATA_DIR / name
        if not path.exists():
            pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def universe_path(market: str) -> Path:
    return DATA_DIR / ("candidate_universe_kr.csv" if market == "KR" else "candidate_universe_us.csv")


def load_universe(market: str) -> pd.DataFrame:
    ensure_base_files()
    path = universe_path(market)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        df = pd.DataFrame(DEFAULT_UNIVERSE_KR if market == "KR" else DEFAULT_UNIVERSE_US)
    for col in ["symbol", "name", "name_kr", "sector", "source", "note"]:
        if col not in df.columns:
            df[col] = "기본후보군" if col == "source" else ""
    df["symbol"] = df["symbol"].astype(str).str.strip()
    df = df[df["symbol"] != ""]
    return df.dropna(subset=["symbol"]).drop_duplicates("symbol")


def save_universe(market: str, df: pd.DataFrame):
    path = universe_path(market)
    out = df.copy()
    for col in ["symbol", "name", "name_kr", "sector", "source", "note"]:
        if col not in out.columns:
            out[col] = ""
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out = out[out["symbol"] != ""]
    out = out.drop_duplicates("symbol")
    out[["symbol", "name", "name_kr", "sector", "source", "note"]].to_csv(path, index=False, encoding="utf-8-sig")


def normalize_candidate_symbol(symbol: str, market: str) -> str:
    s = str(symbol or "").strip().upper()
    if market == "KR" and s.isdigit() and len(s) == 6:
        # 코스피/코스닥 구분이 애매할 때는 기본적으로 .KS를 붙입니다.
        # 코스닥은 039030.KQ처럼 직접 입력하는 것이 가장 정확합니다.
        s = f"{s}.KS"
    return s


def universe_summary(market: str) -> dict:
    df = load_universe(market)
    return {
        "count": int(len(df)),
        "sectors": int(df["sector"].nunique()) if "sector" in df.columns else 0,
        "path": str(universe_path(market).relative_to(BASE_DIR)),
        "modified": datetime.fromtimestamp(universe_path(market).stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if universe_path(market).exists() else "-",
    }


def safe_float(x, default=np.nan):
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def yf_download(symbol: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """v2.0.1 SPEED: 동일 종목/기간 데이터는 TTL 동안 재사용합니다.
    분석 품질은 유지하고 yfinance 반복 호출만 줄입니다.
    """
    try:
        key = _yf_cache_key(symbol, period, interval)
        ttl = _yf_cache_ttl_seconds(period, interval)
        now_ts = datetime.now().timestamp()
        hit = YF_DATA_CACHE.get(key)
        if hit and now_ts - hit.get("ts", 0) < ttl and isinstance(hit.get("df"), pd.DataFrame):
            return hit["df"].copy()
        df = yf.download(symbol, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
        out = _normalize_yf_frame(df)
        if not out.empty:
            YF_DATA_CACHE[key] = {"ts": now_ts, "df": out}
        return out.copy()
    except Exception as e:
        log_error(f"yf_download {symbol}", e)
        return pd.DataFrame()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    close = out["Close"].astype(float)
    high = out["High"].astype(float)
    low = out["Low"].astype(float)
    for n in [5, 20, 50, 60, 120, 200]:
        out[f"MA{n}"] = close.rolling(n, min_periods=max(3, n // 3)).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=7).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=7).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI"] = 100 - (100 / (1 + rs))
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False).mean()
    prev_close = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    out["ATR"] = tr.rolling(14, min_periods=7).mean()
    out["VOL_MA20"] = out["Volume"].rolling(20, min_periods=5).mean()
    out["RET_5D"] = close.pct_change(5) * 100
    out["RET_20D"] = close.pct_change(20) * 100
    out["RET_60D"] = close.pct_change(60) * 100
    return out


def pct_change_last(symbol: str, period: str = "5d") -> float:
    df = yf_download(symbol, period=period, interval="1d")
    if len(df) < 2:
        return 0.0
    return (safe_float(df["Close"].iloc[-1]) / safe_float(df["Close"].iloc[-2]) - 1) * 100


def infer_market_session(market: str) -> dict:
    """KST 기준 장전/장중/장마감 구분. 시장 판단 사유 표시용입니다."""
    now = now_kst()
    wd = now.weekday()  # Monday=0
    hhmm = now.hour * 100 + now.minute
    if market == "KR":
        if wd >= 5:
            label = "휴장/주말"
            mode = "closed"
        elif hhmm < 900:
            label = "장전"
            mode = "premarket"
        elif hhmm <= 1530:
            label = "장중"
            mode = "intraday"
        elif hhmm < 1730:
            label = "장마감 직후"
            mode = "postclose_early"
        else:
            label = "장마감 후"
            mode = "postclose"
    else:
        # 미국장은 서머타임/휴장일을 완벽히 반영하지 않고, KST 기준 참고 상태로 표시합니다.
        if wd in [5, 6]:
            label = "미국장 휴장/주말 가능"
            mode = "closed"
        elif hhmm < 2230:
            label = "미국장 전"
            mode = "premarket"
        elif hhmm >= 2230 or hhmm <= 600:
            label = "미국장 중/마감 근접"
            mode = "intraday"
        else:
            label = "미국장 마감 후"
            mode = "postclose"
    return {"mode": mode, "label": label, "kst": now.strftime("%Y-%m-%d %H:%M:%S")}


def _indicator_contribution(name: str, chg: float, meta: dict) -> tuple:
    """시장 지표별 영향 점수. risk 계열은 상승 우호, burden 계열은 상승 부담입니다."""
    kind = meta.get("kind", "risk")
    weight = float(meta.get("weight", 1.0))
    direction = "neutral"
    raw = 0.0
    # 변화폭이 큰 경우 가중치를 1.5배 적용해 위험회피/우호 전환을 빠르게 반영합니다.
    if kind == "burden":
        if chg <= -0.8:
            raw, direction = 1.5, "favorable"
        elif chg < -0.2:
            raw, direction = 1.0, "favorable"
        elif chg >= 1.2:
            raw, direction = -1.5, "burden"
        elif chg > 0.5:
            raw, direction = -1.0, "burden"
    else:
        if chg >= 1.0:
            raw, direction = 1.5, "favorable"
        elif chg > 0.4:
            raw, direction = 1.0, "favorable"
        elif chg <= -1.0:
            raw, direction = -1.5, "burden"
        elif chg < -0.4:
            raw, direction = -1.0, "burden"
    return raw * weight, direction


def calculate_market_internals(market: str, max_symbols: int = 80) -> dict:
    """v1.9.8: 후보군 기반 시장 내부 강도 계산.
    전체 상장종목 전수 데이터가 아니라 앱 후보군 기준 보조지표입니다.
    """
    rounded_minute = now_kst().minute // 5 * 5
    cache_key = f"{market}_{now_kst().strftime('%Y%m%d_%H')}{rounded_minute:02d}"
    if cache_key in MARKET_INTERNALS_CACHE:
        return MARKET_INTERNALS_CACHE[cache_key]
    try:
        uni = load_universe(market).head(max_symbols)
    except Exception:
        uni = pd.DataFrame()
    if uni.empty or 'symbol' not in uni.columns:
        res = {"available": False, "score": 0.0, "note": "후보군 내부강도 계산 불가", "rows": []}
        MARKET_INTERNALS_CACHE[cache_key] = res
        return res

    prefetch_yf_cache(uni['symbol'].dropna().astype(str).tolist()[:max_symbols], period='1mo', interval='1d')
    changes, vol_ratios, rows = [], [], []
    near_high = 0
    near_low = 0
    valid = 0
    for sym in uni['symbol'].dropna().astype(str).tolist()[:max_symbols]:
        df = yf_download(sym, period='1mo', interval='1d')
        if df.empty or len(df) < 6:
            continue
        try:
            close = df['Close'].astype(float)
            vol = df['Volume'].astype(float) if 'Volume' in df.columns else pd.Series(dtype=float)
            last = float(close.iloc[-1]); prev = float(close.iloc[-2])
            chg = (last / prev - 1) * 100 if prev else 0.0
            changes.append(chg); valid += 1
            high20 = float(close.tail(20).max()); low20 = float(close.tail(20).min())
            if high20 > 0 and last >= high20 * 0.98:
                near_high += 1
            if low20 > 0 and last <= low20 * 1.02:
                near_low += 1
            if len(vol) >= 6 and float(vol.tail(20).mean()) > 0:
                vol_ratios.append(float(vol.iloc[-1]) / float(vol.tail(20).mean()))
            rows.append({"symbol": sym, "change_pct": round(chg, 2)})
        except Exception:
            continue
    if valid == 0:
        res = {"available": False, "score": 0.0, "note": "후보군 내부강도 표본 부족", "rows": []}
        MARKET_INTERNALS_CACHE[cache_key] = res
        return res
    up = sum(1 for x in changes if x > 0)
    down = sum(1 for x in changes if x < 0)
    positive_ratio = up / valid * 100
    avg_change = float(np.nanmean(changes)) if changes else 0.0
    median_change = float(np.nanmedian(changes)) if changes else 0.0
    avg_vol_ratio = float(np.nanmean(vol_ratios)) if vol_ratios else np.nan
    near_high_ratio = near_high / valid * 100
    near_low_ratio = near_low / valid * 100

    score = 0.0
    if positive_ratio >= 65: score += 1.2
    elif positive_ratio >= 55: score += 0.6
    elif positive_ratio <= 35: score -= 1.2
    elif positive_ratio <= 45: score -= 0.6
    if avg_change >= 0.8: score += 0.8
    elif avg_change <= -0.8: score -= 0.8
    if np.isfinite(avg_vol_ratio):
        if avg_vol_ratio >= 1.25 and avg_change > 0: score += 0.5
        elif avg_vol_ratio >= 1.25 and avg_change < 0: score -= 0.5
    if near_high_ratio >= 30: score += 0.5
    if near_low_ratio >= 30: score -= 0.5

    if score >= 1.5:
        note = "후보군 내부 강도 우호"
    elif score <= -1.5:
        note = "후보군 내부 강도 부담"
    else:
        note = "후보군 내부 강도 중립"
    res = {
        "available": True,
        "score": round(float(score), 2),
        "note": note,
        "valid_count": valid,
        "up_count": up,
        "down_count": down,
        "positive_ratio": round(positive_ratio, 1),
        "avg_change_pct": round(avg_change, 2),
        "median_change_pct": round(median_change, 2),
        "avg_volume_ratio": round(avg_vol_ratio, 2) if np.isfinite(avg_vol_ratio) else None,
        "near_high_ratio": round(near_high_ratio, 1),
        "near_low_ratio": round(near_low_ratio, 1),
        "rows": rows[:20],
    }
    MARKET_INTERNALS_CACHE[cache_key] = res
    return res


def calculate_sector_internals(market: str, max_symbols: int = 160) -> dict:
    """v1.9.8: 후보군을 섹터별로 나눠 내부 강도를 계산합니다.
    전체 시장 업종지수 데이터가 아니라 현재 앱 후보군 기준 보조값입니다.
    """
    rounded_minute = now_kst().minute // 10 * 10
    cache_key = f"sector_{market}_{now_kst().strftime('%Y%m%d_%H')}{rounded_minute:02d}"
    if cache_key in MARKET_INTERNALS_CACHE:
        return MARKET_INTERNALS_CACHE[cache_key]
    try:
        uni = load_universe(market).head(max_symbols)
    except Exception:
        uni = pd.DataFrame()
    if uni.empty or 'symbol' not in uni.columns or 'sector' not in uni.columns:
        res = {"available": False, "score": 0.0, "note": "섹터 내부강도 계산 불가", "rows": []}
        MARKET_INTERNALS_CACHE[cache_key] = res
        return res
    prefetch_yf_cache(uni['symbol'].dropna().astype(str).tolist()[:max_symbols], period='1mo', interval='1d')
    rows = []
    for sector, sub in uni.groupby('sector', dropna=False):
        changes, vol_ratios = [], []
        valid = near_high = near_low = 0
        for sym in sub['symbol'].dropna().astype(str).tolist()[:30]:
            df = yf_download(sym, period='1mo', interval='1d')
            if df.empty or len(df) < 6:
                continue
            try:
                close = df['Close'].astype(float)
                vol = df['Volume'].astype(float) if 'Volume' in df.columns else pd.Series(dtype=float)
                last = float(close.iloc[-1]); prev = float(close.iloc[-2])
                if not prev:
                    continue
                chg = (last / prev - 1) * 100
                changes.append(chg); valid += 1
                high20 = float(close.tail(20).max()); low20 = float(close.tail(20).min())
                if high20 > 0 and last >= high20 * 0.98:
                    near_high += 1
                if low20 > 0 and last <= low20 * 1.02:
                    near_low += 1
                if len(vol) >= 6 and float(vol.tail(20).mean()) > 0:
                    vol_ratios.append(float(vol.iloc[-1]) / float(vol.tail(20).mean()))
            except Exception:
                continue
        if valid == 0:
            continue
        up = sum(1 for x in changes if x > 0)
        down = sum(1 for x in changes if x < 0)
        positive_ratio = up / valid * 100
        avg_change = float(np.nanmean(changes))
        median_change = float(np.nanmedian(changes))
        avg_vol_ratio = float(np.nanmean(vol_ratios)) if vol_ratios else np.nan
        near_high_ratio = near_high / valid * 100
        near_low_ratio = near_low / valid * 100
        sector_score = 0.0
        if positive_ratio >= 65: sector_score += 1.0
        elif positive_ratio >= 55: sector_score += 0.5
        elif positive_ratio <= 35: sector_score -= 1.0
        elif positive_ratio <= 45: sector_score -= 0.5
        if avg_change >= 1.0: sector_score += 0.8
        elif avg_change <= -1.0: sector_score -= 0.8
        if np.isfinite(avg_vol_ratio):
            if avg_vol_ratio >= 1.3 and avg_change > 0: sector_score += 0.4
            elif avg_vol_ratio >= 1.3 and avg_change < 0: sector_score -= 0.4
        if near_high_ratio >= 35: sector_score += 0.4
        if near_low_ratio >= 35: sector_score -= 0.4
        if sector_score >= 1.2:
            label = '강함'
        elif sector_score <= -1.2:
            label = '약함'
        else:
            label = '중립'
        rows.append({
            'sector': str(sector),
            'valid_count': valid,
            'up_count': up,
            'down_count': down,
            'positive_ratio': round(positive_ratio, 1),
            'avg_change_pct': round(avg_change, 2),
            'median_change_pct': round(median_change, 2),
            'avg_volume_ratio': round(avg_vol_ratio, 2) if np.isfinite(avg_vol_ratio) else None,
            'near_high_ratio': round(near_high_ratio, 1),
            'near_low_ratio': round(near_low_ratio, 1),
            'sector_internal_score': round(sector_score, 2),
            'label': label,
        })
    if not rows:
        res = {"available": False, "score": 0.0, "note": "섹터 내부강도 표본 부족", "rows": []}
        MARKET_INTERNALS_CACHE[cache_key] = res
        return res
    valid_sectors = len(rows)
    strong = sum(1 for r in rows if r['sector_internal_score'] >= 1.2)
    weak = sum(1 for r in rows if r['sector_internal_score'] <= -1.2)
    avg_sector_score = float(np.nanmean([r['sector_internal_score'] for r in rows]))
    strong_ratio = strong / valid_sectors * 100
    weak_ratio = weak / valid_sectors * 100
    score = 0.0
    if strong_ratio >= 40: score += 1.0
    elif strong_ratio >= 25: score += 0.5
    if weak_ratio >= 40: score -= 1.0
    elif weak_ratio >= 25: score -= 0.5
    if avg_sector_score >= 0.6: score += 0.5
    elif avg_sector_score <= -0.6: score -= 0.5
    note = '섹터 확산 우호' if score >= 1.0 else ('섹터 확산 부담' if score <= -1.0 else '섹터 확산 중립')
    res = {
        'available': True,
        'score': round(float(score), 2),
        'note': note,
        'valid_sector_count': valid_sectors,
        'strong_sector_count': strong,
        'weak_sector_count': weak,
        'strong_sector_ratio': round(strong_ratio, 1),
        'weak_sector_ratio': round(weak_ratio, 1),
        'avg_sector_score': round(avg_sector_score, 2),
        'rows': sorted(rows, key=lambda r: r.get('sector_internal_score', 0), reverse=True),
    }
    MARKET_INTERNALS_CACHE[cache_key] = res
    return res



def _market_row_value(rows: list, indicator: str, field: str = "change_pct", default: float = 0.0) -> float:
    try:
        for r in rows or []:
            if str(r.get("indicator", "")) == indicator:
                return safe_float(r.get(field), default)
    except Exception:
        pass
    return default


def build_market_control_profile(score: float, rows: list, internals: dict, sector_internals: dict, event_risk: dict) -> dict:
    """v2.0.2 MARKET: 시장 판단 최종 규칙.

    화면 판정은 5단계로 단순하게 유지하되, 내부에는 시장위험도/공격허용도/방어필요도/하드블록을 별도로 둔다.
    이 함수는 분석 항목을 줄이지 않고 기존 지표점수 위에 리스크 제어 레이어만 얹는다.
    """
    rows = rows or []
    internals = internals or {}
    sector_internals = sector_internals or {}
    event_risk = event_risk or {}
    risk_points = 0.0
    hard_blocks = []
    warning_blocks = []
    supportive_blocks = []

    # 지수/매크로 하드블록: 큰 변동이 동시에 발생하면 시장점수가 좋아도 신규매수 강도를 낮춘다.
    for r in rows:
        name = str(r.get("indicator", ""))
        chg = safe_float(r.get("change_pct"), 0.0)
        direction = str(r.get("direction", "neutral"))
        if direction == "burden":
            risk_points += min(16.0, abs(chg) * 2.5 + 2.0)
        elif direction == "favorable":
            supportive_blocks.append(f"{name} {chg:+.2f}%")
        if name in ["VIX", "US10Y", "USD/KRW", "DOLLAR"] and chg >= 2.5:
            hard_blocks.append(f"{name} 급등 {chg:+.2f}%")
        if name in ["NASDAQ_FUT", "S&P500_FUT", "NASDAQ", "KOSPI", "KOSDAQ", "Semiconductor ETF", "SMH"] and chg <= -1.8:
            hard_blocks.append(f"{name} 급락 {chg:+.2f}%")
        if name in ["WTI"] and abs(chg) >= 3.0:
            warning_blocks.append(f"유가 변동성 {chg:+.2f}%")

    pos_ratio = safe_float(internals.get("positive_ratio"), np.nan)
    avg_chg = safe_float(internals.get("avg_change_pct"), np.nan)
    vol_ratio = safe_float(internals.get("avg_volume_ratio"), np.nan)
    if np.isfinite(pos_ratio):
        if pos_ratio <= 35:
            risk_points += 18
            hard_blocks.append(f"후보군 상승비율 약함 {pos_ratio:.1f}%")
        elif pos_ratio <= 45:
            risk_points += 9
            warning_blocks.append(f"후보군 상승비율 둔화 {pos_ratio:.1f}%")
        elif pos_ratio >= 60:
            supportive_blocks.append(f"후보군 상승확산 {pos_ratio:.1f}%")
    if np.isfinite(avg_chg):
        if avg_chg <= -1.2:
            risk_points += 10
            warning_blocks.append(f"후보군 평균등락률 약세 {avg_chg:.2f}%")
        elif avg_chg >= 0.8:
            supportive_blocks.append(f"후보군 평균등락률 우호 {avg_chg:.2f}%")
    if np.isfinite(vol_ratio) and vol_ratio >= 1.4 and np.isfinite(avg_chg) and avg_chg < 0:
        risk_points += 8
        warning_blocks.append("하락 거래량 증가")

    weak_ratio = safe_float(sector_internals.get("weak_sector_ratio"), np.nan)
    strong_ratio = safe_float(sector_internals.get("strong_sector_ratio"), np.nan)
    if np.isfinite(weak_ratio):
        if weak_ratio >= 45:
            risk_points += 14
            hard_blocks.append(f"약한 섹터 비율 과다 {weak_ratio:.1f}%")
        elif weak_ratio >= 30:
            risk_points += 7
            warning_blocks.append(f"약한 섹터 증가 {weak_ratio:.1f}%")
    if np.isfinite(strong_ratio) and strong_ratio >= 35:
        supportive_blocks.append(f"강한 섹터 비율 {strong_ratio:.1f}%")

    if str(event_risk.get("level", "없음")) == "높음":
        risk_points += 14
        hard_blocks.append("중요 일정 리스크 높음")
    elif str(event_risk.get("level", "없음")) == "중간":
        risk_points += 7
        warning_blocks.append("일정 리스크 중간")

    # 기본 점수가 나쁘면 위험도를 추가한다. 점수가 좋으면 일부 완화하되 하드블록은 지우지 않는다.
    score = safe_float(score, 0.0)
    if score < -3.5:
        risk_points += 18
    elif score < -1.0:
        risk_points += 8
    elif score > 3.5:
        risk_points -= 8
    elif score > 5.5:
        risk_points -= 12

    risk_score = clamp(risk_points, 0, 100)
    defense_need = int(round(risk_score))
    attack_permission = int(round(clamp(100 - risk_score, 0, 100)))

    # 5단계 최종 판정. 하드블록이 과다하면 점수가 좋아도 위험회피/불리로 캡을 씌운다.
    hard_count = len(hard_blocks)
    if hard_count >= 3 or risk_score >= 78 or score <= -5.5:
        state, label, use_ratio, entry_tighten = "risk_off", "위험회피", 0.00, 0.00
    elif hard_count >= 2 or risk_score >= 58 or score <= -2.5:
        state, label, use_ratio, entry_tighten = "burden", "불리", 0.07, 0.60
    elif score >= 5.5 and risk_score <= 28:
        state, label, use_ratio, entry_tighten = "strong_favorable", "강한 우호", 0.45, 1.10
    elif score >= 2.0 and risk_score <= 42:
        state, label, use_ratio, entry_tighten = "favorable", "우호", 0.30, 1.00
    elif score >= -1.0 and risk_score <= 55:
        state, label, use_ratio, entry_tighten = "neutral", "중립", 0.15, 0.80
    else:
        state, label, use_ratio, entry_tighten = "burden", "불리", 0.07, 0.60

    if state == "strong_favorable":
        strategy_note = "강한 우호: 조건 충족 주도 섹터/종목은 분할 접근 가능. 단, 추격 이격은 재확인."
    elif state == "favorable":
        strategy_note = "우호: 손익비와 진입가 이격이 맞는 종목만 분할 접근 가능."
    elif state == "neutral":
        strategy_note = "중립: 선별 접근. 눌림 확인/돌파 확인과 손익비를 우선 확인."
    elif state == "burden":
        strategy_note = "불리: 권장금액 축소. 강한 섹터의 우량 후보만 관찰 또는 소액 조건부."
    else:
        strategy_note = "위험회피: 일반 신규매수 금지. 강한 관찰 후보와 보유 리스크 점검 우선."

    return {
        "state": state,
        "label": label,
        "use_cash_ratio": use_ratio,
        "entry_tighten": entry_tighten,
        "market_risk_score": round(float(risk_score), 1),
        "attack_permission": attack_permission,
        "defense_need": defense_need,
        "hard_blocks": hard_blocks[:8],
        "warning_blocks": warning_blocks[:8],
        "supportive_blocks": supportive_blocks[:8],
        "hard_block_count": hard_count,
        "strategy_note": strategy_note,
    }


def korean_market_control_profile_df(market_info: dict) -> pd.DataFrame:
    if not isinstance(market_info, dict):
        return pd.DataFrame()
    rows = [
        {"항목": "시장위험도", "값": market_info.get("market_risk_score", "-")},
        {"항목": "공격허용도", "값": market_info.get("attack_permission", "-")},
        {"항목": "방어필요도", "값": market_info.get("defense_need", "-")},
        {"항목": "하드블록 수", "값": market_info.get("hard_block_count", 0)},
        {"항목": "현금사용비율", "값": f"{safe_float(market_info.get('use_cash_ratio'),0)*100:.0f}%"},
    ]
    return pd.DataFrame(rows)

def build_market_risk_rules(market_info: dict) -> list:
    """시장 상태에 따른 강제/권고 규칙을 사용자에게 투명하게 보여주기 위한 목록."""
    state = market_info.get('state', 'neutral') if isinstance(market_info, dict) else 'neutral'
    rules = []
    if state == 'strong_favorable':
        rules += [
            '공격허용도 우위: 조건 충족 주도주 분할 접근 가능',
            '손익비 1.5 이상 우선',
            '돌파/눌림 확인 종목은 권장금액 정상 적용',
            '단기 급등 이격 확대 시 현재가 기준 재평가',
        ]
    elif state == 'risk_off':
        rules += [
            '신규 매수 권장금액 0원',
            '매수 가능 후보는 관찰 후보로 강등',
            '보유 종목 손절/비중 리스크 우선 점검',
            '주도주라도 즉시 추격매수 금지',
        ]
    elif state == 'burden':
        rules += [
            '권장금액 기본값 대비 대폭 축소',
            '손익비 1.5 미만 제외',
            '진입가 이격률 2~3% 초과 시 대기 우선',
            '시장 민감 섹터는 보수 판정',
        ]
    elif state == 'neutral':
        rules += [
            '선별 접근',
            '눌림 확인 완료 또는 돌파 확인 종목만 검토',
            '추격매수 위험 제외 필터 유지 권장',
        ]
    else:
        rules += [
            '조건 충족 종목만 분할 접근 가능',
            '손절가와 목표가가 명확한 종목만 검토',
            '장중 급등 후 이격 확대 시 판정 재계산 필요',
        ]
    return rules


def save_market_state_log(market_info: dict):
    """시장 판단 결과를 로그로 저장해 이후 시장 상태별 성과 학습에 사용할 수 있게 합니다."""
    try:
        if not isinstance(market_info, dict):
            return
        market = market_info.get('market', '-')
        path = DATA_DIR / f"market_state_log_{market}.csv"
        internals = market_info.get('internals', {}) if isinstance(market_info.get('internals', {}), dict) else {}
        sector_internal = market_info.get('sector_internals', {}) if isinstance(market_info.get('sector_internals', {}), dict) else {}
        event = market_info.get('event_risk', {}) if isinstance(market_info.get('event_risk', {}), dict) else {}
        row = {
            'created_at': market_info.get('created_at', now_kst().strftime('%Y-%m-%d %H:%M:%S')),
            'market': market,
            'session_label': market_info.get('session', {}).get('label', '-'),
            'state': market_info.get('state', '-'),
            'label': market_info.get('label', '-'),
            'score': market_info.get('score', np.nan),
            'market_risk_score': market_info.get('market_risk_score', np.nan),
            'attack_permission': market_info.get('attack_permission', np.nan),
            'defense_need': market_info.get('defense_need', np.nan),
            'hard_block_count': market_info.get('hard_block_count', np.nan),
            'indicator_score': market_info.get('score_breakdown', {}).get('지표 가중점수', np.nan),
            'internals_score': market_info.get('score_breakdown', {}).get('후보군 내부강도', np.nan),
            'sector_internals_score': market_info.get('score_breakdown', {}).get('섹터 내부강도', np.nan),
            'event_risk_score': market_info.get('score_breakdown', {}).get('일정 리스크', np.nan),
            'positive_ratio': internals.get('positive_ratio', np.nan),
            'sector_strong_ratio': sector_internal.get('strong_sector_ratio', np.nan),
            'sector_weak_ratio': sector_internal.get('weak_sector_ratio', np.nan),
            'event_level': event.get('level', '-'),
            'burden_reasons': '; '.join(market_info.get('burden_reasons', []) or []),
            'favorable_reasons': '; '.join(market_info.get('favorable_reasons', []) or []),
        }
        new = pd.DataFrame([row])
        if path.exists():
            old = pd.read_csv(path, encoding='utf-8-sig')
            df = pd.concat([old, new], ignore_index=True)
        else:
            df = new
        df = df.drop_duplicates(['created_at', 'market'], keep='last')
        df.tail(1000).to_csv(path, index=False, encoding='utf-8-sig')
    except Exception as e:
        log_error('save_market_state_log', e)


def market_state_log_summary_df(market: str) -> pd.DataFrame:
    """최근 시장판단 로그 요약. 추천 결과 성과와 직접 연결하기 전 단계의 상태 점검용입니다."""
    path = DATA_DIR / f"market_state_log_{market}.csv"
    if not path.exists():
        return pd.DataFrame()
    try:
        df = pd.read_csv(path, encoding='utf-8-sig')
        if df.empty:
            return pd.DataFrame()
        rows = []
        for label, sub in df.tail(200).groupby('label', dropna=False):
            rows.append({
                '시장상태': label,
                '기록수': len(sub),
                '평균 시장점수': round(pd.to_numeric(sub.get('score'), errors='coerce').mean(), 2),
                '평균 상승비율': round(pd.to_numeric(sub.get('positive_ratio'), errors='coerce').mean(), 1),
                '강한 섹터비율': round(pd.to_numeric(sub.get('sector_strong_ratio'), errors='coerce').mean(), 1),
                '약한 섹터비율': round(pd.to_numeric(sub.get('sector_weak_ratio'), errors='coerce').mean(), 1),
            })
        return pd.DataFrame(rows).sort_values('기록수', ascending=False)
    except Exception:
        return pd.DataFrame()


def event_risk_adjustment_from_settings() -> dict:
    """v1.9.8: FOMC/CPI/실적/옵션만기 등 일정 리스크를 수동으로 시장점수에 반영."""
    try:
        settings = read_settings()
    except Exception:
        settings = {}
    level = str(settings.get('manual_event_risk', '없음') or '없음')
    note = str(settings.get('manual_event_note', '') or '').strip()
    if level == '높음':
        score = -1.5; label = '높음'; msg = '중요 일정 리스크 높음: 매수 기준 강화'
    elif level == '중간':
        score = -0.7; label = '중간'; msg = '일정 리스크 중간: 권장금액 보수 적용'
    else:
        score = 0.0; label = '없음'; msg = '수동 입력 일정 리스크 없음'
    return {"level": label, "note": note, "score": score, "message": msg}


def calculate_market_state(market: str) -> dict:
    symbols = MARKET_SYMBOLS[market]
    prefetch_yf_cache(list(symbols.values()), period="5d", interval="1d")
    meta_map = MARKET_INDICATOR_META.get(market, {})
    session = infer_market_session(market)
    rows = []
    score = 0.0
    burden_reasons = []
    favorable_reasons = []
    for name, sym in symbols.items():
        chg = pct_change_last(sym)
        meta = meta_map.get(name, {"weight": 1.0, "kind": "risk", "role": name})
        contrib, direction = _indicator_contribution(name, chg, meta)
        score += contrib
        if direction == "burden":
            burden_reasons.append(f"{name} {chg:+.2f}%")
        elif direction == "favorable":
            favorable_reasons.append(f"{name} {chg:+.2f}%")
        rows.append({
            "indicator": name,
            "symbol": sym,
            "change_pct": round(chg, 2),
            "direction": direction,
            "score": round(contrib, 2),
            "weight": float(meta.get("weight", 1.0)),
            "role": meta.get("role", name),
        })

    # v1.9.8: 후보군 내부강도와 수동 일정 리스크를 시장점수에 추가 반영한다.
    internals = calculate_market_internals(market)
    if internals.get("available"):
        score += float(internals.get("score", 0.0))
        if internals.get("score", 0) <= -1.0:
            burden_reasons.append(f"내부강도 부담: 상승비율 {internals.get('positive_ratio')}%, 평균 {internals.get('avg_change_pct')}%")
        elif internals.get("score", 0) >= 1.0:
            favorable_reasons.append(f"내부강도 우호: 상승비율 {internals.get('positive_ratio')}%, 평균 {internals.get('avg_change_pct')}%")
    sector_internals = calculate_sector_internals(market)
    if sector_internals.get("available"):
        score += float(sector_internals.get("score", 0.0))
        if sector_internals.get("score", 0) <= -0.8:
            burden_reasons.append(f"섹터 확산 부담: 약한 섹터 {sector_internals.get('weak_sector_ratio')}%")
        elif sector_internals.get("score", 0) >= 0.8:
            favorable_reasons.append(f"섹터 확산 우호: 강한 섹터 {sector_internals.get('strong_sector_ratio')}%")
    event_risk = event_risk_adjustment_from_settings()
    score += float(event_risk.get("score", 0.0))
    if event_risk.get("score", 0) < 0:
        burden_reasons.append(event_risk.get("message", "일정 리스크"))

    score_breakdown = {
        "지표 가중점수": round(float(sum([r.get('score', 0) for r in rows])), 2),
        "후보군 내부강도": round(float(internals.get('score', 0.0)), 2),
        "섹터 내부강도": round(float(sector_internals.get('score', 0.0)), 2),
        "일정 리스크": round(float(event_risk.get('score', 0.0)), 2),
        "최종 시장점수": round(float(score), 2),
    }

    # v2.0.2 MARKET: 5단계 시장상태 + 시장위험도/공격허용도/방어필요도/하드블록을 함께 산출합니다.
    control_profile = build_market_control_profile(score, rows, internals, sector_internals, event_risk)
    state = control_profile.get("state", "neutral")
    label = control_profile.get("label", "중립")
    use_ratio = safe_float(control_profile.get("use_cash_ratio"), 0.15)
    entry_tighten = safe_float(control_profile.get("entry_tighten"), 0.8)
    strategy_note = control_profile.get("strategy_note", "선별 접근")

    return {
        "market": market,
        "score": round(float(score), 2),
        "state": state,
        "label": label,
        "use_cash_ratio": use_ratio,
        "entry_tighten": entry_tighten,
        "market_risk_score": control_profile.get("market_risk_score", 0),
        "attack_permission": control_profile.get("attack_permission", 0),
        "defense_need": control_profile.get("defense_need", 0),
        "hard_blocks": control_profile.get("hard_blocks", []),
        "warning_blocks": control_profile.get("warning_blocks", []),
        "supportive_blocks": control_profile.get("supportive_blocks", []),
        "hard_block_count": control_profile.get("hard_block_count", 0),
        "rows": rows,
        "session": session,
        "burden_reasons": burden_reasons[:6],
        "favorable_reasons": favorable_reasons[:6],
        "strategy_note": strategy_note,
        "internals": internals,
        "sector_internals": sector_internals,
        "event_risk": event_risk,
        "score_breakdown": score_breakdown,
        "risk_rules": build_market_risk_rules({"state": state, "market_risk_score": control_profile.get("market_risk_score", 0), "hard_blocks": control_profile.get("hard_blocks", [])}),
        "created_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
    }


def sector_market_adjustment(sector: str, market_info: dict) -> tuple:
    """금리/환율/유가 같은 시장 변수의 섹터별 민감도 보정. 점수는 -3~+3 범위로 제한합니다."""
    if not isinstance(market_info, dict):
        return 0.0, ""
    row_map = {r.get("indicator"): r for r in market_info.get("rows", []) if isinstance(r, dict)}
    adj = 0.0
    reasons = []
    def _chg(key):
        try:
            return float(row_map.get(key, {}).get("change_pct", 0))
        except Exception:
            return 0.0
    wti = _chg("WTI")
    us10y = _chg("US10Y")
    fx = _chg("USD/KRW")
    dollar = _chg("DOLLAR")
    vix = _chg("VIX")
    s = str(sector)
    if "Airline" in s and wti > 0.5:
        adj -= 2.0; reasons.append("유가 상승은 항공주 부담")
    if "Energy" in s and wti > 0.5:
        adj += 1.5; reasons.append("유가 상승은 에너지주 우호")
    if any(x in s for x in ["Software", "Growth", "Battery", "EV", "AI", "Semiconductor"]):
        if us10y > 0.5:
            adj -= 1.5; reasons.append("금리 상승은 성장/기술주 부담")
        if vix > 1.2:
            adj -= 1.0; reasons.append("VIX 상승은 고변동 성장주 부담")
    if any(x in s for x in ["Defense", "Shipbuilding", "Auto", "Semiconductor"]):
        if fx > 0.5 or dollar > 0.5:
            adj += 0.8; reasons.append("환율/달러 강세는 일부 수출주에 중립~우호")
    if "Finance" in s and us10y > 0.5:
        adj += 0.8; reasons.append("금리 상승은 금융주에 일부 우호")
    adj = max(-3.0, min(3.0, adj))
    return adj, "; ".join(reasons[:3])


def sector_strength(market: str) -> pd.DataFrame:
    all_syms = []
    for _syms in SECTOR_REPS[market].values():
        all_syms.extend(_syms)
    prefetch_yf_cache(all_syms, period="5d", interval="1d")
    rows = []
    for sector, syms in SECTOR_REPS[market].items():
        changes = []
        for sym in syms:
            changes.append(pct_change_last(sym))
        avg = float(np.nanmean(changes)) if changes else 0.0
        score = max(0, min(100, 50 + avg * 10))
        rows.append({"sector": sector, "avg_change_pct": round(avg, 2), "sector_score": round(score, 1)})
    return pd.DataFrame(rows).sort_values("sector_score", ascending=False)


def clamp(x: float, lo: float = 0, hi: float = 100) -> float:
    try:
        return float(max(lo, min(hi, x)))
    except Exception:
        return 0.0



def detect_leader_mode(
    attractiveness: float,
    sector_score: float,
    market_info: dict,
    close: float,
    ma20: float,
    ma60: float,
    ret20: float,
    ret60: float,
    vol: float,
    vol_ma20: float,
    news_score: float,
) -> Tuple[bool, str]:
    """강한 주도주/모멘텀 종목 여부를 정량 조건으로 판정한다.

    핵심 목적은 '가격이 높다 = 무조건 매수금지'가 아니라,
    비싼 가격을 정당화할 만큼 섹터·추세·거래대금·시장 상태가 강한지 별도 판단하는 것이다.
    """
    checks = []
    checks.append(attractiveness >= 78)  # v1.6은 실전 후보가 너무 적어지지 않도록 85보다 완화
    checks.append(sector_score >= 70)
    checks.append(market_info.get("state") in ["strong_favorable", "favorable", "neutral"])
    checks.append(close > ma20 and ma20 >= ma60)
    checks.append((ret20 >= 5) or (ret60 >= 12))
    checks.append(vol >= vol_ma20 * 0.9 if vol_ma20 and vol_ma20 > 0 else True)
    checks.append(news_score >= 6)
    passed = sum(bool(x) for x in checks)
    is_leader = passed >= 5
    reason = f"주도주 조건 {passed}/7개 충족"
    return is_leader, reason


def classify_pullback_state(
    df: pd.DataFrame,
    close: float,
    entry: float,
    ma5: float,
    ma20: float,
    ma60: float,
    rsi: float,
    macd: float,
    macd_sig: float,
    vol: float,
    vol_ma20: float,
    resistance_room_pct: float,
    entry_distance_pct: float,
    risk_reward: float,
    is_leader: bool,
) -> Tuple[str, str, str]:
    """차트 데이터를 보고 현재 눌림/돌파/추격 상태를 직접 판정한다."""
    recent = df.tail(20).copy()
    if recent.empty:
        return "판단불가", "차트 데이터 부족", "차트 데이터 확보 후 재확인"
    recent_high = safe_float(recent["High"].max(), close)
    pullback_pct = (recent_high - close) / recent_high * 100 if recent_high > 0 else 0
    prev_low = safe_float(recent["Low"].iloc[-2], close) if len(recent) >= 2 else close
    prev_close = safe_float(recent["Close"].iloc[-2], close) if len(recent) >= 2 else close
    today_low = safe_float(recent["Low"].iloc[-1], close)
    today_open = safe_float(recent["Open"].iloc[-1], close)
    today_close = safe_float(recent["Close"].iloc[-1], close)
    close_recovered = today_close >= today_open or today_close >= prev_close * 0.995
    support_zone = False
    if is_leader:
        support_zone = (close >= ma5 * 0.98 and close <= ma20 * 1.05) or (close >= ma20 * 0.98 and close <= ma20 * 1.04)
        enough_pullback = pullback_pct >= 2
        deep_failed_level = ma20 * 0.97
    else:
        support_zone = close >= ma20 * 0.97 and close <= ma20 * 1.04
        enough_pullback = pullback_pct >= 4
        deep_failed_level = ma60 * 0.98
    volume_cooled = vol <= vol_ma20 * 1.15 if vol_ma20 and vol_ma20 > 0 else True
    rebound_signal = close_recovered and today_low >= min(prev_low, ma20 * 0.97) and rsi >= 45 and macd >= macd_sig * 0.98
    if close < deep_failed_level or (close < ma20 and close < ma60):
        return "눌림 실패", "주요 이동평균/지지선 이탈로 눌림보다 추세 훼손 가능성", "신규매수 금지, 다음 지지선 재확인"
    if entry_distance_pct >= (8 if is_leader else 5) or (rsi >= 74 and resistance_room_pct < 3):
        return "추격매수 위험", "진입가 이격 또는 RSI/저항 조건상 손익비가 약화된 구간", "신규매수 금지, 눌림 또는 거래량 동반 재돌파 대기"
    if resistance_room_pct <= 3 and vol >= vol_ma20 * 0.95:
        return "돌파 확인 대기", "저항선 근처로 종가 돌파와 거래량 확인이 필요한 구간", "종가 기준 돌파 + 거래량 유지 전까지 성급한 진입 금지"
    if enough_pullback and support_zone and volume_cooled and rebound_signal and risk_reward >= 1.5 and entry_distance_pct <= (3 if is_leader else 2.5):
        return "눌림 확인 완료", "조정 후 지지권에서 회복 신호와 손익비가 확인됨", "우선진입가 근처에서만 분할 접근 가능"
    if enough_pullback and support_zone and volume_cooled:
        return "눌림 진행 중", "조정과 거래량 진정은 보이나 반등 확인이 아직 부족함", "관심 유지, 반등 캔들/종가 회복 확인 전 매수 금지"
    if pullback_pct < (2 if is_leader else 4) and close > ma20 * (1.03 if is_leader else 1.04):
        return "눌림 전", "아직 충분한 조정 없이 가격이 높은 위치에 있음", "추격매수 금지, 5일선~20일선 또는 우선진입가 재접근 대기"
    return "진입가 대기", "추세는 유지되나 명확한 눌림 확인 또는 돌파 확인이 부족함", "진입가 이격률과 거래량을 재확인"

def analyze_symbol(row: dict, market: str, market_info: dict, sector_score: float, settings: dict) -> dict:
    symbol = row.get("symbol", "")
    name = row.get("name", symbol)
    name_kr = row.get("name_kr", name)
    sector = row.get("sector", "")
    df = yf_download(symbol, period="1y", interval="1d")
    if df.empty or len(df) < 60:
        return {"symbol": symbol, "name": name, "name_kr": name_kr, "sector": sector, "error": "데이터 부족", "final_score": 0, "decision": "관망/제외"}
    df = add_indicators(df)
    last = df.iloc[-1]
    close = safe_float(last["Close"])
    atr = safe_float(last.get("ATR"), close * 0.03)
    if not np.isfinite(atr) or atr <= 0:
        atr = close * 0.03
    ma5 = safe_float(last.get("MA5"), close)
    ma20 = safe_float(last.get("MA20"), close)
    ma60 = safe_float(last.get("MA60"), close)
    ma120 = safe_float(last.get("MA120"), close)
    rsi = safe_float(last.get("RSI"), 50)
    macd = safe_float(last.get("MACD"), 0)
    macd_sig = safe_float(last.get("MACD_SIGNAL"), 0)
    vol = safe_float(last.get("Volume"), 0)
    vol_ma20 = safe_float(last.get("VOL_MA20"), vol)
    ret20 = safe_float(last.get("RET_20D"), 0)
    ret60 = safe_float(last.get("RET_60D"), 0)
    recent = df.tail(60)
    support1 = safe_float(recent["Low"].tail(20).min(), close * 0.95)
    support2 = safe_float(recent["Low"].min(), close * 0.90)
    resistance1 = safe_float(recent["High"].tail(20).max(), close * 1.05)
    resistance2 = safe_float(recent["High"].max(), close * 1.10)
    # Entry near support/MA20 but not too low. This is a conservative desired entry, not a guarantee.
    entry = max(min(close * 0.985, ma20 * 1.005), support1 * 1.01)
    stop = min(entry - atr * 1.2, support1 * 0.985)
    if stop <= 0 or stop >= entry:
        stop = entry * 0.95
    target1 = max(resistance1, entry + (entry - stop) * 1.8)
    target2 = max(resistance2, entry + (entry - stop) * 2.5)
    risk_pct = (entry - stop) / entry * 100
    reward_pct = (target1 - entry) / entry * 100
    rr = reward_pct / risk_pct if risk_pct > 0 else 0
    entry_distance_pct = (close - entry) / entry * 100
    resistance_room_pct = (resistance1 - close) / close * 100 if close > 0 else 0
    trend_score = 0
    trend_score += 6 if close > ma20 else 0
    trend_score += 6 if ma20 > ma60 else 0
    trend_score += 4 if ma60 > ma120 else 0
    trend_score += clamp(ret20, -10, 10) / 10 * 4
    trend_score = clamp(trend_score, 0, 20)
    chart_score = 7 if close > support1 else 2
    chart_score += 4 if resistance_room_pct > 5 else (2 if resistance_room_pct > 2 else 0)
    chart_score += 4 if ret60 > 0 else 1
    chart_score = clamp(chart_score, 0, 15)
    indicator_score = 0
    indicator_score += 5 if 45 <= rsi <= 65 else (3 if 35 <= rsi < 45 or 65 < rsi <= 72 else 1)
    indicator_score += 5 if macd > macd_sig else 2
    indicator_score += 5 if vol > vol_ma20 * 1.1 else (3 if vol > vol_ma20 * 0.8 else 1)
    indicator_score = clamp(indicator_score, 0, 15)
    sector_theme_score = clamp(sector_score * 0.15, 0, 15)
    market_sector_adjustment, market_sector_note = sector_market_adjustment(sector, market_info)
    sector_theme_score = clamp(sector_theme_score + market_sector_adjustment, 0, 15)
    fundamentals_score = 10.0  # placeholder until financial data module is added
    news_score = 6.0           # placeholder until news quality module is added
    history_score = 5.0        # placeholder until enough model history exists
    attractiveness = trend_score + chart_score + indicator_score + sector_theme_score + fundamentals_score + news_score + history_score
    rr_score = clamp((rr - 1.0) / 1.5 * 25, 0, 25)
    if entry_distance_pct <= 0:
        entry_score = 25
    elif entry_distance_pct <= 2:
        entry_score = 22
    elif entry_distance_pct <= 3:
        entry_score = 16
    elif entry_distance_pct <= 5:
        entry_score = 9
    else:
        entry_score = 2
    stop_clarity_score = 15 if risk_pct <= 5 else (11 if risk_pct <= 8 else 5)
    resistance_score = 15 if resistance_room_pct >= 8 else (10 if resistance_room_pct >= 5 else (5 if resistance_room_pct >= 2 else 1))
    market_score = {"strong_favorable": 10, "favorable": 9, "neutral": 7, "burden": 3, "risk_off": 0}.get(market_info.get("state"), 5)
    event_score = 8.0  # no event calendar module yet
    trade_fit = rr_score + entry_score + stop_clarity_score + resistance_score + market_score + event_score
    final_score = attractiveness * 0.45 + trade_fit * 0.55

    is_leader, leader_reason = detect_leader_mode(
        attractiveness=attractiveness,
        sector_score=sector_score,
        market_info=market_info,
        close=close,
        ma20=ma20,
        ma60=ma60,
        ret20=ret20,
        ret60=ret60,
        vol=vol,
        vol_ma20=vol_ma20,
        news_score=news_score,
    )
    pullback_state, pullback_reason, pullback_action = classify_pullback_state(
        df=df, close=close, entry=entry, ma5=ma5, ma20=ma20, ma60=ma60,
        rsi=rsi, macd=macd, macd_sig=macd_sig, vol=vol, vol_ma20=vol_ma20,
        resistance_room_pct=resistance_room_pct, entry_distance_pct=entry_distance_pct,
        risk_reward=rr, is_leader=is_leader,
    )

    hard_blocks = []
    cautions = []
    if rr < 1.3:
        hard_blocks.append("손익비 1.3 미만")

    # v1.6: 강한 주도주는 가격 이격만으로 무조건 금지하지 않는다.
    # 대신 '주도주 조건부 접근'과 권장금액 축소로 리스크를 제한한다.
    if is_leader:
        if entry_distance_pct > 8:
            hard_blocks.append(f"주도주 기준 초과 이격 +{entry_distance_pct:.1f}%")
        elif entry_distance_pct > 5:
            cautions.append(f"주도주 고이격 +{entry_distance_pct:.1f}%: 소액/확인 접근만")
        elif entry_distance_pct > 3:
            cautions.append(f"주도주 조건부 이격 +{entry_distance_pct:.1f}%")
    else:
        if entry_distance_pct > 3:
            hard_blocks.append(f"진입가 대비 +{entry_distance_pct:.1f}% 이격")
        elif entry_distance_pct > 2:
            cautions.append(f"진입가 대비 +{entry_distance_pct:.1f}% 이격")

    if resistance_room_pct < 2:
        hard_blocks.append("저항선까지 여유 2% 미만")
    if risk_pct > 8:
        hard_blocks.append("손절폭 8% 초과")
    if market_info.get("state") == "risk_off":
        hard_blocks.append("시장 위험회피")
    if close < ma20 and close < ma60:
        hard_blocks.append("20일선/60일선 하회")
    if pullback_state == "눌림 실패":
        hard_blocks.append("눌림 실패/추세 훼손")

    # Decision
    if hard_blocks:
        if any("이격" in h for h in hard_blocks) or pullback_state == "추격매수 위험":
            decision = "추격매수 금지"
        else:
            decision = "관망/제외"
    elif is_leader and attractiveness >= 78 and rr >= 1.5 and pullback_state in ["눌림 확인 완료", "돌파 확인 대기", "진입가 대기", "눌림 전", "눌림 진행 중"]:
        if pullback_state == "눌림 확인 완료" and entry_distance_pct <= 3:
            decision = "주도주 조건부 접근"
        elif pullback_state == "돌파 확인 대기":
            decision = "돌파 확인 필요"
        else:
            decision = "주도주 조건부 접근"
    elif final_score >= 75 and trade_fit >= 75 and rr >= 1.5 and entry_distance_pct <= 2 and pullback_state in ["눌림 확인 완료", "진입가 대기"]:
        decision = "매수 가능"
    elif pullback_state == "눌림 확인 완료" and final_score >= 70 and rr >= 1.5:
        decision = "매수 가능"
    elif attractiveness >= 75 and 2 < entry_distance_pct <= 6:
        decision = "진입가 대기"
    elif pullback_state == "돌파 확인 대기" or (resistance_room_pct <= 3 and vol > vol_ma20):
        decision = "돌파 확인 필요"
    elif pullback_state == "추격매수 위험":
        decision = "추격매수 금지"
    elif final_score >= 65:
        decision = "진입가 대기"
    else:
        decision = "관망/제외"
    position = calculate_position_size(settings, market_info, entry, stop, hard_blocks, decision=decision, is_leader=is_leader, pullback_state=pullback_state)
    good_points = []
    bad_points = []
    if is_leader: good_points.append(f"주도주 조건부 기준 충족({leader_reason})")
    if pullback_state == "눌림 확인 완료": good_points.append("차트 상태: 눌림 확인 완료")
    if trend_score >= 14: good_points.append("추세 점수 양호")
    if sector_theme_score >= 10: good_points.append("섹터 강도 우호")
    if rr >= 1.5: good_points.append(f"손익비 {rr:.2f}로 조건 충족")
    if entry_distance_pct <= 2: good_points.append("진입가 이격률 낮음")
    if rsi > 70: bad_points.append("RSI 과열권")
    if entry_distance_pct > 2: bad_points.append("현재가가 우선진입가보다 높음")
    if resistance_room_pct < 5: bad_points.append("저항선까지 여유 제한")
    if pullback_state in ["눌림 전", "눌림 진행 중", "추격매수 위험"]: bad_points.append(f"차트 상태: {pullback_state}")
    if market_sector_note:
        (good_points if market_sector_adjustment > 0 else bad_points).append(market_sector_note)
    if market_info.get("state") in ["burden", "risk_off"]: bad_points.append("시장 환경 부담")
    return {
        "created_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
        "market": market,
        "symbol": symbol,
        "name": name,
        "name_kr": name_kr,
        "sector": sector,
        "market_session": market_info.get("session", {}).get("label", "-"),
        "market_sector_adjustment": round(market_sector_adjustment, 2),
        "market_sector_note": market_sector_note,
        "close": round(close, 2),
        "entry": round(entry, 2),
        "stop": round(stop, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "risk_pct": round(risk_pct, 2),
        "reward_pct": round(reward_pct, 2),
        "risk_reward": round(rr, 2),
        "entry_distance_pct": round(entry_distance_pct, 2),
        "resistance_room_pct": round(resistance_room_pct, 2),
        "attractiveness_score": round(attractiveness, 1),
        "trade_fit_score": round(trade_fit, 1),
        "final_score": round(final_score, 1),
        "trend_score": round(trend_score, 1),
        "chart_score": round(chart_score, 1),
        "indicator_score": round(indicator_score, 1),
        "sector_score_component": round(sector_theme_score, 1),
        "fundamentals_score": round(fundamentals_score, 1),
        "news_score": round(news_score, 1),
        "history_score": round(history_score, 1),
        "rr_score": round(rr_score, 1),
        "entry_score": round(entry_score, 1),
        "stop_clarity_score": round(stop_clarity_score, 1),
        "resistance_score": round(resistance_score, 1),
        "market_score_component": round(market_score, 1),
        "event_score": round(event_score, 1),
        "decision": decision,
        "leader_mode": "Y" if is_leader else "N",
        "leader_reason": leader_reason,
        "pullback_state": pullback_state,
        "pullback_reason": pullback_reason,
        "pullback_action": pullback_action,
        "hard_blocks": "; ".join(hard_blocks),
        "cautions": "; ".join(cautions),
        "good_points": "; ".join(good_points[:4]),
        "bad_points": "; ".join(bad_points[:4]),
        "support1": round(support1, 2),
        "support2": round(support2, 2),
        "resistance1": round(resistance1, 2),
        "resistance2": round(resistance2, 2),
        "rsi": round(rsi, 2),
        "macd": round(macd, 3),
        "atr": round(atr, 2),
        **position,
    }


def calculate_position_size(settings: dict, market_info: dict, entry: float, stop: float, hard_blocks: List[str], decision: str = "", is_leader: bool = False, pullback_state: str = "") -> dict:
    total_assets = float(settings.get("total_assets", DEFAULT_SETTINGS["total_assets"]))
    cash = float(settings.get("cash_krw", DEFAULT_SETTINGS["cash_krw"]))
    risk_per_trade_pct = float(settings.get("risk_per_trade_pct", 0.5))
    max_single_pct = float(settings.get("max_single_position_pct", 10.0))
    min_cash_reserve_pct = float(settings.get("min_cash_reserve_pct", 20.0))
    if hard_blocks or entry <= 0 or stop <= 0 or stop >= entry:
        return {"recommended_amount": 0, "position_reason": "매수금지 조건 또는 손절가 오류"}
    risk_amount = total_assets * (risk_per_trade_pct / 100)
    stop_pct = (entry - stop) / entry
    technical_amount = risk_amount / stop_pct if stop_pct > 0 else 0
    reserve_cash = total_assets * (min_cash_reserve_pct / 100)
    usable_cash = max(0, cash - reserve_cash)
    market_cap = cash * float(market_info.get("use_cash_ratio", 0.15))
    single_cap = total_assets * (max_single_pct / 100)
    amount = max(0, min(technical_amount, usable_cash, market_cap, single_cap))
    scale_note = ""
    if decision == "주도주 조건부 접근":
        amount *= 0.4
        scale_note = ", 주도주 고이격/조건부 접근으로 40% 축소"
    elif pullback_state in ["눌림 전", "눌림 진행 중", "돌파 확인 대기"] and decision != "매수 가능":
        amount *= 0.5
        scale_note = f", 차트상태 {pullback_state}로 50% 축소"
    reason = f"허용손실 {risk_amount:,.0f}원, 손절폭 {stop_pct*100:.1f}%, 시장상태 {market_info.get('label')} 반영{scale_note}"
    return {"recommended_amount": int(round(amount / 10000) * 10000), "position_reason": reason}


def apply_filter_presets(df: pd.DataFrame, presets: dict) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out
    if presets.get("exclude_chasing", True):
        out = out[~out["decision"].isin(["추격매수 금지"])]
    if presets.get("rr_good", True):
        out = out[out["risk_reward"] >= 1.5]
    if presets.get("exclude_blocked", True):
        out = out[out["hard_blocks"].fillna("").astype(str).str.len() == 0]
    if presets.get("buyable_only", False):
        out = out[out["decision"].isin(["매수 가능", "주도주 조건부 접근"])]
    if presets.get("pullback_watch", False):
        out = out[out["decision"].isin(["진입가 대기", "주도주 조건부 접근"]) | out.get("pullback_state", pd.Series(index=out.index, dtype=str)).isin(["눌림 진행 중", "눌림 확인 완료"])]
    if presets.get("breakout_watch", False):
        out = out[out["decision"].isin(["돌파 확인 필요"])]
    return out


def run_ranking(market: str = "KR", mode: str = "auto", selected_sectors: Optional[List[str]] = None, limit: int = 30, top_n: int = 10, presets: Optional[dict] = None) -> Tuple[pd.DataFrame, dict, pd.DataFrame]:
    ensure_base_files()
    settings = read_settings()
    market_info = calculate_market_state(market)
    save_market_state_log(market_info)
    sector_df = sector_strength(market)
    universe = load_universe(market)
    if mode == "auto":
        chosen = sector_df.head(3)["sector"].tolist()
    else:
        chosen = selected_sectors or sector_df.head(3)["sector"].tolist()
    candidates = universe[universe["sector"].isin(chosen)].copy()
    if candidates.empty:
        candidates = universe.copy()
    # rough liquidity and data quality pass is done inside analyze; limit count for speed.
    candidates = candidates.head(max(5, int(limit)))
    # v2.0.1 SPEED: 정밀분석 대상은 유지하되, yfinance 1년 데이터를 한 번에 선조회해 반복 호출을 줄입니다.
    prefetch_yf_cache(candidates['symbol'].dropna().astype(str).tolist(), period="1y", interval="1d")
    rows = []
    sector_map = {r["sector"]: r["sector_score"] for _, r in sector_df.iterrows()}
    for _, r in candidates.iterrows():
        try:
            rows.append(analyze_symbol(r.to_dict(), market, market_info, sector_map.get(r["sector"], 50), settings))
        except Exception as e:
            log_error(f"analyze_symbol {r.get('symbol')}", e)
            rows.append({"symbol": r.get("symbol"), "name": r.get("name"), "name_kr": r.get("name_kr"), "sector": r.get("sector"), "error": str(e), "final_score": 0, "decision": "관망/제외"})
    df = pd.DataFrame(rows)
    batch_id = f"{market}_{now_kst().strftime('%Y%m%d_%H%M%S')}"
    created_at_text = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    if not df.empty and "final_score" in df.columns:
        df = df.sort_values(["final_score", "trade_fit_score"], ascending=False, na_position="last")
        df["batch_id"] = batch_id
        df["created_at"] = created_at_text
        df["market"] = market
    raw_path = DATA_DIR / f"recommendations_{market}_raw.csv"
    df.to_csv(raw_path, index=False, encoding="utf-8-sig")
    presets = presets or {"exclude_chasing": False, "rr_good": False, "exclude_blocked": False}
    filtered = apply_filter_presets(df, presets)
    top = filtered.head(top_n)
    if top.empty:
        top = df.head(top_n)
    out_path = DATA_DIR / f"latest_recommendations_{market}.csv"
    top.to_csv(out_path, index=False, encoding="utf-8-sig")
    status = {"market_info": market_info, "selected_sectors": chosen, "top_n": top_n, "analysis_limit": limit, "created_at": created_at_text, "batch_id": batch_id}
    (DATA_DIR / f"today_status_{market}.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return top, market_info, sector_df



def _trade_result_from_prices(r: pd.Series, prices: pd.DataFrame) -> dict:
    """추천 당시 진입가/손절가/목표가 대비 이후 가격 결과를 계산합니다."""
    entry = safe_float(r.get("entry"), np.nan)
    stop = safe_float(r.get("stop"), np.nan)
    target1 = safe_float(r.get("target1"), np.nan)
    close_at_rec = safe_float(r.get("close"), np.nan)
    decision = str(r.get("decision", ""))
    if prices.empty:
        return {"outcome": "가격데이터 없음"}
    highs = prices["High"].astype(float)
    lows = prices["Low"].astype(float)
    closes = prices["Close"].astype(float)
    last_close = safe_float(closes.iloc[-1], np.nan)
    max_high = safe_float(highs.max(), np.nan)
    min_low = safe_float(lows.min(), np.nan)
    entry_hit = bool(np.isfinite(entry) and ((lows <= entry) & (highs >= entry)).any())
    target1_hit = bool(np.isfinite(target1) and (highs >= target1).any())
    stop_hit = bool(np.isfinite(stop) and (lows <= stop).any())
    reference_price = entry if entry_hit and np.isfinite(entry) else close_at_rec
    if not np.isfinite(reference_price) or reference_price <= 0:
        reference_price = safe_float(closes.iloc[0], np.nan)
    max_gain_pct = (max_high / reference_price - 1) * 100 if np.isfinite(reference_price) and reference_price > 0 and np.isfinite(max_high) else np.nan
    max_drawdown_pct = (min_low / reference_price - 1) * 100 if np.isfinite(reference_price) and reference_price > 0 and np.isfinite(min_low) else np.nan
    close_return_pct = (last_close / reference_price - 1) * 100 if np.isfinite(reference_price) and reference_price > 0 and np.isfinite(last_close) else np.nan
    if "금지" in decision or "관망" in decision or "제외" in decision:
        if max_gain_pct >= 5:
            outcome = "관망 후 상승_기회비용"
        elif max_drawdown_pct <= -5:
            outcome = "관망 적중_리스크회피"
        else:
            outcome = "관망 유지_중립"
    else:
        if target1_hit and stop_hit:
            outcome = "동시도달_분봉확인필요"
        elif target1_hit:
            outcome = "1차익절 도달"
        elif stop_hit:
            outcome = "손절 도달"
        elif not entry_hit:
            outcome = "진입가 미도달"
        elif close_return_pct > 0:
            outcome = "보유 수익권"
        else:
            outcome = "보유 손실권"
    return {
        "actual_high": max_high,
        "actual_low": min_low,
        "actual_close": last_close,
        "entry_hit": entry_hit,
        "target1_hit": target1_hit,
        "stop_hit": stop_hit,
        "close_return_pct": round(close_return_pct, 3) if np.isfinite(close_return_pct) else np.nan,
        "max_gain_pct": round(max_gain_pct, 3) if np.isfinite(max_gain_pct) else np.nan,
        "max_drawdown_pct": round(max_drawdown_pct, 3) if np.isfinite(max_drawdown_pct) else np.nan,
        "outcome": outcome,
    }



def _bool_value(v) -> bool:
    if isinstance(v, bool):
        return v
    if pd.isna(v):
        return False
    return str(v).strip().lower() in ["true", "1", "y", "yes", "예", "도달"]


def classify_failure_reason(row: pd.Series) -> str:
    """결과가 좋지 않았거나 관망 판단이 틀렸을 때 원인을 자동 분류합니다."""
    outcome = str(row.get("outcome", ""))
    decision = str(row.get("decision", ""))
    blocks = str(row.get("hard_blocks", ""))
    cautions = str(row.get("cautions", ""))
    entry_dist = safe_float(row.get("entry_distance_pct", np.nan), np.nan)
    rr = safe_float(row.get("risk_reward", np.nan), np.nan)
    close_ret = safe_float(row.get("close_return_pct", np.nan), np.nan)
    max_dd = safe_float(row.get("max_drawdown_pct", np.nan), np.nan)
    max_gain = safe_float(row.get("max_gain_pct", np.nan), np.nan)
    pullback = str(row.get("pullback_state", ""))
    reasons = []
    if "기회비용" in outcome:
        reasons.append("관망 후 상승_기회비용")
    if "손절" in outcome or (np.isfinite(max_dd) and max_dd <= -5):
        reasons.append("하락/손절 리스크")
    if np.isfinite(entry_dist) and entry_dist > 3:
        reasons.append("진입가 이격 과다")
    if np.isfinite(rr) and rr < 1.5:
        reasons.append("손익비 부족")
    if "위험회피" in blocks or "시장 위험" in blocks or "위험회피" in cautions:
        reasons.append("시장 위험회피")
    if "추격" in decision or "추격" in blocks or "추격" in pullback:
        reasons.append("추격매수 위험")
    if "눌림 실패" in pullback:
        reasons.append("눌림 실패")
    if "돌파" in decision and np.isfinite(close_ret) and close_ret < 0:
        reasons.append("돌파 실패")
    if np.isfinite(max_gain) and max_gain >= 5 and ("관망" in decision or "제외" in decision):
        reasons.append("강한 종목 필터 과소평가")
    if not reasons and outcome:
        if "1차익절" in outcome or "수익권" in outcome or "리스크회피" in outcome:
            reasons.append("판단 유효")
        else:
            reasons.append("추가 확인 필요")
    return "; ".join(dict.fromkeys(reasons)) if reasons else "추가 확인 필요"


def classify_decision_validity(row: pd.Series) -> str:
    """앱의 판정이 실제 결과와 맞았는지 학습용으로 분류합니다."""
    outcome = str(row.get("outcome", ""))
    decision = str(row.get("decision", ""))
    target = _bool_value(row.get("target1_hit", False))
    stop = _bool_value(row.get("stop_hit", False))
    close_ret = safe_float(row.get("close_return_pct", np.nan), np.nan)
    if "관망" in decision or "제외" in decision or "금지" in decision:
        if "리스크회피" in outcome or (np.isfinite(close_ret) and close_ret <= -2):
            return "관망 판단 적중"
        if "기회비용" in outcome or (np.isfinite(close_ret) and close_ret >= 3):
            return "관망 판단 과보수"
        return "관망 판단 중립"
    if target and not stop:
        return "매수 판단 적중"
    if stop and not target:
        return "매수 판단 실패"
    if target and stop:
        return "분봉 확인 필요"
    if np.isfinite(close_ret) and close_ret > 0:
        return "매수 판단 부분 적중"
    if np.isfinite(close_ret) and close_ret < 0:
        return "매수 판단 미흡"
    return "검증 보류"


def enrich_learning_results(result_df: pd.DataFrame, market: str, horizon_days: int) -> pd.DataFrame:
    if result_df.empty:
        return result_df
    out = result_df.copy()
    now_text = now_kst().strftime("%Y-%m-%d %H:%M:%S")
    eval_date = now_kst().strftime("%Y-%m-%d")
    out["evaluation_date"] = eval_date
    out["update_key"] = out.apply(lambda r: f"{market}|{r.get('symbol','')}|{r.get('batch_id','')}|{int(horizon_days)}|{eval_date}", axis=1)
    out["failure_reason"] = out.apply(classify_failure_reason, axis=1)
    out["decision_validity"] = out.apply(classify_decision_validity, axis=1)
    out["learning_group"] = out["decision"].astype(str).apply(lambda x: "관망/제외" if ("관망" in x or "제외" in x or "금지" in x) else "매수/대기 후보")
    out["learning_updated_at"] = now_text
    return out


def _bucket_score(v) -> str:
    x = safe_float(v, np.nan)
    if not np.isfinite(x): return "데이터 없음"
    if x >= 80: return "80점 이상"
    if x >= 70: return "70~79점"
    if x >= 60: return "60~69점"
    return "60점 미만"


def _bucket_rr(v) -> str:
    x = safe_float(v, np.nan)
    if not np.isfinite(x): return "데이터 없음"
    if x >= 2.0: return "2.0 이상"
    if x >= 1.5: return "1.5~2.0"
    if x >= 1.3: return "1.3~1.5"
    return "1.3 미만"


def _bucket_entry_distance(v) -> str:
    x = safe_float(v, np.nan)
    if not np.isfinite(x): return "데이터 없음"
    if x <= 0: return "진입가 이하"
    if x <= 2: return "0~2%"
    if x <= 3: return "2~3%"
    if x <= 5: return "3~5%"
    return "5% 초과"


def summarize_learning_by(df: pd.DataFrame, group_col: str) -> pd.DataFrame:
    if df.empty or group_col not in df.columns:
        return pd.DataFrame()
    rows = []
    for key, sub in df.groupby(group_col, dropna=False):
        rows.append({
            "구분": key if str(key) != "nan" else "데이터 없음",
            "표본수": len(sub),
            "1차목표 도달률": round(_rate(sub.get("target1_hit", pd.Series(dtype=bool))), 1) if "target1_hit" in sub.columns else np.nan,
            "손절 도달률": round(_rate(sub.get("stop_hit", pd.Series(dtype=bool))), 1) if "stop_hit" in sub.columns else np.nan,
            "평균 종가수익률": round(pd.to_numeric(sub.get("close_return_pct", pd.Series(dtype=float)), errors="coerce").mean(), 2),
            "평균 최대상승률": round(pd.to_numeric(sub.get("max_gain_pct", pd.Series(dtype=float)), errors="coerce").mean(), 2),
            "평균 최대하락률": round(pd.to_numeric(sub.get("max_drawdown_pct", pd.Series(dtype=float)), errors="coerce").mean(), 2),
        })
    return pd.DataFrame(rows).sort_values("표본수", ascending=False)


def build_learning_summary_tables(hist: pd.DataFrame) -> dict:
    if hist.empty:
        return {}
    df = hist.copy()
    if "final_score" in df.columns:
        df["종합점수 구간"] = df["final_score"].apply(_bucket_score)
    if "risk_reward" in df.columns:
        df["손익비 구간"] = df["risk_reward"].apply(_bucket_rr)
    if "entry_distance_pct" in df.columns:
        df["진입가 이격 구간"] = df["entry_distance_pct"].apply(_bucket_entry_distance)
    tables = {
        "판정별 성과": summarize_learning_by(df, "decision") if "decision" in df.columns else pd.DataFrame(),
        "검증판정별 성과": summarize_learning_by(df, "decision_validity") if "decision_validity" in df.columns else pd.DataFrame(),
        "실패원인별 성과": summarize_learning_by(df, "failure_reason") if "failure_reason" in df.columns else pd.DataFrame(),
        "종합점수 구간별 성과": summarize_learning_by(df, "종합점수 구간") if "종합점수 구간" in df.columns else pd.DataFrame(),
        "손익비 구간별 성과": summarize_learning_by(df, "손익비 구간") if "손익비 구간" in df.columns else pd.DataFrame(),
        "진입가 이격 구간별 성과": summarize_learning_by(df, "진입가 이격 구간") if "진입가 이격 구간" in df.columns else pd.DataFrame(),
        "차트상태별 성과": summarize_learning_by(df, "pullback_state") if "pullback_state" in df.columns else pd.DataFrame(),
    }
    # save main tables for external review
    for name, table in tables.items():
        if not table.empty:
            safe_name = name.replace("/", "_").replace(" ", "_")
            table.to_csv(DATA_DIR / f"learning_{safe_name}.csv", index=False, encoding="utf-8-sig")
    return tables


def get_universe_count(market: str) -> int:
    try:
        return int(len(load_universe(market)))
    except Exception:
        return 0


def render_universe_manager(market: str):
    st.subheader("후보군 관리")
    st.caption("v1.9.8: 현재 앱이 어떤 종목을 대상으로 TOP 추천을 만드는지 확인하고, 후보군을 직접 추가/삭제할 수 있습니다.")
    info = universe_summary(market)
    u1, u2, u3, u4 = st.columns(4)
    u1.metric("후보군 수", f"{info['count']}개")
    u2.metric("섹터 수", f"{info['sectors']}개")
    u3.metric("시장", "한국" if market == "KR" else "미국")
    u4.metric("파일 수정", info.get("modified", "-"))
    st.info(f"현재 후보군 파일: {info['path']} · 전체 상장종목 전수분석이 아니라 이 후보군 안에서 1차 선별 후 정밀분석합니다.")

    df = load_universe(market)
    sector_counts = df["sector"].fillna("미분류").value_counts().reset_index()
    sector_counts.columns = ["섹터", "종목 수"]
    left, right = st.columns([1.05, 2.2])
    with left:
        st.write("#### 섹터별 후보 수")
        st.dataframe(sector_counts, use_container_width=True, hide_index=True, height=260)
        st.write("#### 후보군 추가")
        with st.form(f"add_universe_{market}"):
            new_symbol = st.text_input("종목코드/티커", placeholder="예: 005930.KS, 039030.KQ, NVDA")
            new_name_kr = st.text_input("한글명", placeholder="예: 삼성전자")
            new_name = st.text_input("영문명", placeholder="예: Samsung Electronics")
            new_sector = st.text_input("섹터", value="Custom")
            new_note = st.text_input("메모", placeholder="추가 이유 또는 확인 필요 사항")
            submitted = st.form_submit_button("후보군에 추가")
        if submitted:
            sym = normalize_candidate_symbol(new_symbol, market)
            if not sym:
                st.warning("종목코드/티커를 입력해야 합니다.")
            elif sym.upper() in df["symbol"].astype(str).str.upper().tolist():
                st.warning("이미 후보군에 있는 종목입니다.")
            else:
                add_row = {"symbol": sym, "name": new_name or sym, "name_kr": new_name_kr or sym, "sector": new_sector or "Custom", "source": "사용자추가", "note": new_note}
                df2 = pd.concat([df, pd.DataFrame([add_row])], ignore_index=True)
                save_universe(market, df2)
                st.success(f"추가 완료: {sym}")
                st.rerun()
    with right:
        st.write("#### 후보군 표")
        search_text = st.text_input("후보군 검색", placeholder="종목명, 티커, 섹터 검색", key=f"universe_search_{market}")
        view = df.copy()
        if search_text:
            q = search_text.lower().strip()
            mask = False
            for col in ["symbol", "name", "name_kr", "sector", "source", "note"]:
                mask = mask | view[col].astype(str).str.lower().str.contains(q, na=False)
            view = view[mask]
        st.dataframe(view[["symbol", "name_kr", "name", "sector", "source", "note"]].rename(columns={
            "symbol": "종목코드/티커", "name_kr": "한글명", "name": "영문명", "sector": "섹터", "source": "출처", "note": "메모"
        }), use_container_width=True, hide_index=True, height=380)
        st.write("#### 후보군 삭제")
        delete_options = [f"{r.get('symbol')} | {r.get('name_kr')} | {r.get('sector')}" for _, r in df.iterrows()]
        del_selected = st.multiselect("삭제할 종목 선택", delete_options, key=f"delete_universe_{market}")
        if st.button("선택 종목 삭제", key=f"delete_universe_btn_{market}"):
            if not del_selected:
                st.warning("삭제할 종목을 선택하세요.")
            else:
                del_symbols = [x.split("|")[0].strip() for x in del_selected]
                df2 = df[~df["symbol"].astype(str).isin(del_symbols)].copy()
                save_universe(market, df2)
                st.success(f"삭제 완료: {len(del_symbols)}개")
                st.rerun()

    with st.expander("후보군 관리 원칙", expanded=False):
        st.write("- 후보군은 전체 상장종목이 아닙니다. 앱이 분석할 1차 대상 목록입니다.")
        st.write("- 한국 코스닥 종목은 039030.KQ처럼 거래소 접미사를 직접 입력하는 것이 가장 정확합니다.")
        st.write("- 후보군을 늘릴수록 기회 포착 범위는 넓어지지만, TOP 추천 계산 시간이 길어질 수 있습니다.")
        st.write("- 실전 운용은 후보군 300~500개 → 정밀분석 30~50개 → TOP 10 구조가 목표입니다.")


def update_gate_status(market: str, horizon_days: int = 5, force: bool = False) -> dict:
    """장마감 결과 업데이트 실행 가능 여부를 판단합니다.

    원칙:
    - 한국주식: 한국 시간 평일 17:30 이후, 하루 1회
    - 미국주식: 한국 시간 화~토 06:10 이후, 하루 1회
    - 한국/미국 공휴일 전체 캘린더는 아직 반영하지 않습니다.
    """
    now = now_kst()
    today = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # Monday=0
    if market == "KR":
        time_ok = (weekday <= 4) and ((now.hour, now.minute) >= (17, 30))
        time_rule = "한국주식은 평일 17:30 이후 하루 1회 실행 권장"
    else:
        time_ok = (1 <= weekday <= 5) and ((now.hour, now.minute) >= (6, 10))
        time_rule = "미국주식은 한국시간 화~토 06:10 이후 하루 1회 실행 권장"
    log_path = DATA_DIR / "update_run_log.csv"
    already = False
    if log_path.exists():
        try:
            log_df = pd.read_csv(log_path, encoding="utf-8-sig")
            if not log_df.empty:
                mask = (
                    (log_df.get("market", "").astype(str) == str(market)) &
                    (log_df.get("run_date", "").astype(str) == today) &
                    (pd.to_numeric(log_df.get("horizon_days", 0), errors="coerce") == int(horizon_days))
                )
                already = bool(mask.any())
        except Exception:
            already = False
    allowed = bool(force or (time_ok and not already))
    if force:
        reason = "강제 재검증 모드: 시간/중복 제한을 무시하고 기존 기록을 덮어쓸 수 있습니다."
    elif already:
        reason = "오늘 같은 시장/검증기간의 장마감 결과 업데이트가 이미 실행되었습니다. 중복 학습 방지를 위해 차단합니다."
    elif not time_ok:
        reason = f"아직 권장 실행 시간이 아닙니다. {time_rule}"
    else:
        reason = "실행 가능"
    return {"allowed": allowed, "already": already, "time_ok": time_ok, "reason": reason, "time_rule": time_rule, "run_date": today}


def mark_update_run(market: str, horizon_days: int, result_count: int, force: bool = False):
    log_path = DATA_DIR / "update_run_log.csv"
    row = {
        "run_date": now_kst().strftime("%Y-%m-%d"),
        "run_at": now_kst().strftime("%Y-%m-%d %H:%M:%S"),
        "market": market,
        "horizon_days": int(horizon_days),
        "result_count": int(result_count),
        "force": bool(force),
    }
    if log_path.exists():
        old = pd.read_csv(log_path, encoding="utf-8-sig")
        df = pd.concat([old, pd.DataFrame([row])], ignore_index=True)
    else:
        df = pd.DataFrame([row])
    df = df.drop_duplicates(["run_date", "market", "horizon_days"], keep="last")
    df.to_csv(log_path, index=False, encoding="utf-8-sig")

def update_results(market: str = "KR", horizon_days: int = 5, force: bool = False) -> pd.DataFrame:
    """최근 추천 결과를 실제 가격과 비교해 학습 데이터로 저장합니다.

    v1.9 개선:
    - 단순 당일 고저가가 아니라 최근 n거래일 기준 최대상승/최대하락/종가수익률을 저장합니다.
    - 매수 후보뿐 아니라 관망/제외 후보도 기회비용과 리스크회피 여부를 기록합니다.
    - batch_id, created_at, updated_at을 누적해 주간 학습 리포트에서 요인별 검증이 가능하게 합니다.
    """
    gate = update_gate_status(market, horizon_days, force=force)
    if not gate.get("allowed"):
        return pd.DataFrame([{"outcome": "업데이트 차단", "reason": gate.get("reason", "실행 제한"), "market": market, "horizon_days": horizon_days}])
    path = DATA_DIR / f"latest_recommendations_{market}.csv"
    if not path.exists():
        return pd.DataFrame()
    rec = pd.read_csv(path, encoding="utf-8-sig")
    rows = []
    for _, r in rec.iterrows():
        sym = str(r.get("symbol", "")).strip()
        if not sym:
            continue
        period = "1mo" if horizon_days > 5 else "10d"
        df = yf_download(sym, period=period, interval="1d")
        if df.empty:
            continue
        d = df.tail(max(1, int(horizon_days))).copy()
        result = _trade_result_from_prices(r, d)
        row = {**r.to_dict(), **result}
        row["horizon_days"] = horizon_days
        row["updated_at"] = now_kst().strftime("%Y-%m-%d %H:%M:%S")
        row["market"] = market
        rows.append(row)
    result_df = pd.DataFrame(rows)
    if not result_df.empty:
        result_df = enrich_learning_results(result_df, market, horizon_days)
        out = DATA_DIR / f"results_{market}_{now_kst().strftime('%Y%m%d')}.csv"
        result_df.to_csv(out, index=False, encoding="utf-8-sig")
        append_history(result_df)
        create_failure_analysis(result_df, market)
        build_factor_learning_table()
        try:
            build_learning_summary_tables(pd.read_csv(DATA_DIR / "trade_learning_history.csv", encoding="utf-8-sig"))
        except Exception as e:
            log_error("build_learning_summary_tables", e)
        mark_update_run(market, horizon_days, len(result_df), force=force)
    return result_df


def append_history(result_df: pd.DataFrame):
    hist_path = DATA_DIR / "trade_learning_history.csv"
    if hist_path.exists():
        old = pd.read_csv(hist_path, encoding="utf-8-sig")
        all_df = pd.concat([old, result_df], ignore_index=True)
    else:
        all_df = result_df.copy()
    if "update_key" in all_df.columns:
        all_df = all_df.drop_duplicates(["update_key"], keep="last")
    else:
        key_cols = [c for c in ["market", "symbol", "batch_id", "created_at", "horizon_days"] if c in all_df.columns]
        if key_cols:
            all_df = all_df.drop_duplicates(key_cols, keep="last")
    all_df.to_csv(hist_path, index=False, encoding="utf-8-sig")


def _rate(series) -> float:
    try:
        if len(series) == 0:
            return np.nan
        return float(pd.Series(series).astype(bool).mean() * 100)
    except Exception:
        return np.nan


def build_factor_learning_table() -> pd.DataFrame:
    """점수 요인별 성과를 요약해 가중치 보정의 근거 파일을 만듭니다."""
    hist_path = DATA_DIR / "trade_learning_history.csv"
    if not hist_path.exists():
        return pd.DataFrame()
    df = pd.read_csv(hist_path, encoding="utf-8-sig")
    if df.empty:
        return pd.DataFrame()
    rows = []
    factor_cols = [
        "final_score", "attractiveness_score", "trade_fit_score", "trend_score", "chart_score",
        "indicator_score", "sector_score_component", "risk_reward", "entry_distance_pct",
        "resistance_room_pct",
    ]
    for col in factor_cols:
        if col not in df.columns:
            continue
        vals = pd.to_numeric(df[col], errors="coerce")
        if vals.notna().sum() < 5:
            continue
        try:
            q = pd.qcut(vals.rank(method="first"), 3, labels=["하위", "중위", "상위"])
        except Exception:
            continue
        for bucket in ["하위", "중위", "상위"]:
            sub = df[q == bucket]
            if sub.empty:
                continue
            target_rate = _rate(sub.get("target1_hit", pd.Series(dtype=bool))) if "target1_hit" in sub.columns else np.nan
            stop_rate = _rate(sub.get("stop_hit", pd.Series(dtype=bool))) if "stop_hit" in sub.columns else np.nan
            avg_ret = pd.to_numeric(sub.get("close_return_pct", pd.Series(dtype=float)), errors="coerce").mean()
            avg_gain = pd.to_numeric(sub.get("max_gain_pct", pd.Series(dtype=float)), errors="coerce").mean()
            avg_dd = pd.to_numeric(sub.get("max_drawdown_pct", pd.Series(dtype=float)), errors="coerce").mean()
            rows.append({
                "요인": col,
                "구간": bucket,
                "표본수": len(sub),
                "1차목표도달률(%)": round(target_rate, 2) if np.isfinite(target_rate) else np.nan,
                "손절도달률(%)": round(stop_rate, 2) if np.isfinite(stop_rate) else np.nan,
                "평균종가수익률(%)": round(avg_ret, 2) if np.isfinite(avg_ret) else np.nan,
                "평균최대상승률(%)": round(avg_gain, 2) if np.isfinite(avg_gain) else np.nan,
                "평균최대하락률(%)": round(avg_dd, 2) if np.isfinite(avg_dd) else np.nan,
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out.to_csv(DATA_DIR / "factor_learning_summary.csv", index=False, encoding="utf-8-sig")
    return out


def create_failure_analysis(df: pd.DataFrame, market: str):
    lines = []
    lines.append(f"[{now_kst().strftime('%Y-%m-%d %H:%M:%S')}] {market} 결과 분석")
    lines.append("")
    if df.empty:
        lines.append("결과 데이터 없음")
    else:
        counts = df["outcome"].value_counts().to_dict() if "outcome" in df.columns else {}
        lines.append("[결과 요약]")
        for k, v in counts.items():
            lines.append(f"- {k}: {v}건")
        lines.append("")
        lines.append("[핵심 수치]")
        for col, label in [("close_return_pct", "평균 종가수익률"), ("max_gain_pct", "평균 최대상승률"), ("max_drawdown_pct", "평균 최대하락률")]:
            if col in df.columns:
                val = pd.to_numeric(df[col], errors="coerce").mean()
                if np.isfinite(val):
                    lines.append(f"- {label}: {val:.2f}%")
        lines.append("")
        lines.append("[학습 메모]")
        if "entry_distance_pct" in df.columns:
            hi = df[pd.to_numeric(df["entry_distance_pct"], errors="coerce") > 3]
            lines.append(f"- 진입가 이격률 3% 초과 종목: {len(hi)}건. 추격매수 위험 조건 유지 여부 확인.")
        if "risk_reward" in df.columns:
            low_rr = df[pd.to_numeric(df["risk_reward"], errors="coerce") < 1.5]
            lines.append(f"- 손익비 1.5 미만 종목: {len(low_rr)}건. 손익비 필터 유효성 확인.")
        if "outcome" in df.columns:
            opp = df[df["outcome"].astype(str).str.contains("기회비용", na=False)]
            avoid = df[df["outcome"].astype(str).str.contains("리스크회피", na=False)]
            lines.append(f"- 관망 후 상승 기회비용: {len(opp)}건 / 관망으로 리스크 회피: {len(avoid)}건")
    path = REPORTS_DIR / f"failure_analysis_{market}_{now_kst().strftime('%Y%m%d')}.txt"
    path.write_text("\n".join(lines), encoding="utf-8")


def weekly_learning_report() -> Tuple[str, dict]:
    hist_path = DATA_DIR / "trade_learning_history.csv"
    if not hist_path.exists():
        text = "학습 보류: 누적 결과 데이터가 없습니다. 장마감 결과 업데이트를 먼저 실행하세요."
        path = REPORTS_DIR / f"weekly_learning_report_{now_kst().strftime('%Y_W%W')}.txt"
        path.write_text(text, encoding="utf-8")
        return text, {}
    df = pd.read_csv(hist_path, encoding="utf-8-sig")
    factor = build_factor_learning_table()
    summary_tables = build_learning_summary_tables(df)
    suggestions = []
    lines = [f"주간 학습 리포트 - {now_kst().strftime('%Y-W%W')}", ""]
    n = len(df)
    lines.append(f"검증 표본 수: {n}건")
    min_n = int(read_settings().get("min_learning_samples", 80))
    if n < min_n:
        lines.append(f"학습 보류: 최소 표본 수 {min_n}건 미만입니다. 자동 가중치 변경은 하지 않습니다.")
    if "outcome" in df.columns:
        lines.append("\n[결과 분포]")
        for k, v in df["outcome"].value_counts().items():
            lines.append(f"- {k}: {v}건")
    if "target1_hit" in df.columns:
        lines.append(f"\n전체 1차목표 도달률: {_rate(df['target1_hit']):.1f}%")
    if "stop_hit" in df.columns:
        lines.append(f"전체 손절 도달률: {_rate(df['stop_hit']):.1f}%")
    if "close_return_pct" in df.columns:
        avg_ret = pd.to_numeric(df["close_return_pct"], errors="coerce").mean()
        lines.append(f"평균 종가수익률: {avg_ret:.2f}%" if np.isfinite(avg_ret) else "평균 종가수익률: 계산 불가")
    if "entry_distance_pct" in df.columns and "target1_hit" in df.columns:
        vals = pd.to_numeric(df["entry_distance_pct"], errors="coerce")
        near = df[vals <= 2]
        far = df[vals > 3]
        if len(near) >= 5:
            near_rate = _rate(near["target1_hit"])
            lines.append(f"\n진입가 이격 2% 이하 1차목표 도달률: {near_rate:.1f}% / {len(near)}건")
        if len(far) >= 5:
            far_rate = _rate(far["target1_hit"])
            lines.append(f"진입가 이격 3% 초과 1차목표 도달률: {far_rate:.1f}% / {len(far)}건")
            if len(near) >= 5 and far_rate + 10 < near_rate:
                suggestions.append({"field": "entry_distance", "suggestion": "진입가 이격률 감점 강화", "delta": +3})
    if "risk_reward" in df.columns and "target1_hit" in df.columns:
        rr = pd.to_numeric(df["risk_reward"], errors="coerce")
        good_rr = df[rr >= 1.5]
        bad_rr = df[rr < 1.5]
        if len(good_rr) >= 5:
            lines.append(f"손익비 1.5 이상 1차목표 도달률: {_rate(good_rr['target1_hit']):.1f}% / {len(good_rr)}건")
        if len(bad_rr) >= 5:
            lines.append(f"손익비 1.5 미만 1차목표 도달률: {_rate(bad_rr['target1_hit']):.1f}% / {len(bad_rr)}건")
    if not factor.empty:
        lines.append("\n[요인별 성과 요약]")
        # 표본 수가 있는 상위 구간 중 평균수익률이 높은 요인을 간단히 표시
        tmp = factor.copy()
        tmp["평균종가수익률(%)"] = pd.to_numeric(tmp["평균종가수익률(%)"], errors="coerce")
        best = tmp[tmp["구간"].eq("상위")].sort_values("평균종가수익률(%)", ascending=False).head(5)
        for _, r in best.iterrows():
            lines.append(f"- {r['요인']} 상위구간: 표본 {int(r['표본수'])}건 / 평균종가수익률 {r['평균종가수익률(%)']}% / 1차목표 {r['1차목표도달률(%)']}%")
    if summary_tables:
        lines.append("\n[판정/실패원인 학습 요약]")
        for table_name in ["검증판정별 성과", "실패원인별 성과", "손익비 구간별 성과", "진입가 이격 구간별 성과"]:
            t = summary_tables.get(table_name, pd.DataFrame())
            if not t.empty:
                lines.append(f"- {table_name}: {len(t)}개 구간 저장")

    lines.append("\n[가중치 제안]")
    if suggestions and n >= min_n:
        for s in suggestions:
            lines.append(f"- {s['suggestion']} ({s['delta']:+})")
    elif suggestions:
        lines.append("- 표본 부족으로 자동 반영 보류. 참고 제안만 저장합니다.")
        for s in suggestions:
            lines.append(f"  · {s['suggestion']} ({s['delta']:+})")
    else:
        lines.append("- 현재 표본 기준 자동 조정 제안 없음. 손실 방지 조건은 유지.")
    text = "\n".join(lines)
    path = REPORTS_DIR / f"weekly_learning_report_{now_kst().strftime('%Y_W%W')}.txt"
    path.write_text(text, encoding="utf-8")
    sug_path = DATA_DIR / f"weight_suggestion_{now_kst().strftime('%Y_W%W')}.json"
    sug_path.write_text(json.dumps({"created_at": now_kst().isoformat(), "sample_count": n, "suggestions": suggestions, "auto_apply": False}, ensure_ascii=False, indent=2), encoding="utf-8")
    return text, {"suggestions": suggestions, "factor_summary_rows": len(factor)}



def _split_blocks(block_text: str) -> List[str]:
    if block_text is None or (isinstance(block_text, float) and pd.isna(block_text)):
        return []
    return [b.strip() for b in str(block_text).split(';') if b.strip()]


STRING_RESULT_COLUMNS = [
    'decision', 'original_decision', 'premarket_decision', 'hard_blocks', 'cautions',
    'position_reason', 'current_price_time', 'last_candle_time', 'price_refresh_at',
    'intraday_price_alert', 'intraday_action_note', 'intraday_reevaluated_at',
    'premarket_market_label', 'current_market_label', 'market_change_note',
    'pullback_state', 'leader_mode', 'name', 'name_kr', 'sector'
]


def ensure_string_columns(df: pd.DataFrame, columns: Optional[List[str]] = None) -> pd.DataFrame:
    """문자열 결과 컬럼을 object 타입으로 고정합니다.
    pandas 3.x에서는 float64 컬럼에 빈 문자열/문자열을 넣으면 TypeError가 발생할 수 있어,
    장중 재평가/현재가 갱신 전에 문자열 컬럼 타입을 미리 풀어줍니다.
    """
    columns = columns or STRING_RESULT_COLUMNS
    for col in columns:
        if col not in df.columns:
            df[col] = ''
        else:
            df[col] = df[col].astype('object')
            df[col] = df[col].where(~df[col].isna(), '')
    return df


def safe_set_cell(df: pd.DataFrame, idx, col: str, value):
    """pandas dtype 충돌을 피하면서 셀 값을 저장합니다."""
    if isinstance(value, str):
        if col not in df.columns:
            df[col] = ''
        if str(df[col].dtype) != 'object':
            df[col] = df[col].astype('object')
        df.at[idx, col] = value
    else:
        df.at[idx, col] = value


def recalculate_decision_after_price(row: pd.Series, market_info: dict, settings: dict) -> dict:
    """v1.9.8: 장중 현재가 새로고침 후 진입가 이격률/판정/권장금액을 재계산합니다.
    기존 추천 당시의 분석점수는 유지하고, 현재가 변화로 달라지는 매매 적합도만 보정합니다.
    """
    r = row.copy()
    close = safe_float(r.get('close'), np.nan)
    entry = safe_float(r.get('entry'), np.nan)
    stop = safe_float(r.get('stop'), np.nan)
    target1 = safe_float(r.get('target1'), np.nan)
    resistance1 = safe_float(r.get('resistance1'), np.nan)
    final_score = safe_float(r.get('final_score'), 0)
    trade_fit = safe_float(r.get('trade_fit_score'), 0)
    leader = str(r.get('leader_mode', 'N')) == 'Y'
    state = market_info.get('state', 'neutral')

    entry_distance_pct = ((close / entry) - 1) * 100 if np.isfinite(close) and np.isfinite(entry) and entry > 0 else np.nan
    resistance_room_pct = ((resistance1 / close) - 1) * 100 if np.isfinite(close) and np.isfinite(resistance1) and close > 0 else np.nan
    stop_pct = ((entry - stop) / entry) * 100 if np.isfinite(entry) and np.isfinite(stop) and entry > 0 else np.nan
    risk_reward = ((target1 - entry) / (entry - stop)) if np.isfinite(target1) and np.isfinite(entry) and np.isfinite(stop) and entry > stop else np.nan

    blocks = []
    cautions = []
    if state == 'risk_off':
        blocks.append('시장 위험회피')
    if np.isfinite(risk_reward) and risk_reward < 1.3:
        blocks.append('손익비 1.3 미만')
    if np.isfinite(stop_pct) and stop_pct > 8:
        blocks.append('손절폭 8% 초과')
    if np.isfinite(resistance_room_pct) and resistance_room_pct < 2:
        blocks.append('저항까지 여유 2% 미만')
    if np.isfinite(entry_distance_pct) and entry_distance_pct > 8:
        blocks.append('진입가 이격률 8% 초과')
    elif np.isfinite(entry_distance_pct) and entry_distance_pct > 3:
        cautions.append('진입가 이격률 3% 초과')

    if blocks:
        if any('시장 위험회피' in b for b in blocks):
            decision = '관망/제외'
        elif any('진입가 이격률 8%' in b for b in blocks):
            decision = '추격매수 금지'
        else:
            decision = '관망/제외'
    else:
        if leader and final_score >= 70 and np.isfinite(entry_distance_pct) and entry_distance_pct <= 8 and state in ['favorable', 'neutral', 'burden']:
            decision = '주도주 조건부 접근'
        elif np.isfinite(entry_distance_pct) and entry_distance_pct > 3:
            decision = '추격매수 금지'
        elif np.isfinite(risk_reward) and risk_reward >= 1.5 and final_score >= 75 and trade_fit >= 70 and state in ['favorable', 'neutral']:
            decision = '매수 가능'
        elif np.isfinite(resistance_room_pct) and resistance_room_pct <= 3:
            decision = '돌파 확인 필요'
        elif final_score >= 65:
            decision = '진입가 대기'
        else:
            decision = '관망/제외'

    pos = calculate_position_size(settings, market_info, entry, stop, blocks, decision, leader, str(r.get('pullback_state', '')))
    return {
        'entry_distance_pct': round(entry_distance_pct, 2) if np.isfinite(entry_distance_pct) else np.nan,
        'resistance_room_pct': round(resistance_room_pct, 2) if np.isfinite(resistance_room_pct) else np.nan,
        'risk_reward': round(risk_reward, 2) if np.isfinite(risk_reward) else np.nan,
        'decision': decision,
        'hard_blocks': '; '.join(blocks),
        'cautions': '; '.join(cautions),
        **pos,
    }


def refresh_recommendation_current_prices(market: str) -> Tuple[pd.DataFrame, str]:
    """v1.9.8: 저장된 TOP 추천의 현재가를 다시 조회하고, 현재가 기준으로 판정/권장금액을 재계산합니다."""
    rec = load_latest_recommendations(market)
    if rec.empty:
        return rec, '저장된 추천 결과가 없습니다. 먼저 TOP 추천 새로 계산을 실행하세요.'
    settings = read_settings()
    status_path = DATA_DIR / f'today_status_{market}.json'
    if status_path.exists():
        try:
            market_info = json.loads(status_path.read_text(encoding='utf-8')).get('market_info', calculate_market_state(market))
        except Exception:
            market_info = calculate_market_state(market)
    else:
        market_info = calculate_market_state(market)

    now_text = now_kst().strftime('%Y-%m-%d %H:%M:%S KST')
    if 'original_decision' not in rec.columns:
        rec['original_decision'] = rec.get('decision', '')
    if 'recommendation_close' not in rec.columns:
        rec['recommendation_close'] = rec.get('close', np.nan)
    rec = ensure_string_columns(rec)

    updated = 0
    messages = []
    for idx, r in rec.iterrows():
        sym = str(r.get('symbol', '')).strip()
        if not sym:
            continue
        try:
            df = yf_download(sym, period='5d', interval='1d')
            if df.empty:
                messages.append(f'{sym}: 현재가 조회 실패')
                continue
            new_close = safe_float(df['Close'].iloc[-1], np.nan)
            if not np.isfinite(new_close) or new_close <= 0:
                messages.append(f'{sym}: 현재가 없음')
                continue
            old_close = safe_float(rec.at[idx, 'close'], np.nan)
            rec.at[idx, 'close'] = new_close
            if np.isfinite(old_close) and old_close > 0:
                rec.at[idx, 'price_change_from_prev_pct'] = round((new_close / old_close - 1) * 100, 2)
            base_close = safe_float(rec.at[idx, 'recommendation_close'], np.nan)
            if np.isfinite(base_close) and base_close > 0:
                rec.at[idx, 'price_change_from_recommendation_pct'] = round((new_close / base_close - 1) * 100, 2)
            safe_set_cell(rec, idx, 'current_price_time', now_text)
            try:
                safe_set_cell(rec, idx, 'last_candle_time', pd.to_datetime(df['Date'].iloc[-1]).strftime('%Y-%m-%d'))
            except Exception:
                safe_set_cell(rec, idx, 'last_candle_time', '-')
            recalced = recalculate_decision_after_price(rec.loc[idx], market_info, settings)
            for k, v in recalced.items():
                safe_set_cell(rec, idx, k, v)
            updated += 1
        except Exception as e:
            log_error(f'refresh_current_price {sym}', e)
            messages.append(f'{sym}: 오류')
    rec['price_refresh_at'] = now_text
    if 'final_score' in rec.columns and 'trade_fit_score' in rec.columns:
        rec = rec.sort_values(['final_score', 'trade_fit_score'], ascending=False, na_position='last')
    out_path = DATA_DIR / f'latest_recommendations_{market}.csv'
    rec.to_csv(out_path, index=False, encoding='utf-8-sig')
    log_path = DATA_DIR / f'current_price_refresh_log_{market}.csv'
    log_row = pd.DataFrame([{'market': market, 'refreshed_at': now_text, 'updated_count': updated, 'message': '; '.join(messages[:10])}])
    if log_path.exists():
        try:
            pd.concat([pd.read_csv(log_path, encoding='utf-8-sig'), log_row], ignore_index=True).to_csv(log_path, index=False, encoding='utf-8-sig')
        except Exception:
            log_row.to_csv(log_path, index=False, encoding='utf-8-sig')
    else:
        log_row.to_csv(log_path, index=False, encoding='utf-8-sig')
    set_data_status('last_current_price_refresh_time', now_text)
    set_data_status('last_price_query_time', now_text)
    msg = f'현재가 새로고침 완료: {updated}개 종목 반영'
    if messages:
        msg += f' / 일부 실패: {len(messages)}건'
    return rec, msg



def _market_change_note(old_info: dict, new_info: dict) -> str:
    old_label = old_info.get('label', '-') if isinstance(old_info, dict) else '-'
    new_label = new_info.get('label', '-') if isinstance(new_info, dict) else '-'
    old_score = safe_float(old_info.get('score', 0), 0) if isinstance(old_info, dict) else 0
    new_score = safe_float(new_info.get('score', 0), 0) if isinstance(new_info, dict) else 0
    delta = new_score - old_score
    if old_label == new_label:
        return f'시장상태 유지: {old_label} / 점수변화 {delta:+.0f}'
    return f'시장상태 변경: {old_label} → {new_label} / 점수변화 {delta:+.0f}'


def _intraday_action_note(row: pd.Series, pre_decision: str, cur_decision: str, market_info: dict) -> str:
    dist = safe_float(row.get('entry_distance_pct'), np.nan)
    price_chg = safe_float(row.get('price_change_from_recommendation_pct'), np.nan)
    state = market_info.get('state', '') if isinstance(market_info, dict) else ''
    notes = []
    if state == 'risk_off':
        notes.append('현재 시장이 위험회피로 전환/유지되어 신규 매수는 관망 우선입니다.')
    elif state == 'burden':
        notes.append('현재 시장이 불리해져 권장금액과 매수 기준을 보수적으로 재계산했습니다.')
    if np.isfinite(price_chg) and price_chg >= 5:
        notes.append('추천 당시보다 현재가가 크게 상승해 추격매수 위험이 커졌습니다.')
    elif np.isfinite(price_chg) and price_chg <= -5:
        notes.append('추천 당시보다 현재가가 크게 하락했습니다. 눌림인지 추세 훼손인지 추가 확인이 필요합니다.')
    if np.isfinite(dist) and dist > 3:
        notes.append('현재가가 우선진입가에서 3% 이상 멀어져 즉시 진입보다 대기가 우선입니다.')
    if pre_decision != cur_decision:
        notes.append(f'장전판정이 {pre_decision}에서 현재판정 {cur_decision}으로 변경되었습니다.')
    if not notes:
        notes.append('현재가와 시장상태를 반영해도 판정 변화가 크지 않습니다.')
    return ' '.join(notes)


def intraday_reevaluate_recommendations(market: str) -> Tuple[pd.DataFrame, str]:
    """v1.9.4: 장중 시장상태를 다시 계산하고 추천 종목의 현재판정을 재평가합니다.
    장전판정/장전시장상태와 현재판정/현재시장상태를 비교해 기록합니다.
    """
    rec = load_latest_recommendations(market)
    if rec.empty:
        return rec, '저장된 추천 결과가 없습니다. 먼저 TOP 추천 새로 계산을 실행하세요.'
    settings = read_settings()
    status_path = DATA_DIR / f'today_status_{market}.json'
    if status_path.exists():
        try:
            status = json.loads(status_path.read_text(encoding='utf-8'))
        except Exception:
            status = {}
    else:
        status = {}
    pre_market_info = status.get('market_info', calculate_market_state(market))
    current_market_info = calculate_market_state(market)
    save_market_state_log(current_market_info)
    now_text = now_kst().strftime('%Y-%m-%d %H:%M:%S KST')

    if 'original_decision' not in rec.columns:
        rec['original_decision'] = rec.get('decision', '')
    if 'premarket_decision' not in rec.columns:
        rec['premarket_decision'] = rec.get('original_decision', rec.get('decision', ''))
    if 'recommendation_close' not in rec.columns:
        rec['recommendation_close'] = rec.get('close', np.nan)
    rec = ensure_string_columns(rec)

    updated = 0
    changed = 0
    for idx, r in rec.iterrows():
        sym = str(r.get('symbol', '')).strip()
        if not sym:
            continue
        pre_decision = str(rec.at[idx, 'premarket_decision']) if 'premarket_decision' in rec.columns else str(r.get('decision', '-'))
        try:
            df = yf_download(sym, period='5d', interval='1d')
            if not df.empty:
                new_close = safe_float(df['Close'].iloc[-1], np.nan)
                if np.isfinite(new_close) and new_close > 0:
                    old_close = safe_float(rec.at[idx, 'close'], np.nan)
                    rec.at[idx, 'close'] = new_close
                    if np.isfinite(old_close) and old_close > 0:
                        rec.at[idx, 'price_change_from_prev_pct'] = round((new_close / old_close - 1) * 100, 2)
                    base_close = safe_float(rec.at[idx, 'recommendation_close'], np.nan)
                    if np.isfinite(base_close) and base_close > 0:
                        rec.at[idx, 'price_change_from_recommendation_pct'] = round((new_close / base_close - 1) * 100, 2)
                    safe_set_cell(rec, idx, 'current_price_time', now_text)
                    try:
                        safe_set_cell(rec, idx, 'last_candle_time', pd.to_datetime(df['Date'].iloc[-1]).strftime('%Y-%m-%d'))
                    except Exception:
                        safe_set_cell(rec, idx, 'last_candle_time', '-')
        except Exception as e:
            log_error(f'intraday_reevaluate price {sym}', e)
        recalced = recalculate_decision_after_price(rec.loc[idx], current_market_info, settings)
        cur_decision = str(recalced.get('decision', rec.at[idx, 'decision'] if 'decision' in rec.columns else '-'))
        if pre_decision != cur_decision:
            changed += 1
        for k, v in recalced.items():
            safe_set_cell(rec, idx, k, v)
        # 장중 급등/급락에 따른 차트상태 보조 표시
        price_chg = safe_float(rec.at[idx, 'price_change_from_recommendation_pct'], np.nan) if 'price_change_from_recommendation_pct' in rec.columns else np.nan
        if np.isfinite(price_chg) and price_chg >= 5:
            safe_set_cell(rec, idx, 'intraday_price_alert', '장중 급등/추격주의')
            if cur_decision not in ['관망/제외']:
                safe_set_cell(rec, idx, 'pullback_state', '추격매수 위험')
        elif np.isfinite(price_chg) and price_chg <= -5:
            safe_set_cell(rec, idx, 'intraday_price_alert', '장중 급락/눌림 또는 훼손 확인')
        else:
            safe_set_cell(rec, idx, 'intraday_price_alert', '변동 제한')
        safe_set_cell(rec, idx, 'intraday_action_note', _intraday_action_note(rec.loc[idx], pre_decision, cur_decision, current_market_info))
        safe_set_cell(rec, idx, 'intraday_reevaluated_at', now_text)
        safe_set_cell(rec, idx, 'premarket_market_label', pre_market_info.get('label', '-'))
        safe_set_cell(rec, idx, 'current_market_label', current_market_info.get('label', '-'))
        safe_set_cell(rec, idx, 'market_change_note', _market_change_note(pre_market_info, current_market_info))
        updated += 1

    rec['price_refresh_at'] = now_text
    if 'final_score' in rec.columns and 'trade_fit_score' in rec.columns:
        rec = rec.sort_values(['final_score', 'trade_fit_score'], ascending=False, na_position='last')
    out_path = DATA_DIR / f'latest_recommendations_{market}.csv'
    rec.to_csv(out_path, index=False, encoding='utf-8-sig')
    status['current_market_info'] = current_market_info
    status['intraday_reevaluated_at'] = now_text
    status['market_change_note'] = _market_change_note(pre_market_info, current_market_info)
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding='utf-8')
    log_path = DATA_DIR / f'intraday_reevaluation_log_{market}.csv'
    log_row = pd.DataFrame([{
        'market': market,
        'reevaluated_at': now_text,
        'updated_count': updated,
        'changed_decision_count': changed,
        'premarket_label': pre_market_info.get('label', '-'),
        'current_label': current_market_info.get('label', '-'),
        'note': _market_change_note(pre_market_info, current_market_info),
    }])
    if log_path.exists():
        try:
            pd.concat([pd.read_csv(log_path, encoding='utf-8-sig'), log_row], ignore_index=True).to_csv(log_path, index=False, encoding='utf-8-sig')
        except Exception:
            log_row.to_csv(log_path, index=False, encoding='utf-8-sig')
    else:
        log_row.to_csv(log_path, index=False, encoding='utf-8-sig')
    set_data_status('last_current_price_refresh_time', now_text)
    set_data_status('last_price_query_time', now_text)
    return rec, f'장중 재평가 완료: {updated}개 종목 / 판정 변경 {changed}개 / {_market_change_note(pre_market_info, current_market_info)}'

def load_latest_recommendations(market: str) -> pd.DataFrame:
    path = DATA_DIR / f"latest_recommendations_{market}.csv"
    if path.exists():
        try:
            return pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def render_score_bar(label: str, value: float, max_value: float = 100.0):
    if st is None:
        return
    pct = max(0, min(100, value / max_value * 100))
    st.progress(int(pct), text=f"{label}: {value:.1f}/{max_value:.0f}")


def format_krw(x: float) -> str:
    try:
        x = float(x)
        if abs(x) >= 100_000_000:
            return f"{x/100_000_000:.1f}억 원"
        if abs(x) >= 10_000:
            return f"{x/10_000:,.0f}만 원"
        return f"{x:,.0f}원"
    except Exception:
        return "-"




def format_percent(x: float) -> str:
    try:
        return f"{float(x):+.2f}%"
    except Exception:
        return "-"


def korean_market_rows(rows: list) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns={"indicator": "지표", "symbol": "티커", "change_pct": "등락률(%)", "direction": "영향", "score": "점수", "weight": "가중치", "role": "판단역할"})
    if "영향" in df.columns:
        df["영향"] = df["영향"].map(DIRECTION_KR).fillna(df["영향"])
    return df



def korean_market_internals_df(internals: dict) -> pd.DataFrame:
    if not isinstance(internals, dict) or not internals.get('available'):
        return pd.DataFrame([{"항목": "후보군 내부강도", "값": "계산 불가", "해석": internals.get('note', '-') if isinstance(internals, dict) else '-'}])
    rows = [
        {"항목": "유효 표본", "값": f"{internals.get('valid_count', 0)}개", "해석": "후보군 중 데이터 조회 성공 종목"},
        {"항목": "상승/하락", "값": f"{internals.get('up_count', 0)} / {internals.get('down_count', 0)}", "해석": "상승 종목 수와 하락 종목 수"},
        {"항목": "상승비율", "값": f"{internals.get('positive_ratio', 0)}%", "해석": "시장 폭, 체감 강도"},
        {"항목": "평균등락률", "값": f"{internals.get('avg_change_pct', 0)}%", "해석": "후보군 평균 흐름"},
        {"항목": "중앙등락률", "값": f"{internals.get('median_change_pct', 0)}%", "해석": "극단값을 줄인 체감 흐름"},
        {"항목": "거래량비율", "값": f"{internals.get('avg_volume_ratio', '-')}", "해석": "최근 거래량/20일 평균 거래량"},
        {"항목": "20일 고점 근접", "값": f"{internals.get('near_high_ratio', 0)}%", "해석": "강한 종목 비율"},
        {"항목": "20일 저점 근접", "값": f"{internals.get('near_low_ratio', 0)}%", "해석": "약한 종목 비율"},
        {"항목": "내부강도 점수", "값": f"{internals.get('score', 0)}", "해석": internals.get('note', '-')},
    ]
    return pd.DataFrame(rows)


def korean_sector_internals_df(sector_internals: dict) -> pd.DataFrame:
    if not isinstance(sector_internals, dict) or not sector_internals.get('available'):
        return pd.DataFrame([{"섹터": "계산 불가", "해석": sector_internals.get('note', '-') if isinstance(sector_internals, dict) else '-'}])
    rows = sector_internals.get('rows', []) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df['섹터'] = df['sector'].map(sector_kr).fillna(df['sector'])
    df = df.rename(columns={
        'valid_count': '표본수',
        'up_count': '상승',
        'down_count': '하락',
        'positive_ratio': '상승비율(%)',
        'avg_change_pct': '평균등락률(%)',
        'median_change_pct': '중앙등락률(%)',
        'avg_volume_ratio': '거래량비율',
        'near_high_ratio': '20일고점근접(%)',
        'near_low_ratio': '20일저점근접(%)',
        'sector_internal_score': '섹터내부점수',
        'label': '판정',
    })
    use = ['섹터','표본수','상승','하락','상승비율(%)','평균등락률(%)','거래량비율','20일고점근접(%)','20일저점근접(%)','섹터내부점수','판정']
    return df[[c for c in use if c in df.columns]]


def korean_risk_rules_df(market_info: dict) -> pd.DataFrame:
    rules = market_info.get('risk_rules', []) if isinstance(market_info, dict) else []
    if not rules:
        return pd.DataFrame()
    return pd.DataFrame([{'번호': i+1, '적용 규칙': r} for i, r in enumerate(rules)])


def korean_score_breakdown_df(market_info: dict) -> pd.DataFrame:
    bd = market_info.get('score_breakdown', {}) if isinstance(market_info, dict) else {}
    if not bd:
        return pd.DataFrame()
    return pd.DataFrame([{"구분": k, "점수": v} for k, v in bd.items()])

def korean_sector_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["섹터"] = out["sector"].map(sector_kr)
    out = out.rename(columns={"avg_change_pct": "평균등락률(%)", "sector_score": "섹터점수"})
    return out[["섹터", "평균등락률(%)", "섹터점수"]]


def korean_recommendation_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = {
        "name_kr": "종목명", "symbol": "티커", "sector": "섹터", "final_score": "종합점수",
        "original_decision": "장전판정", "decision": "현재판정", "pullback_state": "차트상태", "leader_mode": "주도주",
        "risk_reward": "손익비", "entry_distance_pct": "진입가이격률(%)", "price_change_from_recommendation_pct": "추천가대비(%)", "hard_blocks": "매수금지사유",
        "recommended_amount": "권장금액", "current_price_time": "현재가조회"
    }
    use = [c for c in cols if c in df.columns]
    out = df[use].rename(columns=cols).copy()
    if "섹터" in out.columns:
        out["섹터"] = out["섹터"].map(sector_kr).fillna(out["섹터"])
    if "주도주" in out.columns:
        out["주도주"] = out["주도주"].map({"Y": "예", "N": "아니오"}).fillna(out["주도주"])
    if "권장금액" in out.columns:
        out["권장금액"] = out["권장금액"].apply(format_krw)
    return out


def fetch_market_news(market: str, limit: int = 20) -> pd.DataFrame:
    """무료 RSS 기준 시장 뉴스/속보를 가져온다. 원문 API가 아니므로 누락 가능성이 있다."""
    if feedparser is None:
        return pd.DataFrame()
    query = (
        "한국증시 OR 코스피 OR 코스닥 OR 원달러 OR 반도체 OR 조선 OR 방산 OR 2차전지"
        if market == "KR"
        else "미국증시 OR 나스닥 OR S&P500 OR 엔비디아 OR 반도체 OR 금리 OR 연준 OR CPI"
    )
    url = f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ko&gl=KR&ceid=KR:ko"
    rows = []
    try:
        set_data_status("last_news_query_time", now_kst().strftime("%Y-%m-%d %H:%M:%S KST"))
        feed = feedparser.parse(url)
        for e in feed.entries[:limit]:
            title = str(getattr(e, 'title', '')).strip()
            source = getattr(getattr(e, 'source', None), 'title', '') or '구글뉴스'
            published = str(getattr(e, 'published', ''))
            link = str(getattr(e, 'link', ''))
            text = title.lower()
            importance = '중간'
            impact = '중립/변동성'
            if any(k in title for k in ['급락','폭락','전쟁','관세','금리 급등','악재','하락','위험']):
                impact = '부담'; importance = '높음'
            elif any(k in title for k in ['급등','호재','수주','실적 개선','상승','투자','AI','반도체']):
                impact = '우호'; importance = '중간'
            if any(k in title for k in ['연준','금리','CPI','PPI','PCE','고용','유가','환율','관세','전쟁','실적']):
                importance = '높음'
            rows.append({'중요도': importance, '영향방향': impact, '제목': title, '출처': source, '시간': published, '링크': link})
    except Exception as e:
        log_error('fetch_market_news', e)
    return pd.DataFrame(rows)



def _format_price(v: float) -> str:
    try:
        if not np.isfinite(float(v)):
            return "-"
        return f"{float(v):,.2f}"
    except Exception:
        return "-"



def format_compact_number(v, suffix="") -> str:
    """큰 숫자를 한국식 조/억 단위로 압축 표기."""
    try:
        x = float(v)
        if not np.isfinite(x):
            return "-"
        sign = "-" if x < 0 else ""
        x = abs(x)
        if x >= 1_0000_0000_0000:
            return f"{sign}{x/1_0000_0000_0000:,.2f}조{suffix}"
        if x >= 1_0000_0000:
            return f"{sign}{x/1_0000_0000:,.1f}억{suffix}"
        if x >= 1_0000:
            return f"{sign}{x/1_0000:,.1f}만{suffix}"
        return f"{sign}{x:,.2f}{suffix}"
    except Exception:
        return "-"


def format_ratio(v, suffix="%") -> str:
    try:
        x = float(v)
        if not np.isfinite(x):
            return "-"
        return f"{x:,.2f}{suffix}"
    except Exception:
        return "-"


def _quarter_label(dt) -> str:
    try:
        d = pd.to_datetime(dt)
        return f"{str(d.year)[2:]}년 {((d.month-1)//3)+1}Q"
    except Exception:
        return str(dt)


def get_recommendation_created_at(market: str) -> str:
    try:
        status_path = DATA_DIR / f"today_status_{market}.json"
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            return str(status.get("created_at", "-"))
        path = DATA_DIR / f"latest_recommendations_{market}.csv"
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime, KST).strftime("%Y-%m-%d %H:%M:%S KST")
    except Exception:
        pass
    return "-"


def render_data_status_board(market: str, target=None):
    """앱 시간과 추천/뉴스/재무/주가 데이터 기준 시각을 상단 우측 상태판에 표시.
    v1.8.5: 큰 카드형 대신 얇은 상태바 + 상세 카드 형태로 축소하고, session_state 기준으로 값을 읽습니다.
    """
    now_text = now_kst().strftime("%Y-%m-%d %H:%M:%S KST")
    rec_time = get_recommendation_created_at(market)
    price_time = get_data_status("last_price_query_time", "차트 조회 전")
    candle_time = get_data_status("last_candle_time", "차트 조회 전")
    news_time = get_data_status("last_news_query_time", "뉴스 조회 전")
    fin_time = get_data_status("last_financial_query_time", "재무 조회 전")
    render_obj = target if target is not None else st
    st.markdown("""
    <style>
    .dh-status-box{border:1px solid #ff4b4b;border-radius:8px;padding:8px 10px;background:#fffafa;margin-top:4px;}
    .dh-status-title{font-weight:700;color:#d62728;margin-bottom:5px;font-size:13px;}
    .dh-status-summary{font-size:12px;color:#111827;font-weight:700;margin-bottom:6px;line-height:1.35;}
    .dh-status-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;}
    .dh-status-item{background:#ffffff;border:1px solid #eee;border-radius:6px;padding:5px 7px;min-height:45px;}
    .dh-status-label{font-size:10px;color:#667085;margin-bottom:2px;}
    .dh-status-value{font-size:12px;font-weight:700;color:#111827;line-height:1.2;word-break:keep-all;}
    .dh-status-caption{font-size:10px;color:#777;margin-top:6px;}
    </style>
    """, unsafe_allow_html=True)
    items = [
        ("현재 앱 시간", now_text),
        ("추천 생성 시각", rec_time),
        ("주가 조회 시각", price_time),
        ("마지막 캔들", candle_time),
        ("뉴스 수집 시각", news_time),
        ("재무 조회 시각", fin_time),
    ]
    current_refresh_time = get_data_status("last_current_price_refresh_time", price_time)
    html = f'<div class="dh-status-box"><div class="dh-status-title">데이터 최신화 상태</div><div class="dh-status-summary">현재 {now_text} | 추천 {rec_time} | 현재가 {current_refresh_time} | 주가 {price_time} | 뉴스 {news_time} | 재무 {fin_time}</div><div class="dh-status-grid">'
    for label, value in items:
        html += f'<div class="dh-status-item"><div class="dh-status-label">{label}</div><div class="dh-status-value">{value}</div></div>'
    html += '</div><div class="dh-status-caption">무료 공개 데이터 기준입니다. 주가·뉴스·재무 데이터는 지연 또는 누락될 수 있으며, 실제 주문 전 증권사 앱에서 현재가와 호가를 반드시 재확인하세요.</div></div>'
    render_obj.markdown(html, unsafe_allow_html=True)

def _financial_rows(symbol: str) -> list:
    """핵심 지표와 최근 분기 실적을 좁은 우측 패널용 2열 표로 생성."""
    rows = []
    try:
        info = _load_ticker_info(symbol)
        set_data_status("last_financial_query_time", now_kst().strftime("%Y-%m-%d %H:%M:%S KST"))
        # v1.8.2: 우측 핵심 투자지표는 사용자가 요청한 핵심 8개만 표시합니다.
        rows.extend([
            ("시가총액", data_limit_text(format_compact_number(info.get("marketCap"), "원"))),
            ("PER", data_limit_text(format_ratio(info.get("trailingPE"), "배"))),
            ("PBR", data_limit_text(format_ratio(info.get("priceToBook"), "배"))),
            ("PSR", data_limit_text(format_ratio(info.get("priceToSalesTrailing12Months"), "배"))),
            ("EPS", data_limit_text(format_compact_number(info.get("trailingEps"), ""))),
            ("BPS", data_limit_text(format_compact_number(info.get("bookValue"), ""))),
            ("ROE", data_limit_text(format_ratio(safe_float(info.get("returnOnEquity"), np.nan) * 100, "%") if np.isfinite(safe_float(info.get("returnOnEquity"), np.nan)) else "무료 데이터 제한")),
            ("영업이익률", data_limit_text(format_ratio(safe_float(info.get("operatingMargins"), np.nan) * 100, "%") if np.isfinite(safe_float(info.get("operatingMargins"), np.nan)) else "무료 데이터 제한")),
            ("─", "최근 4개 분기"),
        ])
        t = yf.Ticker(symbol)
        qfin = getattr(t, "quarterly_financials", pd.DataFrame())
        if qfin is not None and not qfin.empty:
            # yfinance는 보통 최신 분기가 왼쪽에 오므로 최신 4개만 사용
            cols = list(qfin.columns)[:4]
            for c in cols:
                rev = np.nan; op = np.nan; net = np.nan
                for nm in ["Total Revenue", "Operating Revenue", "Revenue"]:
                    if nm in qfin.index:
                        rev = safe_float(qfin.loc[nm, c], np.nan); break
                for nm in ["Operating Income", "Operating Income or Loss"]:
                    if nm in qfin.index:
                        op = safe_float(qfin.loc[nm, c], np.nan); break
                for nm in ["Net Income", "Net Income Common Stockholders"]:
                    if nm in qfin.index:
                        net = safe_float(qfin.loc[nm, c], np.nan); break
                opm = op / rev * 100 if np.isfinite(op) and np.isfinite(rev) and rev != 0 else np.nan
                rows.append((_quarter_label(c), f"매출 {format_compact_number(rev, '원')}"))
                rows.append((" ", f"영업익 {format_compact_number(op, '원')} / 순익 {format_compact_number(net, '원')}"))
                rows.append((" ", f"영업이익률 {format_ratio(opm, '%')}"))
        else:
            rows.append(("분기실적", "무료 데이터 없음"))
        rows.extend([
            ("─", "컨센서스"),
            ("예상매출", format_compact_number(info.get("revenueEstimate"), "원") if info.get("revenueEstimate") else "무료 데이터 제한"),
            ("예상영업익", "무료 데이터 제한"),
            ("실적발표일", str(info.get("earningsTimestampStart", "-"))),
        ])
    except Exception as e:
        log_error(f"_financial_rows {symbol}", e)
        rows.append(("재무 데이터", "불러오기 실패"))
    return rows


def _financial_table_trace(symbol: str):
    rows = _financial_rows(symbol)
    if not rows:
        rows = [("재무 데이터", "없음")]
    left = [r[0] for r in rows]
    right = [r[1] for r in rows]
    return go.Table(
        header=dict(values=["핵심 항목", "값"], fill_color="#111827", font=dict(color="#f9fafb", size=12), align="left", height=24),
        cells=dict(values=[left, right], fill_color="#0b1220", font=dict(color="#e5e7eb", size=10), align="left", height=22),
        columnwidth=[0.38, 0.62],
        name="핵심지표"
    )



def render_fundamental_side_panel(symbol: str):
    """차트 우측 고정 패널: 핵심 투자지표/최근 분기 실적.
    Plotly 내부 테이블이 아니라 Streamlit 표로 렌더링해 차트 오류를 방지합니다.
    """
    try:
        rows = _financial_rows(symbol)
        st.markdown("#### 핵심 투자지표")
        if not rows:
            st.info("무료 데이터에서 핵심 재무지표를 제공하지 않습니다.")
            return
        # 핵심지표와 분기실적을 나눠 표시
        key_rows = []
        quarter_rows = []
        mode = "key"
        for k, v in rows:
            if k == "─" and "최근" in str(v):
                mode = "quarter"
                continue
            if k == "─" and "컨센서스" in str(v):
                # 컨센서스는 우측 패널의 가독성을 위해 최근 분기 요약 하단에 축약 표시
                mode = "quarter"
                continue
            if mode == "key":
                key_rows.append({"항목": k, "값": v})
            else:
                quarter_rows.append({"항목": k, "값": v})
        if key_rows:
            st.dataframe(pd.DataFrame(key_rows), use_container_width=True, hide_index=True, height=285)
        st.markdown("#### 최근 분기 요약")
        if quarter_rows:
            st.dataframe(pd.DataFrame(quarter_rows), use_container_width=True, hide_index=True, height=220)
        else:
            st.caption("분기 실적 데이터가 부족하거나 무료 데이터에서 제공되지 않습니다.")
        st.caption("무료 공개 데이터 기준입니다. 실제 주문 전 증권사 앱/공시에서 재확인하세요.")
    except Exception as e:
        log_error(f"render_fundamental_side_panel {symbol}", e)
        st.warning("핵심 투자지표를 표시하지 못했습니다.")


def _period_to_yf(label: str) -> str:
    return {
        "3개월": "3mo",
        "6개월": "6mo",
        "1년": "1y",
        "2년": "2y",
        "5년": "5y",
    }.get(label, "1y")


def _interval_to_yf(label: str) -> str:
    return {
        "일봉": "1d",
        "주봉": "1wk",
        "월봉": "1mo",
    }.get(label, "1d")


def _volume_profile(df: pd.DataFrame, bins: int = 18) -> pd.DataFrame:
    """가격대별 거래량. 토스/트레이딩뷰식 매물대의 간이 구현."""
    try:
        d = df.dropna(subset=["Close", "Volume"]).copy()
        if len(d) < 5:
            return pd.DataFrame(columns=["가격대", "거래량"])
        prices = d["Close"].astype(float)
        vols = d["Volume"].astype(float)
        lo, hi = float(prices.min()), float(prices.max())
        if hi <= lo:
            return pd.DataFrame(columns=["가격대", "거래량"])
        edges = np.linspace(lo, hi, bins + 1)
        cats = pd.cut(prices, bins=edges, include_lowest=True)
        grouped = vols.groupby(cats, observed=False).sum()
        mids = [(iv.left + iv.right) / 2 for iv in grouped.index]
        out = pd.DataFrame({"가격대": mids, "거래량": grouped.values})
        return out.dropna()
    except Exception:
        return pd.DataFrame(columns=["가격대", "거래량"])


def make_price_chart(symbol: str, levels: Optional[dict] = None, period_label: str = "1년", interval_label: str = "일봉", show_ma: bool = True, show_volume_profile: bool = True, show_macd: bool = True, show_rsi: bool = True):
    """토스증권에 가깝게 보는 한글형 인터랙티브 차트.
    - OHLC hover
    - 이동평균선
    - 거래량
    - MACD/RSI
    - 매물대
    - 진입/손절/목표가 라인
    """
    if go is None or make_subplots is None:
        return None
    period = _period_to_yf(period_label)
    interval = _interval_to_yf(interval_label)
    df = yf_download(symbol, period=period, interval=interval)
    if df.empty:
        return None
    df = add_indicators(df)
    df["Date"] = pd.to_datetime(df["Date"])
    set_data_status("last_price_query_time", now_kst().strftime("%Y-%m-%d %H:%M:%S KST"))
    try:
        set_data_status("last_candle_time", pd.to_datetime(df["Date"].iloc[-1]).strftime("%Y-%m-%d"))
    except Exception:
        set_data_status("last_candle_time", "-")

    # v1.6: 휴장일/주말 공백 제거용 rangebreaks 생성
    # Plotly 날짜축은 실제 거래가 없는 날짜도 빈칸으로 벌어질 수 있습니다.
    # 일봉에서는 데이터에 없는 날짜를 축에서 제거해 토스증권처럼 캔들을 자연스럽게 붙입니다.
    rangebreaks = []
    try:
        if interval_label == "일봉" and len(df) >= 2:
            start_d = df["Date"].min().normalize()
            end_d = df["Date"].max().normalize()
            all_days = pd.date_range(start_d, end_d, freq="D")
            trading_days = set(df["Date"].dt.normalize())
            missing_days = [d for d in all_days if d not in trading_days]
            if missing_days:
                rangebreaks = [dict(values=missing_days)]
    except Exception:
        rangebreaks = []

    # 표시 행 구성: 가격/거래량/MACD/RSI
    rows = 2 + int(show_macd) + int(show_rsi)
    row_heights = [0.56, 0.18]
    if show_macd: row_heights.append(0.15)
    if show_rsi: row_heights.append(0.11)
    # v1.8.1: 매물대는 가격 차트 우측 상단에만 고정합니다.
    # 핵심 펀더멘털 표는 Plotly subplot 안에 넣지 않고 Streamlit 우측 패널로 분리합니다.
    # 이유: Plotly table subplot과 hline/shape가 충돌해 Invalid property zaxis 오류가 발생할 수 있기 때문입니다.
    specs = [[{"type": "xy"}, {"type": "xy"}]]
    for _ in range(2, rows + 1):
        specs.append([{"type": "xy"}, None])

    fig = make_subplots(
        rows=rows,
        cols=2,
        shared_xaxes=True,
        vertical_spacing=0.025,
        horizontal_spacing=0.015,
        row_heights=row_heights,
        column_widths=[0.86, 0.14],
        specs=specs,
    )

    hover = []
    for _, r in df.iterrows():
        hover.append(
            f"날짜: {pd.to_datetime(r['Date']).strftime('%Y-%m-%d')}<br>"
            f"시가: {_format_price(r['Open'])}<br>"
            f"고가: {_format_price(r['High'])}<br>"
            f"저가: {_format_price(r['Low'])}<br>"
            f"종가: {_format_price(r['Close'])}<br>"
            f"거래량: {safe_float(r['Volume'],0):,.0f}"
        )

    fig.add_trace(
        go.Candlestick(
            x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"],
            name="캔들", text=hover, hoverinfo="text",
            increasing_line_color="#ef4444", increasing_fillcolor="#ef4444",
            decreasing_line_color="#3b82f6", decreasing_fillcolor="#3b82f6",
        ), row=1, col=1
    )

    if show_ma:
        ma_specs = [(5, "이평5"), (20, "이평20"), (60, "이평60"), (120, "이평120"), (200, "이평200")]
        for ma, name in ma_specs:
            col = f"MA{ma}"
            if col in df.columns:
                fig.add_trace(go.Scatter(x=df["Date"], y=df[col], mode="lines", name=name, line=dict(width=1.2), hovertemplate=f"{name}: %{{y:,.2f}}<extra></extra>"), row=1, col=1)

    # 가격 기준선
    if levels is not None:
        level_specs = [("entry", "우선진입가", "#22c55e"), ("stop", "손절가", "#ef4444"), ("target1", "1차목표가", "#f59e0b"), ("target2", "2차목표가", "#f97316")]
        x0, x1 = df["Date"].iloc[0], df["Date"].iloc[-1]
        for key, label, color in level_specs:
            val = safe_float(levels.get(key), np.nan)
            if np.isfinite(val) and val > 0:
                fig.add_trace(go.Scatter(x=[x0, x1], y=[val, val], mode="lines", name=label, line=dict(color=color, width=1.2, dash="dot"), hovertemplate=f"{label}: %{{y:,.2f}}<extra></extra>"), row=1, col=1)

    # 현재가 점선
    last_close = safe_float(df["Close"].iloc[-1], np.nan)
    if np.isfinite(last_close):
        fig.add_trace(go.Scatter(x=[df["Date"].iloc[0], df["Date"].iloc[-1]], y=[last_close, last_close], mode="lines", name="현재가", line=dict(width=1, dash="dash"), hovertemplate="현재가: %{y:,.2f}<extra></extra>"), row=1, col=1)

    # 매물대
    if show_volume_profile:
        vp = _volume_profile(df, bins=18)
        if not vp.empty:
            maxv = float(vp["거래량"].max()) or 1.0
            fig.add_trace(go.Bar(x=vp["거래량"] / maxv * 100, y=vp["가격대"], orientation="h", name="매물대", marker=dict(opacity=0.45), hovertemplate="가격대: %{y:,.2f}<br>상대 매물: %{x:.1f}%<extra></extra>"), row=1, col=2)

    # 거래량: 상승/하락별 색
    vol_colors = np.where(df["Close"] >= df["Open"], "#ef4444", "#3b82f6")
    fig.add_trace(go.Bar(x=df["Date"], y=df["Volume"], name="거래량", marker_color=vol_colors, opacity=0.75, hovertemplate="날짜: %{x|%Y-%m-%d}<br>거래량: %{y:,.0f}<extra></extra>"), row=2, col=1)
    if "VOL_MA20" in df.columns:
        fig.add_trace(go.Scatter(x=df["Date"], y=df["VOL_MA20"], mode="lines", name="거래량20", line=dict(width=1.2), hovertemplate="거래량20: %{y:,.0f}<extra></extra>"), row=2, col=1)

    current_row = 3
    if show_macd:
        hist = df["MACD"] - df["MACD_SIGNAL"]
        hist_colors = np.where(hist >= 0, "#ef4444", "#3b82f6")
        fig.add_trace(go.Bar(x=df["Date"], y=hist, name="MACD 막대", marker_color=hist_colors, opacity=0.55, hovertemplate="MACD 막대: %{y:,.2f}<extra></extra>"), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=df["Date"], y=df["MACD"], mode="lines", name="MACD", line=dict(width=1.2), hovertemplate="MACD: %{y:,.2f}<extra></extra>"), row=current_row, col=1)
        fig.add_trace(go.Scatter(x=df["Date"], y=df["MACD_SIGNAL"], mode="lines", name="신호선", line=dict(width=1.2), hovertemplate="신호선: %{y:,.2f}<extra></extra>"), row=current_row, col=1)
        current_row += 1
    if show_rsi:
        fig.add_trace(go.Scatter(x=df["Date"], y=df["RSI"], mode="lines", name="RSI14", line=dict(width=1.3), hovertemplate="RSI14: %{y:,.1f}<extra></extra>"), row=current_row, col=1)
        fig.add_hline(y=70, line_dash="dot", opacity=0.35, row=current_row, col=1)
        fig.add_hline(y=50, line_dash="dot", opacity=0.25, row=current_row, col=1)
        fig.add_hline(y=30, line_dash="dot", opacity=0.35, row=current_row, col=1)
        fig.update_yaxes(range=[0, 100], row=current_row, col=1)

    # 축/날짜/레이아웃 한글화
    fig.update_yaxes(title_text="가격", side="right", row=1, col=1)
    # v1.8.2: 매물대는 주가 가격축과 같은 y축 범위를 사용합니다.
    # 주가를 가격축 기준으로 확대/축소하면 매물대도 같은 가격대에 맞춰 보입니다.
    fig.update_yaxes(title_text="매물대", showticklabels=False, matches="y", row=1, col=2)
    fig.update_yaxes(title_text="거래량", row=2, col=1)

    # v1.5: 주가/거래량/MACD/RSI의 날짜축을 하나로 강제 연결합니다.
    # 가격 차트를 확대/이동하면 밑의 거래량·보조지표도 같은 날짜 구간으로 함께 움직입니다.
    for _r in range(1, rows + 1):
        fig.update_xaxes(
            matches="x",
            rangeslider_visible=False,
            showgrid=True,
            tickformat="%Y-%m-%d",
            hoverformat="%Y-%m-%d",
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikedash="dot",
            spikecolor="#94a3b8",
            rangebreaks=rangebreaks,
            row=_r,
            col=1,
        )
        if _r != rows:
            fig.update_xaxes(showticklabels=False, row=_r, col=1)

    # 매물대는 날짜축이 아니라 가격축 기준 보조 영역입니다.
    # x축은 고정하되 y축은 주가 가격축과 매칭해 캔들 가격대와 1:1로 대응되게 합니다.
    fig.update_xaxes(
        fixedrange=True,
        showgrid=False,
        showticklabels=False,
        title_text="",
        row=1,
        col=2,
    )
    # 우측 하단은 표 패널로 사용합니다. 날짜축과 연결하지 않습니다.

    # 차트 영역과 매물대/펀더멘털 영역을 시각적으로 분리하는 세로 경계선입니다.
    # 캔들/거래량/MACD/RSI가 매물대 영역까지 넘어가 보이지 않게 구분합니다.
    fig.add_shape(
        type="line", xref="paper", yref="paper",
        x0=0.855, x1=0.855, y0=0, y1=1,
        line=dict(color="#64748b", width=1, dash="dot"),
        layer="above"
    )

    # 날짜 선택 버튼은 하나만 두고, 모든 날짜 기반 보조지표에 같은 범위를 적용합니다.
    fig.update_xaxes(
        rangeselector=dict(
            buttons=list([
                dict(count=1, label="1개월", step="month", stepmode="backward"),
                dict(count=3, label="3개월", step="month", stepmode="backward"),
                dict(count=6, label="6개월", step="month", stepmode="backward"),
                dict(count=1, label="1년", step="year", stepmode="backward"),
                dict(step="all", label="전체"),
            ]),
            bgcolor="#111827",
            activecolor="#ef4444",
            font=dict(color="#e5e7eb"),
        ),
        row=1,
        col=1,
    )
    fig.update_layout(
        height=760,
        margin=dict(l=8, r=8, t=35, b=30),
        template="plotly_dark",
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        title=f"{symbol} 주가 차트",
        paper_bgcolor="#0b1220",
        plot_bgcolor="#0b1220",
        font=dict(family="Malgun Gothic, Arial", color="#e5e7eb"),
    )
    return fig


def _load_ticker_info(symbol: str) -> dict:
    try:
        t = yf.Ticker(symbol)
        try:
            return t.get_info()
        except Exception:
            return t.info or {}
    except Exception:
        return {}


def _load_quarterly_revenue(symbol: str) -> Optional[pd.Series]:
    try:
        t = yf.Ticker(symbol)
        qfin = t.quarterly_financials
        revenue_series = None
        for row_name in ['Total Revenue', 'Operating Revenue', 'Revenue']:
            if hasattr(qfin, 'index') and row_name in qfin.index:
                revenue_series = qfin.loc[row_name].dropna()
                break
        if revenue_series is None or len(revenue_series) == 0:
            return None
        return revenue_series.sort_index()
    except Exception as e:
        log_error(f'_load_quarterly_revenue {symbol}', e)
        return None


def make_revenue_chart(symbol: str):
    """분기 매출 차트. 무료 데이터 특성상 한국 종목은 일부만 제공될 수 있다."""
    if go is None:
        return None
    rev = _load_quarterly_revenue(symbol)
    fig = go.Figure()
    if rev is not None and len(rev) > 0:
        x = [str(pd.to_datetime(i).date()) if not isinstance(i, str) else i for i in rev.index]
        y = [float(v) / 100000000 for v in rev.values]
        fig.add_trace(go.Bar(x=x, y=y, name='분기 매출(억원)', hovertemplate="기간: %{x}<br>매출: %{y:,.0f}억원<extra></extra>"))
        fig.update_yaxes(title_text='억원')
    else:
        fig.add_annotation(text='무료 데이터에서 분기 매출 데이터가 충분하지 않습니다. 한국 종목은 종목별 제공 품질 차이가 큽니다.', x=0.5, y=0.5, showarrow=False, xref='paper', yref='paper')
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=40, b=10), template='plotly_dark', title='분기 매출', font=dict(family="Malgun Gothic, Arial"))
    return fig


def _valuation_values(symbol: str) -> dict:
    info = _load_ticker_info(symbol)
    return {
        "현재 PER": safe_float(info.get('trailingPE'), np.nan),
        "예상 PER": safe_float(info.get('forwardPE'), np.nan),
        "현재 PBR": safe_float(info.get('priceToBook'), np.nan),
        "EPS": safe_float(info.get('trailingEps'), np.nan),
        "BPS": safe_float(info.get('bookValue'), np.nan),
    }


def make_single_valuation_chart(symbol: str, metric: str = "PER"):
    """PER 또는 PBR 표시. 과거 시계열이 없으면 현재값 중심으로 표시."""
    if go is None:
        return None
    vals = _valuation_values(symbol)
    fig = go.Figure()
    if metric == "PER":
        labels, data = [], []
        for k in ["현재 PER", "예상 PER"]:
            v = vals.get(k, np.nan)
            if np.isfinite(v):
                labels.append(k); data.append(v)
        title = "PER"
    else:
        labels, data = [], []
        v = vals.get("현재 PBR", np.nan)
        if np.isfinite(v):
            labels.append("현재 PBR"); data.append(v)
        title = "PBR"
    if data:
        fig.add_trace(go.Bar(x=labels, y=data, name=title, hovertemplate="%{x}: %{y:,.2f}<extra></extra>"))
    else:
        fig.add_annotation(text=f'무료 데이터에서 {title} 값이 제공되지 않습니다.', x=0.5, y=0.5, showarrow=False, xref='paper', yref='paper')
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=40, b=10), template='plotly_dark', title=title, font=dict(family="Malgun Gothic, Arial"))
    return fig


def render_symbol_chart_tabs(symbol: str, levels: Optional[dict] = None, key_prefix: str = ''):
    """추천 상세/직접분석에서 공통으로 쓰는 차트 탭."""
    with st.container():
        c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1, 1])
        period_label = c1.selectbox("차트 기간", ["3개월", "6개월", "1년", "2년", "5년"], index=2, key=f"{key_prefix}_period")
        interval_label = c2.selectbox("봉 종류", ["일봉", "주봉", "월봉"], index=0, key=f"{key_prefix}_interval")
        show_ma = c3.checkbox("이동평균선", value=True, key=f"{key_prefix}_ma")
        show_profile = c4.checkbox("매물대", value=True, key=f"{key_prefix}_profile")
        show_sub = c5.checkbox("보조지표", value=True, key=f"{key_prefix}_sub")
    st.markdown('''<style>.dh-single-tab{display:inline-block;color:#ff4b4b;border-bottom:2px solid #ff4b4b;padding:0 2px 6px 2px;margin:4px 0 8px 0;font-weight:700;}</style><div class="dh-single-tab">주가</div>''', unsafe_allow_html=True)
    st.caption('마우스를 캔들 위에 올리면 날짜·시가·고가·저가·종가·거래량을 볼 수 있습니다. 휴장일 공백은 제거되며, 주가·거래량·MACD·RSI가 같은 날짜축으로 함께 움직입니다. 오른쪽에는 매물대와 핵심 투자지표/최근 분기 요약이 고정 표시됩니다.')
    chart_col, info_col = st.columns([0.82, 0.18])
    with chart_col:
        fig = make_price_chart(symbol, levels, period_label=period_label, interval_label=interval_label, show_ma=show_ma, show_volume_profile=show_profile, show_macd=show_sub, show_rsi=show_sub)
        if fig:
            st.plotly_chart(fig, use_container_width=True, key=f'{key_prefix}_price', config={"displayModeBar": True, "scrollZoom": True, "displaylogo": False})
        else:
            st.warning('주가 차트를 불러오지 못했습니다. 티커/인터넷 연결/무료 데이터 제공 여부를 확인하세요.')
    with info_col:
        render_fundamental_side_panel(symbol)
    refresh_data_status_board()

def streamlit_app():
    st.set_page_config(page_title="Donhyun Stock Guard", layout="wide")
    init_data_status_state()
    ensure_base_files()
    settings = read_settings()
    with st.sidebar:
        st.header("분석 범위")
        market = st.radio("시장", ["KR", "US"], format_func=lambda x: "한국주식" if x == "KR" else "미국주식", horizontal=True)
        analysis_limit = st.selectbox("정밀분석 개수", [15, 30, 50], index=1)
        top_n = st.radio("결과 표시", [5, 10], index=1, horizontal=True)
        uni_count = get_universe_count(market)
        st.caption(f"현재 후보군: {uni_count}개 · 전체 상장종목 전수분석은 아니며, 후보군에서 {analysis_limit}개만 정밀분석합니다.")
        st.caption("v2.0.2 MARKET: 속도 최적화는 유지하고 시장 판단 최종 규칙을 통합합니다.")

        st.divider()
        st.header("계좌/리스크 설정")
        settings["total_assets"] = st.number_input("전체 자산", value=int(settings.get("total_assets", 150_000_000)), step=1_000_000)
        settings["stock_value"] = st.number_input("현재 주식 평가금액", value=int(settings.get("stock_value", 100_000_000)), step=1_000_000)
        settings["cash_krw"] = st.number_input("남은 원화 현금", value=int(settings.get("cash_krw", 50_000_000)), step=1_000_000)
        settings["risk_per_trade_pct"] = st.slider("1회 손실 허용률(%)", 0.1, 2.0, float(settings.get("risk_per_trade_pct", 0.5)), 0.1)
        settings["max_single_position_pct"] = st.slider("1종목 최대 비중(%)", 3.0, 30.0, float(settings.get("max_single_position_pct", 10.0)), 1.0)
        settings["min_cash_reserve_pct"] = st.slider("현금 최소 유지율(%)", 0.0, 50.0, float(settings.get("min_cash_reserve_pct", 20.0)), 1.0)
        st.divider()
        st.subheader("시장 일정 리스크")
        settings["manual_event_risk"] = st.selectbox("오늘 주요 일정 리스크", ["없음", "중간", "높음"], index=["없음", "중간", "높음"].index(str(settings.get("manual_event_risk", "없음")) if str(settings.get("manual_event_risk", "없음")) in ["없음", "중간", "높음"] else "없음"))
        settings["manual_event_note"] = st.text_input("일정 메모", value=str(settings.get("manual_event_note", "")), placeholder="예: CPI 발표, FOMC, 옵션만기, 대형주 실적")
        st.caption("자동 경제캘린더 연동 전까지는 수동 입력값을 시장점수에 반영합니다.")
        if st.button("설정 저장"):
            save_settings(settings)
            st.success("저장 완료")

        st.divider()
        st.header("추천 필터")
        presets = {
            "exclude_chasing": st.checkbox("추격매수 위험 제외", value=True),
            "rr_good": st.checkbox("손익비 1.5 이상", value=True),
            "exclude_blocked": st.checkbox("매수금지 사유 제외", value=True),
            "buyable_only": st.checkbox("오늘 매수 가능 후보만", value=False),
            "pullback_watch": st.checkbox("눌림목/진입가 대기 후보", value=False),
            "breakout_watch": st.checkbox("돌파 확인 후보", value=False),
        }
    header_left, header_right = st.columns([0.9, 2.1])
    with header_left:
        st.title("Donhyun Stock Guard v2.0.2")
        st.caption("목표: 크게 잃을 가능성을 먼저 줄이고, 그다음 손익비가 유리한 후보만 선별합니다. 투자 추천/자동매매가 아니라 판단 보조 도구입니다.")
    global STATUS_RENDER_TARGET, CURRENT_MARKET_FOR_STATUS
    CURRENT_MARKET_FOR_STATUS = market
    with header_right:
        STATUS_RENDER_TARGET = st.empty()
        render_data_status_board(market, target=STATUS_RENDER_TARGET)
    tabs = st.tabs(["오늘 TOP 추천", "종목 직접 분석", "조건 검색", "성과/학습", "후보군 관리", "한국투자 API", "진단/파일"])
    with tabs[0]:
        st.subheader("오늘의 TOP 추천")
        colA, colB, colC = st.columns([1.2, 1.2, 2])
        with colA:
            mode = st.radio("섹터 선택 방식", ["auto", "manual"], format_func=lambda x: "앱이 유리한 섹터 자동 선택" if x == "auto" else "내가 섹터 직접 선택")
        sector_df = sector_strength(market)
        sectors = sector_df["sector"].tolist()
        with colB:
            selected = st.multiselect("직접 선택 섹터", sectors, default=sectors[:1], disabled=(mode == "auto"))
        with colC:
            st.info(f"추천은 시장 → 섹터 → 종목 순서로 진행합니다. 현재 후보군 {get_universe_count(market)}개 중 섹터/필터를 거쳐 {analysis_limit}개만 정밀분석합니다.")
        top_btn_col, intraday_btn_col = st.columns([1, 1])
        with top_btn_col:
            if st.button("TOP 추천 새로 계산", type="primary"):
                with st.spinner("시장/섹터/종목을 정밀분석 중입니다. 처음 실행 시 시간이 걸릴 수 있습니다."):
                    top, market_info, sector_df = run_ranking(market, mode, selected, analysis_limit, top_n, presets)
                st.success("계산 완료")
                st.rerun()
        with intraday_btn_col:
            if st.button("시장+종목 전체 재평가", type="secondary"):
                with st.spinner("시장상태와 추천 종목 현재가를 함께 재조회해 현재판정과 권장금액을 다시 계산합니다."):
                    _, msg = intraday_reevaluate_recommendations(market)
                st.success(msg)
                st.rerun()
        st.caption("시장+종목 전체 재평가는 종목 현재가뿐 아니라 지수·금리·환율·유가 등 시장상태까지 함께 반영합니다. 기존 현재가 단독 새로고침 버튼은 혼선을 줄이기 위해 제거했습니다.")
        rec = load_latest_recommendations(market)
        status_path = DATA_DIR / f"today_status_{market}.json"
        if status_path.exists():
            status = json.loads(status_path.read_text(encoding="utf-8"))
            market_info = status.get("market_info", calculate_market_state(market))
        else:
            status = {}
            market_info = calculate_market_state(market)
        current_market_info = status.get("current_market_info", market_info)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("장전 시장상태", market_info.get("label", "-"), f"점수 {market_info.get('score', 0)}")
        c2.metric("현재 시장상태", current_market_info.get("label", market_info.get("label", "-")), f"위험도 {current_market_info.get('market_risk_score', market_info.get('market_risk_score', 0))}")
        c3.metric("공격허용도", f"{current_market_info.get('attack_permission', market_info.get('attack_permission',0))}%", f"현금 {current_market_info.get('use_cash_ratio', market_info.get('use_cash_ratio',0))*100:.0f}%")
        c4.metric("방어필요도", f"{current_market_info.get('defense_need', market_info.get('defense_need',0))}%")
        c5.metric("최종 결과", f"TOP {min(top_n, len(rec)) if not rec.empty else 0}")
        st.caption(f"시장 판단 구분: {current_market_info.get('session', market_info.get('session', {})).get('label', '-')} / 판단시각 {current_market_info.get('created_at', market_info.get('created_at', '-'))}")
        if current_market_info.get("burden_reasons"):
            st.warning("시장 부담 요인: " + ", ".join(current_market_info.get("burden_reasons", [])[:5]))
        if current_market_info.get("strategy_note"):
            st.info("오늘 적용 규칙: " + str(current_market_info.get("strategy_note")))
        if status.get("intraday_reevaluated_at"):
            note = status.get("market_change_note", "")
            if current_market_info.get("label") != market_info.get("label"):
                st.warning(f"장중 시장 재평가: {status.get('intraday_reevaluated_at')} / {note}")
            else:
                st.info(f"장중 시장 재평가: {status.get('intraday_reevaluated_at')} / {note}")
        if market_info.get("state") == "risk_off":
            st.error("🚫 현재 시장 상태가 위험회피로 판정되어 신규 매수 권장금액을 0원으로 제한합니다. 종목 점수가 높아도 오늘은 관망/관찰 후보와 실제 매수 가능 후보를 분리해서 보세요.")
        elif market_info.get("state") == "burden":
            st.warning("⚠️ 시장 상태가 불리합니다. 권장금액을 축소하고, 진입가 이격률과 손익비 기준을 강화합니다.")
        with st.expander("시장 판단 상세", expanded=False):
            st.write(f"장 구분: {market_info.get('session', {}).get('label', '-')} / 시장점수: {market_info.get('score', 0)}")
            if market_info.get("burden_reasons"):
                st.warning("부담 요인: " + ", ".join(market_info.get("burden_reasons", [])))
            if market_info.get("favorable_reasons"):
                st.success("우호 요인: " + ", ".join(market_info.get("favorable_reasons", [])))
            st.write("##### 시장 제어 프로필")
            st.caption("v2.0.2: 시장상태 5단계와 별도로 시장위험도·공격허용도·방어필요도·하드블록을 계산합니다.")
            st.dataframe(korean_market_control_profile_df(market_info), use_container_width=True, hide_index=True)
            if market_info.get("hard_blocks"):
                st.error("하드블록: " + ", ".join(market_info.get("hard_blocks", [])[:6]))
            if market_info.get("warning_blocks"):
                st.warning("주의블록: " + ", ".join(market_info.get("warning_blocks", [])[:6]))
            if market_info.get("supportive_blocks"):
                st.success("공격 우호 근거: " + ", ".join(market_info.get("supportive_blocks", [])[:6]))
            st.write("##### 지표별 시장점수")
            st.dataframe(korean_market_rows(market_info.get("rows", [])), use_container_width=True)
            bd_df = korean_score_breakdown_df(market_info)
            if not bd_df.empty:
                st.write("##### 시장점수 구성")
                st.dataframe(bd_df, use_container_width=True, hide_index=True)
            st.write("##### 후보군 내부강도")
            st.caption("전체 상장종목이 아니라 현재 앱 후보군 기준입니다. 상승/하락 종목 수, 평균등락률, 거래량을 시장 체감 강도 보조값으로 봅니다.")
            st.dataframe(korean_market_internals_df(market_info.get("internals", {})), use_container_width=True, hide_index=True)
            st.write("##### 섹터별 내부강도")
            st.caption("후보군을 섹터별로 나눠 상승비율·평균등락률·거래량·고점/저점 근접도를 계산합니다. 전체 업종지수 데이터가 아니라 앱 후보군 기준입니다.")
            st.dataframe(korean_sector_internals_df(market_info.get("sector_internals", {})), use_container_width=True, hide_index=True, height=260)
            rules_df = korean_risk_rules_df(market_info)
            if not rules_df.empty:
                st.write("##### 시장상태별 적용 규칙")
                st.dataframe(rules_df, use_container_width=True, hide_index=True)
            log_summary = market_state_log_summary_df(market)
            if not log_summary.empty:
                st.write("##### 최근 시장판단 로그 요약")
                st.caption("최근 저장된 시장 판단 로그 기준입니다. 아직 성과와 직접 연결된 통계는 v2.0 이후 보강 예정입니다.")
                st.dataframe(log_summary, use_container_width=True, hide_index=True)
            ev = market_info.get("event_risk", {})
            if ev:
                st.write("##### 일정 리스크")
                st.dataframe(pd.DataFrame([{"위험도": ev.get("level", "-"), "점수반영": ev.get("score", 0), "메모": ev.get("note", "-"), "해석": ev.get("message", "-")}]), use_container_width=True, hide_index=True)
            if market_info.get("state") == "risk_off":
                st.error("시장 위험회피: 신규 매수 0원 또는 관망 우선")
            elif market_info.get("state") == "burden":
                st.warning("시장 불리: 권장금액 축소 및 매수 기준 강화")
            elif market_info.get("state") == "neutral":
                st.info("시장 중립: 진입가 대기 우선")
            elif market_info.get("state") == "strong_favorable":
                st.success("시장 강한 우호: 조건 충족 주도 섹터/종목은 분할 접근 가능")
            else:
                st.success("시장 우호: 조건 충족 종목만 검토")
        st.write("#### 섹터 강도")
        st.dataframe(korean_sector_df(sector_df), use_container_width=True, height=220)
        st.write("#### 추천 결과")
        if not rec.empty:
            if "price_refresh_at" in rec.columns and rec["price_refresh_at"].dropna().astype(str).str.len().any():
                latest_price_time = rec["price_refresh_at"].dropna().astype(str).iloc[-1]
            else:
                latest_price_time = "현재가 새로고침 전"
            st.caption(f"장중 현재가 재평가 기준: {latest_price_time} · 장전판정과 현재판정이 다르면 현재가는 이미 매수조건에서 멀어졌을 수 있습니다.")
            if "intraday_reevaluated_at" in rec.columns and rec["intraday_reevaluated_at"].dropna().astype(str).str.len().any():
                st.caption(f"장중 시장 재평가 기준: {rec['intraday_reevaluated_at'].dropna().astype(str).iloc[-1]}")
        if rec.empty:
            st.warning("아직 추천 결과가 없습니다. [TOP 추천 새로 계산]을 눌러 생성하세요.")
        else:
            buyable_df = rec[rec["decision"].isin(["매수 가능", "주도주 조건부 접근"])] if "decision" in rec.columns else pd.DataFrame()
            watch_df = rec[~rec.index.isin(buyable_df.index)] if not rec.empty else pd.DataFrame()
            st.write("##### 매수 가능 후보")
            if buyable_df.empty:
                st.info("현재 조건에서 실제 매수 가능 후보는 없습니다. 시장 위험회피/매수금지 사유가 있으면 권장금액은 0원입니다.")
            else:
                st.dataframe(korean_recommendation_df(buyable_df), use_container_width=True, height=180)
            st.write("##### 관찰 후보")
            if watch_df.empty:
                st.info("관찰 후보가 없습니다.")
            else:
                st.dataframe(korean_recommendation_df(watch_df), use_container_width=True, height=180)

            st.write("##### 종목별 상세 근거")
            for i, r in rec.reset_index(drop=True).iterrows():
                chart_state = r.get('pullback_state', '-')
                leader_tag = ' / 주도주' if str(r.get('leader_mode','N')) == 'Y' else ''
                original_decision = str(r.get('original_decision', r.get('decision', '-')))
                current_decision = str(r.get('decision','-'))
                decision_text = current_decision if original_decision in ['', '-', current_decision] else f"{original_decision} → {current_decision}"
                title = f"{i+1}. {r.get('name_kr', r.get('name', r.get('symbol')))} ({r.get('symbol')}) / 점수 {safe_float(r.get('final_score'),0):.1f}점 / 판정: {decision_text} / 차트상태: {chart_state}{leader_tag} / 권장금액 {format_krw(r.get('recommended_amount',0))}"
                with st.expander(title, expanded=(i == 0)):
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("현재가", f"{safe_float(r.get('close'),0):,.2f}")
                    m2.metric("우선진입가", f"{safe_float(r.get('entry'),0):,.2f}")
                    m3.metric("손절가", f"{safe_float(r.get('stop'),0):,.2f}")
                    m4.metric("1차목표가", f"{safe_float(r.get('target1'),0):,.2f}")
                    m5.metric("손익비", f"{safe_float(r.get('risk_reward'),0):.2f}")
                    if str(r.get('current_price_time', '')).strip():
                        st.caption(f"현재가 재조회: {r.get('current_price_time')} / 마지막 캔들: {r.get('last_candle_time', '-')} / 추천가 대비 변동률: {safe_float(r.get('price_change_from_recommendation_pct'), 0):+.2f}%")
                    if str(r.get('intraday_reevaluated_at', '')).strip():
                        st.info(f"장중 재평가: {r.get('market_change_note', '-')} / {r.get('intraday_price_alert', '-')} / {r.get('intraday_action_note', '-')}")
                    render_score_bar("종목 매력도", safe_float(r.get("attractiveness_score"), 0))
                    render_score_bar("매매 적합도", safe_float(r.get("trade_fit_score"), 0))
                    render_score_bar("최종 종합점수", safe_float(r.get("final_score"), 0))
                    st.write("**좋은 점**", r.get("good_points", "-"))
                    st.write("**주의/불리한 점**", r.get("bad_points", "-"))
                    st.write("**주도주 판단**", r.get("leader_reason", "-") if str(r.get("leader_mode", "N")) == "Y" else "해당 없음")
                    st.write("**차트 진입상태**", f"{r.get('pullback_state','-')} · {r.get('pullback_reason','-')}")
                    st.write("**앱 행동 판단**", r.get("pullback_action", "-"))
                    st.write("**매수금지 사유**", r.get("hard_blocks", "없음") or "없음")
                    st.write("**권장금액 산정 이유**", r.get("position_reason", "-"))
                    st.write("**핵심 가격**", f"지지 {r.get('support1')} / 저항 {r.get('resistance1')} / 진입가 이격 {r.get('entry_distance_pct')}% / 저항여유 {r.get('resistance_room_pct')}%")
                    st.markdown("---")
                    st.write("**차트 바로 보기**")
                    st.caption("v2.0.2 MARKET: 분석 점수 계산은 유지하고, 시장점수·공격허용도·방어필요도·하드블록을 함께 표시합니다.")
                    show_chart = st.toggle("이 종목 차트 표시", value=False, key=f"show_chart_{market}_{i}_{str(r.get('symbol')).replace('.', '_')}")
                    if show_chart:
                        render_symbol_chart_tabs(str(r.get('symbol')), r.to_dict() if hasattr(r, 'to_dict') else dict(r), key_prefix=f"rec_{market}_{i}_{str(r.get('symbol')).replace('.', '_')}")

        st.write("#### 시장 뉴스/속보")
        st.caption("무료 Google News RSS 기준입니다. 투자 판단 전 원문과 공시를 추가 확인하세요.")
        news_df = fetch_market_news(market, limit=20)
        refresh_data_status_board(market)
        st.caption(f"뉴스 수집 시각: {get_data_status('last_news_query_time', '-')}")
        if news_df.empty:
            st.info("뉴스를 가져오지 못했습니다. 인터넷 연결 또는 RSS 응답 상태를 확인하세요.")
        else:
            for ni, nr in news_df.iterrows():
                label = f"{nr.get('중요도','-')} / {nr.get('영향방향','-')} / {nr.get('출처','-')}"
                with st.expander(f"{ni+1}. {nr.get('제목','')}"):
                    st.write(label)
                    st.write(f"시간: {nr.get('시간','-')}")
                    if nr.get('링크'):
                        st.markdown(f"[원문 열기]({nr.get('링크')})")

        # 추천 종목별 차트는 각 추천 상세 펼침 영역 안에 내장했습니다.
    with tabs[1]:
        st.subheader("종목 직접 분석")
        user_symbol = st.text_input("종목명/종목코드/티커 입력", value="삼성전자" if market == "KR" else "NVDA")
        if st.button("이 종목 분석하기"):
            resolved_symbol, row = resolve_symbol(user_symbol, market)
            if not resolved_symbol:
                st.warning("종목명을 입력하세요.")
                return
            sd = sector_strength(market)
            sector_s = sd.set_index("sector")["sector_score"].to_dict().get(row.get("sector"), 50)
            mi = calculate_market_state(market)
            res = analyze_symbol(row, market, mi, sector_s, settings)
            st.write(f"### {res.get('name_kr')} ({res.get('symbol')})")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("최종 판정", res.get('decision'))
            k2.metric("종합점수", f"{safe_float(res.get('final_score'),0):.1f}점")
            k3.metric("차트상태", res.get('pullback_state'))
            k4.metric("권장금액", format_krw(res.get('recommended_amount',0)))
            st.write("**앱 행동 판단:**", res.get('pullback_action', '-'))
            st.write("**매수금지 사유:**", res.get('hard_blocks', '없음') or '없음')
            st.write("**권장금액 산정 이유:**", res.get('position_reason', '-'))
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("현재가", f"{safe_float(res.get('close'),0):,.2f}")
            m2.metric("우선진입가", f"{safe_float(res.get('entry'),0):,.2f}")
            m3.metric("손절가", f"{safe_float(res.get('stop'),0):,.2f}")
            m4.metric("1차목표가", f"{safe_float(res.get('target1'),0):,.2f}")
            m5.metric("손익비", f"{safe_float(res.get('risk_reward'),0):.2f}")
            render_score_bar("종목 매력도", safe_float(res.get("attractiveness_score"), 0))
            render_score_bar("매매 적합도", safe_float(res.get("trade_fit_score"), 0))
            render_score_bar("최종 종합점수", safe_float(res.get("final_score"), 0))
            with st.expander("상세 분석 근거", expanded=True):
                st.write("좋은 점:", res.get('good_points', '-'))
                st.write("주의/불리한 점:", res.get('bad_points', '-'))
                st.write("주도주 판단:", res.get('leader_reason', '-') if res.get('leader_mode') == 'Y' else '해당 없음')
                st.write("차트 진입상태:", f"{res.get('pullback_state')} · {res.get('pullback_reason')}")
                st.write("핵심 가격:", f"지지 {res.get('support1')} / 저항 {res.get('resistance1')} / 진입가 이격 {res.get('entry_distance_pct')}% / 저항여유 {res.get('resistance_room_pct')}%")
            st.markdown("---")
            st.write("### 차트/재무 보기")
            render_symbol_chart_tabs(str(res.get("symbol")), res, key_prefix=f"direct_{market}_{str(res.get('symbol')).replace('.', '_')}")
    with tabs[2]:
        st.subheader("조건 검색")
        st.caption("복잡한 필터를 몰라도 추천 필터 체크박스만으로 후보를 좁히는 화면입니다.")
        raw_path = DATA_DIR / f"recommendations_{market}_raw.csv"
        if raw_path.exists():
            raw = pd.read_csv(raw_path, encoding="utf-8-sig")
            filtered = apply_filter_presets(raw, presets)
            st.write(f"필터 적용 결과: {len(filtered)}개 / 원본 {len(raw)}개")
            if filtered.empty:
                st.warning("후보가 0개입니다. 손익비 기준을 완화하거나 정밀분석 개수를 50개로 늘려보세요. 현재 시장이 위험회피이거나 '매수금지 사유 제외' 필터가 켜져 있으면 후보가 대부분 제거될 수 있습니다.")
            st.dataframe(korean_recommendation_df(filtered), use_container_width=True)
        else:
            st.info("먼저 TOP 추천 계산을 실행해야 조건 검색 결과가 나옵니다.")
    with tabs[3]:
        st.subheader("성과/학습")
        st.caption("v1.9.5: 장마감 결과 중복 방지, 실패 원인 자동 분류, 관망/제외 판단 검증, 점수 구간별 학습표를 강화한 안정화 버전입니다.")
        lcol1, lcol2, lcol3 = st.columns(3)
        horizon_days = lcol1.selectbox("검증 기간", [1, 3, 5, 10], index=2, help="추천 이후 몇 거래일 범위에서 목표가/손절/최대상승/최대하락을 볼지 선택합니다.")
        gate = update_gate_status(market, int(horizon_days), force=False)
        force_update = lcol3.checkbox("강제 재검증", value=False, help="데이터 오류 등으로 다시 검증해야 할 때만 사용합니다. 중복 기록은 덮어쓰기 방식으로 처리합니다.")
        st.caption(f"장마감 업데이트 제한: {gate.get('time_rule')} · 현재 상태: {gate.get('reason')}")
        run_disabled = (not gate.get("allowed")) and (not force_update)
        if lcol2.button("장마감 결과 업데이트", disabled=run_disabled):
            with st.spinner("추천 결과와 실제 가격을 비교하는 중"):
                result = update_results(market, horizon_days=int(horizon_days), force=bool(force_update))
            if not result.empty and "reason" in result.columns and str(result.iloc[0].get("outcome", "")) == "업데이트 차단":
                st.warning(str(result.iloc[0].get("reason", "업데이트가 차단되었습니다.")))
            else:
                st.success(f"업데이트 완료: {len(result)}건")
                if not result.empty:
                    show_cols = [c for c in ["name_kr","symbol","decision","outcome","entry_hit","target1_hit","stop_hit","close_return_pct","max_gain_pct","max_drawdown_pct"] if c in result.columns]
                    st.dataframe(result[show_cols], use_container_width=True, height=260)
        if lcol3.button("주간 학습 리포트 생성"):
            text, sug = weekly_learning_report()
            st.text(text)

        hist_path = DATA_DIR / "trade_learning_history.csv"
        factor_path = DATA_DIR / "factor_learning_summary.csv"
        if hist_path.exists():
            hist = pd.read_csv(hist_path, encoding="utf-8-sig")
            st.write(f"#### 누적 검증 기록: {len(hist)}건")
            m1, m2, m3, m4 = st.columns(4)
            if "target1_hit" in hist.columns:
                m1.metric("1차목표 도달률", f"{_rate(hist['target1_hit']):.1f}%")
            else:
                m1.metric("1차목표 도달률", "-")
            if "stop_hit" in hist.columns:
                m2.metric("손절 도달률", f"{_rate(hist['stop_hit']):.1f}%")
            else:
                m2.metric("손절 도달률", "-")
            if "close_return_pct" in hist.columns:
                avg_ret = pd.to_numeric(hist["close_return_pct"], errors="coerce").mean()
                m3.metric("평균 종가수익률", f"{avg_ret:.2f}%" if np.isfinite(avg_ret) else "-")
            else:
                m3.metric("평균 종가수익률", "-")
            if "max_drawdown_pct" in hist.columns:
                avg_dd = pd.to_numeric(hist["max_drawdown_pct"], errors="coerce").mean()
                m4.metric("평균 최대하락률", f"{avg_dd:.2f}%" if np.isfinite(avg_dd) else "-")
            else:
                m4.metric("평균 최대하락률", "-")
            if "outcome" in hist.columns:
                st.write("##### 결과 분포")
                outcome_df = hist["outcome"].fillna("-").value_counts().reset_index()
                outcome_df.columns = ["결과", "건수"]
                st.dataframe(outcome_df, use_container_width=True, hide_index=True, height=220)
            st.write("##### v1.9.5 학습 안정화 요약")
            summary_tables = build_learning_summary_tables(hist)
            if summary_tables:
                st.caption("추천 판정, 실패 원인, 점수 구간, 손익비, 진입가 이격률, 차트상태별 실제 성과를 비교합니다.")
                table_names = list(summary_tables.keys())
                selected_table = st.selectbox("학습표 선택", table_names, index=0)
                selected_df = summary_tables.get(selected_table, pd.DataFrame())
                if selected_df is not None and not selected_df.empty:
                    st.dataframe(selected_df, use_container_width=True, hide_index=True, height=260)
            st.write("##### 최근 검증 기록")
            show_cols = [c for c in ["updated_at","market","name_kr","symbol","decision","decision_validity","failure_reason","outcome","final_score","risk_reward","entry_distance_pct","close_return_pct","max_gain_pct","max_drawdown_pct"] if c in hist.columns]
            st.dataframe(hist[show_cols].tail(80), use_container_width=True, height=320)
            if factor_path.exists():
                factor_df = pd.read_csv(factor_path, encoding="utf-8-sig")
                st.write("##### 요인별 학습 요약")
                st.caption("각 점수 요인을 하위/중위/상위 구간으로 나눠 실제 성과를 비교합니다. 표본이 적을 때는 참고용으로만 보세요.")
                st.dataframe(factor_df, use_container_width=True, height=320)
            else:
                st.info("요인별 학습 요약은 장마감 결과 업데이트 후 생성됩니다.")
        else:
            st.info("아직 누적 학습 데이터가 없습니다. 장마감 결과 업데이트 후 생성됩니다.")
        st.markdown("---")
        st.write("#### v1.9 학습엔진 사용 순서")
        st.write("1) 장전 또는 장중에 TOP 추천을 생성합니다. 2) 장마감 후 또는 며칠 뒤 이 탭에서 장마감 결과 업데이트를 누릅니다. 3) 표본이 쌓이면 주간 학습 리포트로 어떤 조건이 잘 맞았는지 확인합니다. 4) 자동 가중치 반영은 아직 보류이며, 먼저 검증 리포트로 확인합니다.")
    with tabs[4]:
        render_universe_manager(market)
    with tabs[5]:
        render_kis_api_tab(market)

    with tabs[6]:
        st.subheader("진단/파일")
        st.write("필수 폴더와 파일 상태를 확인합니다.")
        files = [DATA_DIR / "candidate_universe_kr.csv", DATA_DIR / "candidate_universe_us.csv", DATA_DIR / f"latest_recommendations_{market}.csv", REPORTS_DIR / "app_error_log.txt"]
        status_rows = []
        for p in files:
            status_rows.append({"file": str(p.relative_to(BASE_DIR)), "exists": p.exists(), "modified": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if p.exists() else "-"})
        st.dataframe(pd.DataFrame(status_rows).rename(columns={"file":"파일", "exists":"존재", "modified":"수정시각"}), use_container_width=True)
        st.write("#### v2.0.2 MARKET / SPEED 캐시 상태")
        st.caption("분석 품질을 낮추지 않고 동일 데이터를 반복 다운로드하지 않기 위한 내부 캐시입니다. 앱 재시작 시 초기화됩니다.")
        cache_rows = []
        try:
            for k, v in list(YF_PREFETCH_LOG.items()):
                row = {"구분": k, **v}
                cache_rows.append(row)
        except Exception:
            cache_rows = []
        st.dataframe(pd.DataFrame(cache_rows) if cache_rows else pd.DataFrame([{"구분":"아직 선조회 기록 없음"}]), use_container_width=True, hide_index=True)
        st.write(f"현재 세션 가격데이터 캐시 종목/기간 수: {len(YF_DATA_CACHE)}")
        if st.button("진단 리포트 저장"):
            report = {"version": APP_VERSION, "created_at": now_kst().isoformat(), "settings": settings, "files": status_rows}
            path = REPORTS_DIR / f"diagnostic_report_{now_kst().strftime('%Y%m%d_%H%M%S')}.json"
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            st.success(f"저장 완료: {path}")


def cli_main(args: List[str]):
    ensure_base_files()
    cmd = args[0] if args else ""
    try:
        if cmd == "kr_rank":
            top, _, _ = run_ranking("KR", "auto", None, 30, 10, {"exclude_chasing": False, "rr_good": False, "exclude_blocked": False})
            print(f"KR ranking complete: {len(top)} rows")
        elif cmd == "us_rank":
            top, _, _ = run_ranking("US", "auto", None, 30, 10, {"exclude_chasing": False, "rr_good": False, "exclude_blocked": False})
            print(f"US ranking complete: {len(top)} rows")
        elif cmd == "kr_update":
            df = update_results("KR")
            print(f"KR update complete: {len(df)} rows")
        elif cmd == "us_update":
            df = update_results("US")
            print(f"US update complete: {len(df)} rows")
        elif cmd == "weekly_learning":
            text, _ = weekly_learning_report()
            print(text)
        else:
            print("Unknown command. Use kr_rank, us_rank, kr_update, us_update, weekly_learning")
    except Exception as e:
        log_error(f"cli_main {cmd}", e)
        raise


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--runner":
        cli_main(sys.argv[2:])
    else:
        if st is None:
            print("Streamlit is not installed. Run 01_INSTALL.bat first.")
        else:
            streamlit_app()
