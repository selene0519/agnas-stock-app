"""Operational Plus Engine for ARCFLOW/NEXORA local Streamlit app.

This module intentionally avoids network calls. It consolidates already-generated CSV/JSON
reports into user-facing tables for the 일반 모드 screens:
- budget / recommended quantity
- selected symbol supply & order-flow snapshot
- news narrative summaries
- valuation / financial KPI snapshots
- macro / market regime snapshot
- custom screener over local candidate reports

The functions are defensive: missing files return small empty tables rather than raising.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import json
import math
import re
from datetime import datetime

try:
    import pandas as pd
except Exception:  # pragma: no cover
    pd = None  # type: ignore

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"


def _empty_df():
    return pd.DataFrame() if pd is not None else []


def read_csv_safe(path: str | Path):
    if pd is None:
        return _empty_df()
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists() or p.stat().st_size == 0:
        return pd.DataFrame()
    try:
        return pd.read_csv(p, encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            return pd.read_csv(p, encoding="cp949")
        except Exception:
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def read_json_safe(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    if not p.exists() or p.stat().st_size == 0:
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:
            return {}


def _first(row: Any, names: Iterable[str], default: Any = "") -> Any:
    for name in names:
        try:
            if name in row:
                val = row.get(name)
                if val is not None and str(val).strip().lower() not in {"", "nan", "none", "nat", "-"}:
                    return val
        except Exception:
            continue
    return default


def _to_num(value: Any, default: float = math.nan) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        try:
            if math.isnan(float(value)):
                return default
        except Exception:
            pass
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat", "-", "미수신", "아니오"}:
        return default
    text = text.replace(",", "").replace("$", "").replace("₩", "").replace("원", "")
    text = text.replace("%", "")
    try:
        return float(text)
    except Exception:
        return default


def _market_slug(market: str) -> str:
    return "kr" if str(market).strip() in {"한국주식", "국장", "KR", "kr"} else "us"


def _market_label(market: str) -> str:
    return "한국주식" if _market_slug(market) == "kr" else "미국주식"


def _money(value: float, market: str) -> str:
    if value is None or math.isnan(float(value)):
        return "-"
    if _market_slug(market) == "kr":
        return f"{float(value):,.0f}원"
    return f"${float(value):,.2f}"


def _qty(value: float, market: str, allow_fractional: bool = False) -> str:
    if value is None or math.isnan(float(value)) or float(value) <= 0:
        return "0"
    if _market_slug(market) == "us" and allow_fractional:
        return f"{float(value):,.3f}주"
    return f"{math.floor(float(value)):,.0f}주"


def _candidate_paths(market: str) -> list[Path]:
    """Return candidate-like files in priority order.

    Earlier v37/v40 builds only looked at A/B swing CSVs.  In real use those files
    can be empty while predictions.csv, watchlist or risk reports still contain
    actionable rows.  This broader list keeps user-facing tables populated and
    avoids the confusing "후보 CSV 없음" state.
    """
    slug = _market_slug(market)
    explicit = [
        REPORT_DIR / f"swing_candidates_{slug}_A_top3.csv",
        REPORT_DIR / f"swing_candidates_{slug}_B_watch.csv",
        REPORT_DIR / f"swing_candidates_{slug}_C_excluded.csv",
        REPORT_DIR / f"risk_priority_candidates_{slug}.csv",
        REPORT_DIR / "risk_priority_candidates.csv",
        REPORT_DIR / f"operational_buy_budget_{slug}.csv",
        ROOT / "predictions.csv",
        REPORT_DIR / "predictions.csv",
        ROOT / f"watchlist_{slug}_growth.csv",
        ROOT / f"watchlist_{slug}.csv",
        ROOT / f"candidate_universe_{slug}.csv",
    ]
    patterns = [
        f"*candidate*{slug}*.csv", f"*{slug}*candidate*.csv",
        "*buy*candidate*.csv", "*risk*priority*.csv", "*prediction*.csv",
    ]
    extra: list[Path] = []
    for base in [REPORT_DIR, ROOT, DATA_DIR]:
        if not base.exists():
            continue
        for pat in patterns:
            extra.extend(base.glob(pat))
    out: list[Path] = []
    for p in explicit + extra:
        if p not in out:
            out.append(p)
    return out


def _looks_like_market(value: Any, market: str) -> bool:
    text = str(value or "").strip().lower()
    if not text or text in {"nan", "none", "nat", "-"}:
        return True
    if _market_slug(market) == "kr":
        return any(x in text for x in ["한국", "국장", "kr", "korea", "kospi", "kosdaq"])
    return any(x in text for x in ["미국", "미장", "us", "usa", "nasdaq", "nyse", "amex"])


def load_candidate_pool(market: str, include_c: bool = False):
    if pd is None:
        return _empty_df()
    frames = []
    for path in _candidate_paths(market):
        df = read_csv_safe(path)
        if df.empty:
            continue
        df = df.copy()
        df["_source_file"] = str(path.relative_to(ROOT)) if path.is_absolute() and str(path).startswith(str(ROOT)) else str(path)
        # C/excluded files are not default buy candidates, but are used in risk screens.
        if "C_excluded" in path.name and not include_c:
            continue
        # Apply market filter only when the file clearly has a market column.
        for mc in ["market", "시장"]:
            if mc in df.columns:
                maybe = df[df[mc].map(lambda x: _looks_like_market(x, market))].copy()
                if not maybe.empty:
                    df = maybe
                break
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    if "symbol" not in out.columns:
        for c in ["ticker", "종목코드", "티커", "종목", "code"]:
            if c in out.columns:
                out["symbol"] = out[c]
                break
    if "name" not in out.columns:
        for c in ["종목명", "stock_name", "company", "회사명"]:
            if c in out.columns:
                out["name"] = out[c]
                break
    if "symbol" in out.columns:
        out["_symbol_norm"] = out["symbol"].astype(str).str.upper().str.strip()
        out = out[~out["_symbol_norm"].isin(["", "-", "NAN", "NONE", "NAT"])]
        out = out.drop_duplicates(subset=["_symbol_norm"], keep="first")
    return out.reset_index(drop=True)


def load_holdings(market: str):
    if pd is None:
        return _empty_df()
    slug = _market_slug(market)
    paths = [
        ROOT / f"holdings_{slug}.csv",
        DATA_DIR / f"holdings_{slug}.csv",
        DATA_DIR / "portfolio" / f"holdings_{slug}.csv",
        ROOT / "holdings.csv",
        DATA_DIR / "holdings.csv",
    ]
    frames = []
    for p in paths:
        df = read_csv_safe(p)
        if not df.empty:
            df = df.copy()
            df["_source_file"] = str(p.relative_to(ROOT)) if p.is_absolute() else str(p)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True, sort=False)
    if "market" in out.columns:
        mlabel = _market_label(market)
        maybe = out[out["market"].astype(str).eq(mlabel)].copy()
        if not maybe.empty:
            out = maybe
    if "symbol" not in out.columns:
        for c in ["ticker", "종목코드", "티커", "종목"]:
            if c in out.columns:
                out["symbol"] = out[c]
                break
    return out


def operation_settings(market: str) -> dict[str, Any]:
    defaults = {
        "account_capital": 10_000_000.0 if _market_slug(market) == "kr" else 10_000.0,
        "available_cash": 10_000_000.0 if _market_slug(market) == "kr" else 10_000.0,
        "risk_per_trade_pct": 0.7,
        "max_position_pct": 20.0,
        "allow_fractional_shares": False,
    }
    for p in [DATA_DIR / "user_operation_settings.json", DATA_DIR / "operation_settings.json"]:
        raw = read_json_safe(p)
        if not raw:
            continue
        # Accept either flat json or market-specific json.
        candidates = [raw]
        for key in [market, _market_label(market), _market_slug(market), "default"]:
            if isinstance(raw.get(key), dict):
                candidates.insert(0, raw[key])
        for src in candidates:
            for k in defaults:
                if k in src:
                    defaults[k] = src[k]
    return defaults


def _candidate_row_to_budget(row: Any, market: str, settings: dict[str, Any]) -> dict[str, Any]:
    symbol = str(_first(row, ["symbol", "ticker", "종목코드", "티커", "종목"], "-")).upper()
    name = _first(row, ["name", "종목명", "company", "회사명"], "-")
    current = _to_num(_first(row, ["current_price", "현재가", "price", "close", "last", "realtime_price"]))
    entry = _to_num(_first(row, ["entry", "entry_price", "buy_price", "우선진입가", "조건부 진입가", "recommended_entry", "ideal_entry"]))
    stop = _to_num(_first(row, ["stop", "stop_price", "손절가", "risk_stop", "loss_cut_price"]))
    tp1 = _to_num(_first(row, ["tp1", "target1", "1차익절가", "1차 목표가", "target_price_1"]))
    if math.isnan(entry) and not math.isnan(current):
        entry = current
    rr = _to_num(_first(row, ["rr1", "risk_reward", "손익비", "rr", "risk_reward_ratio"]))
    if math.isnan(rr) and not math.isnan(entry) and not math.isnan(stop) and not math.isnan(tp1) and entry > stop:
        rr = (tp1 - entry) / (entry - stop)
    account = _to_num(settings.get("account_capital"), 10_000_000 if _market_slug(market) == "kr" else 10_000)
    cash = _to_num(settings.get("available_cash"), account)
    risk_pct = _to_num(settings.get("risk_per_trade_pct"), 0.7)
    max_pct = _to_num(settings.get("max_position_pct"), 20.0)
    allow_fractional = bool(settings.get("allow_fractional_shares", False))
    risk_budget = max(0.0, account * risk_pct / 100.0)
    cap_budget = max(0.0, min(cash, account * max_pct / 100.0))
    qty_by_cap = cap_budget / entry if entry and entry > 0 else 0.0
    per_share_risk = entry - stop if not math.isnan(stop) and not math.isnan(entry) else math.nan
    qty_by_risk = risk_budget / per_share_risk if per_share_risk and per_share_risk > 0 else qty_by_cap
    qty_raw = max(0.0, min(qty_by_cap, qty_by_risk))
    if _market_slug(market) != "us" or not allow_fractional:
        qty_out = math.floor(qty_raw)
    else:
        qty_out = qty_raw
    order_amt = qty_out * entry if entry and entry > 0 else 0.0
    split_1, split_2 = qty_out * 0.5, qty_out * 0.3
    split_3 = max(0.0, qty_out - split_1 - split_2)
    if _market_slug(market) != "us" or not allow_fractional:
        split_1, split_2 = math.floor(split_1), math.floor(split_2)
        split_3 = max(0, math.floor(qty_out) - split_1 - split_2)
    action = str(_first(row, ["final_decision", "final_action", "final_decision_after_no_buy_filter", "매수행동", "판정", "risk_priority_action"], "확인 필요"))
    reason = str(_first(row, ["risk_priority_reason", "reason", "action_reason", "주의사유", "aggressive_reasons", "decision_reason"], "-"))
    if qty_out <= 0:
        qty_reason = "진입가/현금/손절 기준 확인 필요"
    elif not math.isnan(per_share_risk) and per_share_risk > 0:
        qty_reason = "계좌 리스크와 종목당 최대 비중 중 작은 값"
    else:
        qty_reason = "손절가 없음 — 종목당 최대 비중 기준"
    return {
        "종목코드": symbol,
        "종목명": name,
        "시장": _market_label(market),
        "판단": action,
        "현재가": _money(current, market),
        "진입가": _money(entry, market),
        "손절가": _money(stop, market),
        "1차목표": _money(tp1, market),
        "손익비": "-" if math.isnan(rr) else f"{rr:.2f}",
        "권장수량": _qty(qty_out, market, allow_fractional),
        "주문예상금액": _money(order_amt, market),
        "분할계획": f"1차 {_qty(split_1, market, allow_fractional)} / 2차 {_qty(split_2, market, allow_fractional)} / 3차 {_qty(split_3, market, allow_fractional)}",
        "1R위험금액": _money(min(risk_budget, max(0.0, qty_out * per_share_risk)) if not math.isnan(per_share_risk) else math.nan, market),
        "수량근거": qty_reason,
        "주의": reason[:180] if reason else "-",
    }


def build_buy_budget_table(market: str, limit: int = 40):
    if pd is None:
        return _empty_df()
    df = load_candidate_pool(market, include_c=False)
    if df.empty:
        # Last-resort: watchlist rows still let the user see that the app has symbols,
        # but criteria are missing.  This is much clearer than a blank table.
        df = load_holdings(market)
    if df.empty:
        return pd.DataFrame()
    settings = operation_settings(market)
    rows = [_candidate_row_to_budget(r, market, settings) for _, r in df.head(limit).iterrows()]
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    # Move rows with usable quantity and visible entry criteria to the top.
    try:
        out["_qty_num"] = out["권장수량"].astype(str).str.replace("주", "", regex=False).str.replace(",", "", regex=False).astype(float)
        out["_has_entry"] = ~out["진입가"].astype(str).isin(["-", "$nan", "nan", "0원", "$0.00"])
        out = out.sort_values(["_has_entry", "_qty_num"], ascending=[False, False]).drop(columns=["_qty_num", "_has_entry"], errors="ignore")
    except Exception:
        pass
    return out.head(limit)


def build_sell_budget_table(market: str, limit: int = 80):
    if pd is None:
        return _empty_df()
    sources = [
        REPORT_DIR / "portfolio_response_summary.csv",
        REPORT_DIR / "sell_management_summary.csv",
        DATA_DIR / "portfolio" / "position_daily_snapshot.csv",
    ]
    frames = [read_csv_safe(p) for p in sources]
    frames = [x for x in frames if not x.empty]
    if not frames:
        frames = [load_holdings(market)]
    frames = [x for x in frames if not x.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    if "market" in df.columns:
        maybe = df[df["market"].astype(str).eq(_market_label(market))].copy()
        if not maybe.empty:
            df = maybe
    rows = []
    for _, r in df.head(limit).iterrows():
        symbol = str(_first(r, ["symbol", "ticker", "종목코드", "티커", "종목"], "-")).upper()
        name = _first(r, ["name", "종목명", "company", "회사명"], "-")
        qty_n = _to_num(_first(r, ["quantity", "shares", "보유수량", "수량"], 0), 0)
        avg = _to_num(_first(r, ["avg_price", "average_price", "평단가", "매입가"], math.nan))
        cur = _to_num(_first(r, ["current_price", "현재가", "price", "close"], math.nan))
        action = str(_first(r, ["hold_or_sell_decision", "sell_timing_label", "portfolio_action", "action", "매도판단", "보유판단"], "보유 점검"))
        reason = str(_first(r, ["sell_reasons", "portfolio_action_reason", "reason", "sell_warnings", "사유"], "-"))
        sell_ratio = 0.0
        if any(k in action for k in ["손절", "매도", "전량", "이탈"]):
            sell_ratio = 1.0
        elif any(k in action for k in ["축소", "익절", "부분"]):
            sell_ratio = 0.5
        elif any(k in action for k in ["주의", "확인"]):
            sell_ratio = 0.25
        sell_qty = qty_n * sell_ratio
        if _market_slug(market) != "us":
            sell_qty = math.floor(sell_qty)
        pnl_pct = (cur / avg - 1) * 100 if avg and avg > 0 and cur and cur > 0 else math.nan
        rows.append({
            "종목코드": symbol,
            "종목명": name,
            "시장": _market_label(market),
            "보유수량": _qty(qty_n, market, False),
            "평단가": _money(avg, market),
            "현재가": _money(cur, market),
            "수익률": "-" if math.isnan(pnl_pct) else f"{pnl_pct:+.2f}%",
            "판단": action,
            "권장매도수량": _qty(sell_qty, market, False),
            "예상회수금액": _money(sell_qty * cur if cur and not math.isnan(cur) else math.nan, market),
            "사유": reason[:180] if reason else "-",
        })
    return pd.DataFrame(rows)


def _symbol_options_from_frames(market: str) -> list[str]:
    opts: list[str] = []
    for df in [load_candidate_pool(market, include_c=True), load_holdings(market)]:
        if df is None or df.empty:
            continue
        for c in ["symbol", "ticker", "종목코드", "티커", "종목"]:
            if c in df.columns:
                vals = [str(x).upper().strip() for x in df[c].dropna().tolist() if str(x).strip()]
                opts.extend(vals)
                break
    seen = []
    for x in opts:
        if x not in seen and x not in {"-", "NAN", "NONE"}:
            seen.append(x)
    return seen[:200]


def symbol_options(market: str) -> list[str]:
    return _symbol_options_from_frames(market)


def _filter_symbol(df, symbol: str):
    if df is None or df.empty or not symbol:
        return df.iloc[0:0].copy() if df is not None and hasattr(df, "iloc") else _empty_df()
    sym = str(symbol).upper().strip()
    for c in ["symbol", "ticker", "종목코드", "티커", "종목"]:
        if c in df.columns:
            out = df[df[c].astype(str).str.upper().str.strip().eq(sym)].copy()
            if not out.empty:
                return out
    return df.iloc[0:0].copy()


def _valid_numbers_from_row(row: Any, cols: list[str]) -> list[float]:
    vals: list[float] = []
    for c in cols:
        try:
            if c in row.index:
                v = _to_num(row.get(c), math.nan)
                if not math.isnan(v):
                    vals.append(v)
        except Exception:
            continue
    return vals


def _fmt_pct_num(value: Any) -> str:
    v = _to_num(value, math.nan)
    if math.isnan(v):
        return "-"
    return f"{v:.2f}%"


def build_selected_symbol_flow(market: str, symbol: str) -> dict[str, Any]:
    candidates = load_candidate_pool(market, include_c=True)
    cand = _filter_symbol(candidates, symbol)
    quote_paths = [REPORT_DIR / f"intraday_realtime_snapshot_{_market_slug(market)}.csv", REPORT_DIR / "intraday_realtime_snapshot.csv"]
    order_paths = [REPORT_DIR / f"intraday_orderbook_snapshot_{_market_slug(market)}.csv", REPORT_DIR / "intraday_orderbook_snapshot.csv"]
    flow_paths = [REPORT_DIR / f"intraday_flow_snapshot_{_market_slug(market)}.csv", REPORT_DIR / "intraday_flow_snapshot.csv"]
    sector_paths = [REPORT_DIR / f"intraday_sector_flow_snapshot_{_market_slug(market)}.csv", REPORT_DIR / "intraday_sector_flow_snapshot.csv"]
    def first_match(paths):
        for p in paths:
            m = _filter_symbol(read_csv_safe(p), symbol)
            if not m.empty:
                return m
        return _empty_df()
    quote, order, flow, sector = first_match(quote_paths), first_match(order_paths), first_match(flow_paths), first_match(sector_paths)
    rows = []

    # 후보/기준가
    if cand is None or cand.empty:
        rows.append({"구분": "후보/기준가", "상태": "데이터 없음", "핵심 요약": "후보 리포트에 없음", "초보자 해석": "관심종목이지만 현재 매수 기준가가 생성되지 않았습니다.", "다음 행동": "장전 업데이트 또는 후보 스캔을 먼저 실행"})
    else:
        r = cand.iloc[0]
        entry = _first(r, ["entry", "entry_price", "우선진입가", "조건부 진입가", "preferred_entry"], "-")
        stop = _first(r, ["stop", "stop_price", "손절가", "stop_loss"], "-")
        tp1 = _first(r, ["tp1", "target1", "1차익절가", "target_price", "1차 목표가"], "-")
        decision = _first(r, ["final_decision", "risk_final_decision", "판정", "매수행동", "grade"], "확인 필요")
        rows.append({"구분": "후보/기준가", "상태": "수신", "핵심 요약": f"진입 {entry} / 손절 {stop} / 목표 {tp1}", "초보자 해석": str(decision), "다음 행동": "현재가가 진입가 근처인지 먼저 확인"})

    # 현재가
    if quote is None or quote.empty:
        rows.append({"구분": "현재가", "상태": "미수신", "핵심 요약": "현재가 없음", "초보자 해석": "실시간/저장 현재가가 없습니다.", "다음 행동": "run_intraday_refresh.bat 실행 또는 API 설정 확인"})
    else:
        r = quote.iloc[0]
        cur = _first(r, ["current_price", "현재가", "price", "last_price"], "-")
        chg = _first(r, ["change_pct", "장중등락률", "등락률"], "-")
        vol = _first(r, ["volume", "장중 거래량", "거래량"], "-")
        rows.append({"구분": "현재가", "상태": "수신", "핵심 요약": f"현재가 {cur} / 등락 {chg} / 거래량 {vol}", "초보자 해석": "가격 기준은 확인됨", "다음 행동": "진입가·손절가와 거리 확인"})

    # 호가
    if order is None or order.empty:
        rows.append({"구분": "호가", "상태": "미수신", "핵심 요약": "호가 없음", "초보자 해석": "매수·매도 잔량 근거가 없습니다.", "다음 행동": "호가 판단은 제외하고 가격/거래량 중심으로 보기"})
    else:
        r = order.iloc[0]
        bid = _first(r, ["bid_total_volume", "매수잔량"], "-")
        ask = _first(r, ["ask_total_volume", "매도잔량"], "-")
        ratio = _first(r, ["bid_ask_ratio", "매수/매도 잔량비"], "-")
        spread = _first(r, ["spread_pct", "스프레드"], "-")
        nums = _valid_numbers_from_row(r, ["bid_total_volume", "ask_total_volume", "bid_ask_ratio", "orderbook_imbalance", "spread_pct", "execution_strength"])
        if not nums or all(abs(x) < 1e-12 for x in nums):
            rows.append({"구분": "호가", "상태": "미수신", "핵심 요약": "잔량/스프레드 값 없음", "초보자 해석": "API가 호가를 제공하지 않았거나 장외 시간입니다.", "다음 행동": "호가 근거는 매수 판단에서 제외"})
        else:
            rows.append({"구분": "호가", "상태": "수신", "핵심 요약": f"매수잔량 {bid} / 매도잔량 {ask} / 잔량비 {ratio}", "초보자 해석": f"스프레드 {spread}", "다음 행동": "스프레드가 크면 지정가·분할만 고려"})

    # 수급
    if flow is None or flow.empty:
        rows.append({"구분": "수급", "상태": "미수신", "핵심 요약": "수급 없음", "초보자 해석": "외국인/기관/프로그램 수급 근거가 없습니다.", "다음 행동": "수급 점수는 보수적으로 0점 처리"})
    else:
        r = flow.iloc[0]
        score = _first(r, ["flow_score", "수급점수"], "-")
        label = _first(r, ["flow_label", "수급라벨"], "-")
        nums = _valid_numbers_from_row(r, ["program_net_buy", "foreign_net_buy", "institution_net_buy", "retail_net_buy", "flow_score"])
        if not nums or all(abs(x) < 1e-12 for x in nums):
            rows.append({"구분": "수급", "상태": "데이터 부족", "핵심 요약": "수급 값 0 또는 없음", "초보자 해석": "실제 매수세가 없다는 뜻이 아니라 수집값이 부족하다는 뜻입니다.", "다음 행동": "수급 근거는 제외하고 차트·가격 기준 우선"})
        else:
            rows.append({"구분": "수급", "상태": "수신", "핵심 요약": f"수급점수 {score} / {label}", "초보자 해석": "양수면 매수세 우위, 음수면 매도세 우위로 참고", "다음 행동": "가격 신호와 같은 방향인지 확인"})

    # 업종
    if sector is None or sector.empty:
        rows.append({"구분": "업종", "상태": "데이터 없음", "핵심 요약": "업종 흐름 없음", "초보자 해석": "섹터 보정 근거가 없습니다.", "다음 행동": "시장·거시 화면에서 섹터 분위기 확인"})
    else:
        r = sector.iloc[0]
        sec = _first(r, ["sector", "업종", "섹터"], "-")
        chg = _first(r, ["sector_change_pct", "섹터등락률"], "-")
        lab = _first(r, ["sector_flow_label", "sector_flow_score", "섹터수급"], "-")
        rows.append({"구분": "업종", "상태": "수신", "핵심 요약": f"{sec} / 등락 {chg}", "초보자 해석": f"업종 흐름 {lab}", "다음 행동": "종목 방향과 업종 방향이 같은지 확인"})

    return {
        "symbol": symbol,
        "market": _market_label(market),
        "summary": pd.DataFrame(rows) if pd is not None else rows,
        "candidate": cand,
        "quote": quote,
        "orderbook": order,
        "flow": flow,
        "sector": sector,
    }


def _find_files(patterns: Iterable[str]) -> list[Path]:
    out: list[Path] = []
    for base in [REPORT_DIR, DATA_DIR, ROOT]:
        if not base.exists():
            continue
        for pat in patterns:
            out.extend(base.glob(pat))
    seen = []
    for p in out:
        if p.exists() and p not in seen:
            seen.append(p)
    return seen


def build_news_narrative_table(market: str, limit: int = 50):
    if pd is None:
        return _empty_df()
    paths = _find_files(["*news*.csv", "news/*.csv", "*catalyst*.csv"])
    frames = []
    for p in paths:
        df = read_csv_safe(p)
        if df.empty:
            continue
        df = df.copy()
        df["_source_file"] = str(p.relative_to(ROOT)) if p.is_absolute() else str(p)
        frames.append(df)
    candidates = load_candidate_pool(market, include_c=False)
    if not candidates.empty:
        keep_cols = [c for c in ["symbol", "name", "catalyst_reasons", "catalyst_warnings", "aggressive_reasons", "aggressive_warnings", "final_decision", "grade"] if c in candidates.columns]
        if keep_cols:
            cdf = candidates[keep_cols].copy()
            cdf["_source_file"] = "candidate_reports"
            frames.append(cdf)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True, sort=False)
    rows = []
    for _, r in raw.head(300).iterrows():
        symbol = str(_first(r, ["symbol", "ticker", "종목코드", "티커", "종목"], "-")).upper()
        title = str(_first(r, ["title", "headline", "news_title", "제목", "name", "종목명"], "-"))
        summary = str(_first(r, ["summary", "description", "news_summary", "요약", "catalyst_reasons", "aggressive_reasons"], "-"))
        warning = str(_first(r, ["risk", "warning", "catalyst_warnings", "aggressive_warnings", "위험", "주의"], "-"))
        sentiment = str(_first(r, ["sentiment", "sentiment_label", "news_sentiment", "tone"], "중립"))
        if title == "-" and summary == "-":
            continue
        rows.append({
            "종목코드": symbol,
            "제목/종목": title[:120],
            "한글 요약": _simple_korean_news_summary(summary, warning),
            "감성": _normalize_sentiment(sentiment, summary, warning),
            "리스크 키워드": _extract_risk_keywords(f"{summary} {warning}"),
            "출처": str(r.get("_source_file", "-")),
        })
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    out = out.drop_duplicates(subset=["종목코드", "제목/종목", "한글 요약"], keep="first")
    return out.head(limit)


def _simple_korean_news_summary(summary: str, warning: str = "") -> str:
    text = re.sub(r"\s+", " ", str(summary or "").strip())
    warn = re.sub(r"\s+", " ", str(warning or "").strip())
    if not text or text == "-":
        text = "후보 리포트 기준 설명이 아직 부족합니다."
    if warn and warn != "-":
        return f"{text[:180]} / 주의: {warn[:100]}"
    return text[:220]


def _normalize_sentiment(raw: str, summary: str = "", warning: str = "") -> str:
    text = f"{raw} {summary} {warning}".lower()
    if any(k in text for k in ["bear", "negative", "risk", "warn", "down", "하락", "위험", "주의", "손절", "악재"]):
        return "부정/주의"
    if any(k in text for k in ["bull", "positive", "up", "growth", "beat", "상승", "호재", "강세", "성장"]):
        return "긍정"
    return "중립"


def _extract_risk_keywords(text: str) -> str:
    keys = []
    source = str(text or "")
    mapping = [
        ("실적", ["earn", "guidance", "revenue", "margin", "실적", "매출", "이익"]),
        ("금리", ["rate", "yield", "fed", "금리", "국채"]),
        ("규제", ["regulat", "lawsuit", "sec", "규제", "소송"]),
        ("수급", ["flow", "volume", "거래량", "수급", "기관", "외국인"]),
        ("과열", ["overheat", "chase", "과열", "추격", "고점"]),
        ("환율", ["fx", "currency", "dollar", "환율", "달러"]),
    ]
    low = source.lower()
    for label, pats in mapping:
        if any(p.lower() in low for p in pats):
            keys.append(label)
    return ", ".join(keys) if keys else "-"


def build_financial_kpi_table(market: str, limit: int = 80):
    if pd is None:
        return _empty_df()
    paths = _find_files(["*financial*.csv", "*valuation*.csv", "*fundamental*.csv", "*dart*.csv", "*kpi*.csv"])
    frames = []
    for p in paths:
        df = read_csv_safe(p)
        if df.empty:
            continue
        df = df.copy()
        df["_source_file"] = str(p.relative_to(ROOT)) if p.is_absolute() else str(p)
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    raw = pd.concat(frames, ignore_index=True, sort=False)
    if "market" in raw.columns:
        maybe = raw[raw["market"].astype(str).eq(_market_label(market))]
        if not maybe.empty:
            raw = maybe.copy()
    rows = []
    for _, r in raw.head(limit * 3).iterrows():
        symbol = str(_first(r, ["symbol", "ticker", "corp_code", "종목코드", "티커"], "-")).upper()
        name = _first(r, ["name", "corp_name", "종목명", "company"], "-")
        rows.append({
            "종목코드": symbol,
            "종목명": name,
            "매출": _first(r, ["revenue", "sales", "매출액"], "-"),
            "영업이익": _first(r, ["operating_income", "op_income", "영업이익"], "-"),
            "순이익": _first(r, ["net_income", "순이익"], "-"),
            "PER": _first(r, ["per", "PER"], "-"),
            "PBR": _first(r, ["pbr", "PBR"], "-"),
            "ROE": _first(r, ["roe", "ROE"], "-"),
            "부채비율": _first(r, ["debt_ratio", "부채비율"], "-"),
            "영업이익률": _first(r, ["operating_margin", "op_margin", "영업이익률"], "-"),
            "가치판단": _first(r, ["valuation_label", "financial_judgment", "judgment", "평가"], "-"),
            "출처": str(r.get("_source_file", "-")),
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.drop_duplicates(subset=["종목코드", "종목명"], keep="first").head(limit)


def build_macro_table(market: str):
    if pd is None:
        return _empty_df()
    rows = []
    for path, label in [
        (REPORT_DIR / "market_regime_summary.json", "시장 국면"),
        (REPORT_DIR / "market_breadth_summary.json", "시장 폭"),
        (REPORT_DIR / "api_data_status_center.json", "데이터 상태"),
        (REPORT_DIR / "portfolio_risk_metrics.json", "포트폴리오 리스크"),
    ]:
        data = read_json_safe(path)
        if not data:
            rows.append({"구분": label, "상태": "파일 없음", "핵심 판단": "-", "보조 지표": "-"})
            continue
        rows.append({
            "구분": label,
            "상태": data.get("overall_status") or data.get("status") or "확인",
            "핵심 판단": data.get("market_regime") or data.get("strategy_mode") or data.get("portfolio_risk_level") or data.get("summary") or "-",
            "보조 지표": ", ".join(f"{k}:{v}" for k, v in list(data.items())[:5] if not isinstance(v, (dict, list)))[:220],
        })
    bench = read_csv_safe(DATA_DIR / "market" / "benchmark_daily.csv")
    if not bench.empty:
        rows.append({"구분": "벤치마크", "상태": f"{len(bench)}행", "핵심 판단": "시장 누적 데이터 있음", "보조 지표": ", ".join(bench.columns[:8])})
    return pd.DataFrame(rows)


def build_custom_screener(market: str, min_prob: float = 0.0, min_rr: float = 0.0, require_positive_news: bool = False, exclude_chase: bool = True, limit: int = 100):
    if pd is None:
        return _empty_df()
    df = load_candidate_pool(market, include_c=True)
    if df.empty:
        return pd.DataFrame()
    work = df.copy()
    prob_cols = [c for c in ["prob_up_5d", "prob_tp1_5d", "상승확률", "success_probability", "confidence_score", "신뢰도"] if c in work.columns]
    rr_cols = [c for c in ["rr1", "risk_reward", "손익비", "rr", "risk_reward_ratio"] if c in work.columns]
    if prob_cols:
        work["_prob"] = work[prob_cols[0]].apply(lambda x: _to_num(x, math.nan))
        # Accept both 0~1 and 0~100 formats.
        p = work["_prob"].copy()
        p100 = p.where(p > 1, p * 100)
        work = work[p100.fillna(0) >= min_prob]
    if rr_cols:
        work["_rr"] = work[rr_cols[0]].apply(lambda x: _to_num(x, math.nan))
        work = work[work["_rr"].fillna(0) >= min_rr]
    if exclude_chase:
        pieces = []
        for c in ["aggressive_warnings", "risk_priority_reason", "주의사유", "chase_risk", "final_decision", "exclude_reason", "hard_filter_reason"]:
            if c in work.columns:
                pieces.append(work[c].astype(str))
        if pieces:
            text = pieces[0]
            for p in pieces[1:]:
                text = text + " " + p
            work = work[~text.str.contains("추격|과열|고점|제외|금지", regex=True, na=False)]
    if require_positive_news:
        pieces = []
        for c in ["catalyst_reasons", "aggressive_reasons", "news_summary", "title", "reason"]:
            if c in work.columns:
                pieces.append(work[c].astype(str))
        if pieces:
            text = pieces[0]
            for p in pieces[1:]:
                text = text + " " + p
            work = work[text.str.contains("호재|상승|강세|성장|positive|bull|beat", case=False, regex=True, na=False)]
        else:
            work = work.iloc[0:0]
    rows = []
    for _, r in work.head(limit).iterrows():
        rows.append({
            "종목코드": str(_first(r, ["symbol", "ticker", "종목코드", "티커", "종목"], "-")).upper(),
            "종목명": _first(r, ["name", "종목명", "company", "회사명"], "-"),
            "판정": _first(r, ["final_decision", "risk_final_decision", "판정", "grade"], "-"),
            "진입가": _first(r, ["entry", "entry_price", "우선진입가", "조건부 진입가", "preferred_entry"], "-"),
            "손절가": _first(r, ["stop", "stop_price", "손절가", "stop_loss"], "-"),
            "1차목표": _first(r, ["tp1", "target1", "1차익절가", "target_price", "1차 목표가"], "-"),
            "손익비": _first(r, ["rr1", "risk_reward", "손익비", "rr"], "-"),
            "상승확률/신뢰도": _first(r, ["prob_up_5d", "prob_tp1_5d", "상승확률", "confidence_score", "신뢰도"], "-"),
            "사유": str(_first(r, ["aggressive_reasons", "reason", "주의사유", "risk_priority_reason"], "-"))[:180],
        })
    return pd.DataFrame(rows)
