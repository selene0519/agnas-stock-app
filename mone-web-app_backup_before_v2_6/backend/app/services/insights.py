from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from app.services import data_loader as data

SUCCESS_TOKENS = ("success", "hit", "true", "1", "성공", "적중", "도달", "수익", "익절", "상승")
FAIL_TOKENS = ("fail", "miss", "false", "0", "실패", "불일치", "손절", "하락", "미도달", "loss")
NEUTRAL_TOKENS = ("neutral", "대기", "관망", "pending", "hold", "보류", "검증", "데이터")


def _read(path: Path) -> pd.DataFrame:
    return data.read_csv(path).fillna("")


def _txt(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", "nat"}:
        return ""
    return text


def _first(row: dict[str, Any] | pd.Series, names: list[str], fallback: str = "") -> str:
    lower = {str(c).strip().lower(): c for c in row.keys()}
    for name in names:
        key = name.strip().lower()
        if key in lower:
            value = _txt(row.get(lower[key], ""))
            if value:
                return value
    return fallback


def _symbol(row: dict[str, Any] | pd.Series, market: str) -> str:
    return data.normalize_symbol(_first(row, data.SYMBOL_ALIASES + ["ticker", "종목코드", "code"], ""), market)


def _name(row: dict[str, Any] | pd.Series, fallback: str = "") -> str:
    return _first(row, data.NAME_ALIASES + ["stock_name", "name", "종목명"], fallback)


def _market(row: dict[str, Any] | pd.Series) -> str:
    raw = _first(row, ["market", "시장"], "").lower()
    if raw in {"us", "미국", "미국주식", "usa", "nas", "nasdaq", "nyse"}:
        return "us"
    if raw in {"kr", "한국", "한국주식", "국장", "kospi", "kosdaq"}:
        return "kr"
    return ""


def _row_matches_market(row: dict[str, Any] | pd.Series, market: str) -> bool:
    m = _market(row)
    if not m:
        sym = _symbol(row, market)
        if market == "kr":
            return sym.isdigit() or len(sym) == 6
        return bool(sym and not sym.isdigit())
    return m == market


def _date(row: dict[str, Any] | pd.Series) -> str:
    return _first(row, ["target_date", "prediction_date", "date", "created_at", "예측일", "기준일", "날짜"], "날짜 없음")[:10]


def _period_key(date_text: str) -> str:
    text = _txt(date_text)
    if len(text) >= 7 and text[4] == "-":
        return text[:7]
    if len(text) >= 6 and text[:6].isdigit():
        return f"{text[:4]}-{text[4:6]}"
    return "기간 미상"


def _classify_result(row: dict[str, Any] | pd.Series) -> str:
    candidates = [
        _first(row, ["prediction_result", "final_result", "result", "decision_success", "direction_hit", "close_in_range", "open_in_range", "return_1d", "return_pct"], ""),
        _first(row, ["RETURN_1D", "PRICE_1D", "price_1d", "status", "상태"], ""),
    ]
    joined = " ".join(candidates).lower()
    if any(token in joined for token in SUCCESS_TOKENS):
        return "success"
    if any(token in joined for token in FAIL_TOKENS):
        return "fail"
    if any(token in joined for token in NEUTRAL_TOKENS):
        return "neutral"
    for c in ["return_1d", "RETURN_1D", "return_pct", "수익률"]:
        try:
            if c in row:
                val = float(str(row.get(c, "")).replace("%", "").replace(",", ""))
                if val > 0:
                    return "success"
                if val < 0:
                    return "fail"
        except Exception:
            pass
    return "neutral"


def _pct(success: int, fail: int, neutral: int = 0) -> str:
    denom = success + fail
    if denom <= 0:
        return "검증 데이터 부족"
    return f"{success / denom * 100:.1f}%"


def _rows(df: pd.DataFrame, market: str) -> list[dict[str, Any]]:
    if df.empty:
        return []
    out = []
    for row in data.dataframe_records(df, len(df)):
        if _row_matches_market(row, market):
            out.append(row)
    return out


def _count_by_result(rows: list[dict[str, Any]]) -> Counter:
    counter = Counter()
    for row in rows:
        counter[_classify_result(row)] += 1
    return counter


def _symbol_decision(success: int, fail: int, neutral: int, total: int) -> str:
    judged = success + fail
    if judged < 3:
        return "검증 표본 부족"
    rate = success / judged if judged else 0
    if rate >= 0.62 and fail <= success:
        return "예측 신뢰 우선 후보"
    if rate <= 0.40 and fail >= 3:
        return "자동 보정 필요"
    if neutral > judged:
        return "관망/대기 비중 높음"
    return "일반 추적"


def _by_symbol(rows: list[dict[str, Any]], market: str, limit: int = 80) -> list[dict[str, Any]]:
    bucket: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = _symbol(row, market)
        if not sym:
            continue
        item = bucket.setdefault(sym, {
            "symbol": sym,
            "name": _name(row, sym),
            "predictions": 0,
            "success": 0,
            "fail": 0,
            "neutral": 0,
            "lastDate": "",
            "failureReason": "",
        })
        item["predictions"] += 1
        cls = _classify_result(row)
        item[cls] += 1
        date = _date(row)
        if date and date > str(item.get("lastDate", "")):
            item["lastDate"] = date
        reason = _first(row, ["failure_reason", "prediction_error_reason", "reason", "prediction_cause_summary", "메모", "memo"], "")
        if cls == "fail" and reason:
            item["failureReason"] = reason[:120]
    items = []
    for item in bucket.values():
        success = int(item["success"])
        fail = int(item["fail"])
        neutral = int(item["neutral"])
        item["successRate"] = _pct(success, fail, neutral)
        item["decision"] = _symbol_decision(success, fail, neutral, int(item["predictions"]))
        items.append(item)
    return sorted(items, key=lambda x: (int(x["fail"]), int(x["predictions"])), reverse=True)[:limit]


def _by_period(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bucket: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        bucket[_period_key(_date(row))][_classify_result(row)] += 1
    out = []
    for period, c in sorted(bucket.items(), reverse=True):
        success = c["success"]
        fail = c["fail"]
        neutral = c["neutral"]
        out.append({
            "period": period,
            "success": success,
            "fail": fail,
            "neutral": neutral,
            "successRate": _pct(success, fail, neutral),
            "total": success + fail + neutral,
        })
    return out[:24]


def _failure_action(reason: str) -> str:
    text = (reason or "").lower()
    if "뉴스" in text or "event" in text or "공시" in text:
        return "뉴스/공시 이벤트 가중치 점검"
    if "수급" in text or "flow" in text:
        return "수급 조건 가중치 하향/필터 강화"
    if "손절" in text or "변동" in text or "vol" in text:
        return "변동성/손절폭 보정"
    if "과열" in text or "rsi" in text:
        return "과열 구간 진입 제한"
    return "동일 조건 반복 실패 여부 확인"


def _failure_rows(rows: list[dict[str, Any]], market: str, limit: int = 80) -> list[dict[str, Any]]:
    failures = []
    for row in rows:
        if _classify_result(row) != "fail":
            continue
        sym = _symbol(row, market) or "코드 없음"
        reason = _first(row, ["failure_reason", "prediction_error_reason", "reason", "prediction_cause_summary", "memo", "메모"], "실패 사유 컬럼 부족")
        failures.append({
            "date": _date(row),
            "symbol": sym,
            "name": _name(row, sym),
            "result": "실패",
            "reason": reason[:160],
            "action": _failure_action(reason),
        })
    return sorted(failures, key=lambda x: str(x.get("date", "")), reverse=True)[:limit]


def _auto_corrections(symbol_rows: list[dict[str, Any]], period_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    suggestions = []
    for row in symbol_rows:
        fail = int(row.get("fail", 0) or 0)
        success = int(row.get("success", 0) or 0)
        judged = success + fail
        if judged >= 3 and fail > success:
            suggestions.append({
                "type": "종목별 보정",
                "target": f"{row.get('name')} ({row.get('symbol')})",
                "reason": f"검증 실패 {fail}건 / 성공 {success}건",
                "suggestion": "해당 종목은 기준가를 더 보수적으로 잡고, 신뢰도 점수를 1단계 낮춰 표시",
                "priority": "높음" if fail >= 4 else "중간",
            })
    for row in period_rows[:6]:
        success = int(row.get("success", 0) or 0)
        fail = int(row.get("fail", 0) or 0)
        if success + fail >= 5 and fail > success:
            suggestions.append({
                "type": "기간별 보정",
                "target": row.get("period", "기간 미상"),
                "reason": f"해당 기간 성공 {success}건 / 실패 {fail}건",
                "suggestion": "시장 환경 약세 구간으로 분류하고 신규 진입 신뢰도를 보수적으로 조정",
                "priority": "중간",
            })
    if not suggestions:
        suggestions.append({
            "type": "상태",
            "target": "전체",
            "reason": "강한 자동 보정 후보가 부족함",
            "suggestion": "검증 표본이 더 쌓이면 종목/기간/전략별 보정 규칙을 자동 제안",
            "priority": "낮음",
        })
    return suggestions[:30]


def prediction_insights(market: str) -> dict[str, Any]:
    predictions_df = _read(data.REPO_ROOT / "predictions.csv")
    history_df = _read(data.HISTORY_DIR / "prediction_history.csv")
    outcome_df = _read(data.HISTORY_DIR / "outcome_history.csv")

    prediction_rows = _rows(predictions_df, market)
    history_rows = _rows(history_df, market)
    outcome_rows = _rows(outcome_df, market)
    validation_rows = outcome_rows or history_rows or prediction_rows
    result_counts = _count_by_result(validation_rows)
    symbol_rows = _by_symbol(validation_rows, market)
    period_rows = _by_period(validation_rows)
    failure_rows = _failure_rows(validation_rows, market)
    corrections = _auto_corrections(symbol_rows, period_rows)

    judged = result_counts["success"] + result_counts["fail"]
    coverage = f"{len(validation_rows) / max(1, len(prediction_rows)) * 100:.1f}%" if prediction_rows else "예측 데이터 부족"
    diagnostics = [
        {"항목": "전체 predictions.csv rows", "값": int(len(predictions_df)), "설명": "전체 예측 원장"},
        {"항목": "현재 시장 predictions rows", "값": int(len(prediction_rows)), "설명": "시장 필터 적용 후"},
        {"항목": "prediction_history rows", "값": int(len(history_rows)), "설명": "현재 시장 기준"},
        {"항목": "outcome_history rows", "값": int(len(outcome_rows)), "설명": "현재 시장 기준"},
        {"항목": "검증 사용 rows", "값": int(len(validation_rows)), "설명": "outcome > history > predictions 순서"},
        {"항목": "판정 가능 rows", "값": int(judged), "설명": "success/fail로 분류 가능한 행"},
        {"항목": "검증 커버리지", "값": coverage, "설명": "검증 rows / 예측 rows"},
    ]
    return {
        "market": market,
        "status": "OK" if validation_rows else "NO_DATA",
        "summary": {
            "predictionRows": int(len(prediction_rows)),
            "historyRows": int(len(history_rows)),
            "outcomeRows": int(len(outcome_rows)),
            "validationRows": int(len(validation_rows)),
            "success": int(result_counts["success"]),
            "fail": int(result_counts["fail"]),
            "neutral": int(result_counts["neutral"]),
            "successRate": _pct(result_counts["success"], result_counts["fail"], result_counts["neutral"]),
            "coverage": coverage,
        },
        "diagnostics": diagnostics,
        "bySymbol": symbol_rows,
        "byPeriod": period_rows,
        "failures": failure_rows,
        "corrections": corrections,
        "sources": ["predictions.csv", "data/history/prediction_history.csv", "data/history/outcome_history.csv"],
    }
