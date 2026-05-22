"""Lightweight beta backtest summaries for existing local OHLC data.

This is a conservative, no-network module. It reads existing CSV files only and
writes a small summary report so the UI/admin checks can see whether enough
history exists for future strategy validation.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(".")
REPORT_DIR = PROJECT_ROOT / "reports"
DATA_DIR = PROJECT_ROOT / "data"
DECISION_DIR = DATA_DIR / "decision_system"

BACKTEST_SUMMARY_CSV = REPORT_DIR / "backtest_beta_summary.csv"
BACKTEST_SUMMARY_JSON = REPORT_DIR / "backtest_beta_summary.json"

OHLC_SOURCE_CANDIDATES = [
    DECISION_DIR / "actual_results.csv",
    REPORT_DIR / "historical_ohlc.csv",
    DATA_DIR / "historical_ohlc.csv",
    PROJECT_ROOT / "predictions.csv",
]



def _iter_ohlc_source_candidates_v29() -> list[Path]:
    """v29: include user-saved price CSV folders, not only predictions/actual_results."""
    static = list(OHLC_SOURCE_CANDIDATES)
    patterns = [
        DATA_DIR / "prices" / "*.csv",
        DATA_DIR / "price" / "*.csv",
        DATA_DIR / "ohlc" / "*.csv",
        DATA_DIR / "market" / "*.csv",
        REPORT_DIR / "*price*.csv",
        REPORT_DIR / "*ohlc*.csv",
        REPORT_DIR / "intraday_realtime_snapshot.csv",
    ]
    out: list[Path] = []
    seen: set[str] = set()
    for p in static:
        key = str(p).replace("\\", "/")
        if key not in seen:
            out.append(p)
            seen.add(key)
    for pat in patterns:
        try:
            for p in sorted(pat.parent.glob(pat.name)):
                key = str(p).replace("\\", "/")
                if key not in seen:
                    out.append(p)
                    seen.add(key)
        except Exception:
            continue
    return out

EMPTY = {"", "-", "N/A", "NA", "None", "none", "nan", "NaN"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _pick_col(df: pd.DataFrame, names: list[str]) -> str | None:
    for name in names:
        if name in df.columns:
            return name
    lower = {str(c).lower(): c for c in df.columns}
    for name in names:
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def _norm_symbol(value: Any) -> str:
    text = "" if value is None else str(value).strip()
    if text in EMPTY:
        return ""
    text = text.replace(".KS", "").replace(".KQ", "")
    if text.endswith(".0"):
        text = text[:-2]
    if text.isdigit() and len(text) <= 6:
        return text.zfill(6)
    return text.upper()


def load_local_ohlc() -> tuple[pd.DataFrame, str]:
    for path in _iter_ohlc_source_candidates_v29():
        raw = _read_csv(path)
        if raw.empty:
            continue
        date_col = _pick_col(raw, ["date", "target_date", "날짜", "datetime"])
        symbol_col = _pick_col(raw, ["symbol", "ticker", "종목코드", "code"])
        close_col = _pick_col(raw, ["close", "종가", "actual_close", "actual_price", "현재가", "current_price"])
        if not date_col or not symbol_col or not close_col:
            continue
        out = pd.DataFrame()
        out["date"] = pd.to_datetime(raw[date_col].astype(str).str.slice(0, 10), errors="coerce")
        out["symbol"] = raw[symbol_col].map(_norm_symbol)
        for target, aliases in {
            "open": ["open", "시가", "actual_open"],
            "high": ["high", "고가", "actual_high"],
            "low": ["low", "저가", "actual_low"],
            "close": ["close", "종가", "actual_close", "actual_price", "현재가", "current_price"],
        }.items():
            col = _pick_col(raw, aliases)
            out[target] = pd.to_numeric(raw[col].astype(str).str.replace(",", "", regex=False), errors="coerce") if col else pd.NA
        out = out.dropna(subset=["date", "symbol", "close"])
        out = out[out["symbol"].astype(str) != ""]
        if not out.empty:
            out = out.sort_values(["symbol", "date"]).drop_duplicates(["symbol", "date"], keep="last")
            # Fill missing OHLC from close for compatibility with close-only files.
            for col in ["open", "high", "low"]:
                out[col] = pd.to_numeric(out[col], errors="coerce").fillna(out["close"])
            return out, str(path)
    return pd.DataFrame(columns=["date", "symbol", "open", "high", "low", "close"]), ""


def _equity_metrics(daily_returns: pd.Series) -> dict[str, float]:
    r = pd.to_numeric(daily_returns, errors="coerce").fillna(0.0)
    if r.empty:
        return {"total_return_pct": 0.0, "avg_daily_return_pct": 0.0, "mdd_pct": 0.0, "win_rate_pct": 0.0}
    equity = (1 + r).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1
    return {
        "total_return_pct": float((equity.iloc[-1] - 1) * 100),
        "avg_daily_return_pct": float(r.mean() * 100),
        "mdd_pct": float(dd.min() * 100),
        "win_rate_pct": float((r > 0).mean() * 100),
    }


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    diff = close.diff()
    up = diff.clip(lower=0).rolling(n).mean()
    down = (-diff.clip(upper=0)).rolling(n).mean()
    rs = up / down.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _strategy_returns(g: pd.DataFrame, strategy: str) -> pd.Series:
    close = pd.to_numeric(g["close"], errors="coerce")
    ret = close.pct_change().fillna(0.0)
    if strategy == "breakout_20":
        signal = close > close.shift(1).rolling(20).max()
    elif strategy in {"ma10_ma20", "ma5_ma20"}:
        signal = close.rolling(10).mean() > close.rolling(20).mean()
    elif strategy == "mean_reversion_rsi":
        rsi = _rsi(close)
        signal = rsi < 35
    elif strategy == "pullback_ma20":
        ma20 = close.rolling(20).mean()
        signal = (close > ma20) & (close / close.rolling(20).max() - 1 < -0.04)
    else:
        signal = pd.Series(False, index=g.index)
    return ret.where(signal.shift(1).fillna(False), 0.0)


def run_backtest_beta(ohlc: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict[str, Any]]:
    source = "provided"
    if ohlc is None:
        ohlc, source = load_local_ohlc()
    summary: dict[str, Any] = {"updated_at": _now(), "source": source, "status": "NO_DATA", "warnings": []}
    if ohlc is None or ohlc.empty:
        return pd.DataFrame(), {**summary, "warnings": ["백테스트에 사용할 OHLC 데이터가 없습니다."]}
    results: list[dict[str, Any]] = []
    strategies = {
        "breakout_20": "20일 고점 돌파",
        "ma10_ma20": "MA10 > MA20 추세",
        "mean_reversion_rsi": "RSI 저점 반등",
        "pullback_ma20": "20일선 눌림목",
    }
    usable_symbols = 0
    for strategy, label in strategies.items():
        symbol_returns: list[pd.Series] = []
        for symbol, g in ohlc.groupby("symbol"):
            g = g.sort_values("date").copy()
            if len(g) < 30:
                continue
            sr = _strategy_returns(g, strategy)
            sr.index = g["date"]
            symbol_returns.append(sr)
        if not symbol_returns:
            results.append({"strategy": strategy, "전략": label, "status": "DATA_SHORT", "symbols": 0, "days": 0, "total_return_pct": 0.0, "avg_daily_return_pct": 0.0, "mdd_pct": 0.0, "win_rate_pct": 0.0})
            continue
        usable_symbols = max(usable_symbols, len(symbol_returns))
        combined = pd.concat(symbol_returns, axis=1).fillna(0.0).mean(axis=1).sort_index()
        metrics = _equity_metrics(combined)
        results.append({"strategy": strategy, "전략": label, "status": "OK", "symbols": len(symbol_returns), "days": int(len(combined)), **metrics})
    out = pd.DataFrame(results)
    summary.update({"status": "OK" if usable_symbols else "DATA_SHORT", "strategy_count": len(results), "usable_symbol_count": usable_symbols})
    if usable_symbols == 0:
        summary["warnings"].append("30일 이상 OHLC가 있는 종목이 부족합니다.")
    return out, summary


def save_backtest_beta_summary(base_dir: str | Path = ".") -> dict[str, Any]:
    base = Path(base_dir)
    out, summary = run_backtest_beta()
    csv_path = base / BACKTEST_SUMMARY_CSV
    json_path = base / BACKTEST_SUMMARY_JSON
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if out.empty:
        out = pd.DataFrame(columns=["strategy", "전략", "status", "symbols", "days", "total_return_pct", "avg_daily_return_pct", "mdd_pct", "win_rate_pct"])
    out.to_csv(csv_path, index=False, encoding="utf-8-sig")
    summary.update({"summary_csv": str(BACKTEST_SUMMARY_CSV), "summary_json": str(BACKTEST_SUMMARY_JSON)})
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    print(json.dumps(save_backtest_beta_summary(), ensure_ascii=False, indent=2, default=str))
