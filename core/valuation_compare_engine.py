"""
밸류에이션 비교 엔진
- trade_validation CSV에서 PER/PBR/ROE/영업이익률/부채비율을 읽어 섹터 평균 산출
- 개별 종목과 섹터 평균 비교
- 저평가 성장주 판정 근거 제공
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPORT_DIR = Path("reports")

_FIN_COLS = ["per", "pbr", "roe", "operatingMargin", "debtRatio", "revenueGrowth", "epsGrowth"]
_FIN_LABELS = {
    "per": "PER",
    "pbr": "PBR",
    "roe": "ROE (%)",
    "operatingMargin": "영업이익률 (%)",
    "debtRatio": "부채비율 (%)",
    "revenueGrowth": "매출 성장률 (%)",
    "epsGrowth": "EPS 성장률 (%)",
}
_LOWER_IS_BETTER = {"per", "pbr", "debtRatio"}
_HIGHER_IS_BETTER = {"roe", "operatingMargin", "revenueGrowth", "epsGrowth"}


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "nan", "None", "-", "False", "True", "확인 필요"}:
            return default
        s = s.replace(",", "").replace("%", "").replace("배", "").replace("x", "").replace("X", "")
        return float(s)
    except Exception:
        return default


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def load_fundamental_universe() -> pd.DataFrame:
    """모든 현재 trade_validation CSV에서 섹터+재무 데이터만 추출한다."""
    frames: list[pd.DataFrame] = []
    for path in sorted(REPORT_DIR.glob("mone_v36_final_trade_validation_*.csv")):
        # 날짜 스냅샷 제외: 파일명 파트 수로 판단
        parts = path.stem.replace("mone_v36_final_trade_validation_", "").split("_")
        if len(parts) >= 4:
            continue  # 날짜 스냅샷
        df = _read_csv(path)
        if df.empty:
            continue
        cols = ["symbol", "name", "market", "sector", "mode", "horizon"] + [c for c in _FIN_COLS if c in df.columns]
        df2 = df[[c for c in cols if c in df.columns]].copy()
        for col in _FIN_COLS:
            if col not in df2.columns:
                df2[col] = float("nan")
            else:
                df2[col] = df2[col].apply(_safe_float)
        frames.append(df2)
    if not frames:
        return pd.DataFrame()
    try:
        return pd.concat(frames, ignore_index=True, sort=False)
    except Exception:
        return frames[0]


def build_sector_averages(df: pd.DataFrame) -> pd.DataFrame:
    """섹터별 재무 지표 중앙값을 계산한다."""
    if df.empty or "sector" not in df.columns:
        return pd.DataFrame()
    df2 = df.copy()
    df2["sector"] = df2["sector"].apply(_safe_str).replace("", "미분류")
    agg: dict[str, Any] = {}
    for col in _FIN_COLS:
        if col in df2.columns:
            agg[col] = "median"
    if not agg:
        return pd.DataFrame()
    result = (
        df2.groupby("sector")[list(agg.keys())]
        .agg("median")
        .reset_index()
        .rename(columns={"sector": "섹터"})
    )
    return result


def compare_symbol_to_sector(
    symbol: str,
    df: pd.DataFrame,
    sector_avg: pd.DataFrame,
) -> dict[str, Any]:
    """
    특정 종목의 재무 지표를 섹터 평균과 비교한다.

    Returns:
        {
            "symbol": str,
            "name": str,
            "sector": str,
            "metrics": [{"항목": str, "종목값": float, "섹터중앙값": float, "판단": str}, ...],
            "undervalued_signals": [...],
            "growth_signals": [...],
            "overall_verdict": str,
        }
    """
    symbol_upper = str(symbol).upper().strip()
    # 종목 행 찾기 (symbol 컬럼 우선, name도 시도)
    symbol_rows = df[
        df["symbol"].apply(lambda x: str(x).upper().strip()) == symbol_upper
    ] if "symbol" in df.columns else pd.DataFrame()

    if symbol_rows.empty and "name" in df.columns:
        symbol_rows = df[df["name"].apply(lambda x: str(x).strip()) == symbol.strip()]

    if symbol_rows.empty:
        return {
            "symbol": symbol, "name": "-", "sector": "-",
            "metrics": [], "undervalued_signals": [], "growth_signals": [],
            "overall_verdict": "데이터 없음",
        }

    row = symbol_rows.iloc[0]
    name = _safe_str(row.get("name", symbol))
    sector = _safe_str(row.get("sector", "")) or "미분류"

    # 섹터 평균 행
    sector_row: pd.Series | None = None
    if not sector_avg.empty and "섹터" in sector_avg.columns:
        match = sector_avg[sector_avg["섹터"] == sector]
        if not match.empty:
            sector_row = match.iloc[0]

    metrics = []
    undervalued_signals: list[str] = []
    growth_signals: list[str] = []

    for col in _FIN_COLS:
        label = _FIN_LABELS.get(col, col)
        sym_val = _safe_float(row.get(col, float("nan")))
        sec_val = float(sector_row[col]) if sector_row is not None and col in sector_row.index else float("nan")

        verdict = "-"
        if not np.isnan(sym_val) and not np.isnan(sec_val) and sec_val != 0:
            ratio = sym_val / sec_val
            if col in _LOWER_IS_BETTER:
                if ratio < 0.8:
                    verdict = "섹터 대비 낮음 (우호)"
                    if col == "per":
                        undervalued_signals.append(f"PER {sym_val:.1f} < 섹터 중앙값 {sec_val:.1f}")
                    elif col == "pbr":
                        undervalued_signals.append(f"PBR {sym_val:.1f} < 섹터 중앙값 {sec_val:.1f}")
                elif ratio > 1.2:
                    verdict = "섹터 대비 높음 (부담)"
                else:
                    verdict = "섹터 평균 수준"
            elif col in _HIGHER_IS_BETTER:
                if ratio > 1.2:
                    verdict = "섹터 대비 높음 (우호)"
                    if col == "roe":
                        undervalued_signals.append(f"ROE {sym_val:.1f}% > 섹터 중앙값 {sec_val:.1f}%")
                    if col in {"revenueGrowth", "epsGrowth"}:
                        growth_signals.append(f"{label} {sym_val:.1f}% > 섹터 {sec_val:.1f}%")
                elif ratio < 0.8:
                    verdict = "섹터 대비 낮음 (부담)"
                else:
                    verdict = "섹터 평균 수준"
        elif not np.isnan(sym_val):
            verdict = "섹터 비교 데이터 없음"

        metrics.append({
            "항목": label,
            "종목값": f"{sym_val:.2f}" if not np.isnan(sym_val) else "-",
            "섹터중앙값": f"{sec_val:.2f}" if not np.isnan(sec_val) else "-",
            "판단": verdict,
        })

    # 최종 판단
    uv_count = len(undervalued_signals)
    gr_count = len(growth_signals)
    if uv_count >= 2 and gr_count >= 1:
        overall_verdict = "저평가 성장주 가능성 높음"
    elif uv_count >= 1 and gr_count >= 1:
        overall_verdict = "저평가 성장주 후보"
    elif uv_count >= 2:
        overall_verdict = "저평가 (성장성 확인 필요)"
    elif gr_count >= 2:
        overall_verdict = "성장주 (밸류에이션 확인 필요)"
    else:
        overall_verdict = "판단 보류 (데이터 부족 또는 평균 수준)"

    return {
        "symbol": symbol,
        "name": name,
        "sector": sector,
        "metrics": metrics,
        "undervalued_signals": undervalued_signals,
        "growth_signals": growth_signals,
        "overall_verdict": overall_verdict,
    }


def build_sector_comparison_table(sector_avg: pd.DataFrame) -> pd.DataFrame:
    """섹터별 재무 지표 비교 테이블 (UI 표시용)."""
    if sector_avg.empty:
        return pd.DataFrame()
    display = sector_avg.copy()
    col_renames = {"섹터": "섹터"}
    for col in _FIN_COLS:
        if col in display.columns:
            display[col] = display[col].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "-"
            )
            col_renames[col] = _FIN_LABELS.get(col, col)
    return display.rename(columns=col_renames)
