from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


REPORT_DIR = Path("reports")
CATALYST_VALIDATION_REPORT_CSV = REPORT_DIR / "catalyst_validation_report.csv"
CATALYST_VALIDATION_SUMMARY_JSON = REPORT_DIR / "catalyst_validation_summary.json"
DEFAULT_CANDIDATE_FILES = [
    REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
]
REQUIRED_COLUMNS = [
    "symbol",
    "market",
    "catalyst_score",
    "news_importance_score",
    "news_freshness_score",
    "disclosure_score",
    "earnings_score",
    "supply_score",
    "catalyst_reasons",
    "catalyst_warnings",
    "decision_change_log",
]
SCORE_COLUMNS = [
    "catalyst_score",
    "news_importance_score",
    "news_freshness_score",
    "disclosure_score",
    "earnings_score",
    "supply_score",
]
OPTIONAL_STATUS_COLUMNS = [
    "catalyst_data_status",
    "news_data_status",
    "disclosure_data_status",
    "earnings_data_status",
    "supply_data_status",
    "catalyst_score_source",
]


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "nat"} else text


def _status_from(errors: list[str], warnings: list[str]) -> str:
    if errors:
        return "ERROR"
    if warnings:
        return "WARNING"
    return "OK"


def _read_candidate(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    try:
        df = pd.read_csv(path, dtype=str, low_memory=False).fillna("")
    except Exception:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    df["source_file"] = str(path)
    if "market" not in df.columns or df["market"].astype(str).str.strip().eq("").all():
        inferred = "한국주식" if "_kr_" in path.name else "미국주식" if "_us_" in path.name else ""
        df["market"] = inferred
    return df


def load_candidate_catalyst_data(candidate_files: list[str | Path] | None = None) -> pd.DataFrame:
    frames = [_read_candidate(Path(path)) for path in (candidate_files or DEFAULT_CANDIDATE_FILES)]
    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)
    populated = [frame for frame in frames if not frame.empty]
    if populated:
        return pd.concat(populated, ignore_index=True, sort=False)
    return pd.concat(frames, ignore_index=True, sort=False)


def _missing_required_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in REQUIRED_COLUMNS if col not in df.columns]


def _score_series(df: pd.DataFrame, column: str) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce")


def validate_catalyst_score_distribution(df: pd.DataFrame) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    missing = _missing_required_columns(df)
    if missing:
        errors.append(f"missing catalyst columns: {missing}")
        return {
            "row_count": int(len(df)),
            "missing_columns": missing,
            "catalyst_score_min": 0.0,
            "catalyst_score_max": 0.0,
            "catalyst_score_mean": 0.0,
            "catalyst_score_std": 0.0,
            "catalyst_score_unique_count": 0,
            "component_unique_counts": {},
            "score_distribution_status": "ERROR",
            "score_distribution_warning": "필수 catalyst 컬럼 누락",
            "warnings": warnings,
            "errors": errors,
        }

    scores = _score_series(df, "catalyst_score")
    valid_scores = scores.dropna()
    if valid_scores.empty:
        errors.append("catalyst_score has no numeric values")
        min_score = max_score = mean_score = std_score = 0.0
        unique_count = 0
    else:
        min_score = round(float(valid_scores.min()), 4)
        max_score = round(float(valid_scores.max()), 4)
        mean_score = round(float(valid_scores.mean()), 4)
        std_score = round(float(valid_scores.std(ddof=0)), 4)
        unique_count = int(valid_scores.nunique(dropna=True))
        if valid_scores.lt(0).any() or valid_scores.gt(100).any():
            errors.append("catalyst_score outside 0~100 range")
        score_range = max_score - min_score
        if unique_count <= 1:
            warnings.append("catalyst_score unique count <= 1")
        if score_range <= 5:
            warnings.append("catalyst_score range <= 5")
        if std_score <= 2 and len(valid_scores) >= 3:
            warnings.append("catalyst_score standard deviation <= 2")

    component_unique_counts: dict[str, int] = {}
    for col in SCORE_COLUMNS:
        series = _score_series(df, col).dropna()
        component_unique_counts[col] = int(series.nunique(dropna=True)) if not series.empty else 0
        if not series.empty and (series.lt(0).any() or series.gt(100).any()):
            errors.append(f"{col} outside 0~100 range")

    return {
        "row_count": int(len(df)),
        "missing_columns": missing,
        "catalyst_score_min": min_score,
        "catalyst_score_max": max_score,
        "catalyst_score_mean": mean_score,
        "catalyst_score_std": std_score,
        "catalyst_score_unique_count": unique_count,
        "component_unique_counts": component_unique_counts,
        "score_distribution_status": _status_from(errors, warnings),
        "score_distribution_warning": " / ".join(warnings) if warnings else "",
        "warnings": warnings,
        "errors": errors,
    }


def validate_decision_log_diversity(df: pd.DataFrame) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if "decision_change_log" not in df.columns:
        errors.append("decision_change_log column missing")
        return {
            "decision_log_unique_count": 0,
            "top_decision_log": "",
            "top_decision_log_ratio": 0.0,
            "decision_log_status": "ERROR",
            "decision_log_warning": "decision_change_log 컬럼 누락",
            "warnings": warnings,
            "errors": errors,
        }
    logs = df["decision_change_log"].map(_safe_str)
    non_empty = logs[logs.ne("")]
    if non_empty.empty:
        warnings.append("decision_change_log is empty")
        return {
            "decision_log_unique_count": 0,
            "top_decision_log": "",
            "top_decision_log_ratio": 0.0,
            "decision_log_status": "WARNING",
            "decision_log_warning": "decision_change_log 비어 있음",
            "warnings": warnings,
            "errors": errors,
        }

    counts = non_empty.value_counts(dropna=False)
    top_log = str(counts.index[0])
    top_ratio = round(float(counts.iloc[0] / len(non_empty)), 4)
    if top_ratio >= 0.9:
        warnings.append("decision_change_log 동일 문구 90% 이상 반복")
        status = "STRONG_WARNING"
    elif top_ratio >= 0.7:
        warnings.append("decision_change_log 동일 문구 70% 이상 반복")
        status = "WARNING"
    else:
        status = "OK"
    group_warnings: list[str] = []
    for group_col in ["market", "source_file"]:
        if group_col not in df.columns:
            continue
        grouped = pd.DataFrame({"group": df[group_col].map(_safe_str), "log": logs})
        for group, group_df in grouped.groupby("group"):
            group_non_empty = group_df["log"][group_df["log"].ne("")]
            if len(group_non_empty) < 3:
                continue
            group_counts = group_non_empty.value_counts(dropna=False)
            group_ratio = float(group_counts.iloc[0] / len(group_non_empty))
            if group_ratio >= 0.9:
                group_warnings.append(f"{group_col}={group}: decision_change_log 동일 문구 90% 이상 반복")
            elif group_ratio >= 0.7:
                group_warnings.append(f"{group_col}={group}: decision_change_log 동일 문구 70% 이상 반복")
    if group_warnings:
        warnings.extend(group_warnings)
        if status == "OK":
            status = "WARNING"
    return {
        "decision_log_unique_count": int(non_empty.nunique(dropna=True)),
        "top_decision_log": top_log,
        "top_decision_log_ratio": top_ratio,
        "decision_log_status": status,
        "decision_log_warning": " / ".join(warnings) if warnings else "",
        "decision_log_group_warnings": group_warnings,
        "warnings": warnings,
        "errors": errors,
    }


def validate_symbol_level_catalyst_variation(df: pd.DataFrame) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    missing = [col for col in ["symbol", "catalyst_score"] if col not in df.columns]
    if missing:
        errors.append(f"missing symbol variation columns: {missing}")
    duplicated_symbols = 0
    symbol_count = 0
    if not missing and not df.empty:
        symbol_count = int(df["symbol"].map(_safe_str).replace("", pd.NA).dropna().nunique())
        score_by_symbol = df.assign(_score=_score_series(df, "catalyst_score")).groupby("symbol")["_score"].nunique(dropna=True)
        duplicated_symbols = int(score_by_symbol.index.duplicated().sum())
        if symbol_count >= 3 and int(_score_series(df, "catalyst_score").nunique(dropna=True)) <= 2:
            warnings.append("종목 수 대비 catalyst_score 차별화 부족")
    return {
        "symbol_count": symbol_count,
        "duplicated_symbol_count": duplicated_symbols,
        "symbol_variation_status": _status_from(errors, warnings),
        "symbol_variation_warning": " / ".join(warnings) if warnings else "",
        "warnings": warnings,
        "errors": errors,
    }


def _score_band(value: Any) -> str:
    score = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(score):
        return "데이터 없음"
    score = float(score)
    if score <= 30:
        return "낮음"
    if score <= 50:
        return "보통 이하"
    if score <= 70:
        return "보통"
    if score <= 85:
        return "높음"
    return "매우 높음"


def _row_data_flags(row: dict[str, Any]) -> dict[str, bool]:
    reasons = _safe_str(row.get("catalyst_reasons"))
    warnings = _safe_str(row.get("catalyst_warnings"))
    log = _safe_str(row.get("decision_change_log"))
    text = f"{reasons} / {warnings} / {log}".lower()
    news_status = _safe_str(row.get("news_data_status"))
    disclosure_status = _safe_str(row.get("disclosure_data_status"))
    no_news = news_status == "no_recent_issue" or "뉴스 데이터 부족" in text or "no recent news" in text
    no_disclosure = disclosure_status == "no_recent_issue" or "공시 데이터 부족" in text or "no recent disclosure" in text
    fallback = "fallback" in text or "데이터 부족" in text or "중립" in text
    available = _safe_str(row.get("catalyst_score_source")) == "api_confirmed" or (
        bool(reasons or warnings or log) and not (no_news and no_disclosure and fallback)
    )
    neutral = not fallback and 40 <= float(pd.to_numeric(pd.Series([row.get("catalyst_score")]), errors="coerce").fillna(0).iloc[0]) <= 60
    return {
        "api_data_available": available,
        "no_recent_news": no_news,
        "no_recent_disclosure": no_disclosure,
        "fallback_or_default_score": fallback,
        "actual_neutral_score": neutral,
    }


def build_catalyst_validation_report(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame()
    for col in REQUIRED_COLUMNS:
        out[col] = df[col] if col in df.columns else ""
    for col in OPTIONAL_STATUS_COLUMNS:
        if col in df.columns:
            out[col] = df[col]
    if "source_file" in df.columns:
        out["source_file"] = df["source_file"]
    flags = [_row_data_flags(row) for row in out.to_dict(orient="records")]
    flag_df = pd.DataFrame(flags)
    for col in flag_df.columns:
        out[col] = flag_df[col]
    out["catalyst_data_available"] = out.get("api_data_available", False)
    out["catalyst_score_band"] = out["catalyst_score"].map(_score_band) if "catalyst_score" in out.columns else "데이터 없음"

    row_statuses: list[str] = []
    row_warnings: list[str] = []
    for row in out.to_dict(orient="records"):
        warnings: list[str] = []
        score = pd.to_numeric(pd.Series([row.get("catalyst_score")]), errors="coerce").iloc[0]
        if pd.isna(score):
            warnings.append("catalyst_score numeric value missing")
            status = "ERROR"
        elif score < 0 or score > 100:
            warnings.append("catalyst_score outside 0~100")
            status = "ERROR"
        else:
            if row.get("fallback_or_default_score"):
                warnings.append("fallback/default catalyst evidence")
            if not row.get("catalyst_data_available"):
                warnings.append("symbol-level catalyst data weak")
            status = "WARNING" if warnings else "OK"
        row_statuses.append(status)
        row_warnings.append(" / ".join(warnings))
    out["catalyst_validation_status"] = row_statuses
    out["catalyst_validation_warning"] = row_warnings
    return out


def build_catalyst_validation_summary(report_df: pd.DataFrame) -> dict[str, Any]:
    distribution = validate_catalyst_score_distribution(report_df)
    decision_log = validate_decision_log_diversity(report_df)
    symbol_variation = validate_symbol_level_catalyst_variation(report_df)
    warnings = list(distribution.get("warnings", [])) + list(decision_log.get("warnings", [])) + list(symbol_variation.get("warnings", []))
    errors = list(distribution.get("errors", [])) + list(decision_log.get("errors", [])) + list(symbol_variation.get("errors", []))
    if "catalyst_validation_status" in report_df.columns:
        errors.extend(report_df.loc[report_df["catalyst_validation_status"].eq("ERROR"), "catalyst_validation_warning"].dropna().astype(str).unique().tolist())
    market_counts = report_df["market"].map(_safe_str).replace("", "unknown").value_counts().to_dict() if "market" in report_df.columns else {}
    overall_status = "ERROR" if errors else "WARNING" if warnings else "OK"
    return {
        "overall_status": overall_status,
        "row_count": int(len(report_df)),
        "market_counts": market_counts,
        "catalyst_score_min": distribution.get("catalyst_score_min", 0.0),
        "catalyst_score_max": distribution.get("catalyst_score_max", 0.0),
        "catalyst_score_mean": distribution.get("catalyst_score_mean", 0.0),
        "catalyst_score_std": distribution.get("catalyst_score_std", 0.0),
        "catalyst_score_unique_count": distribution.get("catalyst_score_unique_count", 0),
        "score_distribution_status": distribution.get("score_distribution_status", "ERROR"),
        "score_distribution_warning": distribution.get("score_distribution_warning", ""),
        "component_unique_counts": distribution.get("component_unique_counts", {}),
        "decision_log_unique_count": decision_log.get("decision_log_unique_count", 0),
        "top_decision_log": decision_log.get("top_decision_log", ""),
        "top_decision_log_ratio": decision_log.get("top_decision_log_ratio", 0.0),
        "decision_log_status": decision_log.get("decision_log_status", "ERROR"),
        "decision_log_warning": decision_log.get("decision_log_warning", ""),
        "decision_log_group_warnings": decision_log.get("decision_log_group_warnings", []),
        "symbol_count": symbol_variation.get("symbol_count", 0),
        "symbol_variation_status": symbol_variation.get("symbol_variation_status", "ERROR"),
        "warning_count": int(len(warnings)),
        "error_count": int(len(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "errors": list(dict.fromkeys(errors)),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def save_catalyst_validation_reports(
    candidate_files: list[str | Path] | None = None,
    report_path: str | Path = CATALYST_VALIDATION_REPORT_CSV,
    summary_path: str | Path = CATALYST_VALIDATION_SUMMARY_JSON,
) -> dict[str, Any]:
    df = load_candidate_catalyst_data(candidate_files)
    report_df = build_catalyst_validation_report(df)
    summary = build_catalyst_validation_summary(report_df)
    report_target = Path(report_path)
    summary_target = Path(summary_path)
    report_target.parent.mkdir(parents=True, exist_ok=True)
    summary_target.parent.mkdir(parents=True, exist_ok=True)
    report_df.to_csv(report_target, index=False, encoding="utf-8-sig")
    summary_target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return {
        "ok": summary.get("overall_status") != "ERROR",
        "report_path": str(report_target),
        "summary_path": str(summary_target),
        "summary": summary,
    }


def main() -> int:
    result = save_catalyst_validation_reports()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result.get("summary", {}).get("overall_status") == "ERROR" else 0


if __name__ == "__main__":
    raise SystemExit(main())
