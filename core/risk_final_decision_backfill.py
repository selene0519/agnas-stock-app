from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


DECISION_WAIT = "관망 우위"
DECISION_DATA_LACK = "데이터 부족"
DECISION_STOP_FIRST = "손절 우선"
DECISION_REDUCE_FIRST = "비중 축소 우선"
DECISION_HOLD_OK = "보유 가능"
DECISION_BUY_OK = "매수 가능"

METADATA_COLUMNS = [
    "risk_final_decision",
    "risk_final_decision_source",
    "risk_final_decision_reason",
    "risk_final_decision_filled",
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


def _compact(value: Any) -> str:
    return _safe_str(value).replace(" ", "").replace("_", "").replace("-", "").lower()


def _is_missing(value: Any) -> bool:
    return _safe_str(value) == ""


def _is_false(value: Any) -> bool:
    text = _compact(value)
    return text in {"false", "0", "00", "no", "n", "off", "거짓", "불가", "금지", "미통과"}


def _is_true(value: Any) -> bool:
    text = _compact(value)
    return text in {"true", "1", "10", "yes", "y", "on", "ok", "가능", "통과"}


def normalize_risk_final_decision(value: Any) -> str:
    text = _safe_str(value)
    compact = _compact(text)
    if not compact:
        return ""
    if text in {
        DECISION_WAIT,
        DECISION_DATA_LACK,
        DECISION_STOP_FIRST,
        DECISION_REDUCE_FIRST,
        DECISION_HOLD_OK,
        DECISION_BUY_OK,
        "눌림목 매수 가능",
        "돌파 확인 후 접근",
    }:
        return text
    if any(token in compact for token in ["데이터부족", "notenoughdata", "insufficientdata"]):
        return DECISION_DATA_LACK
    if any(token in compact for token in ["손절", "stoploss", "stop"]):
        return DECISION_STOP_FIRST
    if any(token in compact for token in ["비중축소", "축소", "reduce", "trim"]):
        return DECISION_REDUCE_FIRST
    if any(token in compact for token in ["금지", "제외", "관망", "관찰", "watch", "cexcluded", "c/excluded"]):
        return DECISION_WAIT
    if any(token in compact for token in ["보유", "hold"]):
        return DECISION_HOLD_OK
    if any(token in compact for token in ["매수가능", "눌림목매수가능", "돌파확인후접근", "buy", "entry"]):
        return DECISION_BUY_OK
    if compact in {"a"}:
        return DECISION_BUY_OK
    if compact in {"b"}:
        return DECISION_WAIT
    if compact in {"c"}:
        return DECISION_WAIT
    return ""


def _has_data_lack(row: dict[str, Any]) -> bool:
    prediction_result = _compact(row.get("prediction_result"))
    failure_reason = _safe_str(row.get("failure_reason"))
    return prediction_result == "notenoughdata" or "실제 OHLC 데이터 부족" in failure_reason or "ohlc 데이터 부족" in failure_reason.lower()


def _has_conservative_block(row: dict[str, Any]) -> bool:
    if _is_false(row.get("strategy_trade_allowed")) or _is_false(row.get("trade_allowed")):
        return True
    market_risk = _safe_str(row.get("market_risk_level"))
    if "위험" in market_risk:
        return True
    if _safe_str(row.get("strategy_mode")) == "위험장":
        return True
    if _is_false(row.get("rr_pass")):
        return True
    if _safe_str(row.get("hard_block_reason")):
        return True
    return _has_data_lack(row)


def _conservative_result(row: dict[str, Any]) -> dict[str, Any]:
    decision = DECISION_DATA_LACK if _has_data_lack(row) else DECISION_WAIT
    return {
        "risk_final_decision": decision,
        "risk_final_decision_source": "fallback_conservative",
        "risk_final_decision_reason": "데이터 부족 또는 위험 조건으로 보수 판단",
        "risk_final_decision_filled": True,
    }


def _candidate_from_strategy(value: Any) -> str:
    compact = _compact(value)
    if not compact:
        return ""
    if any(token in compact for token in ["금지", "신규매수금지", "cexcluded", "c/excluded"]) or compact == "c":
        return DECISION_WAIT
    if any(token in compact for token in ["손절", "stop"]):
        return DECISION_STOP_FIRST
    if any(token in compact for token in ["비중축소", "축소", "reduce"]):
        return DECISION_REDUCE_FIRST
    if compact in {"b", "watch", "관찰"} or any(token in compact for token in ["관망", "관찰", "watch"]):
        return DECISION_WAIT
    if compact in {"a", "매수가능", "buy"} or any(token in compact for token in ["매수", "buy", "entry"]):
        return DECISION_BUY_OK
    return normalize_risk_final_decision(value)


def _candidate_from_forecast(value: Any) -> str:
    text = _safe_str(value)
    if not text:
        return ""
    if any(
        token in text
        for token in [
            "강한 관찰 후보",
            "완전 제외 후보",
            "추격매수 금지 후보",
            "시장 약세 속 역행 후보",
        ]
    ):
        return DECISION_WAIT
    return normalize_risk_final_decision(text)


def _candidate_from_prediction_result(value: Any) -> str:
    compact = _compact(value)
    if compact == "notenoughdata":
        return DECISION_DATA_LACK
    if compact == "neutral":
        return DECISION_WAIT
    if compact == "fail":
        return DECISION_REDUCE_FIRST
    if compact == "success":
        return DECISION_HOLD_OK
    return ""


def _safe_buy_decision(row: dict[str, Any], candidate: str) -> str:
    if candidate != DECISION_BUY_OK:
        return candidate
    if _has_conservative_block(row):
        return DECISION_WAIT
    rr_present = not _is_missing(row.get("rr_pass"))
    trade_present = not _is_missing(row.get("strategy_trade_allowed")) or not _is_missing(row.get("trade_allowed"))
    if rr_present and trade_present and (
        _is_true(row.get("rr_pass"))
        and not _is_false(row.get("strategy_trade_allowed"))
        and not _is_false(row.get("trade_allowed"))
    ):
        return DECISION_BUY_OK
    return DECISION_WAIT


def infer_risk_final_decision(row: dict[str, Any]) -> dict[str, Any]:
    existing_raw = _safe_str(row.get("risk_final_decision"))
    existing = normalize_risk_final_decision(existing_raw)
    already_filled = _is_true(row.get("risk_final_decision_filled"))
    if existing_raw and not already_filled:
        return {
            "risk_final_decision": existing or existing_raw,
            "risk_final_decision_source": _safe_str(row.get("risk_final_decision_source")) or "original",
            "risk_final_decision_reason": _safe_str(row.get("risk_final_decision_reason")) or "기존 risk_final_decision 유지",
            "risk_final_decision_filled": False,
        }

    if _has_conservative_block(row):
        return _conservative_result(row)

    final_decision_keys = [
        "final_decision",
        "final_decision_after_disclosure",
        "final_decision_after_no_buy_filter",
        "final_decision_after_market_filter",
        "final_decision_after_adjustment",
        "final_judgment",
        "suggested_action",
    ]
    for key in final_decision_keys:
        candidate = normalize_risk_final_decision(row.get(key))
        if candidate:
            candidate = _safe_buy_decision(row, candidate)
            return {
                "risk_final_decision": candidate,
                "risk_final_decision_source": "final_decision",
                "risk_final_decision_reason": f"{key} 기반 보수 보정",
                "risk_final_decision_filled": True,
            }

    for key in ["risk_adjusted_decision", "strategy_adjusted_grade", "grade"]:
        candidate = _candidate_from_strategy(row.get(key))
        if candidate:
            candidate = _safe_buy_decision(row, candidate)
            source = "strategy_grade"
            return {
                "risk_final_decision": candidate,
                "risk_final_decision_source": source,
                "risk_final_decision_reason": f"{key} 기반 보수 보정",
                "risk_final_decision_filled": True,
            }

    candidate = _candidate_from_forecast(row.get("forecast_label"))
    if candidate:
        return {
            "risk_final_decision": _safe_buy_decision(row, candidate),
            "risk_final_decision_source": "forecast_label",
            "risk_final_decision_reason": "forecast_label 기반 보수 보정",
            "risk_final_decision_filled": True,
        }

    candidate = _candidate_from_prediction_result(row.get("prediction_result"))
    if candidate:
        return {
            "risk_final_decision": candidate,
            "risk_final_decision_source": "prediction_result",
            "risk_final_decision_reason": "prediction_result 기반 보수 보정",
            "risk_final_decision_filled": True,
        }

    return _conservative_result(row)


def backfill_risk_final_decision(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy() if df is not None else pd.DataFrame()
    for col in METADATA_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    if out.empty:
        return out

    original_prediction_result = out["prediction_result"].copy() if "prediction_result" in out.columns else None
    rows = out.to_dict(orient="records")
    inferred = [infer_risk_final_decision(row) for row in rows]
    for idx, result in zip(out.index, inferred):
        out.loc[idx, "risk_final_decision"] = result["risk_final_decision"]
        out.loc[idx, "risk_final_decision_source"] = result["risk_final_decision_source"]
        out.loc[idx, "risk_final_decision_reason"] = result["risk_final_decision_reason"]
        out.loc[idx, "risk_final_decision_filled"] = bool(result["risk_final_decision_filled"])

    if original_prediction_result is not None:
        out["prediction_result"] = original_prediction_result
    return out


def _missing_count(series: pd.Series) -> int:
    text = series.astype(str).str.strip().str.lower()
    return int((series.isna() | text.isin({"", "nan", "none", "null", "nat"})).sum())


def backfill_predictions_file(path: str | Path = "predictions.csv") -> dict[str, Any]:
    target = Path(path)
    if not target.exists() or target.stat().st_size <= 0:
        return {"ok": False, "path": str(target), "error": "predictions.csv missing or empty"}

    df = pd.read_csv(target, dtype=str, low_memory=False).fillna("")
    before_missing = _missing_count(df["risk_final_decision"]) if "risk_final_decision" in df.columns else len(df)
    out = backfill_risk_final_decision(df)
    after_missing = _missing_count(out["risk_final_decision"]) if "risk_final_decision" in out.columns else len(out)

    backup_dir = target.parent / "backups" if target.parent != Path(".") else Path("backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"{target.stem}_before_risk_final_decision_backfill_{stamp}{target.suffix}"
    shutil.copy2(target, backup_path)

    out.to_csv(target, index=False, encoding="utf-8-sig")
    source_counts = out["risk_final_decision_source"].astype(str).str.strip().replace("", "unknown").value_counts().to_dict()
    filled_count = int(out["risk_final_decision_filled"].astype(str).str.lower().isin({"true", "1", "1.0"}).sum())
    return {
        "ok": True,
        "path": str(target),
        "backup_path": str(backup_path),
        "rows": int(len(out)),
        "before_missing_count": int(before_missing),
        "after_missing_count": int(after_missing),
        "before_missing_rate": round(float(before_missing / len(out)), 4) if len(out) else 1.0,
        "after_missing_rate": round(float(after_missing / len(out)), 4) if len(out) else 1.0,
        "risk_final_decision_filled_count": filled_count,
        "risk_final_decision_source_counts": source_counts,
    }


def main() -> int:
    result = backfill_predictions_file("predictions.csv")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
