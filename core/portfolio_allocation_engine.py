from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PORTFOLIO_ALLOCATION_SUMMARY = DATA_DIR / "portfolio_allocation_summary.csv"

ALLOCATION_COLUMNS = [
    "holding_type",
    "current_value",
    "current_weight_pct",
    "recommended_min_pct",
    "recommended_max_pct",
    "allocation_status",
    "adjustment_suggestion",
    "is_estimated_type",
    "updated_at",
]

TYPE_RULES = {
    "장기 핵심 ETF/우량주": (50, 60),
    "중기 성장주/주도주": (25, 35),
    "단기 테마/스윙": (10, 15),
    "현금": (10, 20),
}


def _now() -> str:
    from datetime import datetime

    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _num(value: Any) -> float:
    try:
        text = str(value).replace(",", "").replace("%", "").replace("원", "").replace("$", "").strip()
        if text == "" or text.lower() in {"nan", "none", "n/a"}:
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def _first(row: Any, keys: list[str]) -> str:
    for key in keys:
        try:
            value = row.get(key, "")
        except Exception:
            value = ""
        if value not in (None, ""):
            return str(value)
    return ""


def classify_holding_type(row: Any) -> tuple[str, bool, str]:
    explicit = _first(row, ["holding_type", "보유유형", "type"])
    if explicit:
        text = explicit.lower()
        if any(k in text for k in ["cash", "현금"]):
            return "현금", False, "holding_type 명시"
        if any(k in text for k in ["etf", "우량", "core", "장기"]):
            return "장기 핵심 ETF/우량주", False, "holding_type 명시"
        if any(k in text for k in ["growth", "성장", "주도", "중기"]):
            return "중기 성장주/주도주", False, "holding_type 명시"
        if any(k in text for k in ["swing", "theme", "테마", "단기"]):
            return "단기 테마/스윙", False, "holding_type 명시"

    combined = " ".join(_first(row, ["symbol", "ticker", "name", "종목명", "theme", "group", "risk_level", "memo"]).lower().split())
    if any(k in combined for k in ["cash", "현금"]):
        return "현금", True, "이름/메모 기준 추정"
    if any(k in combined for k in ["spy", "qqq", "voo", "schd", "etf", "삼성전자", "apple", "microsoft", "msft"]):
        return "장기 핵심 ETF/우량주", True, "심볼/이름 기준 추정"
    if any(k in combined for k in ["성장", "growth", "ai", "반도체", "2차전지", "주도"]):
        return "중기 성장주/주도주", True, "테마/그룹 기준 추정"
    if any(k in combined for k in ["테마", "swing", "단기", "고위험", "speculative"]):
        return "단기 테마/스윙", True, "위험/테마 기준 추정"
    return "중기 성장주/주도주", True, "보유유형 없음: 중기 성장주로 보수 추정"


def calculate_portfolio_allocation(holdings_df: pd.DataFrame) -> pd.DataFrame:
    if holdings_df is None or holdings_df.empty:
        return pd.DataFrame(columns=["ticker", "holding_type", "evaluation_amount", "is_estimated_type", "type_reason"])
    rows: list[dict[str, Any]] = []
    for _, row in holdings_df.iterrows():
        htype, estimated, reason = classify_holding_type(row)
        quantity = _num(_first(row, ["quantity", "qty", "수량", "보유수량"]))
        current_price = _num(_first(row, ["current_price", "현재가", "last_price"]))
        buy_amount = _num(_first(row, ["buy_amount", "평가금액", "evaluation_amount", "amount"]))
        value = buy_amount if buy_amount else quantity * current_price
        rows.append(
            {
                "ticker": _first(row, ["ticker", "symbol", "종목코드", "종목"]),
                "name": _first(row, ["name", "종목명", "회사명"]),
                "holding_type": htype,
                "evaluation_amount": value,
                "is_estimated_type": estimated,
                "type_reason": reason,
            }
        )
    return pd.DataFrame(rows)


def _recommended_ranges(market_context: dict[str, Any] | None = None) -> dict[str, tuple[float, float]]:
    ranges = {k: tuple(v) for k, v in TYPE_RULES.items()}
    risk = _num((market_context or {}).get("market_risk_score", 0))
    if risk >= 80:
        ranges["현금"] = (20, 30)
        ranges["단기 테마/스윙"] = (5, 10)
    elif risk >= 60:
        ranges["현금"] = (15, 25)
        ranges["단기 테마/스윙"] = (8, 12)
    return ranges


def evaluate_portfolio_allocation(holdings_df: pd.DataFrame, market_context: dict[str, Any] | None = None) -> pd.DataFrame:
    detail = calculate_portfolio_allocation(holdings_df)
    ranges = _recommended_ranges(market_context)
    if detail.empty:
        out = pd.DataFrame(columns=ALLOCATION_COLUMNS)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        out.to_csv(PORTFOLIO_ALLOCATION_SUMMARY, index=False, encoding="utf-8-sig")
        return out
    total = float(detail["evaluation_amount"].sum())
    grouped = detail.groupby("holding_type", dropna=False).agg(
        current_value=("evaluation_amount", "sum"),
        is_estimated_type=("is_estimated_type", "max"),
    ).reset_index()
    rows: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        htype = str(row.get("holding_type", "중기 성장주/주도주"))
        current_value = float(row.get("current_value", 0) or 0)
        weight = (current_value / total * 100) if total > 0 else 0.0
        rec_min, rec_max = ranges.get(htype, (0, 0))
        if total <= 0:
            status = "확인 필요"
            suggestion = "평가금액 데이터 부족"
        elif weight > rec_max:
            status = "과다"
            suggestion = f"{htype} 비중 조정 검토"
        elif weight < rec_min:
            status = "부족"
            suggestion = f"{htype} 비중 보강 여부 검토"
        else:
            status = "적정 범위"
            suggestion = "현재 비중 유지 검토"
        rows.append(
            {
                "holding_type": htype,
                "current_value": round(current_value, 2),
                "current_weight_pct": round(weight, 2),
                "recommended_min_pct": rec_min,
                "recommended_max_pct": rec_max,
                "allocation_status": status,
                "adjustment_suggestion": suggestion,
                "is_estimated_type": bool(row.get("is_estimated_type", False)),
                "updated_at": _now(),
            }
        )

    if "현금" not in set(grouped["holding_type"].astype(str)):
        rec_min, rec_max = ranges["현금"]
        rows.append(
            {
                "holding_type": "현금",
                "current_value": 0,
                "current_weight_pct": 0,
                "recommended_min_pct": rec_min,
                "recommended_max_pct": rec_max,
                "allocation_status": "부족",
                "adjustment_suggestion": "현금 비중 부족 여부 확인",
                "is_estimated_type": True,
                "updated_at": _now(),
            }
        )

    out = pd.DataFrame(rows, columns=ALLOCATION_COLUMNS)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out.to_csv(PORTFOLIO_ALLOCATION_SUMMARY, index=False, encoding="utf-8-sig")
    return out


def detect_portfolio_concentration(holdings_df: pd.DataFrame) -> list[str]:
    if holdings_df is None or holdings_df.empty:
        return ["보유종목 데이터 없음"]
    notes: list[str] = []
    sector_col = next((c for c in ["sector", "theme", "group", "섹터", "테마"] if c in holdings_df.columns), "")
    if sector_col:
        values = holdings_df[sector_col].astype(str).replace("", "미분류")
        top = values.value_counts(normalize=True).head(1)
        if not top.empty and float(top.iloc[0]) >= 0.5:
            notes.append(f"{top.index[0]} 쏠림 가능성")
    detail = calculate_portfolio_allocation(holdings_df)
    if not detail.empty:
        swing_value = float(detail.loc[detail["holding_type"].eq("단기 테마/스윙"), "evaluation_amount"].sum())
        total = float(detail["evaluation_amount"].sum())
        if total > 0 and swing_value / total >= 0.2:
            notes.append("단기 테마/스윙 비중 과다 가능성")
    return notes or ["특정 쏠림 신호 제한"]
