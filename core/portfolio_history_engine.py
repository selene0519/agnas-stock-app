"""Portfolio history accumulation and risk metrics.

This module is intentionally dependency-light and safe to run repeatedly.
It appends/updates one row per day so Streamlit reruns do not duplicate data.

Outputs
-------
- data/portfolio/portfolio_daily_nav.csv
- data/portfolio/position_daily_snapshot.csv
- data/market/benchmark_daily.csv
- reports/portfolio_risk_metrics.json
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

try:
    from core.portfolio_risk_manager import load_all_holdings, build_sector_metadata_map
except Exception:  # pragma: no cover - defensive import fallback
    load_all_holdings = None  # type: ignore
    build_sector_metadata_map = None  # type: ignore

PROJECT_ROOT = Path(".")
REPORT_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"
PORTFOLIO_DIR = DATA_DIR / "portfolio"
MARKET_DIR = DATA_DIR / "market"
DECISION_DIR = DATA_DIR / "decision_system"

PORTFOLIO_DAILY_NAV_CSV = PORTFOLIO_DIR / "portfolio_daily_nav.csv"
POSITION_DAILY_SNAPSHOT_CSV = PORTFOLIO_DIR / "position_daily_snapshot.csv"
BENCHMARK_DAILY_CSV = MARKET_DIR / "benchmark_daily.csv"
PORTFOLIO_RISK_METRICS_JSON = REPORT_DIR / "portfolio_risk_metrics.json"
PORTFOLIO_SETTINGS_JSON = PORTFOLIO_DIR / "portfolio_settings.json"

EMPTY_STRINGS = {"", "-", "N/A", "NA", "None", "none", "nan", "NaN", "저장값 없음", "데이터 없음", "현재가 미수신", "가격 기준 미산출"}

PRICE_SOURCE_FILES = [
    REPORT_DIR / "intraday_realtime_snapshot.csv",
    REPORT_DIR / "buy_priority_candidates.csv",
    REPORT_DIR / "watchlist_buy_candidates.csv",
    REPORT_DIR / "swing_candidates.csv",
    REPORT_DIR / "swing_candidates_kr.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    DECISION_DIR / "actual_results.csv",
]

CANDIDATE_BENCHMARK_NAMES = {
    "KOSPI", "KOSDAQ", "S&P500", "S&P 500", "SP500", "NASDAQ", "NASDAQ100",
    "^KS11", "^KQ11", "^GSPC", "^IXIC", "SPY", "QQQ", "DIA", "IWM",
}

BENCHMARK_SOURCES = {
    "KOSPI": ["^KS11", "KOSPI", "코스피"],
    "KOSDAQ": ["^KQ11", "KOSDAQ", "코스닥"],
    "S&P500": ["^GSPC", "SPY", "S&P500", "S&P 500", "SP500"],
    "NASDAQ": ["^IXIC", "QQQ", "NASDAQ", "나스닥"],
}

INDEX_OHLCV_BENCHMARK_FILES = {
    "KOSPI": MARKET_DIR / "ohlcv" / "kr_KOSPI_daily.csv",
    "KOSDAQ": MARKET_DIR / "ohlcv" / "kr_KOSDAQ_daily.csv",
    "SPY": MARKET_DIR / "ohlcv" / "us_SPY_daily.csv",
    "QQQ": MARKET_DIR / "ohlcv" / "us_QQQ_daily.csv",
    "SP500": MARKET_DIR / "ohlcv" / "us_SP500_daily.csv",
}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text in EMPTY_STRINGS else text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        text = _safe_str(value)
        if not text:
            return default
        text = text.replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
        if not text:
            return default
        out = float(text)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def _safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size <= 0:
        return {}
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            data = json.loads(path.read_text(encoding=enc))
            return data if isinstance(data, dict) else {}
        except Exception:
            continue
    return {}


def _write_csv_update_by_key(df_new: pd.DataFrame, path: Path, key_cols: list[str]) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _safe_read_csv(path)
    if existing.empty:
        out = df_new.copy()
    else:
        out = pd.concat([existing, df_new], ignore_index=True, sort=False).fillna("")
        # Keep the latest row for a key so repeated app reruns update today's snapshot.
        out = out.drop_duplicates(subset=[c for c in key_cols if c in out.columns], keep="last")
    out.to_csv(path, index=False, encoding="utf-8-sig")
    return out


def _pick(row: dict[str, Any], keys: list[str], default: Any = "") -> Any:
    for key in keys:
        if key in row and _safe_str(row.get(key)):
            return row.get(key)
    return default


def _norm_symbol(value: Any, market_hint: str = "") -> str:
    raw = _safe_str(value).replace(".KS", "").replace(".KQ", "").strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    if not raw:
        return ""
    digits = "".join(ch for ch in raw if ch.isdigit())
    hint = str(market_hint or "")
    if digits and (len(digits) <= 6) and ("한국" in hint or raw.isdigit() or len(digits) == len(raw)):
        return digits.zfill(6)
    return raw.upper()


def _market_from_symbol(symbol: str, market: str = "") -> str:
    if _safe_str(market):
        if market in {"KR", "KOREA", "KOSPI", "KOSDAQ", "국장"}:
            return "한국주식"
        if market in {"US", "USA", "미장"}:
            return "미국주식"
        return market
    return "한국주식" if symbol.isdigit() and len(symbol) == 6 else "미국주식"


def _symbol_from_row(row: dict[str, Any]) -> str:
    market = _safe_str(_pick(row, ["market", "시장", "market_name"], ""))
    return _norm_symbol(_pick(row, ["symbol", "ticker", "종목코드", "code", "종목"], ""), market)


def _date_from_row(row: dict[str, Any]) -> str:
    raw = _safe_str(_pick(row, ["date", "target_date", "날짜", "datetime", "updated_at", "timestamp", "collected_at"], ""))
    if not raw:
        return ""
    # Accept common ISO and timestamp strings.
    text = raw[:10].replace("/", "-")
    return text if len(text) == 10 else ""


def _price_from_row(row: dict[str, Any]) -> float:
    return _safe_float(_pick(row, [
        "현재가", "current_price", "last_price", "price", "close", "종가", "actual_close", "actual_price", "Close", "adj_close"
    ], 0), 0.0)


def _build_price_map(base_dir: str | Path = ".") -> dict[str, dict[str, Any]]:
    base = Path(base_dir)
    price_map: dict[str, dict[str, Any]] = {}
    # Later sources can update if they are newer or the existing source is empty.
    for rel in PRICE_SOURCE_FILES:
        path = base / rel
        df = _safe_read_csv(path)
        if df.empty:
            continue
        for row in df.to_dict(orient="records"):
            symbol = _symbol_from_row(row)
            if not symbol:
                continue
            price = _price_from_row(row)
            if price <= 0:
                continue
            date = _date_from_row(row)
            source_name = str(rel).replace("\\", "/")
            prev = price_map.get(symbol)
            should_update = prev is None
            if prev is not None:
                prev_date = _safe_str(prev.get("price_date"))
                if date and (not prev_date or date >= prev_date):
                    should_update = True
                # Prefer actual close and intraday snapshot over stale candidate files when date ties/unknown.
                if "actual_results" in source_name or "intraday_realtime" in source_name:
                    should_update = True
            if should_update:
                price_map[symbol] = {
                    "price": price,
                    "price_source": source_name,
                    "price_date": date,
                }
    return price_map


def _load_holdings(base_dir: str | Path = ".") -> pd.DataFrame:
    base = Path(base_dir)
    if load_all_holdings is not None:
        try:
            meta = build_sector_metadata_map(base) if build_sector_metadata_map is not None else None
            df = load_all_holdings(base, meta)  # type: ignore[misc]
            return df.fillna("") if isinstance(df, pd.DataFrame) else pd.DataFrame()
        except Exception:
            pass
    frames: list[pd.DataFrame] = []
    for rel, market in ((Path("data/holdings_kr.csv"), "한국주식"), (Path("data/holdings_us.csv"), "미국주식"), (Path("holdings_kr.csv"), "한국주식"), (Path("holdings_us.csv"), "미국주식")):
        df = _safe_read_csv(base / rel)
        if not df.empty:
            if "market" not in df.columns:
                df["market"] = market
            frames.append(df)
    return pd.concat(frames, ignore_index=True, sort=False).fillna("") if frames else pd.DataFrame()


def _cash_from_settings(base_dir: str | Path = ".") -> float:
    base = Path(base_dir)
    for path in [base / PORTFOLIO_SETTINGS_JSON, base / PORTFOLIO_DIR / "cash_balance.json", base / DATA_DIR / "operation_settings.json"]:
        data = _safe_read_json(path)
        if not data:
            continue
        for key in ["cash", "available_cash", "cash_balance", "현금", "매수 가능 현금"]:
            val = _safe_float(data.get(key), 0.0)
            if val > 0:
                return val
    return 0.0


def build_position_snapshot(base_dir: str | Path = ".", as_of_date: str | None = None) -> pd.DataFrame:
    as_of_date = as_of_date or _today()
    holdings = _load_holdings(base_dir)
    price_map = _build_price_map(base_dir)
    rows: list[dict[str, Any]] = []
    if holdings.empty:
        return pd.DataFrame(columns=[
            "date", "updated_at", "market", "symbol", "name", "quantity", "avg_price", "close_price",
            "price_source", "price_date", "market_value", "cost_basis", "unrealized_pnl", "unrealized_return_pct",
            "weight_pct", "sector",
        ])

    temp_values: list[float] = []
    temp_rows: list[dict[str, Any]] = []
    for row in holdings.to_dict(orient="records"):
        symbol = _symbol_from_row(row)
        if not symbol:
            continue
        market = _market_from_symbol(symbol, _safe_str(_pick(row, ["market", "시장"], "")))
        price_info = price_map.get(symbol, {})
        avg_price = _safe_float(_pick(row, ["avg_price", "average_price", "평균단가"], 0), 0.0)
        quantity = _safe_float(_pick(row, ["quantity", "qty", "shares", "보유수량", "수량"], 0), 0.0)
        close_price = _safe_float(price_info.get("price"), 0.0)
        if close_price <= 0:
            close_price = _safe_float(_pick(row, ["current_price", "last_price", "현재가", "close_price"], 0), 0.0)
        if close_price <= 0:
            close_price = avg_price
        market_value = close_price * quantity if close_price > 0 and quantity > 0 else _safe_float(_pick(row, ["position_value", "evaluation_amount", "평가금액"], 0), 0.0)
        cost_basis = avg_price * quantity if avg_price > 0 and quantity > 0 else 0.0
        unrealized_pnl = market_value - cost_basis if cost_basis > 0 else 0.0
        unrealized_return_pct = (unrealized_pnl / cost_basis * 100) if cost_basis > 0 else 0.0
        item = {
            "date": as_of_date,
            "updated_at": _now(),
            "market": market,
            "symbol": symbol,
            "name": _safe_str(_pick(row, ["name", "종목명", "stock_name"], "")) or symbol,
            "quantity": quantity,
            "avg_price": avg_price,
            "close_price": close_price,
            "price_source": _safe_str(price_info.get("price_source")) or "holdings_fallback",
            "price_date": _safe_str(price_info.get("price_date")),
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_return_pct": unrealized_return_pct,
            "weight_pct": 0.0,
            "sector": _safe_str(_pick(row, ["sector", "섹터", "theme", "테마"], "")),
        }
        temp_rows.append(item)
        temp_values.append(market_value)
    total_holdings = sum(temp_values)
    for item in temp_rows:
        item["weight_pct"] = (float(item["market_value"]) / total_holdings * 100) if total_holdings > 0 else 0.0
        rows.append(item)
    return pd.DataFrame(rows)


def _ensure_nav_returns(nav: pd.DataFrame) -> pd.DataFrame:
    if nav.empty:
        return nav
    out = nav.copy().fillna("")
    if "date" in out.columns:
        out = out.sort_values("date")
    total = pd.to_numeric(out.get("total_value", 0), errors="coerce")
    returns = pd.to_numeric(out.get("daily_return", ""), errors="coerce") if "daily_return" in out.columns else pd.Series(index=out.index, dtype=float)
    calc = total.pct_change()
    returns = returns.where(returns.notna(), calc)
    out["daily_return"] = returns.fillna(0.0)
    first = total[total > 0].iloc[0] if (total > 0).any() else 0.0
    if first > 0:
        out["cumulative_return"] = (total / first - 1.0).fillna(0.0)
    else:
        out["cumulative_return"] = 0.0
    running_max = total.cummax()
    drawdown = (total / running_max - 1.0).fillna(0.0).where(running_max > 0, 0.0)
    out["max_drawdown_pct"] = (drawdown.cummin() * 100).fillna(0.0)
    return out


def _benchmark_schema() -> list[str]:
    return ["date", "benchmark", "close", "daily_return", "updated_at", "source"]


def _maybe_backfill_benchmark_from_existing(path: Path = BENCHMARK_DAILY_CSV) -> pd.DataFrame:
    existing = _safe_read_csv(path)
    if not existing.empty:
        for col in _benchmark_schema():
            if col not in existing.columns:
                existing[col] = ""
        return existing[_benchmark_schema()]
    path.parent.mkdir(parents=True, exist_ok=True)
    empty = pd.DataFrame(columns=_benchmark_schema())
    empty.to_csv(path, index=False, encoding="utf-8-sig")
    return empty


def _extract_benchmark_rows_from_local_files(base_dir: str | Path = ".") -> pd.DataFrame:
    """Best-effort local benchmark extraction without API calls.

    Some existing datasets may already contain rows for KOSPI/KOSDAQ/S&P500/NASDAQ.
    This function searches common CSVs and converts them into benchmark_daily rows.
    It never fabricates benchmark prices.
    """
    base = Path(base_dir)
    rows: list[dict[str, Any]] = []
    for benchmark, rel_path in INDEX_OHLCV_BENCHMARK_FILES.items():
        path = base / rel_path
        df = _safe_read_csv(path)
        if df.empty:
            continue
        for raw in df.to_dict(orient="records"):
            date = _date_from_row(raw)
            close = _safe_float(_pick(raw, ["close", "Close", "adj_close", "Adj Close"], 0), 0.0)
            if not date or close <= 0:
                continue
            rows.append({
                "date": date,
                "benchmark": benchmark,
                "close": close,
                "daily_return": "",
                "updated_at": _now(),
                "source": _safe_str(_pick(raw, ["source"], "")) or str(rel_path),
            })

    source_files = [
        base / DECISION_DIR / "actual_results.csv",
        base / "predictions.csv",
        base / REPORT_DIR / "market_regime_summary.csv",
        base / REPORT_DIR / "benchmark_daily.csv",
    ]
    for path in source_files:
        df = _safe_read_csv(path)
        if df.empty:
            continue
        for raw in df.to_dict(orient="records"):
            symbol = _safe_str(_pick(raw, ["symbol", "ticker", "code", "종목코드", "benchmark", "index", "지수"], ""))
            name = _safe_str(_pick(raw, ["name", "종목명", "index_name", "benchmark_name", "market", "시장"], ""))
            text = f"{symbol} {name}".upper()
            benchmark = ""
            for bname, aliases in BENCHMARK_SOURCES.items():
                if any(str(alias).upper() in text for alias in aliases):
                    benchmark = bname
                    break
            if not benchmark:
                continue
            date = _date_from_row(raw)
            price = _price_from_row(raw)
            if not date or price <= 0:
                continue
            rows.append({
                "date": date,
                "benchmark": benchmark,
                "close": price,
                "daily_return": "",
                "updated_at": _now(),
                "source": str(path.relative_to(base)) if path.is_relative_to(base) else str(path),
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=_benchmark_schema())


def _fetch_benchmark_rows_yfinance(lookback_days: int = 420) -> pd.DataFrame:
    """Optional yfinance benchmark fetch. Fails silently when unavailable/offline."""
    try:
        import yfinance as yf  # type: ignore
    except Exception:
        return pd.DataFrame(columns=_benchmark_schema())
    rows: list[dict[str, Any]] = []
    period = f"{max(30, int(lookback_days))}d"
    for benchmark, aliases in BENCHMARK_SOURCES.items():
        ticker = aliases[0]
        try:
            hist = yf.Ticker(ticker).history(period=period, auto_adjust=False)
        except Exception:
            hist = pd.DataFrame()
        if hist is None or hist.empty or "Close" not in hist.columns:
            continue
        temp = hist.reset_index()
        date_col = "Date" if "Date" in temp.columns else temp.columns[0]
        for _, r in temp.iterrows():
            try:
                date = str(pd.to_datetime(r[date_col]).date())
                close = float(r["Close"])
            except Exception:
                continue
            if close <= 0:
                continue
            rows.append({
                "date": date,
                "benchmark": benchmark,
                "close": close,
                "daily_return": "",
                "updated_at": _now(),
                "source": f"yfinance:{ticker}",
            })
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=_benchmark_schema())


def _ensure_benchmark_returns(benchmark: pd.DataFrame) -> pd.DataFrame:
    if benchmark is None or benchmark.empty:
        return pd.DataFrame(columns=_benchmark_schema())
    out = benchmark.copy().fillna("")
    for col in _benchmark_schema():
        if col not in out.columns:
            out[col] = ""
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = out.dropna(subset=["close"])
    out = out[out["close"] > 0]
    out["date"] = out["date"].astype(str).str.slice(0, 10)
    out = out.drop_duplicates(subset=["date", "benchmark"], keep="last").sort_values(["benchmark", "date"])
    calc = out.groupby("benchmark")["close"].pct_change()
    existing = pd.to_numeric(out.get("daily_return", ""), errors="coerce")
    out["daily_return"] = existing.where(existing.notna(), calc).fillna(0.0)
    return out[_benchmark_schema()]


def save_benchmark_daily_history(base_dir: str | Path = ".", lookback_days: int = 420) -> pd.DataFrame:
    """Create/update data/market/benchmark_daily.csv for beta/alpha.

    Priority:
    1) keep existing user history
    2) add local index rows when present
    3) best-effort yfinance fetch when the user's environment allows it

    The function is safe to run repeatedly and does not require web access.
    """
    base = Path(base_dir)
    target = base / BENCHMARK_DAILY_CSV
    existing = _maybe_backfill_benchmark_from_existing(target)
    local_rows = _extract_benchmark_rows_from_local_files(base)
    yf_rows = _fetch_benchmark_rows_yfinance(lookback_days=lookback_days)
    frames = [df for df in [existing, yf_rows, local_rows] if df is not None and not df.empty]
    out = pd.concat(frames, ignore_index=True, sort=False).fillna("") if frames else pd.DataFrame(columns=_benchmark_schema())
    out = _ensure_benchmark_returns(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False, encoding="utf-8-sig")
    return out


def calculate_portfolio_risk_metrics(nav_df: pd.DataFrame | None = None, benchmark_df: pd.DataFrame | None = None) -> dict[str, Any]:
    nav = _ensure_nav_returns(nav_df if nav_df is not None else _safe_read_csv(PORTFOLIO_DAILY_NAV_CSV))
    benchmark = benchmark_df if benchmark_df is not None else _safe_read_csv(BENCHMARK_DAILY_CSV)
    metrics: dict[str, Any] = {
        "updated_at": _now(),
        "history_days": int(len(nav)) if nav is not None else 0,
        "status": "NO_DATA",
        "warnings": [],
    }
    if nav is None or nav.empty or "total_value" not in nav.columns:
        metrics["warnings"].append("포트폴리오 일별 기록이 없습니다.")
        return metrics

    total = pd.to_numeric(nav.get("total_value"), errors="coerce").fillna(0.0)
    returns = pd.to_numeric(nav.get("daily_return"), errors="coerce").fillna(0.0)
    metrics["status"] = "OK"
    metrics["latest_date"] = str(nav.get("date", pd.Series([""])).iloc[-1]) if len(nav) else ""
    metrics["latest_total_value"] = float(total.iloc[-1]) if len(total) else 0.0
    metrics["cumulative_return_pct"] = float(pd.to_numeric(nav.get("cumulative_return"), errors="coerce").fillna(0.0).iloc[-1] * 100) if "cumulative_return" in nav.columns and len(nav) else 0.0
    metrics["max_drawdown_pct"] = float(pd.to_numeric(nav.get("max_drawdown_pct"), errors="coerce").fillna(0.0).min()) if "max_drawdown_pct" in nav.columns else 0.0
    metrics["volatility_pct"] = float(returns.std(ddof=0) * math.sqrt(252) * 100) if len(returns) >= 2 else None

    if len(returns) >= 20 and returns.std(ddof=0) > 0:
        metrics["sharpe_ratio"] = float((returns.mean() / returns.std(ddof=0)) * math.sqrt(252))
        var = returns.quantile(0.05)
        tail = returns[returns <= var]
        metrics["var_95_pct"] = float(var * 100)
        metrics["var_pct"] = metrics["var_95_pct"]
        metrics["cvar_95_pct"] = float((tail.mean() if len(tail) else var) * 100)
        metrics["cvar_pct"] = metrics["cvar_95_pct"]
    else:
        metrics["warnings"].append("샤프비율·VaR/CVaR는 20일 이상 수익률 기록이 필요합니다.")

    if benchmark is not None and not benchmark.empty and len(nav) >= 20:
        b = benchmark.copy().fillna("")
        if "date" in b.columns and "daily_return" in b.columns:
            # Use the first benchmark available. Multi-benchmark selection can be added later.
            if "benchmark" in b.columns:
                first_benchmark = _safe_str(b["benchmark"].iloc[0])
                b = b[b["benchmark"].astype(str) == first_benchmark]
                metrics["benchmark"] = first_benchmark
            merged = nav[["date", "daily_return"]].merge(b[["date", "daily_return"]], on="date", how="inner", suffixes=("_portfolio", "_benchmark"))
            rp = pd.to_numeric(merged.get("daily_return_portfolio"), errors="coerce").dropna()
            rb = pd.to_numeric(merged.get("daily_return_benchmark"), errors="coerce").dropna()
            if len(rp) >= 20 and len(rb) >= 20 and rb.var(ddof=0) > 0:
                n = min(len(rp), len(rb))
                rp = rp.iloc[-n:]
                rb = rb.iloc[-n:]
                beta = float(rp.cov(rb) / rb.var(ddof=0))
                alpha = float((rp.mean() - beta * rb.mean()) * 252 * 100)
                metrics["beta"] = beta
                metrics["alpha"] = alpha
            else:
                metrics["warnings"].append("베타·알파는 벤치마크 수익률 20일 이상 필요합니다.")
        else:
            metrics["warnings"].append("벤치마크 daily_return 데이터가 없어 베타·알파를 계산하지 못했습니다.")
    else:
        metrics["warnings"].append("베타·알파는 benchmark_daily.csv 기록이 필요합니다.")

    return metrics


def save_daily_portfolio_snapshot(base_dir: str | Path = ".", as_of_date: str | None = None) -> dict[str, Any]:
    """Save/update today's portfolio and position history, then refresh metrics."""
    base = Path(base_dir)
    as_of_date = as_of_date or _today()
    positions = build_position_snapshot(base, as_of_date)
    cash = _cash_from_settings(base)
    holdings_value = float(pd.to_numeric(positions.get("market_value", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()) if not positions.empty else 0.0
    total_value = holdings_value + cash
    kr_value = float(pd.to_numeric(positions.loc[positions.get("market", "") == "한국주식", "market_value"], errors="coerce").fillna(0.0).sum()) if not positions.empty and "market" in positions.columns else 0.0
    us_value = float(pd.to_numeric(positions.loc[positions.get("market", "") == "미국주식", "market_value"], errors="coerce").fillna(0.0).sum()) if not positions.empty and "market" in positions.columns else 0.0

    if not positions.empty:
        _write_csv_update_by_key(positions, base / POSITION_DAILY_SNAPSHOT_CSV, ["date", "market", "symbol"])
    else:
        (base / POSITION_DAILY_SNAPSHOT_CSV).parent.mkdir(parents=True, exist_ok=True)
        if not (base / POSITION_DAILY_SNAPSHOT_CSV).exists():
            positions.to_csv(base / POSITION_DAILY_SNAPSHOT_CSV, index=False, encoding="utf-8-sig")

    nav_row = pd.DataFrame([{
        "date": as_of_date,
        "updated_at": _now(),
        "total_value": total_value,
        "cash": cash,
        "holdings_value": holdings_value,
        "daily_return": "",
        "cumulative_return": "",
        "kr_value": kr_value,
        "us_value": us_value,
        "max_drawdown_pct": "",
        "position_count": int(len(positions)),
    }])
    nav = _write_csv_update_by_key(nav_row, base / PORTFOLIO_DAILY_NAV_CSV, ["date"])
    nav = _ensure_nav_returns(nav)
    nav.to_csv(base / PORTFOLIO_DAILY_NAV_CSV, index=False, encoding="utf-8-sig")

    benchmark = save_benchmark_daily_history(base)
    metrics = calculate_portfolio_risk_metrics(nav, benchmark)
    metrics.update({
        "portfolio_daily_nav_path": str(PORTFOLIO_DAILY_NAV_CSV),
        "position_daily_snapshot_path": str(POSITION_DAILY_SNAPSHOT_CSV),
        "benchmark_daily_path": str(BENCHMARK_DAILY_CSV),
        "portfolio_risk_metrics_path": str(PORTFOLIO_RISK_METRICS_JSON),
    })
    target = base / PORTFOLIO_RISK_METRICS_JSON
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return metrics


if __name__ == "__main__":  # pragma: no cover - manual CLI
    result = save_daily_portfolio_snapshot()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
