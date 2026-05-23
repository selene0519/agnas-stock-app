"""v52 시장 분리 + 보유/매도 값 보강 엔진.

v51에서 생긴 문제를 수정합니다.
- 일반 화면은 국장/미장 두 개만 제공합니다. 통합 보기는 만들지 않습니다.
- 매수 위험·제외 숫자는 하나의 표준 리포트만 기준으로 계산해, 기존 매수금지와 숫자가 다르게 보이지 않게 합니다.
- 보유/매도 권장수량은 실제 보유 파일을 우선 읽고, 현재가가 비어 있으면 저장 리포트/yfinance/FDR fallback으로 채웁니다.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    import yfinance as yf  # type: ignore
except Exception:  # pragma: no cover
    yf = None

try:
    import FinanceDataReader as fdr  # type: ignore
except Exception:  # pragma: no cover
    fdr = None

try:
    from core.v43_operational_engine import (
        ROOT, DATA_DIR, REPORT_DIR, read_csv_safe, read_json_safe, write_json,
        get_secret, market_slug, label_for_symbol, discover_symbol_names, to_num, first,
        save_gnews_reports,
    )
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / "data"
    REPORT_DIR = ROOT / "reports"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    def read_csv_safe(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
        except Exception:
            return pd.DataFrame()
    def read_json_safe(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.stat().st_size else {}
        except Exception:
            return {}
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    def get_secret(name: str) -> str:
        return str(os.environ.get(name, "") or "").strip()
    def market_slug(market: str) -> str:
        return "kr" if str(market) in {"한국주식", "국장", "KR", "kr"} else "us"
    def label_for_symbol(symbol: str, market: str, names: dict[str, str] | None = None) -> str:
        return str(symbol)
    def discover_symbol_names(market: str) -> dict[str, str]:
        return {}
    def to_num(value: Any, default: float = math.nan) -> float:
        try:
            s = re.sub(r"[^0-9.\-]", "", str(value or ""))
            return float(s) if s not in {"", "-", "."} else default
        except Exception:
            return default
    def first(row: Any, cols: Iterable[str], default: Any = "-") -> Any:
        for c in cols:
            if c in getattr(row, "index", []):
                v = row.get(c)
                if pd.notna(v) and str(v).strip() not in {"", "-", "nan", "None"}:
                    return v
        return default
    def save_gnews_reports() -> dict[str, Any]:
        return {"status": "NO_GNEWS_ENGINE"}

try:
    from core.v50_stability_engine import run_v50_update
except Exception:  # pragma: no cover
    run_v50_update = None

ACTION_LIGHT_CSV = REPORT_DIR / "v52_action_board_light.csv"
BUY_RISK_LIGHT_CSV = REPORT_DIR / "v52_buy_risk_light.csv"
POSITION_LIGHT_CSV = REPORT_DIR / "v52_position_plan_light.csv"
NEWS_STATUS_JSON = REPORT_DIR / "v52_news_status.json"
STATUS_JSON = REPORT_DIR / "v52_status.json"
DATA_STATUS_JSON = REPORT_DIR / "v52_light_status.json"

BAD_TEXTS = {"", "-", "nan", "NaN", "None", "none", "NULL", "null"}

KR_NAME_FALLBACK = {
    "403870": "HPSP", "131970": "두산테스나", "222800": "심텍", "058470": "리노공업",
    "095340": "ISC", "017670": "SK텔레콤", "375500": "DL이앤씨", "000990": "DB하이텍",
    "006260": "LS", "012450": "한화에어로스페이스", "329180": "HD현대중공업", "032640": "LG유플러스",
    "005930": "삼성전자", "000660": "SK하이닉스",
}
US_NAME_FALLBACK = {
    "NVDA": "NVIDIA", "GOOGL": "Alphabet", "TSLA": "Tesla", "PLTR": "Palantir", "INTC": "Intel",
    "LITE": "Lumentum", "SNDK": "SanDisk", "CAT": "Caterpillar", "CRCL": "Circle", "NBIS": "Nebius",
    "SMCI": "Super Micro Computer", "COST": "Costco", "AMZN": "Amazon", "TSM": "TSMC", "NET": "Cloudflare",
    "RIOT": "Riot Platforms", "IWM": "Russell 2000 ETF", "XLE": "Energy ETF",
}


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def clean_text(value: Any, default: str = "-") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    s = str(value).strip()
    if s in BAD_TEXTS:
        return default
    s = re.sub(r"\bnan\b", "", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip()
    return s if s and s not in BAD_TEXTS else default


def norm_market(value: Any, symbol_hint: Any = "") -> str:
    s = clean_text(value, "")
    h = clean_text(symbol_hint, "")
    target = f"{s} {h}"
    if any(x in target for x in ["한국", "국장", "KOSPI", "KOSDAQ", "KRX"]):
        return "한국주식"
    if any(x in target for x in ["미국", "미장", "NASDAQ", "NYSE", "USA", "US"]):
        return "미국주식"
    if re.search(r"\b\d{6}\b", target):
        return "한국주식"
    return "미국주식"


def sym_clean(value: Any, market: str = "") -> str:
    s = clean_text(value, "")
    if not s:
        return ""
    if market_slug(market or norm_market("", s)) == "kr":
        m = re.search(r"(\d{6})", s)
        if m:
            return m.group(1)
    m = re.search(r"\(([A-Za-z0-9.\-]{1,16})\)", s)
    if m:
        return m.group(1).upper()
    return re.sub(r"[^A-Za-z0-9.\-]", "", s.split()[0]).upper()


def good_symbol(sym: str) -> bool:
    s = clean_text(sym, "")
    return bool(s and s.upper() not in {"NONE", "NAN", "NULL", "-"} and len(s) <= 16)


def fmt_price(value: Any, market: str) -> str:
    v = to_num(value)
    if math.isnan(v) or v <= 0:
        return "-"
    return f"{v:,.0f}원" if market_slug(market) == "kr" else f"${v:,.2f}"


def fmt_qty(value: Any, market: str) -> str:
    v = to_num(value, 0.0)
    if market_slug(market) == "us":
        return f"{v:,.4g}주" if abs(v - int(v)) > 1e-8 else f"{int(v):,}주"
    return f"{int(math.floor(v)):,}주"


_NAME_CACHE: dict[str, dict[str, str]] = {}

def names_for_market(market: str) -> dict[str, str]:
    mk = "한국주식" if market_slug(market) == "kr" else "미국주식"
    if mk not in _NAME_CACHE:
        try:
            names = discover_symbol_names(mk)
        except Exception:
            names = {}
        _NAME_CACHE[mk] = {**(KR_NAME_FALLBACK if market_slug(mk) == "kr" else US_NAME_FALLBACK), **names}
    return _NAME_CACHE[mk]


def add_symbol_label(symbol: str, name: str, market: str) -> str:
    sym = sym_clean(symbol, market)
    nm = clean_text(name, "")
    if not nm:
        nm = names_for_market(market).get(sym, "")
    if nm and sym:
        return f"{nm} ({sym})"
    return sym or nm or "-"


def _read_first(paths: list[Path]) -> pd.DataFrame:
    for p in paths:
        df = read_csv_safe(p)
        if not df.empty:
            return df.copy()
    return pd.DataFrame()


def _read_many(paths: Iterable[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    seen: set[str] = set()
    for p in paths:
        try:
            rp = str(p.resolve())
        except Exception:
            rp = str(p)
        if rp in seen:
            continue
        seen.add(rp)
        df = read_csv_safe(p)
        if not df.empty:
            df = df.copy()
            df["_source_file"] = str(p.relative_to(ROOT)) if str(p).startswith(str(ROOT)) else p.name
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_action_board_light(fetch_missing_prices: bool = True) -> pd.DataFrame:
    src = _read_first([
        REPORT_DIR / "v45_beginner_action_board.csv",
        REPORT_DIR / "v44_beginner_action_board.csv",
        REPORT_DIR / "v45_calibrated_candidates.csv",
    ])
    rows: list[dict[str, Any]] = []
    if src.empty:
        out = pd.DataFrame(columns=["시장", "우선순위", "행동", "종목", "기준가", "손절가", "목표가", "초보자 안내", "이유"])
        out.to_csv(ACTION_LIGHT_CSV, index=False, encoding="utf-8-sig")
        return out
    prices = _load_current_prices()
    for _, r in src.head(400).iterrows():
        symbol_raw = first(r, ["종목코드", "symbol", "ticker", "종목", "code"], "")
        market = norm_market(first(r, ["시장", "market"], ""), symbol_raw)
        sym = sym_clean(symbol_raw, market)
        name = first(r, ["종목명", "name", "company"], "")
        label = add_symbol_label(sym or symbol_raw, name, market) if (sym or clean_text(symbol_raw, "")) else clean_text(first(r, ["종목"], "-"))
        if not clean_text(label, "") or label == "-":
            continue
        basis_raw = first(r, ["기준가", "우선진입가", "entry_price", "preferred_entry", "basis_price"], "-")
        stop_raw = first(r, ["손절가", "stop_price", "stop_loss"], "-")
        target_raw = first(r, ["목표가", "1차 목표가", "target_price", "take_profit1"], "-")
        basis_num = to_num(basis_raw, math.nan)
        stop_num = to_num(stop_raw, math.nan)
        target_num = to_num(target_raw, math.nan)
        px = prices.get(sym.upper(), prices.get(sym, math.nan)) if sym else math.nan
        if (math.isnan(px) or px <= 0) and sym and fetch_missing_prices:
            px = _fetch_price(sym, market)
        # 기준가/손절/목표가가 비어 있으면 현재가 기반의 보수적 임시 기준을 채웁니다.
        # 이 값은 실전 주문가가 아니라 "기준가 계산 전" 상태를 줄이기 위한 참고값입니다.
        if (math.isnan(basis_num) or basis_num <= 0) and not math.isnan(px) and px > 0:
            basis_num = px
        if (math.isnan(stop_num) or stop_num <= 0) and not math.isnan(basis_num) and basis_num > 0:
            stop_num = basis_num * 0.95
        if (math.isnan(target_num) or target_num <= 0) and not math.isnan(basis_num) and basis_num > 0:
            target_num = basis_num * 1.10
        basis_txt = fmt_price(basis_num, market) if not math.isnan(basis_num) and basis_num > 0 else clean_text(basis_raw, "-")
        stop_txt = fmt_price(stop_num, market) if not math.isnan(stop_num) and stop_num > 0 else clean_text(stop_raw, "-")
        target_txt = fmt_price(target_num, market) if not math.isnan(target_num) and target_num > 0 else clean_text(target_raw, "-")
        reason_extra = ""
        if not math.isnan(px) and px > 0 and clean_text(basis_raw, "-") == "-":
            reason_extra = " · 현재가 기반 임시 기준"
        rows.append({
            "시장": market,
            "우선순위": clean_text(first(r, ["우선순위", "priority"], "중간"), "중간"),
            "행동": clean_text(first(r, ["행동", "추천행동", "판단", "action"], "진입가 대기"), "진입가 대기"),
            "종목": label,
            "기준가": basis_txt,
            "손절가": stop_txt,
            "목표가": target_txt,
            "초보자 안내": clean_text(first(r, ["초보자 안내", "beginner_guide", "안내"], ""), "기준가·손절가·뉴스·수급 확인 후 작은 비중부터 검토하세요."),
            "이유": clean_text(first(r, ["이유", "사유", "감점근거", "reason"], "-")) + reason_extra,
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        order = {"높음": 0, "중간": 1, "낮음": 2}
        out["_order"] = out["우선순위"].map(order).fillna(1)
        out = out.sort_values(["시장", "_order", "종목"]).drop(columns=["_order"]).drop_duplicates(subset=["시장", "종목", "행동"], keep="first")
    out.to_csv(ACTION_LIGHT_CSV, index=False, encoding="utf-8-sig")
    return out


def build_buy_risk_light() -> pd.DataFrame:
    """표준 위험 후보표 하나만 생성합니다.

    숫자가 다르게 보였던 원인:
    - 예전 화면은 '하드 매수금지'만 세고,
    - v51 화면은 신규매수 제외/관망/추격/주의까지 같이 세었습니다.
    v52부터 일반모드에서는 이 표준 리포트만 사용합니다.
    """
    src = _read_many([
        REPORT_DIR / "v45_calibrated_candidates.csv",
        REPORT_DIR / "v45_beginner_action_board.csv",
        REPORT_DIR / "v44_beginner_action_board.csv",
        REPORT_DIR / "risk_priority_summary.csv",
        REPORT_DIR / "v51_buy_risk_light.csv",
    ])
    rows: list[dict[str, Any]] = []
    if src.empty:
        out = pd.DataFrame(columns=["시장", "종목", "위험 구분", "초보자 해석", "핵심 사유", "권장 행동"])
        out.to_csv(BUY_RISK_LIGHT_CSV, index=False, encoding="utf-8-sig")
        return out
    for _, r in src.head(800).iterrows():
        symbol_raw = first(r, ["종목코드", "symbol", "ticker", "종목", "code"], "")
        market = norm_market(first(r, ["시장", "market"], ""), symbol_raw)
        sym = sym_clean(symbol_raw, market)
        name = first(r, ["종목명", "name", "company"], "")
        label = add_symbol_label(sym or symbol_raw, name, market) if (sym or clean_text(symbol_raw, "")) else clean_text(first(r, ["종목"], ""), "")
        if not label:
            continue
        combined = " ".join(clean_text(r.get(c, ""), "") for c in r.index)
        # 위험 후보로 볼 조건을 명확하게 통일.
        hard = any(k in combined for k in ["매수금지", "신규매수 제외", "관망/제외", "신규매수 보류", "매수 위험"])
        chase = any(k in combined for k in ["추격", "과열", "갭상승"])
        rr = any(k in combined for k in ["손익비", "rr_pass=False", "RR 부족"])
        caution = any(k in combined for k in ["주의", "비중 축소", "감점", "관망", "소액/분할", "분할 검토", "확신도가 높지"])
        if not (hard or chase or rr or caution):
            continue
        if hard:
            risk = "신규매수 제외"
            interp = "지금은 신규 매수보다 보류가 우선입니다."
            action = "신규매수 보류"
        elif chase:
            risk = "추격/과열 주의"
            interp = "좋은 종목이어도 현재 위치가 부담일 수 있습니다."
            action = "진입가 대기/분할만 검토"
        elif rr:
            risk = "손익비 부족"
            interp = "손절폭 대비 기대수익이 부족합니다."
            action = "기준가 재조정 후 재확인"
        else:
            risk = "주의"
            interp = "매수 전 가격·수급·뉴스를 한 번 더 확인해야 합니다."
            action = "소액 또는 관망"
        reason = clean_text(first(r, ["핵심 사유", "사유", "이유", "감점근거", "reason", "초보자 해석"], ""), "가격·손익비·뉴스·수급 확인 필요")
        rows.append({"시장": market, "종목": label, "위험 구분": risk, "초보자 해석": interp, "핵심 사유": reason, "권장 행동": action})
    out = pd.DataFrame(rows)
    if not out.empty:
        order = {"신규매수 제외": 0, "추격/과열 주의": 1, "손익비 부족": 2, "주의": 3}
        out["_order"] = out["위험 구분"].map(order).fillna(9)
        out = out.sort_values(["시장", "_order", "종목"]).drop(columns=["_order"]).drop_duplicates(subset=["시장", "종목"], keep="first")
    else:
        out = pd.DataFrame(columns=["시장", "종목", "위험 구분", "초보자 해석", "핵심 사유", "권장 행동"])
    out.to_csv(BUY_RISK_LIGHT_CSV, index=False, encoding="utf-8-sig")
    return out


def _load_current_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    candidates = (
        list(REPORT_DIR.glob("*intraday*snapshot*.csv"))
        + list(REPORT_DIR.glob("*quote*.csv"))
        + list(REPORT_DIR.glob("*realtime*.csv"))
        + list(REPORT_DIR.glob("*current*.csv"))
        + list(DATA_DIR.glob("**/*price*.csv"))
        + list(DATA_DIR.glob("**/*ohlc*.csv"))
        + list(REPORT_DIR.glob("*ohlc*.csv"))
    )
    for p in candidates[:100]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        for _, r in df.iterrows():
            sym_raw = first(r, ["종목코드", "symbol", "ticker", "code", "종목"], "")
            market = norm_market(first(r, ["시장", "market"], ""), sym_raw)
            sym = sym_clean(sym_raw, market)
            if not sym:
                continue
            price = to_num(first(r, ["현재가", "current_price", "price", "close", "Close", "last", "종가"], math.nan))
            if not math.isnan(price) and price > 0:
                prices[sym.upper()] = price
                m = re.search(r"(\d{6})", sym)
                if m:
                    prices[m.group(1)] = price
    return prices


def _fetch_price(symbol: str, market: str) -> float:
    sym = sym_clean(symbol, market)
    if not sym:
        return math.nan
    # yfinance fallback. This is used only during background update, not during screen rendering.
    if yf is not None:
        tickers = [sym]
        if market_slug(market) == "kr":
            tickers = [f"{sym}.KS", f"{sym}.KQ"]
        for t in tickers:
            try:
                h = yf.Ticker(t).history(period="5d", interval="1d")
                if h is not None and not h.empty and "Close" in h.columns:
                    v = float(h["Close"].dropna().iloc[-1])
                    if v > 0:
                        return v
            except Exception:
                continue
    if market_slug(market) == "kr" and fdr is not None:
        try:
            h = fdr.DataReader(sym)
            if h is not None and not h.empty and "Close" in h.columns:
                v = float(h["Close"].dropna().iloc[-1])
                if v > 0:
                    return v
        except Exception:
            pass
    return math.nan


def _load_holdings() -> pd.DataFrame:
    # 실제 보유 파일을 우선. v50_position_plan 같은 결과 파일은 마지막 fallback.
    explicit = [
        DATA_DIR / "holdings_kr.csv", DATA_DIR / "holdings_us.csv",
        ROOT / "holdings_kr.csv", ROOT / "holdings_us.csv",
        DATA_DIR / "portfolio_kr.csv", DATA_DIR / "portfolio_us.csv",
        DATA_DIR / "portfolio" / "holdings.csv", DATA_DIR / "portfolio" / "positions.csv",
    ]
    globbed = list(DATA_DIR.glob("**/*holding*.csv")) + list(DATA_DIR.glob("**/*portfolio*.csv")) + list(DATA_DIR.glob("**/*position*.csv"))
    fallback = [REPORT_DIR / "v50_position_plan.csv", REPORT_DIR / "operational_sell_budget_kr.csv", REPORT_DIR / "operational_sell_budget_us.csv"]
    return _read_many(explicit + globbed + fallback)


def _market_from_symbol_and_source(row: pd.Series) -> str:
    sym_raw = first(row, ["종목코드", "symbol", "ticker", "code", "종목"], "")
    src = first(row, ["_source_file"], "")
    m = first(row, ["시장", "market"], "")
    if clean_text(m, ""):
        return norm_market(m, sym_raw)
    if "us" in str(src).lower():
        return "미국주식"
    if "kr" in str(src).lower():
        return "한국주식"
    return norm_market("", sym_raw)


def build_position_plan_light(fetch_missing_prices: bool = True) -> pd.DataFrame:
    holdings = _load_holdings()
    prices = _load_current_prices()
    rows: list[dict[str, Any]] = []
    if holdings.empty:
        out = pd.DataFrame(columns=["시장", "종목", "보유수량", "평단가", "현재가", "수익률", "권장행동", "권장수량", "예상금액", "초보자 안내"])
        out.to_csv(POSITION_LIGHT_CSV, index=False, encoding="utf-8-sig")
        return out
    for _, r in holdings.head(500).iterrows():
        market = _market_from_symbol_and_source(r)
        sym_raw = first(r, ["종목코드", "symbol", "ticker", "code", "종목"], "")
        sym = sym_clean(sym_raw, market)
        name = first(r, ["종목명", "name", "company", "종목명칭"], "")
        if not good_symbol(sym) and not clean_text(name, ""):
            # 진짜 보유종목이 아닌 placeholder만 제외합니다.
            continue
        qty = to_num(first(r, ["보유수량", "quantity", "qty", "shares", "수량"], math.nan))
        avg = to_num(first(r, ["평단가", "avg_price", "average_price", "평균단가", "매입가"], math.nan))
        # 결과 리포트에서 온 행은 권장수량만 있고 보유수량이 없을 수 있으므로 0으로 죽이지 않음.
        if math.isnan(qty):
            qty = to_num(first(r, ["권장수량", "권장매도수량", "recommended_qty"], math.nan))
        if math.isnan(qty) or qty < 0:
            qty = 0.0
        label = add_symbol_label(sym or sym_raw, name, market)
        cur = to_num(first(r, ["현재가", "current_price", "price"], math.nan))
        if (math.isnan(cur) or cur <= 0) and sym:
            cur = prices.get(sym.upper(), prices.get(sym, math.nan))
        source = "저장 현재가"
        if (math.isnan(cur) or cur <= 0) and sym and fetch_missing_prices:
            source = "실시간 fallback"
            cur = _fetch_price(sym, market)
        ret = ((cur - avg) / avg * 100.0) if not math.isnan(cur) and cur > 0 and not math.isnan(avg) and avg > 0 else math.nan
        action = clean_text(first(r, ["권장행동", "판단", "action"], ""), "")
        rec_qty = to_num(first(r, ["권장수량", "권장매도수량", "recommended_qty"], math.nan))
        if not action:
            if math.isnan(cur) or cur <= 0:
                action = "보유 점검"
            elif not math.isnan(ret) and ret <= -7:
                action = "손절/축소 검토"
            elif not math.isnan(ret) and ret >= 12:
                action = "일부 익절 검토"
            else:
                action = "보유 유지"
        if math.isnan(rec_qty):
            if action in {"손절/축소 검토"} and qty > 0:
                rec_qty = max(1, math.floor(qty * 0.3))
            elif action in {"일부 익절 검토"} and qty > 0:
                rec_qty = max(1, math.floor(qty * 0.25))
            else:
                rec_qty = 0.0
        amount = cur * rec_qty if not math.isnan(cur) and cur > 0 and rec_qty > 0 else math.nan
        if math.isnan(cur) or cur <= 0:
            guide = "현재가가 아직 미수신입니다. GitHub 동기화 또는 장중 갱신 후 다시 확인하세요. 행은 삭제하지 않고 보유 정보는 유지했습니다."
        elif action in {"손절/축소 검토"}:
            guide = "손실 구간입니다. 손절 기준 이탈 여부를 먼저 확인하고 성급한 추가매수는 피하세요."
        elif action in {"일부 익절 검토"}:
            guide = "수익 구간입니다. 목표가 근처면 일부 익절을 검토할 수 있습니다."
        else:
            guide = "보유 유지 가능 구간입니다. 실제 주문 전 증권사 현재가와 비교하세요."
        rows.append({
            "시장": market,
            "종목": label,
            "보유수량": fmt_qty(qty, market),
            "평단가": fmt_price(avg, market),
            "현재가": fmt_price(cur, market),
            "수익률": "-" if math.isnan(ret) else f"{ret:.2f}%",
            "권장행동": action,
            "권장수량": fmt_qty(rec_qty, market),
            "예상금액": fmt_price(amount, market),
            "초보자 안내": guide,
            "현재가 출처": source if not math.isnan(cur) and cur > 0 else "미수신",
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(subset=["시장", "종목"], keep="first")
        out = out.sort_values(["시장", "종목"])
    else:
        out = pd.DataFrame(columns=["시장", "종목", "보유수량", "평단가", "현재가", "수익률", "권장행동", "권장수량", "예상금액", "초보자 안내", "현재가 출처"])
    out.to_csv(POSITION_LIGHT_CSV, index=False, encoding="utf-8-sig")
    return out


def build_news_status(fetch_news: bool = False) -> dict[str, Any]:
    key_present = bool(get_secret("GNEWS_API_KEY") or get_secret("NEWS_API_KEY"))
    fetch_result: dict[str, Any] | None = None
    if fetch_news and key_present:
        try:
            fetch_result = save_gnews_reports()
        except Exception as exc:
            fetch_result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    kr = read_csv_safe(REPORT_DIR / "gnews_latest_kr.csv")
    us = read_csv_safe(REPORT_DIR / "gnews_latest_us.csv")
    cache = read_csv_safe(DATA_DIR / "news" / "gnews_cache.csv")
    ok_kr = int((kr.get("status", pd.Series(dtype=str)).astype(str).eq("OK")).sum()) if not kr.empty and "status" in kr.columns else int(len(kr)) if not kr.empty else 0
    ok_us = int((us.get("status", pd.Series(dtype=str)).astype(str).eq("OK")).sum()) if not us.empty and "status" in us.columns else int(len(us)) if not us.empty else 0
    errors: list[str] = []
    for df in (kr, us):
        if not df.empty and "error" in df.columns:
            errors += [clean_text(x, "") for x in df["error"].dropna().astype(str).tolist() if clean_text(x, "")]
    if not key_present:
        status = "키 미인식"
        guide = "로컬 앱 폴더의 .env 또는 GitHub Secrets에 GNEWS_API_KEY를 넣어야 합니다."
    elif ok_kr + ok_us > 0:
        status = "정상"
        guide = "뉴스가 수집되었습니다. LLM API가 없어도 제목/링크/설명 수집은 가능합니다."
    elif errors:
        status = "API 오류"
        guide = "키는 인식됐지만 API가 오류를 반환했습니다. 무료 한도, 키 값, GNews 대시보드를 확인하세요."
    else:
        status = "0건"
        guide = "키는 인식됐지만 검색 결과가 0건입니다. 쿼리/언어/국가 조건 또는 API 무료 한도를 확인하세요."
    data = {
        "updated_at": now(), "key_present": key_present, "status": status, "guide": guide,
        "kr_news": ok_kr, "us_news": ok_us, "cache_rows": int(len(cache)) if not cache.empty else 0,
        "fetch_result": fetch_result, "errors": errors[:5],
    }
    write_json(NEWS_STATUS_JSON, data)
    return data


def run_v52_update(fetch_news: bool = False, include_v50: bool = False, fetch_missing_prices: bool = True) -> dict[str, Any]:
    upstream = None
    if include_v50 and run_v50_update is not None:
        try:
            upstream = run_v50_update(fetch_news=False)
        except Exception as exc:
            upstream = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    action = build_action_board_light(fetch_missing_prices=fetch_missing_prices)
    risk = build_buy_risk_light()
    pos = build_position_plan_light(fetch_missing_prices=fetch_missing_prices)
    news = build_news_status(fetch_news=fetch_news)
    status = {
        "status": "OK", "updated_at": now(), "upstream_v50": upstream,
        "action_rows": int(len(action)), "risk_rows": int(len(risk)), "position_rows": int(len(pos)),
        "news_status": news,
        "note": "v52는 국장/미장 두 보기만 제공하고, 보유/매도 수량의 빈값을 현재가 fallback으로 최대한 채웁니다.",
    }
    write_json(STATUS_JSON, status)
    write_json(DATA_STATUS_JSON, status)
    return status


if __name__ == "__main__":
    print(json.dumps(run_v52_update(fetch_news=False), ensure_ascii=False, indent=2, default=str))
