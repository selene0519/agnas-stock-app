from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = PROJECT_ROOT / "reports"
REVIEW_QUALITY_JSON = REPORT_DIR / "review_quality_summary.json"
REVIEW_QUALITY_CSV = REPORT_DIR / "review_quality_summary.csv"

PREDICTION_REQUIRED_COLUMNS = [
    "target_date",
    "risk_final_decision",
    "prediction_result",
    "actual_open",
    "actual_high",
    "actual_low",
    "actual_close",
    "failure_reason",
]
CANDIDATE_FILES = [
    "swing_candidates_us_A_top3.csv",
    "swing_candidates_us_B_watch.csv",
    "swing_candidates_us_C_excluded.csv",
    "swing_candidates_kr_A_top3.csv",
    "swing_candidates_kr_B_watch.csv",
    "swing_candidates_kr_C_excluded.csv",
]
CANDIDATE_REQUIRED_COLUMNS = [
    "symbol",
    "rr",
    "risk_final_decision",
    "strategy_mode",
    "strategy_adjusted_grade",
    "strategy_trade_allowed",
    "\uc2e4\uc804\ub4f1\uae09",
    "\uc2e4\uc804\ub4f1\uae09\uc0ac\uc720",
    "\uc2e4\uc804\uacbd\uace0",
]


def _resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else PROJECT_ROOT / p


def _status_from(has_error: bool, has_warning: bool) -> str:
    if has_error:
        return "ERROR"
    if has_warning:
        return "WARNING"
    return "OK"


def _read_csv(path: str | Path) -> tuple[pd.DataFrame, str]:
    try:
        return pd.read_csv(_resolve(path)), ""
    except Exception as exc:
        return pd.DataFrame(), str(exc)


def _is_true_series(series: pd.Series) -> pd.Series:
    return series.astype(str).str.strip().str.lower().isin({"true", "1", "1.0", "yes", "y"})


def _nan_ratio(df: pd.DataFrame, column: str) -> float:
    if column not in df.columns or len(df) == 0:
        return 1.0
    text = df[column].astype(str).str.strip().str.lower()
    missing = df[column].isna() | text.isin({"", "nan", "none", "nat"})
    return round(float(missing.mean()), 4)


def _risk_final_decision_warning(rate: float) -> str:
    if rate < 0.05:
        return "OK"
    if rate < 0.10:
        return "NOTICE"
    return "WARNING"


def _contains_mojibake(value: Any) -> bool:
    text = str(value or "")
    return any(token in text for token in ("�", "怨", "諛", "湲", "留", "二쇱", "?쒓", "?대"))


def check_csv_schema(path: str, required_columns: list[str]) -> dict[str, Any]:
    p = _resolve(path)
    result = {
        "file_exists": p.exists(),
        "row_count": 0,
        "missing_columns": list(required_columns),
        "empty_file": False,
        "read_error": "",
        "status": "ERROR",
    }
    if not p.exists():
        result["read_error"] = "file not found"
        return result
    result["empty_file"] = p.stat().st_size == 0
    if result["empty_file"]:
        result["status"] = "ERROR"
        result["read_error"] = "empty file"
        return result
    df, err = _read_csv(p)
    if err:
        result["read_error"] = err
        result["status"] = "ERROR"
        return result
    missing = [col for col in required_columns if col not in df.columns]
    result["row_count"] = int(len(df))
    result["missing_columns"] = missing
    result["status"] = "ERROR" if missing else "OK"
    return result


def check_file_freshness(path: str, max_age_hours: int = 24) -> dict[str, Any]:
    p = _resolve(path)
    result = {
        "exists": p.exists(),
        "modified_at": "",
        "age_hours": None,
        "is_stale": True,
        "status": "ERROR",
    }
    if not p.exists():
        return result
    modified_ts = p.stat().st_mtime
    modified = datetime.fromtimestamp(modified_ts, tz=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - modified).total_seconds() / 3600
    is_stale = age_hours > max_age_hours
    result.update(
        {
            "modified_at": modified.astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "age_hours": round(age_hours, 2),
            "is_stale": bool(is_stale),
            "status": "WARNING" if is_stale else "OK",
        }
    )
    return result


def check_predictions_quality(path: str = "predictions.csv") -> dict[str, Any]:
    required = list(PREDICTION_REQUIRED_COLUMNS)
    schema = check_csv_schema(path, required)
    p = _resolve(path)
    out: dict[str, Any] = {
        **schema,
        "ohlc_missing_rate": 1.0,
        "not_enough_data_rate": 0.0,
        "risk_final_decision_nan_rate": 1.0,
        "risk_final_decision_filled_count": 0,
        "risk_final_decision_source_counts": {},
        "risk_final_decision_warning": "WARNING",
        "flat_ohlc_rate": 0.0,
        "prediction_result_counts": {},
        "actual_ohlc_filled_rate": 0.0,
        "recent_review_rows": [],
    }
    if schema["status"] == "ERROR":
        return out
    df, err = _read_csv(p)
    if err:
        out["read_error"] = err
        out["status"] = "ERROR"
        return out
    if not (("ticker" in df.columns) or ("symbol" in df.columns)):
        out["missing_columns"] = list(dict.fromkeys(out["missing_columns"] + ["ticker or symbol"]))
        out["status"] = "ERROR"
        return out

    ohlc_cols = ["actual_open", "actual_high", "actual_low", "actual_close"]
    ohlc = df[ohlc_cols].apply(pd.to_numeric, errors="coerce")
    complete = ohlc.notna().all(axis=1) if len(df) else pd.Series(dtype=bool)
    flat = complete & ohlc.nunique(axis=1).eq(1)
    result_col = df["prediction_result"].astype(str).str.strip().str.lower()

    out["ohlc_missing_rate"] = round(float((~complete).mean()), 4) if len(df) else 1.0
    out["actual_ohlc_filled_rate"] = round(float(complete.mean()), 4) if len(df) else 0.0
    out["flat_ohlc_rate"] = round(float(flat.mean()), 4) if len(df) else 0.0
    out["not_enough_data_rate"] = round(float(result_col.eq("not_enough_data").mean()), 4) if len(df) else 0.0
    out["risk_final_decision_nan_rate"] = _nan_ratio(df, "risk_final_decision")
    out["risk_final_decision_warning"] = _risk_final_decision_warning(out["risk_final_decision_nan_rate"])
    if "risk_final_decision_filled" in df.columns:
        filled_text = df["risk_final_decision_filled"].astype(str).str.strip().str.lower()
        out["risk_final_decision_filled_count"] = int(filled_text.isin({"true", "1", "1.0", "yes", "y"}).sum())
    if "risk_final_decision_source" in df.columns:
        source_text = df["risk_final_decision_source"].fillna("").astype(str).str.strip().replace("", "unknown")
        out["risk_final_decision_source_counts"] = source_text.value_counts(dropna=False).to_dict()
    out["prediction_result_counts"] = result_col.value_counts(dropna=False).to_dict()

    show_cols = [c for c in ["target_date", "ticker", "symbol", "prediction_result", "failure_reason"] if c in df.columns]
    recent = df.tail(10)[show_cols].fillna("").to_dict(orient="records") if show_cols else []
    out["recent_review_rows"] = recent

    warnings = []
    if out["ohlc_missing_rate"] >= 0.5:
        warnings.append("actual OHLC missing rate >= 50%")
    if out["not_enough_data_rate"] >= 0.5:
        warnings.append("not_enough_data rate >= 50%")
    if out["flat_ohlc_rate"] >= 0.2:
        warnings.append("flat OHLC rate >= 20%")
    if out["risk_final_decision_warning"] == "WARNING":
        warnings.append("risk_final_decision missing rate >= 10%")
    out["warnings"] = warnings
    out["status"] = _status_from(False, bool(warnings))
    return out


def _candidate_file_quality(path: Path, is_a_file: bool, is_c_file: bool) -> dict[str, Any]:
    schema = check_csv_schema(str(path), CANDIDATE_REQUIRED_COLUMNS)
    out = {
        **schema,
        "file": path.name,
        "c_trade_allowed_true_count": 0,
        "a_rr_lt_2_count": 0,
        "a_rr_pass_false_count": 0,
        "a_market_risk_very_high_count": 0,
        "a_overheat_very_high_count": 0,
        "warnings": [],
        "errors": [],
    }
    if not path.exists():
        out["status"] = "WARNING"
        out["warnings"].append("candidate file missing")
        return out
    if schema["read_error"]:
        return out
    df, err = _read_csv(path)
    if err:
        out["read_error"] = err
        out["status"] = "ERROR"
        out["errors"].append(err)
        return out
    if is_c_file and "strategy_trade_allowed" in df.columns:
        out["c_trade_allowed_true_count"] = int(_is_true_series(df["strategy_trade_allowed"]).sum())
        if out["c_trade_allowed_true_count"] > 0:
            out["errors"].append("C_excluded has strategy_trade_allowed=True")
    if is_a_file and len(df):
        if "rr" in df.columns:
            rr = pd.to_numeric(df["rr"], errors="coerce")
            out["a_rr_lt_2_count"] = int(rr.lt(2.0).fillna(False).sum())
            if out["a_rr_lt_2_count"] > 0:
                out["errors"].append("A_top3 has rr < 2.0")
        if "rr_pass" in df.columns:
            false_rr = ~_is_true_series(df["rr_pass"])
            out["a_rr_pass_false_count"] = int(false_rr.sum())
            if out["a_rr_pass_false_count"] > 0:
                out["errors"].append("A_top3 has rr_pass=False")
        if "market_risk_level" in df.columns:
            out["a_market_risk_very_high_count"] = int(df["market_risk_level"].astype(str).eq("\ub9e4\uc6b0 \ub192\uc74c").sum())
            if out["a_market_risk_very_high_count"] > 0:
                out["errors"].append("A_top3 has very high market risk")
        if "overheat_level" in df.columns:
            out["a_overheat_very_high_count"] = int(df["overheat_level"].astype(str).eq("\ub9e4\uc6b0 \ub192\uc74c").sum())
            if out["a_overheat_very_high_count"] > 0:
                out["errors"].append("A_top3 has very high overheat")
    if schema["missing_columns"]:
        out["errors"].append("missing required columns")
    out["status"] = _status_from(bool(out["errors"]), bool(out["warnings"]))
    return out


def check_candidate_files_quality(report_dir: str = "reports") -> dict[str, Any]:
    base = _resolve(report_dir)
    files = []
    warnings: list[str] = []
    errors: list[str] = []
    for name in CANDIDATE_FILES:
        path = base / name
        item = _candidate_file_quality(path, "_A_top3" in name, "_C_excluded" in name)
        files.append(item)
        warnings.extend(f"{name}: {w}" for w in item.get("warnings", []))
        errors.extend(f"{name}: {e}" for e in item.get("errors", []))
    return {
        "files": files,
        "warnings": warnings,
        "errors": errors,
        "status": _status_from(bool(errors), bool(warnings)),
    }


def check_market_regime_quality(path: str = "reports/market_regime_summary.json") -> dict[str, Any]:
    candidates = [_resolve(path), _resolve("data/market_regime_summary.json"), _resolve("market_regime_summary.json")]
    p = next((x for x in candidates if x.exists()), candidates[0])
    fresh = check_file_freshness(str(p), max_age_hours=24)
    out = {
        "file_exists": p.exists(),
        "path": str(p),
        "json_readable": False,
        "is_stale": fresh.get("is_stale", True),
        "market_regime_present": False,
        "market_risk_level_present": False,
        "mojibake_suspected": False,
        "read_error": "",
        "status": "ERROR",
        "data": {},
    }
    if not p.exists():
        out["read_error"] = "file not found"
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        out["read_error"] = str(exc)
        return out
    out["json_readable"] = True
    out["data"] = data
    out["market_regime_present"] = bool(data.get("market_regime") or data.get("strategy_mode"))
    out["market_risk_level_present"] = bool(data.get("market_risk_level") or data.get("risk_level") or data.get("market_risk_score") is not None)
    out["mojibake_suspected"] = any(_contains_mojibake(v) for v in data.values() if isinstance(v, (str, list)))
    errors = []
    warnings = []
    if not out["market_regime_present"]:
        errors.append("market_regime/strategy_mode missing")
    if not out["market_risk_level_present"]:
        errors.append("market risk level/score missing")
    if out["is_stale"]:
        warnings.append("market regime file stale")
    if out["mojibake_suspected"]:
        warnings.append("possible mojibake")
    out["warnings"] = warnings
    out["errors"] = errors
    out["status"] = _status_from(bool(errors), bool(warnings))
    return out


def _collect_messages(prefix: str, result: dict[str, Any]) -> tuple[list[str], list[str]]:
    warnings = [f"{prefix}: {w}" for w in result.get("warnings", [])]
    errors = [f"{prefix}: {e}" for e in result.get("errors", [])]
    if result.get("status") == "ERROR" and result.get("read_error"):
        errors.append(f"{prefix}: {result['read_error']}")
    return warnings, errors


def build_daily_quality_summary() -> dict[str, Any]:
    predictions = check_predictions_quality("predictions.csv")
    candidates = check_candidate_files_quality("reports")
    market = check_market_regime_quality("reports/market_regime_summary.json")

    warnings: list[str] = []
    errors: list[str] = []
    for prefix, result in [("predictions.csv", predictions), ("candidate CSV", candidates), ("market regime", market)]:
        w, e = _collect_messages(prefix, result)
        warnings.extend(w)
        errors.extend(e)
        if result.get("status") == "WARNING" and not w:
            warnings.append(f"{prefix}: WARNING")
        if result.get("status") == "ERROR" and not e:
            errors.append(f"{prefix}: ERROR")

    score = 100 - len(warnings) * 7 - len(errors) * 20
    score = int(max(0, min(100, score)))
    overall_status = "ERROR" if errors else "WARNING" if warnings else "OK"
    reliability = "\uc815\uc0c1" if score >= 80 else "\uc8fc\uc758" if score >= 60 else "\ub0ae\uc74c"

    summary_cards = [
        {"label": "\uc624\ub298 \ud310\ub2e8 \uc2e0\ub8b0\ub3c4", "value": reliability, "status": overall_status},
        {"label": "\ub370\uc774\ud130 \ud488\uc9c8 \uc810\uc218", "value": score, "status": overall_status},
        {"label": "predictions.csv", "value": predictions.get("status"), "status": predictions.get("status")},
        {"label": "actual OHLC", "value": f"{predictions.get('actual_ohlc_filled_rate', 0):.0%}", "status": predictions.get("status")},
        {"label": "\ud6c4\ubcf4 CSV", "value": candidates.get("status"), "status": candidates.get("status")},
        {"label": "\uc2dc\uc7a5\uad6d\uba74 JSON", "value": market.get("status"), "status": market.get("status")},
    ]
    result = {
        "overall_status": overall_status,
        "judgment_reliability": reliability,
        "summary_score": score,
        "summary_cards": summary_cards,
        "warnings": warnings,
        "errors": errors,
        "predictions": predictions,
        "candidates": candidates,
        "market_regime": market,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_QUALITY_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    pd.DataFrame(
        [
            {
                "overall_status": overall_status,
                "judgment_reliability": reliability,
                "summary_score": score,
                "warnings_count": len(warnings),
                "errors_count": len(errors),
                "actual_ohlc_filled_rate": predictions.get("actual_ohlc_filled_rate", 0),
                "not_enough_data_rate": predictions.get("not_enough_data_rate", 0),
                "flat_ohlc_rate": predictions.get("flat_ohlc_rate", 0),
            }
        ]
    ).to_csv(REVIEW_QUALITY_CSV, index=False, encoding="utf-8-sig")
    return result
