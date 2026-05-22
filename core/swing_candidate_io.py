from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.swing_candidate_grade_engine import ensure_grade_change_columns
from core.unified_display_enrichment import COMMON_CANDIDATE_COLUMNS, enrich_candidate_frame


REPORT_DIR = Path("reports")
SWING_CANDIDATE_FILES = [
    REPORT_DIR / "swing_candidates_us_A_top3.csv",
    REPORT_DIR / "swing_candidates_us_B_watch.csv",
    REPORT_DIR / "swing_candidates_us_C_excluded.csv",
    REPORT_DIR / "swing_candidates_kr_A_top3.csv",
    REPORT_DIR / "swing_candidates_kr_B_watch.csv",
    REPORT_DIR / "swing_candidates_kr_C_excluded.csv",
]
BASE_REQUIRED_COLUMNS = [
    "scan_time_kst",
    "market",
    "symbol",
    "name",
    "grade",
    "score",
    "reason",
    "exclude_reason",
]


def read_swing_candidate_csv(path: str | Path, required_columns: list[str] | None = None) -> pd.DataFrame:
    target = Path(path)
    columns = list(dict.fromkeys((required_columns or []) + BASE_REQUIRED_COLUMNS))
    if not target.exists() or target.stat().st_size <= 0:
        return ensure_swing_candidate_schema(pd.DataFrame(columns=columns), columns)
    try:
        df = pd.read_csv(target, dtype=str, low_memory=False).fillna("")
    except Exception:
        df = pd.DataFrame(columns=columns)
    return ensure_swing_candidate_schema(df, columns)


def ensure_swing_candidate_schema(candidate_df: pd.DataFrame, required_columns: list[str] | None = None) -> pd.DataFrame:
    out = candidate_df.copy() if candidate_df is not None else pd.DataFrame()
    for col in required_columns or BASE_REQUIRED_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col != "score" else 0
    out = ensure_grade_change_columns(out)
    return out


def save_swing_candidate_csv(
    candidate_df: pd.DataFrame,
    path: str | Path,
    required_columns: list[str] | None = None,
    preferred_columns: list[str] | None = None,
    encoding: str = "utf-8-sig",
) -> Path:
    target = Path(path)
    out = ensure_swing_candidate_schema(candidate_df, required_columns)
    try:
        out = enrich_candidate_frame(out, source_path=target, ensure_common_columns=True)
    except Exception:
        for col in COMMON_CANDIDATE_COLUMNS:
            if col not in out.columns:
                out[col] = ""
    if preferred_columns:
        preferred = list(dict.fromkeys(list(preferred_columns) + COMMON_CANDIDATE_COLUMNS))
        first = [col for col in preferred if col in out.columns]
        rest = [col for col in out.columns if col not in first]
        out = out[first + rest]
    target.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(target, index=False, encoding=encoding)
    return target


def load_swing_candidate_files(paths: list[str | Path] | None = None, required_columns: list[str] | None = None) -> dict[str, pd.DataFrame]:
    return {str(path): read_swing_candidate_csv(path, required_columns) for path in (paths or SWING_CANDIDATE_FILES)}


def write_swing_candidate_split(
    all_df: pd.DataFrame,
    paths: dict[str, str | Path],
    preferred_columns: dict[str, list[str]] | None = None,
    required_columns: list[str] | None = None,
) -> dict[str, str]:
    out = ensure_swing_candidate_schema(all_df, required_columns)
    if "grade" not in out.columns:
        out["grade"] = ""
    grade_series = out["grade"].astype(str)
    split_map: dict[str, pd.DataFrame] = {
        "all": out,
        "a": out[grade_series.eq("A")].copy(),
        "b": out[grade_series.eq("B")].copy(),
        "c": out[grade_series.eq("C")].copy(),
    }
    result: dict[str, str] = {}
    for key, df in split_map.items():
        if key not in paths:
            continue
        result[key] = str(
            save_swing_candidate_csv(
                df,
                paths[key],
                required_columns=required_columns,
                preferred_columns=(preferred_columns or {}).get(key),
            )
        )
    return result


def summarize_candidate_counts(candidate_df: pd.DataFrame) -> dict[str, Any]:
    if candidate_df is None or candidate_df.empty or "grade" not in candidate_df.columns:
        return {"A": 0, "B": 0, "C": 0, "total": 0}
    grades = candidate_df["grade"].astype(str)
    return {
        "A": int(grades.eq("A").sum()),
        "B": int(grades.eq("B").sum()),
        "C": int(grades.eq("C").sum()),
        "total": int(len(candidate_df)),
    }
