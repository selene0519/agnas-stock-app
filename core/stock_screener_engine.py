"""
고급 종목 스크리너 엔진
- 투자성향 / 투자기간 / 전략태그 / 밸류에이션 / 기술지표 / 데이터 상태 / 손익비 필터
- 현재 trade_validation 데이터를 기반으로 실시간 필터링
- 결과를 정렬된 DataFrame으로 반환
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")

_MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
_HORIZON_LABELS = {"short": "단기", "swing": "스윙", "mid": "중기"}
_MARKET_LABELS = {"kr": "국장", "us": "미장"}
_MARKET_LABELS_REV = {"국장": "kr", "미장": "us"}
_MODE_LABELS_REV = {"보수": "conservative", "균형": "balanced", "공격": "aggressive"}
_HORIZON_LABELS_REV = {"단기": "short", "스윙": "swing", "중기": "mid"}

_DISPLAY_COLS = [
    "시장", "종목코드", "종목명", "섹터", "모드", "기간",
    "진입구분", "타이밍", "진입가", "손절가", "목표가", "확률(%)",
    "최종점수", "손익비", "추천태그", "저평가성장주", "데이터상태",
    "PER", "PBR", "ROE",
]


def _safe_float(value: Any, default: float = float("nan")) -> float:
    try:
        if value is None:
            return default
        s = str(value).strip()
        if s in {"", "nan", "None", "-", "False", "True", "확인 필요"}:
            return default
        return float(s.replace(",", "").replace("%", "").replace("원", "").replace("배", ""))
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


def load_screener_universe() -> pd.DataFrame:
    """현재 버전(날짜 스냅샷 제외) trade_validation CSV 18개를 합쳐 스크리너 유니버스를 만든다."""
    frames: list[pd.DataFrame] = []
    for path in sorted(REPORT_DIR.glob("mone_v36_final_trade_validation_*.csv")):
        parts = path.stem.replace("mone_v36_final_trade_validation_", "").split("_")
        if len(parts) >= 4:
            continue  # 날짜 스냅샷 제외
        if len(parts) < 3:
            continue
        market, mode, horizon = parts[0], parts[1], parts[2]
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


def get_filter_options(df: pd.DataFrame) -> dict[str, list[str]]:
    """스크리너 필터 선택지를 반환한다."""
    opts: dict[str, list[str]] = {
        "시장": ["전체", "국장", "미장"],
        "모드": ["전체", "보수", "균형", "공격"],
        "기간": ["전체", "단기", "스윙", "중기"],
        "진입구분": ["전체"],
        "데이터상태": ["전체", "NORMAL", "PARTIAL", "DATA_PENDING", "CAUTION"],
        "섹터": ["전체"],
        "추천태그": ["전체"],
    }
    if "decisionBucket" in df.columns:
        buckets = [_safe_str(v) for v in df["decisionBucket"].unique() if _safe_str(v)]
        opts["진입구분"] = ["전체"] + sorted(set(buckets))
    if "sector" in df.columns:
        sectors = [_safe_str(v) for v in df["sector"].unique() if _safe_str(v)]
        opts["섹터"] = ["전체"] + sorted(set(sectors))
    if "surgeLabel" in df.columns:
        from collections import Counter
        all_tags: list[str] = []
        for val in df["surgeLabel"].apply(_safe_str):
            for tag in val.split("|"):
                t = tag.strip()
                if t:
                    all_tags.append(t)
        top_tags = [k for k, _ in Counter(all_tags).most_common(20)]
        opts["추천태그"] = ["전체"] + top_tags
    return opts


def apply_filters(
    df: pd.DataFrame,
    *,
    market: str = "전체",
    mode: str = "전체",
    horizon: str = "전체",
    decision_bucket: str = "전체",
    data_status: str = "전체",
    sector: str = "전체",
    surge_tag: str = "전체",
    only_normal: bool = False,
    only_undervalued: bool = False,
    only_priority: bool = False,
    min_score: float = 0.0,
    max_score: float = 100.0,
    min_rr: float = 0.0,
    max_per: float = 999.0,
    min_roe: float = -999.0,
    sort_by: str = "최종점수",
) -> pd.DataFrame:
    """다중 필터를 적용하고 정렬된 결과를 반환한다."""
    sub = df.copy()

    # 시장
    if market != "전체":
        mkt_key = _MARKET_LABELS_REV.get(market, market)
        sub = sub[sub["_market_tag"] == mkt_key]

    # 모드
    if mode != "전체":
        mode_key = _MODE_LABELS_REV.get(mode, mode)
        sub = sub[sub["_mode_tag"] == mode_key]

    # 기간
    if horizon != "전체":
        hz_key = _HORIZON_LABELS_REV.get(horizon, horizon)
        sub = sub[sub["_horizon_tag"] == hz_key]

    # 진입구분
    if decision_bucket != "전체" and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_safe_str).str.contains(decision_bucket, case=False, na=False)]

    # 데이터 상태
    if data_status != "전체" and "dataStatus" in sub.columns:
        sub = sub[sub["dataStatus"].apply(_safe_str) == data_status]

    # NORMAL만
    if only_normal and "dataStatus" in sub.columns:
        sub = sub[sub["dataStatus"].apply(_safe_str) == "NORMAL"]

    # 섹터
    if sector != "전체" and "sector" in sub.columns:
        sub = sub[sub["sector"].apply(_safe_str).str.contains(sector, case=False, na=False)]

    # 추천 태그
    if surge_tag != "전체" and "surgeLabel" in sub.columns:
        sub = sub[sub["surgeLabel"].apply(_safe_str).str.contains(surge_tag, case=False, na=False)]

    # 저평가 성장주만
    if only_undervalued and "isUndervaluedGrowth" in sub.columns:
        sub = sub[sub["isUndervaluedGrowth"].apply(_safe_str) == "True"]

    # 우선 진입만
    if only_priority and "decisionBucket" in sub.columns:
        sub = sub[sub["decisionBucket"].apply(_safe_str).str.contains("우선", na=False)]

    # finalScore 범위
    if "finalScore" in sub.columns:
        scores = sub["finalScore"].apply(_safe_float)
        sub = sub[(scores.isna()) | ((scores >= min_score) & (scores <= max_score))]

    # 손익비 최소
    if min_rr > 0 and "rrActual" in sub.columns:
        rr = sub["rrActual"].apply(_safe_float)
        sub = sub[(rr.isna()) | (rr >= min_rr)]

    # PER 최대
    if max_per < 999.0 and "per" in sub.columns:
        per_vals = sub["per"].apply(_safe_float)
        sub = sub[(per_vals.isna()) | ((per_vals > 0) & (per_vals <= max_per))]

    # ROE 최소
    if min_roe > -999.0 and "roe" in sub.columns:
        roe_vals = sub["roe"].apply(_safe_float)
        sub = sub[(roe_vals.isna()) | (roe_vals >= min_roe)]

    # 정렬
    sort_col_map = {
        "최종점수": "finalScore",
        "손익비": "rrActual",
        "기회점수": "opportunityScore",
        "확률": "probability",
        "PER": "per",
        "ROE": "roe",
    }
    raw_sort = sort_col_map.get(sort_by, "finalScore")
    if raw_sort in sub.columns:
        sub["_sort_key"] = sub[raw_sort].apply(_safe_float)
        ascending = raw_sort in {"per"}  # PER은 낮을수록 좋음
        sub = sub.sort_values("_sort_key", ascending=ascending, na_position="last")
        sub = sub.drop(columns=["_sort_key"])

    return sub.reset_index(drop=True)


def format_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """스크리너 결과를 UI 표시용으로 변환한다."""
    if df.empty:
        return pd.DataFrame(columns=_DISPLAY_COLS)

    def _fmt_price(v: Any, market: str) -> str:
        f = _safe_float(v)
        if pd.isna(f) or f == 0:
            return "-"
        if market == "kr":
            return f"{f:,.0f}원"
        return f"${f:.2f}"

    def _fmt_pct(v: Any) -> str:
        f = _safe_float(v)
        return f"{f:.1f}%" if not pd.isna(f) and f != 0 else "-"

    def _fmt_val(v: Any, decimals: int = 1) -> str:
        f = _safe_float(v)
        return f"{f:.{decimals}f}" if not pd.isna(f) and f != 0 else "-"

    rows = []
    for _, row in df.iterrows():
        market = _safe_str(row.get("_market_tag", ""))
        rows.append({
            "시장": _MARKET_LABELS.get(market, market),
            "종목코드": _safe_str(row.get("symbol", "")),
            "종목명": _safe_str(row.get("name", "")),
            "섹터": _safe_str(row.get("sector", "")) or "-",
            "모드": _MODE_LABELS.get(_safe_str(row.get("_mode_tag", "")), "-"),
            "기간": _HORIZON_LABELS.get(_safe_str(row.get("_horizon_tag", "")), "-"),
            "진입구분": _safe_str(row.get("decisionBucket", "")) or "-",
            "타이밍": _safe_str(row.get("timingLabel", "")) or "-",
            "진입가": _fmt_price(row.get("entry"), market),
            "손절가": _fmt_price(row.get("stop"), market),
            "목표가": _fmt_price(row.get("target"), market),
            "확률(%)": _fmt_pct(row.get("probability")),
            "최종점수": _fmt_val(row.get("finalScore")),
            "손익비": _fmt_val(row.get("rrActual", row.get("rr_actual")), 2),
            "추천태그": _safe_str(row.get("surgeLabel", "")) or "-",
            "저평가성장주": "✓" if _safe_str(row.get("isUndervaluedGrowth")) == "True" else "",
            "데이터상태": _safe_str(row.get("dataStatus", "")) or "-",
            "PER": _fmt_val(row.get("per")),
            "PBR": _fmt_val(row.get("pbr")),
            "ROE": _fmt_pct(row.get("roe")),
        })

    return pd.DataFrame(rows)


def get_screener_summary(df: pd.DataFrame) -> dict[str, Any]:
    """필터 결과 요약 지표."""
    total = len(df)
    if total == 0:
        return {"total": 0}
    result: dict[str, Any] = {"total": total}
    if "isUndervaluedGrowth" in df.columns:
        result["저평가성장주"] = int((df["isUndervaluedGrowth"].apply(_safe_str) == "True").sum())
    if "decisionBucket" in df.columns:
        result["우선진입"] = int(df["decisionBucket"].apply(_safe_str).str.contains("우선", na=False).sum())
    if "dataStatus" in df.columns:
        result["NORMAL"] = int((df["dataStatus"].apply(_safe_str) == "NORMAL").sum())
    if "finalScore" in df.columns:
        scores = df["finalScore"].apply(_safe_float)
        valid = scores[scores > 0]
        result["평균점수"] = round(valid.mean(), 1) if len(valid) > 0 else 0
    return result
