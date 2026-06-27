"""
PENDING 검증 자동 정산 스크립트.

virtual_prediction_ledger.csv에서 validationDueDate <= 오늘인 PENDING 항목을
날짜별 trade_validation CSV의 실제 체결 결과와 대조해 상태를 업데이트합니다.

출력:
  reports/virtual_prediction_ledger.csv  (상태 갱신)
  reports/virtual_validation_results.csv (결과 갱신)
  reports/pending_settlement_status.json (처리 요약)
"""
from __future__ import annotations

import csv
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT    = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
TODAY   = datetime.now().strftime("%Y-%m-%d")

# generate_kr_close_validation.py와 동일한 비용 가정 (편도 수수료+슬리피지)
COST_PCT = {"kr": 0.09, "us": 0.06}

WIN_RESULTS  = {"target_hit", "TARGET_HIT", "WIN", "목표달성", "성공"}
LOSS_RESULTS = {"stop_hit",   "STOP_HIT",   "LOSS", "손절",    "실패"}
EXEC_RESULTS = WIN_RESULTS | LOSS_RESULTS | {"close_exit"}
# 체결 자체가 안 된 경우 (진입가 미터치) — "데이터 없음(EXPIRED)"과는 다른 결과
NOT_EXECUTED_RESULTS = {"not_executed", "NOT_EXECUTED"}

# horizon별 검증 창 (거래일 기준)
# mid 전략은 D+21까지 열어두어야 중기 전략 검증 가능
HORIZON_VALIDATION_DAYS = {
    "short": 5,
    "swing": 10,
    "mid":   21,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{k: row.get(k, "") for k in fieldnames} for row in rows])


def _num(v: Any) -> float | None:
    try:
        s = str(v or "").replace(",", "").strip()
        return float(s) if s and s not in ("", "-", "nan") else None
    except Exception:
        return None


def _sym_norm(v: str, market: str) -> str:
    if market == "kr":
        digits = re.sub(r"\D", "", str(v or ""))
        return digits.zfill(6)[-6:] if digits else ""
    return str(v or "").strip().upper()


def _is_valid_symbol(v: str, market: str) -> bool:
    sym = _sym_norm(v, market)
    if market == "kr":
        return bool(re.fullmatch(r"\d{6}", sym))
    if sym in {"", "NAN", "NA", "NONE", "NULL"}:
        return False
    return bool(re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", sym))


def _build_validation_index(market: str) -> dict[str, dict[str, Any]]:
    """날짜별 validation 파일을 symbol+mode+horizon 키로 인덱싱.

    체결 결과(EXEC_RESULTS)뿐 아니라 '진입가 미터치(not_executed)' 관측도 보존해,
    아래 _find_result가 '데이터 자체가 없음'과 '데이터는 있는데 체결이 안 됨'을
    구분할 수 있게 한다. 전자만 EXPIRED(DATA_PENDING)여야 한다.
    """
    index: dict[str, dict[str, Any]] = {}
    MODES    = ("conservative", "balanced", "aggressive")
    HORIZONS = ("short", "swing", "mid")
    for m in MODES:
        for h in HORIZONS:
            for path in sorted(REPORTS.glob(f"mone_v36_final_trade_validation_{market}_{m}_{h}_????????.csv")):
                for row in _read_csv(path):
                    sym = _sym_norm(row.get("symbol", ""), market)
                    date = row.get("date", path.stem[-8:])
                    key = f"{sym}|{m}|{h}|{date}"
                    result = str(row.get("result") or row.get("outcome_result") or "").strip()
                    if result in EXEC_RESULTS:
                        index[key] = {
                            "kind": "exec",
                            "result": result,
                            "returnPct": _num(row.get("returnPct") or row.get("realized_return_pct") or row.get("return_pct")),
                            "exitPrice": _num(row.get("exitPrice") or row.get("exit_price")),
                            "validationDate": date,
                        }
                    elif result in NOT_EXECUTED_RESULTS:
                        index[key] = {
                            "kind": "not_executed",
                            "result": "NOT_EXECUTED",
                            "returnPct": None,
                            "exitPrice": None,
                            "validationDate": date,
                        }
    return index


def _date_add_days(date_text: str, days: int) -> str:
    from datetime import timedelta
    try:
        base = datetime.fromisoformat(str(date_text)[:10])
    except Exception:
        base = datetime.now()
    return (base + timedelta(days=days)).date().isoformat()


def _window_cutoff(horizon: str, due_date: str) -> str:
    """horizon별 검증 창을 넉넉히 부여해 mid 전략(D+21)까지 커버한다 (달력일, 주말 포함)."""
    extra_days = HORIZON_VALIDATION_DAYS.get(str(horizon or "swing").lower(), 10) + 7
    return _date_add_days(due_date[:10], extra_days)


def _find_result(sym: str, mode: str, horizon: str, due_date: str,
                 market: str, index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """due_date 이후 가장 빠른 체결 결과를 찾는다."""
    cutoff = _window_cutoff(horizon, due_date)
    best_exec: tuple[str, dict[str, Any]] | None = None
    best_not_executed: tuple[str, dict[str, Any]] | None = None
    for key, val in index.items():
        k_sym, k_mode, k_horizon, k_date = key.split("|")
        if k_sym != _sym_norm(sym, market):
            continue
        if k_mode != mode or k_horizon != horizon:
            continue
        if k_date > cutoff:   # 검증 창 초과면 무시
            continue
        if val.get("kind") == "not_executed":
            if best_not_executed is None or k_date > best_not_executed[0]:
                best_not_executed = (k_date, val)
            continue
        if best_exec is None or k_date > best_exec[0]:
            best_exec = (k_date, val)
    # 체결 결과가 있으면 그게 최종. 없으면 '진입가 미터치' 관측이라도 있는지 본다.
    if best_exec:
        return best_exec[1]
    if best_not_executed:
        return best_not_executed[1]
    return None


def _settle_from_ohlcv(market: str, symbol: str, entry: float | None, stop: float | None,
                        target: float | None, created: str, cutoff: str) -> dict[str, Any] | None:
    """검증 스냅샷이 그 심볼에 대해 한 번도 만들어진 적 없을 때 쓰는 최후 수단.

    추천 리스트에서 빠지면(rec_files()가 그 심볼을 더 이상 안 줌) 스냅샷 자체가 끊겨서
    _find_result가 영원히 None을 반환하는 경우가 있었다(예: KR 009150/010950). 그런데
    OHLCV 원본은 따로 보존돼 있으므로, generate_kr_close_validation.py의 validate_one()과
    동일한 규칙(동시 도달 시 손절 우선)으로 매일 단위 재구성하면 스냅샷 없이도 정산할 수 있다.
    """
    if entry is None or not _is_valid_symbol(symbol, market):
        return None
    path = OHLCV_DIR / f"{market}_{_sym_norm(symbol, market)}_daily.csv"
    rows = _read_csv(path)
    if not rows:
        return None
    cost = COST_PCT.get(market, COST_PCT["kr"])
    best_exec: tuple[str, dict[str, Any]] | None = None
    best_not_executed: tuple[str, dict[str, Any]] | None = None
    for row in rows:
        date = str(row.get("date") or row.get("Date") or "")[:10]
        if not date or date < created[:10] or date > cutoff:
            continue
        low   = _num(row.get("low") or row.get("Low"))
        high  = _num(row.get("high") or row.get("High"))
        close = _num(row.get("close") or row.get("Close"))
        if low is None or high is None or close is None:
            continue
        executed = low <= entry <= high
        if not executed:
            if best_not_executed is None or date > best_not_executed[0]:
                best_not_executed = (date, {
                    "kind": "not_executed", "result": "NOT_EXECUTED",
                    "returnPct": None, "exitPrice": None,
                })
            continue
        target_hit = bool(target and high >= target)
        stop_hit = bool(stop and low <= stop)
        if target_hit and stop_hit:
            target_hit = False  # 동시 도달 시 손절 먼저 났다고 가정 (보수적)
        if target_hit:
            result, exit_price = "target_hit", target
        elif stop_hit:
            result, exit_price = "stop_hit", stop
        else:
            result, exit_price = "close_exit", close
        ret = round(((exit_price - entry) / entry * 100) - cost, 4)
        if best_exec is None or date > best_exec[0]:
            best_exec = (date, {"kind": "exec", "result": result, "returnPct": ret, "exitPrice": exit_price})
    if best_exec:
        return best_exec[1]
    if best_not_executed:
        return best_not_executed[1]
    return None


def main() -> None:
    ledger_path = REPORTS / "virtual_prediction_ledger.csv"
    results_path = REPORTS / "virtual_validation_results.csv"

    ledger_rows  = _read_csv(ledger_path)
    results_rows = _read_csv(results_path)

    if not ledger_rows:
        print("virtual_prediction_ledger.csv 없음 — 건너뜀")
        return

    # 결과 맵 (predictionId → row)
    results_map: dict[str, dict[str, str]] = {r.get("predictionId", ""): r for r in results_rows}

    settled = unsettled = skipped = 0
    val_index_kr = _build_validation_index("kr")
    val_index_us = _build_validation_index("us")

    updated_ledger: list[dict] = []
    updated_results: list[dict] = []

    for row in ledger_rows:
        pred_id  = row.get("predictionId", "")
        status   = str(row.get("status") or "PENDING").strip()
        due_date = str(row.get("validationDueDate") or "").strip()
        market   = str(row.get("market") or "kr").lower()
        mode     = str(row.get("mode") or "balanced").lower()
        horizon  = str(row.get("horizon") or "swing").lower()
        symbol   = str(row.get("symbol") or "").strip()

        if not _is_valid_symbol(symbol, market) and pred_id.count("|") >= 4:
            row = dict(row)
            row["status"] = "INVALID_SYMBOL"
            row["result"] = "INVALID_SYMBOL"
            row["exitStatus"] = "INVALID_SYMBOL"
            row["validatedAt"] = TODAY
            updated_ledger.append(row)

            existing = results_map.get(pred_id, dict(row))
            existing = dict(existing)
            existing.update({
                "status": "INVALID_SYMBOL",
                "result": "INVALID_SYMBOL",
                "exitStatus": "INVALID_SYMBOL",
                "dataStatus": "INVALID_SYMBOL",
                "reason": "invalid symbol",
                "validatedAt": TODAY,
            })
            updated_results.append(existing)
            settled += 1
            continue

        # 이미 처리된 항목. 단, 예전 DATA_PENDING은 OHLCV가 나중에 채워질 수 있으므로 재평가한다.
        is_recheckable_data_gap = (
            status == "EXPIRED"
            and str(row.get("result") or "").strip().upper() == "DATA_PENDING"
        )
        if status != "PENDING" and not is_recheckable_data_gap:
            updated_ledger.append(row)
            if pred_id in results_map:
                existing = dict(results_map[pred_id])
                result_key = str(row.get("result") or existing.get("result") or "").strip().upper()
                stale_data_pending = str(existing.get("dataStatus") or "").strip().upper() == "DATA_PENDING"
                if stale_data_pending and result_key in {"TARGET_HIT", "STOP_HIT", "CLOSE_EXIT", "WIN", "LOSS", "CLOSED"}:
                    existing["dataStatus"] = "NORMAL"
                    existing["reason"] = "settled from available OHLCV"
                elif stale_data_pending and result_key == "NOT_EXECUTED":
                    existing["dataStatus"] = "NORMAL"
                    existing["reason"] = "entry not touched during validation window"
                updated_results.append(existing)
            skipped += 1
            continue

        # 기간 미도래
        if due_date and due_date > TODAY:
            updated_ledger.append(row)
            if pred_id in results_map:
                updated_results.append(results_map[pred_id])
            unsettled += 1
            continue

        # 검증 인덱스에서 결과 탐색
        val_index = val_index_kr if market == "kr" else val_index_us
        found = _find_result(symbol, mode, horizon, due_date or TODAY, market, val_index)

        # 스냅샷에 그 심볼이 한 번도 안 잡혔으면(추천 리스트 이탈 등) OHLCV로 직접 재구성
        if found is None:
            cutoff = _window_cutoff(horizon, due_date or TODAY)
            found = _settle_from_ohlcv(
                market, symbol,
                _num(row.get("entryPrice")), _num(row.get("stopPrice")), _num(row.get("targetPrice")),
                row.get("createdAt") or due_date or TODAY, cutoff,
            )

        if found and found.get("kind") == "not_executed":
            # 데이터가 없는 게 아니라 진입가가 한 번도 안 닿아서 거래 자체가 안 일어난 경우.
            # EXPIRED/DATA_PENDING(=데이터 없음)으로 묶으면 원인을 잘못 알려주므로 분리.
            row = dict(row)
            row["status"]      = "NOT_EXECUTED"
            row["returnPct"]   = ""
            row["result"]      = "NOT_EXECUTED"
            row["exitStatus"]  = "NOT_EXECUTED"
            row["exitPrice"]   = ""
            row["validatedAt"] = TODAY
            settled += 1
        elif found:
            result_str = str(found["result"]).strip()
            new_status = (
                "WIN"  if result_str in WIN_RESULTS else
                "LOSS" if result_str in LOSS_RESULTS else
                "CLOSED"
            )
            ret = found.get("returnPct")

            row = dict(row)
            row["status"]      = new_status
            row["returnPct"]   = str(round(ret, 4)) if ret is not None else ""
            row["result"]      = result_str
            row["exitStatus"]  = new_status
            row["exitPrice"]   = str(found.get("exitPrice") or "")
            row["validatedAt"] = TODAY
            settled += 1
        else:
            # 기간 경과했지만 데이터 없음 → EXPIRED
            row = dict(row)
            row["status"]     = "EXPIRED"
            row["result"]     = "DATA_PENDING"
            row["validatedAt"] = TODAY
            settled += 1

        updated_ledger.append(row)

        # results 업데이트
        existing = results_map.get(pred_id, dict(row))
        existing = dict(existing)
        for k in ("status", "returnPct", "result", "exitStatus", "exitPrice", "validatedAt"):
            if row.get(k):
                existing[k] = row[k]
        result_key = str(row.get("result") or "").strip().upper()
        if result_key in {"TARGET_HIT", "STOP_HIT", "CLOSE_EXIT", "WIN", "LOSS", "CLOSED"}:
            existing["dataStatus"] = "NORMAL"
            existing["reason"] = "settled from available OHLCV"
        elif result_key == "NOT_EXECUTED":
            existing["dataStatus"] = "NORMAL"
            existing["reason"] = "entry not touched during validation window"
        elif result_key == "DATA_PENDING":
            existing["dataStatus"] = "DATA_PENDING"
            existing["reason"] = "검증 기간 OHLCV 없음"
        updated_results.append(existing)

    # 저장
    if ledger_rows:
        ledger_fields = list(dict.fromkeys(
            list(ledger_rows[0].keys()) + ["status", "returnPct", "result", "exitStatus", "exitPrice", "validatedAt"]
        ))
        _write_csv(ledger_path, updated_ledger, ledger_fields)

    if updated_results:
        result_fields = list(dict.fromkeys(
            (list(results_rows[0].keys()) if results_rows else []) +
            list(updated_results[0].keys())
        ))
        _write_csv(results_path, updated_results, result_fields)

    summary = {
        "runAt": datetime.now().isoformat(timespec="seconds"),
        "settled": settled,
        "unsettled": unsettled,
        "skipped": skipped,
        "total": len(ledger_rows),
    }
    (REPORTS / "pending_settlement_status.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
