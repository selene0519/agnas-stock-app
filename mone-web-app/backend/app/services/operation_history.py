from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from app.services import data_loader as data

VIRTUAL_HISTORY_FILE = data.HISTORY_DIR / "virtual_operation_history.csv"
PREDICTION_SNAPSHOT_FILE = data.HISTORY_DIR / "prediction_snapshot_history.csv"
VIRTUAL_EVALUATION_FILE = data.HISTORY_DIR / "virtual_operation_evaluation.csv"
AUTO_CORRECTION_FILE = data.HISTORY_DIR / "auto_correction_summary.csv"

MARKETS = ("kr", "us")
MODES = ("conservative", "balanced", "aggressive")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ensure_history_dir() -> None:
    data.HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def _rel(path: Path) -> str:
    try:
        return path.relative_to(data.REPO_ROOT).as_posix()
    except Exception:
        return path.as_posix()


def _read_csv(path: Path) -> pd.DataFrame:
    try:
        return data.read_csv(path)
    except Exception:
        return pd.DataFrame()


def _records(path: Path) -> list[dict[str, Any]]:
    df = _read_csv(path)
    return data.dataframe_records(df) if not df.empty else []


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    _ensure_history_dir()
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _append_rows(path: Path, rows: list[dict[str, Any]], key_fields: list[str]) -> dict[str, Any]:
    _ensure_history_dir()
    before = _records(path)
    existing_keys = {_row_key(row, key_fields) for row in before}
    added: list[dict[str, Any]] = []
    for row in rows:
        key = _row_key(row, key_fields)
        if key in existing_keys:
            continue
        existing_keys.add(key)
        added.append(row)
    merged = before + added
    if merged:
        _write_rows(path, merged)
    elif not path.exists():
        _write_rows(path, [])
    return {"file": _rel(path), "beforeRows": len(before), "addedRows": len(added), "afterRows": len(merged)}


def _row_key(row: dict[str, Any], fields: list[str]) -> str:
    return "|".join(str(row.get(field, "")).strip() for field in fields)


def _market_list(market: str | None) -> list[str]:
    if str(market or "").lower() in {"kr", "us"}:
        return [str(market).lower()]
    return list(MARKETS)


def _mode_list(modes: str | list[str] | None) -> list[str]:
    if modes is None or modes == "all":
        return list(MODES)
    if isinstance(modes, str):
        parts = [p.strip().lower() for p in modes.split(",") if p.strip()]
    else:
        parts = [str(p).strip().lower() for p in modes]
    valid = [m for m in parts if m in MODES]
    return valid or ["balanced"]


def _candidate_universe(market: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in ("action", "pullback", "flow", "risk"):
        try:
            for item in data.candidate_rows(market, kind).get("items", []):
                item = dict(item)
                item["candidateType"] = kind
                rows.append(item)
        except Exception:
            continue
    # predictions/history fallback도 후보로 사용. 기존 기록이 있어도 snapshot 값을 채우기 위함.
    for row in data.read_predictions_csv(market)[:500]:
        try:
            normalized = data.normalize_security_row(row, market)
            normalized["candidateType"] = "prediction"
            rows.append(normalized)
        except Exception:
            continue
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in rows:
        symbol = data.normalize_symbol(item.get("symbol") or data.first_value(item, data.SYMBOL_ALIASES), market)
        if not symbol or symbol in seen:
            continue
        item["symbol"] = symbol
        seen.add(symbol)
        unique.append(item)
    return unique


def _snapshot_base(item: dict[str, Any], market: str, source: str, created_at: str) -> dict[str, Any]:
    symbol = data.normalize_symbol(item.get("symbol"), market)
    name = item.get("name") or data.first_value(item.get("raw", {}) if isinstance(item.get("raw"), dict) else item, data.NAME_ALIASES, symbol)
    return {
        "snapshot_at": created_at,
        "source": source,
        "market": market,
        "market_label": "한국주식" if market == "kr" else "미국주식",
        "symbol": symbol,
        "name": name,
        "candidate_type": item.get("candidateType", item.get("category", "")),
        "swing_group": item.get("swingGrade", ""),
        "swing_group_code": item.get("swingGradeCode", ""),
        "recommendation_modes": ",".join(item.get("recommendationModes", []) or []),
        "current_price": item.get("currentPrice", ""),
        "current_price_text": item.get("currentPriceText", ""),
        "price_time": item.get("priceTime", ""),
        "price_source": item.get("priceSource", ""),
        "entry_price": item.get("entry", ""),
        "entry_text": item.get("entryText", ""),
        "stop_loss": item.get("stop", ""),
        "stop_text": item.get("stopText", ""),
        "target_price": item.get("target", ""),
        "target_text": item.get("targetText", ""),
        "expected_open": item.get("expectedOpenText", ""),
        "expected_close": item.get("expectedCloseText", ""),
        "short_probability": item.get("probShort", item.get("prob1d", "")),
        "short_expected_price": item.get("expectedPriceShortText", item.get("expectedPrice1dText", "")),
        "swing_probability": item.get("probSwing", item.get("prob5d", "")),
        "swing_expected_price": item.get("expectedPriceSwingText", item.get("expectedPrice5dText", "")),
        "mid_probability": item.get("probMid", item.get("prob20d", "")),
        "mid_expected_price": item.get("expectedPriceMidText", item.get("expectedPrice20dText", "")),
        "prediction_model_note": item.get("predictionModelNote", ""),
        "data_status": item.get("dataStatus", ""),
    }


def build_prediction_snapshot_rows(market: str, source: str = "current") -> list[dict[str, Any]]:
    created_at = _now()
    rows: list[dict[str, Any]] = []
    for item in _candidate_universe(market):
        base = _snapshot_base(item, market, source, created_at)
        rows.append({
            "prediction_at": created_at,
            **base,
            "snapshot_kind": "current_candidate",
        })
    return rows


def build_virtual_operation_rows(market: str, modes: list[str], source: str = "current") -> list[dict[str, Any]]:
    created_at = _now()
    rows: list[dict[str, Any]] = []
    for item in _candidate_universe(market):
        base = _snapshot_base(item, market, source, created_at)
        plans = item.get("virtualPlans") or {}
        for mode in modes:
            plan = plans.get(mode) or {}
            settings = data.TRADE_MODE_SETTINGS.get(mode, data.TRADE_MODE_SETTINGS["balanced"])
            rows.append({
                "created_at": created_at,
                **base,
                "mode": mode,
                "mode_label": settings.get("label", mode),
                "buy_rule": plan.get("buyRule", settings.get("buy_rule", "")),
                "sell_rule": plan.get("sellRule", "목표가·손절가·보유기간 종료 중 먼저 발생한 조건으로 청산"),
                "hold_days": plan.get("holdDays", settings.get("hold_days", "")),
                "planned_entry": plan.get("entry", ""),
                "planned_entry_text": plan.get("entryText", ""),
                "shares": plan.get("shares", ""),
                "shares_text": plan.get("sharesText", ""),
                "invested_amount": plan.get("invested", ""),
                "invested_text": plan.get("investedText", ""),
                "expected_loss_amount": plan.get("lossTotal", ""),
                "expected_loss_text": plan.get("lossTotalText", ""),
                "expected_profit_amount": plan.get("profitTotal", ""),
                "expected_profit_text": plan.get("profitTotalText", ""),
                "account_loss_pct": plan.get("accountLossPct", ""),
                "account_loss_pct_text": plan.get("accountLossPctText", ""),
                "account_profit_pct": plan.get("accountProfitPct", ""),
                "account_profit_pct_text": plan.get("accountProfitPctText", ""),
                "execution_status": data._execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
                "status": plan.get("status", ""),
                "summary": plan.get("summary", ""),
            })
    return rows


def _historical_source_rows(market: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source_name, source_rows in (
        ("predictions.csv", data.read_predictions_csv(market)),
        ("prediction_history.csv", data.prediction_history(market).get("items", [])),
        ("outcome_history.csv", data.outcome_history(market).get("items", [])),
    ):
        for row in source_rows:
            try:
                if not data._market_matches(row, market):
                    continue
                normalized = data.normalize_security_row(row, market)
                normalized["candidateType"] = source_name
                # 원래 기록의 날짜를 보존한다.
                normalized["history_source_date"] = data.first_value(row, ["created_at", "prediction_at", "target_date", "date", "기준일", "result_date"], "")
                rows.append(normalized)
            except Exception:
                continue
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in rows:
        key = f"{item.get('candidateType','')}|{item.get('symbol','')}|{item.get('history_source_date','')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:1500]


def backfill_existing_records(market: str = "all", modes: str = "all") -> dict[str, Any]:
    mode_list = _mode_list(modes)
    virtual_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    created_at = _now()
    for mk in _market_list(market):
        for item in _historical_source_rows(mk):
            base = _snapshot_base(item, mk, "existing_history_backfill", created_at)
            history_date = item.get("history_source_date", "")
            snapshot_rows.append({
                "prediction_at": history_date or created_at,
                **base,
                "snapshot_kind": "existing_history_backfill",
                "history_source_date": history_date,
            })
            plans = item.get("virtualPlans") or {}
            for mode in mode_list:
                settings = data.TRADE_MODE_SETTINGS.get(mode, data.TRADE_MODE_SETTINGS["balanced"])
                plan = plans.get(mode) or {}
                virtual_rows.append({
                    "created_at": history_date or created_at,
                    **base,
                    "snapshot_kind": "existing_history_backfill",
                    "history_source_date": history_date,
                    "mode": mode,
                    "mode_label": settings.get("label", mode),
                    "buy_rule": plan.get("buyRule", settings.get("buy_rule", "")),
                    "sell_rule": plan.get("sellRule", "목표가·손절가·보유기간 종료 중 먼저 발생한 조건으로 청산"),
                    "hold_days": plan.get("holdDays", settings.get("hold_days", "")),
                    "planned_entry": plan.get("entry", ""),
                    "planned_entry_text": plan.get("entryText", ""),
                    "shares": plan.get("shares", ""),
                    "shares_text": plan.get("sharesText", ""),
                    "invested_amount": plan.get("invested", ""),
                    "invested_text": plan.get("investedText", ""),
                    "expected_loss_amount": plan.get("lossTotal", ""),
                    "expected_loss_text": plan.get("lossTotalText", ""),
                    "expected_profit_amount": plan.get("profitTotal", ""),
                    "expected_profit_text": plan.get("profitTotalText", ""),
                    "account_loss_pct": plan.get("accountLossPct", ""),
                    "account_loss_pct_text": plan.get("accountLossPctText", ""),
                    "account_profit_pct": plan.get("accountProfitPct", ""),
                    "account_profit_pct_text": plan.get("accountProfitPctText", ""),
                    "execution_status": data._execution_status_for_plan(item.get("currentPrice"), item.get("entry"), mode),
                    "status": plan.get("status", ""),
                    "summary": plan.get("summary", ""),
                })
    virtual_result = _append_rows(VIRTUAL_HISTORY_FILE, virtual_rows, ["created_at", "market", "symbol", "mode", "snapshot_kind"])
    snapshot_result = _append_rows(PREDICTION_SNAPSHOT_FILE, snapshot_rows, ["prediction_at", "market", "symbol", "snapshot_kind"])
    evaluation_result = evaluate_virtual_operations(write=True)
    correction_result = build_auto_correction_summary(write=True)
    return {
        "status": "OK",
        "mode": "backfill_existing_records",
        "virtualOperations": virtual_result,
        "predictionSnapshots": snapshot_result,
        "evaluation": evaluation_result,
        "autoCorrection": correction_result,
    }


def save_current_snapshot(market: str = "all", modes: str = "all", source: str = "manual", include_backfill: bool = False) -> dict[str, Any]:
    mode_list = _mode_list(modes)
    virtual_rows: list[dict[str, Any]] = []
    snapshot_rows: list[dict[str, Any]] = []
    for mk in _market_list(market):
        virtual_rows.extend(build_virtual_operation_rows(mk, mode_list, source=source))
        snapshot_rows.extend(build_prediction_snapshot_rows(mk, source=source))
    virtual_result = _append_rows(VIRTUAL_HISTORY_FILE, virtual_rows, ["created_at", "market", "symbol", "mode", "source"])
    snapshot_result = _append_rows(PREDICTION_SNAPSHOT_FILE, snapshot_rows, ["prediction_at", "market", "symbol", "source"])
    backfill_result = None
    if include_backfill:
        backfill_result = backfill_existing_records(market, modes)
    evaluation_result = evaluate_virtual_operations(write=True)
    correction_result = build_auto_correction_summary(write=True)
    return {
        "status": "OK",
        "mode": "save_current_snapshot",
        "market": market,
        "modes": mode_list,
        "virtualOperations": virtual_result,
        "predictionSnapshots": snapshot_result,
        "backfill": backfill_result,
        "evaluation": evaluation_result,
        "autoCorrection": correction_result,
    }


def history_file_summary() -> dict[str, Any]:
    files = [VIRTUAL_HISTORY_FILE, PREDICTION_SNAPSHOT_FILE, VIRTUAL_EVALUATION_FILE, AUTO_CORRECTION_FILE]
    items = []
    for path in files:
        rows = _records(path)
        items.append({
            "path": _rel(path),
            "exists": path.exists(),
            "rows": len(rows),
            "updatedAt": data.file_mtime(path) if path.exists() else "",
            "preview": rows[-5:] if rows else [],
        })
    return {"status": "OK", "items": items}


def virtual_operation_history(market: str | None = None, mode: str | None = None, limit: int = 250) -> dict[str, Any]:
    rows = _records(VIRTUAL_HISTORY_FILE)
    if market in MARKETS:
        rows = [r for r in rows if str(r.get("market", "")).lower() == market]
    if mode in MODES:
        rows = [r for r in rows if str(r.get("mode", "")).lower() == mode]
    rows = sorted(rows, key=lambda r: str(r.get("created_at", "")), reverse=True)
    return {"status": "OK", "source": _rel(VIRTUAL_HISTORY_FILE), "count": len(rows), "items": rows[:limit]}


def prediction_snapshot_history(market: str | None = None, limit: int = 250) -> dict[str, Any]:
    rows = _records(PREDICTION_SNAPSHOT_FILE)
    if market in MARKETS:
        rows = [r for r in rows if str(r.get("market", "")).lower() == market]
    rows = sorted(rows, key=lambda r: str(r.get("prediction_at", "")), reverse=True)
    return {"status": "OK", "source": _rel(PREDICTION_SNAPSHOT_FILE), "count": len(rows), "items": rows[:limit]}


def _outcome_lookup() -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for market in MARKETS:
        for row in data.outcome_history(market).get("items", []):
            sym = data.normalize_symbol(data.first_value(row, data.SYMBOL_ALIASES + ["ticker", "code", "종목코드"], ""), market)
            if not sym:
                continue
            key = f"{market}|{sym}"
            old = lookup.get(key)
            date = data.first_value(row, ["result_date", "date", "created_at", "target_date", "검증일", "결과일"], "")
            if old is None or str(date) >= str(old.get("_date", "")):
                row = dict(row)
                row["_date"] = date
                lookup[key] = row
    return lookup


def _return_from_outcome(row: dict[str, Any]) -> float | None:
    for aliases in (["return_pct", "수익률", "actual_return", "outcome_return", "realized_return", "return"], ["1d_return", "next_return"]):
        value = data.first_number(row, aliases)
        if value is not None:
            return value
    return None


def _result_from_outcome(row: dict[str, Any]) -> str:
    text = data.first_value(row, ["result", "outcome", "판정", "status", "success", "prediction_result"], "")
    low = text.lower()
    if low in {"success", "win", "true", "1", "성공", "적중"}:
        return "성공"
    if low in {"fail", "failure", "loss", "false", "0", "실패", "불일치"}:
        return "실패"
    if low in {"neutral", "hold", "중립"}:
        return "중립"
    return text or "검증 대기"


def evaluate_virtual_operations(write: bool = True) -> dict[str, Any]:
    history = _records(VIRTUAL_HISTORY_FILE)
    outcomes = _outcome_lookup()
    evaluated: list[dict[str, Any]] = []
    matched = 0
    for row in history:
        market = str(row.get("market", "")).lower()
        symbol = data.normalize_symbol(row.get("symbol", ""), market if market in MARKETS else "kr")
        outcome = outcomes.get(f"{market}|{symbol}") if market in MARKETS and symbol else None
        realized_return = _return_from_outcome(outcome) if outcome else None
        if outcome:
            matched += 1
        evaluated.append({
            "evaluated_at": _now(),
            "created_at": row.get("created_at", ""),
            "market": market,
            "symbol": symbol,
            "name": row.get("name", ""),
            "mode": row.get("mode", ""),
            "mode_label": row.get("mode_label", ""),
            "swing_group": row.get("swing_group", ""),
            "entry_price": row.get("planned_entry", row.get("entry_price", "")),
            "stop_loss": row.get("stop_loss", ""),
            "target_price": row.get("target_price", ""),
            "execution_status": row.get("execution_status", ""),
            "expected_profit_pct": row.get("account_profit_pct", ""),
            "expected_loss_pct": row.get("account_loss_pct", ""),
            "outcome_result": _result_from_outcome(outcome) if outcome else "검증 대기",
            "outcome_date": outcome.get("_date", "") if outcome else "",
            "realized_return_pct": realized_return if realized_return is not None else "",
            "realized_return_text": data.format_percent(realized_return) if realized_return is not None else "실제 수익률 대기",
            "evaluation_source": "outcome_history.csv" if outcome else "outcome 미매칭",
        })
    if write:
        _write_rows(VIRTUAL_EVALUATION_FILE, evaluated)
    return {"status": "OK", "file": _rel(VIRTUAL_EVALUATION_FILE), "rows": len(evaluated), "matchedRows": matched}


def build_auto_correction_summary(write: bool = True) -> dict[str, Any]:
    rows = _records(VIRTUAL_EVALUATION_FILE)
    summary: list[dict[str, Any]] = []
    if rows:
        df = pd.DataFrame(rows)
        for group_cols in (["mode"], ["swing_group"], ["mode", "swing_group"]):
            missing_cols = [c for c in group_cols if c not in df.columns]
            if missing_cols:
                continue
            work = df.copy()
            work["realized_return_num"] = pd.to_numeric(work.get("realized_return_pct", ""), errors="coerce")
            work = work.dropna(subset=["realized_return_num"])
            if work.empty:
                continue
            for keys, sub in work.groupby(group_cols, dropna=False):
                if not isinstance(keys, tuple):
                    keys = (keys,)
                item = {"summary_type": "+".join(group_cols), "updated_at": _now()}
                for col, val in zip(group_cols, keys):
                    item[col] = val
                item["trades"] = int(len(sub))
                item["win_rate"] = f"{(sub['realized_return_num'] > 0).mean() * 100:.1f}%"
                item["avg_return"] = f"{sub['realized_return_num'].mean():.2f}%"
                item["median_return"] = f"{sub['realized_return_num'].median():.2f}%"
                item["suggestion"] = _correction_suggestion(float(sub['realized_return_num'].mean()), int(len(sub)))
                summary.append(item)
    if not summary:
        summary.append({
            "summary_type": "status",
            "updated_at": _now(),
            "trades": 0,
            "win_rate": "검증 데이터 부족",
            "avg_return": "검증 데이터 부족",
            "suggestion": "가상 운용 스냅샷과 outcome_history가 쌓이면 자동 보정 요약을 계산합니다.",
        })
    if write:
        _write_rows(AUTO_CORRECTION_FILE, summary)
    return {"status": "OK", "file": _rel(AUTO_CORRECTION_FILE), "rows": len(summary), "items": summary[:50]}


def _correction_suggestion(avg_return: float, trades: int) -> str:
    if trades < 5:
        return "표본 부족 · 추가 기록 필요"
    if avg_return > 1.0:
        return "현재 기준 유지 가능"
    if avg_return < -1.0:
        return "매수 조건 강화 또는 손절/목표가 재조정 필요"
    return "중립 · 모드별 조건 미세조정 필요"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record MONE virtual operation and prediction snapshots.")
    parser.add_argument("--market", default="all", choices=["all", "kr", "us"])
    parser.add_argument("--modes", default="all")
    parser.add_argument("--source", default="manual")
    parser.add_argument("--backfill-existing", action="store_true")
    args = parser.parse_args()
    result = save_current_snapshot(args.market, args.modes, source=args.source, include_backfill=args.backfill_existing)
    print(pd.Series(result).to_json(force_ascii=False, indent=2))
