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
TODAY   = datetime.now().strftime("%Y-%m-%d")

WIN_RESULTS  = {"target_hit", "TARGET_HIT", "WIN", "목표달성", "성공"}
LOSS_RESULTS = {"stop_hit",   "STOP_HIT",   "LOSS", "손절",    "실패"}
EXEC_RESULTS = WIN_RESULTS | LOSS_RESULTS | {"close_exit"}


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


def _build_validation_index(market: str) -> dict[str, dict[str, Any]]:
    """날짜별 validation 파일을 symbol+mode+horizon 키로 인덱싱."""
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
                            "result": result,
                            "returnPct": _num(row.get("returnPct") or row.get("realized_return_pct") or row.get("return_pct")),
                            "exitPrice": _num(row.get("exitPrice") or row.get("exit_price")),
                            "validationDate": date,
                        }
    return index


def _find_result(sym: str, mode: str, horizon: str, due_date: str,
                 market: str, index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """due_date 이후 가장 빠른 체결 결과를 찾는다."""
    # 검증 기간: 생성일 ~ due_date + 5일 허용
    best = None
    for key, val in index.items():
        k_sym, k_mode, k_horizon, k_date = key.split("|")
        if k_sym != _sym_norm(sym, market):
            continue
        if k_mode != mode or k_horizon != horizon:
            continue
        if k_date > due_date[:10]:   # due_date 이후면 무시
            continue
        if best is None or k_date > best[0]:
            best = (k_date, val)
    return best[1] if best else None


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

        # 이미 처리된 항목
        if status != "PENDING":
            updated_ledger.append(row)
            if pred_id in results_map:
                updated_results.append(results_map[pred_id])
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

        if found:
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
