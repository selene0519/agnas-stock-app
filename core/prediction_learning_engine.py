"""v33 prediction review and learning summary engine.

This module is intentionally conservative: it never changes predictions or places
orders. It reads local CSV files, calculates review-quality summaries when enough
actual outcome columns exist, and saves reports that the Streamlit UI can display.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")
PREDICTION_FILE = Path("predictions.csv")
ACTUAL_RESULTS_FILE = Path("actual_results.csv")
SUMMARY_CSV = REPORT_DIR / "prediction_learning_summary.csv"
SYMBOL_CSV = REPORT_DIR / "prediction_learning_symbol_summary.csv"
SUMMARY_JSON = REPORT_DIR / "prediction_learning_summary.json"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc, low_memory=False).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def _pick_col(df: pd.DataFrame, names: list[str]) -> str | None:
    low = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name in df.columns:
            return name
        key = name.strip().lower()
        if key in low:
            return low[key]
    return None


def _num(x: Any, default: float = math.nan) -> float:
    if x is None:
        return default
    s = str(x).strip().replace(",", "").replace("%", "")
    if not s or s.lower() in {"nan", "none", "nat", "-", "미수신"}:
        return default
    try:
        return float(s)
    except Exception:
        return default


def _boolish(x: Any) -> float:
    s = str(x).strip().lower()
    if s in {"1", "true", "yes", "y", "hit", "success", "성공", "예", "터치", "체결"}:
        return 1.0
    if s in {"0", "false", "no", "n", "fail", "failed", "실패", "아니오", "미체결"}:
        return 0.0
    return math.nan


def _confidence_bucket(v: Any) -> str:
    n = _num(v, math.nan)
    if math.isnan(n):
        return "미분류"
    if n >= 80:
        return "80+ 강함"
    if n >= 65:
        return "65~79 양호"
    if n >= 50:
        return "50~64 보통"
    return "50 미만 약함"


def _market_of(row: pd.Series) -> str:
    for c in ("market", "시장"):
        if c in row.index and str(row.get(c, "")).strip():
            return str(row.get(c)).strip()
    sym = str(row.get("ticker", row.get("symbol", row.get("종목코드", ""))) or "").strip()
    return "한국주식" if sym.isdigit() or sym.endswith((".KS", ".KQ")) else "미국주식"


def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    ticker_col = _pick_col(out, ["ticker", "symbol", "종목코드", "종목", "티커"])
    if ticker_col and ticker_col != "ticker":
        out["ticker"] = out[ticker_col].astype(str).str.strip()
    elif "ticker" not in out.columns:
        out["ticker"] = ""
    if "market" not in out.columns:
        out["market"] = out.apply(_market_of, axis=1)
    date_col = _pick_col(out, ["target_date", "예측대상일", "date", "날짜", "created_at", "prediction_date"])
    if date_col:
        out["_date"] = pd.to_datetime(out[date_col], errors="coerce")
    else:
        out["_date"] = pd.NaT
    conf_col = _pick_col(out, ["confidence_score", "confidence", "신뢰도", "확신도", "종합점수", "score"])
    out["confidence_score_num"] = out[conf_col].map(_num) if conf_col else math.nan
    out["confidence_bucket"] = out["confidence_score_num"].map(_confidence_bucket)
    return out


def _merge_actual_if_possible(pred: pd.DataFrame, actual: pd.DataFrame) -> pd.DataFrame:
    if pred.empty or actual.empty:
        return pred
    p = pred.copy()
    a = _normalise_frame(actual)
    if a.empty:
        return p
    key_cols = [c for c in ["ticker", "market"] if c in p.columns and c in a.columns]
    if "_date" in p.columns and "_date" in a.columns:
        p["_date_key"] = pd.to_datetime(p["_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        a["_date_key"] = pd.to_datetime(a["_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        key_cols.append("_date_key")
    if not key_cols or "ticker" not in key_cols:
        return p
    keep = [c for c in a.columns if c not in p.columns or c in key_cols]
    try:
        return p.merge(a[keep], on=key_cols, how="left", suffixes=("", "_actualfile"))
    except Exception:
        return p


def _add_outcomes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    actual_close_col = _pick_col(out, ["actual_close", "실제종가", "close_actual", "actual_close_actualfile", "종가"])
    pred_close_col = _pick_col(out, ["predicted_close", "expected_close", "예상종가", "pred_close", "target_close"])
    entry_col = _pick_col(out, ["preferred_entry", "우선진입가", "entry_price", "buy_price", "진입가"])
    low_col = _pick_col(out, ["actual_low", "실제저가", "low", "저가"])
    high_col = _pick_col(out, ["actual_high", "실제고가", "high", "고가"])
    stop_col = _pick_col(out, ["stop_loss", "손절가", "stop"])
    tp_col = _pick_col(out, ["take_profit1", "1차목표", "target_price", "익절가"])
    hit_col = _pick_col(out, ["entry_hit", "진입체결", "range_hit", "범위적중", "success", "성공여부"])

    if actual_close_col and pred_close_col:
        actual = out[actual_close_col].map(_num)
        pred = out[pred_close_col].map(_num)
        out["close_error_pct"] = ((pred - actual).abs() / actual.replace({0: math.nan}) * 100).round(2)
    else:
        out["close_error_pct"] = math.nan

    if hit_col:
        out["entry_hit_bool"] = out[hit_col].map(_boolish)
    elif entry_col and low_col and high_col:
        entry = out[entry_col].map(_num)
        low = out[low_col].map(_num)
        high = out[high_col].map(_num)
        out["entry_hit_bool"] = ((low <= entry) & (entry <= high)).astype(float)
        out.loc[entry.isna() | low.isna() | high.isna(), "entry_hit_bool"] = math.nan
    else:
        out["entry_hit_bool"] = math.nan

    if stop_col and low_col:
        stop = out[stop_col].map(_num)
        low = out[low_col].map(_num)
        out["stop_touched_bool"] = (low <= stop).astype(float)
        out.loc[stop.isna() | low.isna(), "stop_touched_bool"] = math.nan
    else:
        out["stop_touched_bool"] = math.nan

    if tp_col and high_col:
        tp = out[tp_col].map(_num)
        high = out[high_col].map(_num)
        out["tp1_touched_bool"] = (high >= tp).astype(float)
        out.loc[tp.isna() | high.isna(), "tp1_touched_bool"] = math.nan
    else:
        out["tp1_touched_bool"] = math.nan
    return out


def _rate(series: pd.Series) -> float | None:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) == 0:
        return None
    return round(float(vals.mean() * 100), 2)


def _make_group_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if df.empty:
        return pd.DataFrame()
    for keys, g in df.groupby(group_cols, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        row = {col: key for col, key in zip(group_cols, keys)}
        close_err = pd.to_numeric(g.get("close_error_pct", pd.Series(dtype=float)), errors="coerce").dropna()
        row.update({
            "sample_count": int(len(g)),
            "reviewable_count": int(g[["entry_hit_bool", "tp1_touched_bool", "stop_touched_bool", "close_error_pct"]].notna().any(axis=1).sum()) if all(c in g.columns for c in ["entry_hit_bool", "tp1_touched_bool", "stop_touched_bool", "close_error_pct"]) else 0,
            "entry_hit_rate_pct": _rate(g.get("entry_hit_bool", pd.Series(dtype=float))),
            "tp1_touch_rate_pct": _rate(g.get("tp1_touched_bool", pd.Series(dtype=float))),
            "stop_touch_rate_pct": _rate(g.get("stop_touched_bool", pd.Series(dtype=float))),
            "avg_close_error_pct": round(float(close_err.mean()), 2) if len(close_err) else None,
        })
        rows.append(row)
    return pd.DataFrame(rows)


def save_prediction_learning_summary() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    pred = _normalise_frame(_read_csv(PREDICTION_FILE))
    actual = _read_csv(ACTUAL_RESULTS_FILE)
    if pred.empty:
        result = {"status": "NO_DATA", "message": "predictions.csv가 없거나 비어 있습니다.", "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        SUMMARY_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    merged = _merge_actual_if_possible(pred, actual)
    scored = _add_outcomes(merged)
    summary = _make_group_summary(scored, ["market", "confidence_bucket"])
    symbol = _make_group_summary(scored, ["market", "ticker"])
    if not summary.empty:
        summary.to_csv(SUMMARY_CSV, index=False, encoding="utf-8-sig")
    if not symbol.empty:
        symbol = symbol.sort_values(["reviewable_count", "sample_count"], ascending=[False, False]).head(200)
        symbol.to_csv(SYMBOL_CSV, index=False, encoding="utf-8-sig")
    reviewable = int(scored[["entry_hit_bool", "tp1_touched_bool", "stop_touched_bool", "close_error_pct"]].notna().any(axis=1).sum())
    result = {
        "status": "OK",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "prediction_rows": int(len(pred)),
        "actual_rows": int(len(actual)) if not actual.empty else 0,
        "reviewable_rows": reviewable,
        "summary_csv": str(SUMMARY_CSV),
        "symbol_csv": str(SYMBOL_CSV),
        "note": "실제 결과 컬럼이 부족한 행은 표본에는 포함하지만 성과율 계산에서는 제외했습니다.",
    }
    SUMMARY_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def read_prediction_learning_summary() -> dict[str, Any]:
    if not SUMMARY_JSON.exists():
        return save_prediction_learning_summary()
    try:
        return json.loads(SUMMARY_JSON.read_text(encoding="utf-8"))
    except Exception:
        return save_prediction_learning_summary()


if __name__ == "__main__":
    print(json.dumps(save_prediction_learning_summary(), ensure_ascii=False, indent=2, default=str))
