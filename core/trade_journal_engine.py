"""
투자장부 분석 엔진
- 전략별(mode × horizon) 추천 현황 집계
- 섹터 / decisionBucket / surgeLabel 분포
- 가상 검증 수익률 표시
- 추격매수 · 손절지연 패턴 탐지
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")
STRATEGY_PERF_JSON = REPORT_DIR / "strategy_performance_report.json"
VIRTUAL_LEDGER_CSV = REPORT_DIR / "virtual_prediction_ledger.csv"

_MARKETS = ["kr", "us"]
_MODES = ["conservative", "balanced", "aggressive"]
_HORIZONS = ["short", "swing", "mid"]
_MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
_HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}
_MARKET_LABELS = {"kr": "국장", "us": "미장"}

_TV_PATTERN = "mone_v36_final_trade_validation_{market}_{mode}_{horizon}.csv"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "nan", "None", "-", "False", "True"}:
            return default
        s = s.replace(",", "").replace("%", "").replace("원", "").replace("배", "")
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


def load_current_trade_validation() -> pd.DataFrame:
    """비날짜 trade_validation CSV 18개(kr×us × 3modes × 3horizons)를 합친다."""
    frames: list[pd.DataFrame] = []
    for market in _MARKETS:
        for mode in _MODES:
            for horizon in _HORIZONS:
                path = REPORT_DIR / _TV_PATTERN.format(market=market, mode=mode, horizon=horizon)
                df = _read_csv(path)
                if df.empty:
                    continue
                df["_market_tag"] = market
                df["_mode_tag"] = mode
                df["_horizon_tag"] = horizon
                frames.append(df)
    if not frames:
        return pd.DataFrame()
    try:
        return pd.concat(frames, ignore_index=True, sort=False).fillna("")
    except Exception:
        return frames[0]


def load_all_trade_validation() -> pd.DataFrame:
    """날짜 스냅샷 포함 전체 trade_validation CSV를 합친다 (패턴 매칭용)."""
    frames: list[pd.DataFrame] = []
    for path in sorted(REPORT_DIR.glob("mone_v36_final_trade_validation_*.csv")):
        name = path.stem  # e.g. mone_v36_final_trade_validation_kr_balanced_swing_20260529
        parts = name.replace("mone_v36_final_trade_validation_", "").split("_")
        if len(parts) < 3:
            continue
        market = parts[0] if parts[0] in _MARKETS else ""
        mode = parts[1] if parts[1] in _MODES else ""
        horizon = parts[2] if parts[2] in _HORIZONS else ""
        snapshot_date = parts[3] if len(parts) >= 4 else "latest"
        df = _read_csv(path)
        if df.empty:
            continue
        df["_market_tag"] = market
        df["_mode_tag"] = mode
        df["_horizon_tag"] = horizon
        df["_snapshot_date"] = snapshot_date
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    try:
        return pd.concat(frames, ignore_index=True, sort=False).fillna("")
    except Exception:
        return frames[0]


def build_strategy_grid(df: pd.DataFrame) -> pd.DataFrame:
    """mode × horizon × market 별 후보 수 및 핵심 지표."""
    if df.empty:
        return pd.DataFrame()
    rows = []
    for market in _MARKETS:
        for mode in _MODES:
            for horizon in _HORIZONS:
                sub = df[
                    (df["_market_tag"] == market) &
                    (df["_mode_tag"] == mode) &
                    (df["_horizon_tag"] == horizon)
                ]
                if sub.empty:
                    continue
                total = len(sub)
                normal = int((sub["dataStatus"] == "NORMAL").sum()) if "dataStatus" in sub.columns else 0
                priority = int((sub["decisionBucket"] == "우선 진입").sum()) if "decisionBucket" in sub.columns else 0
                watch = int(sub["decisionBucket"].str.contains("대기", na=False).sum()) if "decisionBucket" in sub.columns else 0
                hold = int(sub["decisionBucket"].str.contains("보류", na=False).sum()) if "decisionBucket" in sub.columns else 0
                avg_score = sub["finalScore"].apply(_safe_float).replace(0.0, float("nan")).mean()
                undervalued = int((sub["isUndervaluedGrowth"] == "True").sum()) if "isUndervaluedGrowth" in sub.columns else 0
                rows.append({
                    "시장": _MARKET_LABELS[market],
                    "모드": _MODE_LABELS[mode],
                    "기간": _HORIZON_LABELS[horizon],
                    "전체": total,
                    "NORMAL": normal,
                    "우선진입": priority,
                    "대기관찰": watch,
                    "보류": hold,
                    "평균점수": round(avg_score, 1) if pd.notna(avg_score) else 0,
                    "저평가성장주": undervalued,
                })
    return pd.DataFrame(rows)


def build_sector_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """섹터별 추천 건수 및 평균 finalScore."""
    if df.empty:
        return pd.DataFrame()
    df2 = df.copy()
    df2["_sector"] = df2["sector"].apply(_safe_str).replace("", "미분류") if "sector" in df2.columns else "미분류"
    df2["_score"] = df2["finalScore"].apply(_safe_float) if "finalScore" in df2.columns else 0.0
    grouped = (
        df2.groupby("_sector")
        .agg(추천수=("_sector", "count"), 평균점수=("_score", "mean"))
        .reset_index()
        .rename(columns={"_sector": "섹터"})
    )
    grouped["평균점수"] = grouped["평균점수"].round(1)
    return grouped.sort_values("추천수", ascending=False).reset_index(drop=True)


def build_surge_label_distribution(df: pd.DataFrame) -> pd.DataFrame:
    """surgeLabel 태그 분포."""
    if df.empty or "surgeLabel" not in df.columns:
        return pd.DataFrame()
    all_tags: list[str] = []
    for val in df["surgeLabel"].apply(_safe_str):
        for tag in val.split("|"):
            t = tag.strip()
            if t and t != "없음":
                all_tags.append(t)
    if not all_tags:
        return pd.DataFrame()
    counts = Counter(all_tags)
    return pd.DataFrame([{"태그": k, "건수": v} for k, v in counts.most_common(20)])


def build_decision_bucket_summary(df: pd.DataFrame) -> dict[str, int]:
    """decisionBucket 분포."""
    if df.empty or "decisionBucket" not in df.columns:
        return {}
    return {k: int(v) for k, v in df["decisionBucket"].value_counts().items()}


def load_strategy_performance() -> dict[str, Any]:
    if not STRATEGY_PERF_JSON.exists():
        return {}
    try:
        return json.loads(STRATEGY_PERF_JSON.read_text(encoding="utf-8-sig"))
    except Exception:
        try:
            return json.loads(STRATEGY_PERF_JSON.read_text(encoding="utf-8"))
        except Exception:
            return {}


def build_validation_win_rate_table(perf: dict[str, Any]) -> pd.DataFrame:
    """mode × horizon 검증 수익률 표."""
    by_mode = perf.get("virtual_eval", {}).get("by_mode", {})
    if not by_mode:
        return pd.DataFrame()
    rows = []
    for mode_key, data in by_mode.items():
        for horizon_key in ["short", "swing", "mid"]:
            count = data.get(f"{horizon_key}_count", 0)
            wr = data.get(f"{horizon_key}_win_rate")
            avg_r = data.get(f"{horizon_key}_avg_return")
            rows.append({
                "모드": _MODE_LABELS.get(mode_key, mode_key),
                "기간": _HORIZON_LABELS.get(horizon_key, horizon_key),
                "검증건수": int(count),
                "승률(%)": f"{wr:.1f}" if wr is not None else "-",
                "평균수익률(%)": f"{avg_r:+.2f}" if avg_r is not None else "-",
            })
    return pd.DataFrame(rows)


def detect_risk_patterns(df: pd.DataFrame) -> dict[str, Any]:
    """추격매수 · 손익비 부족 · 데이터 품질 패턴 탐지."""
    result: dict[str, Any] = {}
    if df.empty:
        return result
    total = len(df)

    if "timingLabel" in df.columns:
        timing = df["timingLabel"].apply(_safe_str)
        chasing = timing.str.contains("과열", na=False).sum()
        pullback = timing.str.contains("눌림", na=False).sum()
        result["추격과열_건수"] = int(chasing)
        result["눌림목_건수"] = int(pullback)
        result["추격과열_비율"] = round(chasing / total * 100, 1) if total else 0

    if "rrActual" in df.columns:
        rr = df["rrActual"].apply(_safe_float)
        valid_rr = rr[rr > 0]
        low_rr = (valid_rr < 1.5).sum()
        result["손익비부족_건수"] = int(low_rr)
        result["평균손익비"] = round(valid_rr.mean(), 2) if len(valid_rr) > 0 else 0

    if "dataStatus" in df.columns:
        status_counts = df["dataStatus"].value_counts().to_dict()
        result["데이터상태"] = {k: int(v) for k, v in status_counts.items()}
        result["NORMAL_비율"] = round(status_counts.get("NORMAL", 0) / total * 100, 1) if total else 0

    if "entryScore" in df.columns:
        entry_scores = df["entryScore"].apply(_safe_float)
        low_entry = (entry_scores < 40).sum()
        result["진입점수부족_건수"] = int(low_entry)

    return result


def build_summary_metrics(df: pd.DataFrame, perf: dict[str, Any]) -> dict[str, Any]:
    """상단 요약 지표."""
    total = len(df)
    ve = perf.get("virtual_eval", {})
    metrics: dict[str, Any] = {
        "총추천건수": total,
        "총검증건수": ve.get("evaluated", 0),
        "PENDING건수": ve.get("pending", 0),
        "검증율": f"{ve.get('eval_rate_pct', 0):.1f}%",
        "실행건수": ve.get("dated_exec", 0),
        "전체승률": f"{ve.get('overall_win_rate', 0):.1f}%",
    }
    if "dataStatus" in df.columns:
        vc = df["dataStatus"].value_counts()
        metrics["NORMAL건수"] = int(vc.get("NORMAL", 0))
        metrics["DATA_PENDING건수"] = int(vc.get("DATA_PENDING", 0))
    if "market" in df.columns:
        vc2 = df["_market_tag"].value_counts() if "_market_tag" in df.columns else df["market"].value_counts()
        metrics["국장추천"] = int(vc2.get("kr", 0))
        metrics["미장추천"] = int(vc2.get("us", 0))
    return metrics
