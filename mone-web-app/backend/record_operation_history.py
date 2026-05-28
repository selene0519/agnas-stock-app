from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

MARKETS = ("kr", "us")
MODES = ("conservative", "balanced", "aggressive")
MODE_LABELS = {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}
MODE_SETTINGS = {
    "conservative": {"hold_days": 1, "buy_rule": "기준가 이하 또는 기준가 근처에서만 체결", "budget_kr": 1_000_000, "budget_us": 1_000.0},
    "balanced": {"hold_days": 5, "buy_rule": "기준가 ±1% 이내면 체결", "budget_kr": 1_000_000, "budget_us": 1_000.0},
    "aggressive": {"hold_days": 20, "buy_rule": "현재가 또는 예상 시초가 기준 체결", "budget_kr": 1_000_000, "budget_us": 1_000.0},
}

SYMBOL_ALIASES = ["symbol", "ticker", "code", "종목코드", "코드", "SYMBOL", "Ticker", "Code"]
NAME_ALIASES = ["name", "종목", "종목명", "company", "company_name", "NAME", "Name"]
MARKET_ALIASES = ["market", "시장", "MARKET"]
CURRENT_ALIASES = ["current_price", "currentPrice", "현재가", "price", "last", "close", "PRICE"]
ENTRY_ALIASES = ["entry_price", "entry", "base_price", "basePrice", "기준가", "매수가", "buy_price"]
STOP_ALIASES = ["stop_loss", "stop", "stopLoss", "손절가", "손절", "risk_price"]
TARGET_ALIASES = ["target_price", "target", "targetPrice", "목표가", "목표", "take_profit"]
SWING_ALIASES = ["swing_group", "swingGrade", "swing_group_code", "스윙군", "등급", "grade"]
PROB_SHORT_ALIASES = ["short_probability", "probShort", "prob1d", "probability_1d", "단기확률", "1d_probability"]
PROB_SWING_ALIASES = ["swing_probability", "probSwing", "prob5d", "probability_5d", "스윙확률", "5d_probability"]
PROB_MID_ALIASES = ["mid_probability", "probMid", "prob20d", "probability_20d", "중기확률", "20d_probability"]
EXP_SHORT_ALIASES = ["short_expected_price", "expectedPriceShort", "expectedPrice1d", "예상가_단기", "1d_expected_price"]
EXP_SWING_ALIASES = ["swing_expected_price", "expectedPriceSwing", "expectedPrice5d", "예상가_스윙", "5d_expected_price"]
EXP_MID_ALIASES = ["mid_expected_price", "expectedPriceMid", "expectedPrice20d", "예상가_중기", "20d_expected_price"]
EXPECTED_OPEN_ALIASES = ["expected_open", "expectedOpen", "예상시초가", "expected_open_price"]
EXPECTED_CLOSE_ALIASES = ["expected_close", "expectedClose", "예상종가", "expected_close_price"]
RESULT_ALIASES = ["result", "outcome", "판정", "status", "success", "prediction_result"]
RETURN_ALIASES = ["return_pct", "수익률", "actual_return", "outcome_return", "realized_return", "return", "1d_return", "next_return"]
DATE_ALIASES = ["created_at", "prediction_at", "target_date", "date", "기준일", "result_date", "검증일", "결과일"]


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent, *p.parents]:
        if (parent / ".git").exists() or (parent / "reports").exists() or (parent / "data").exists():
            if parent.name == "backend" and parent.parent.name == "mone-web-app":
                return parent.parent.parent
            if parent.name == "mone-web-app":
                return parent.parent
            return parent
    return p.parents[2]


REPO_ROOT = find_repo_root()
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
HISTORY_DIR = DATA_DIR / "history"
VIRTUAL_HISTORY_FILE = HISTORY_DIR / "virtual_operation_history.csv"
PREDICTION_SNAPSHOT_FILE = HISTORY_DIR / "prediction_snapshot_history.csv"
VIRTUAL_EVALUATION_FILE = HISTORY_DIR / "virtual_operation_evaluation.csv"
AUTO_CORRECTION_FILE = HISTORY_DIR / "auto_correction_summary.csv"


def rel(path: Path) -> str:
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except Exception:
        return path.as_posix()


def read_csv_rows(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    encodings = ["utf-8-sig", "utf-8", "cp949", "euc-kr"]
    for enc in encodings:
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.DictReader(f)
                rows = []
                for i, row in enumerate(reader):
                    if limit is not None and i >= limit:
                        break
                    rows.append({str(k).strip(): ("" if v is None else str(v).strip()) for k, v in row.items() if k is not None})
                return rows
        except UnicodeDecodeError:
            continue
        except Exception:
            return []
    return []


def write_csv_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def first_value(row: dict[str, Any], aliases: Iterable[str], default: str = "") -> str:
    # exact first
    for key in aliases:
        if key in row and str(row.get(key, "")).strip() not in {"", "nan", "None", "null"}:
            return str(row.get(key, "")).strip()
    lower = {str(k).lower(): k for k in row.keys()}
    for key in aliases:
        lk = key.lower()
        if lk in lower:
            val = row.get(lower[lk], "")
            if str(val).strip() not in {"", "nan", "None", "null"}:
                return str(val).strip()
    return default


def first_number(row: dict[str, Any], aliases: Iterable[str]) -> float | None:
    val = first_value(row, aliases, "")
    return to_number(val)


def to_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    text = text.replace(",", "")
    text = text.replace("원", "").replace("$", "").replace("%", "")
    text = re.sub(r"[^0-9.\-]", "", text)
    if text in {"", ".", "-", "-."}:
        return None
    try:
        return float(text)
    except Exception:
        return None


def normalize_symbol(value: Any, market: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.split("(")[-1].split(")")[0] if "(" in raw and ")" in raw else raw
    raw = raw.replace(".KS", "").replace(".KQ", "").replace(".KOSPI", "").strip()
    raw = re.sub(r"[^A-Za-z0-9.-]", "", raw)
    if market == "kr" and raw.isdigit():
        return raw.zfill(6)[-6:]
    return raw.upper()


def infer_market(row: dict[str, Any], path: Path | None = None, requested: str | None = None) -> str:
    if requested in MARKETS:
        return requested
    m = first_value(row, MARKET_ALIASES, "").lower()
    if m in {"kr", "kospi", "kosdaq", "국장", "한국"}:
        return "kr"
    if m in {"us", "usa", "nasdaq", "nyse", "미장", "미국"}:
        return "us"
    p = path.as_posix().lower() if path else ""
    if "_us" in p or "/us" in p or "nasdaq" in p:
        return "us"
    return "kr"


def candidate_files() -> list[Path]:
    patterns = [
        "predictions.csv",
        "data/history/prediction_history.csv",
        "data/history/outcome_history.csv",
        "reports/*action*cards*.csv",
        "reports/*pullback*cards*.csv",
        "reports/*risk*cards*.csv",
        "reports/*confidence*cards*.csv",
        "reports/*symbol_snapshot*.csv",
        "reports/*today_summary*.csv",
        "reports/*position_cards*.csv",
        "reports/*candidate*.csv",
        "reports/*scanner*.csv",
    ]
    files: list[Path] = []
    seen: set[Path] = set()
    for pat in patterns:
        for path in REPO_ROOT.glob(pat):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def collect_candidates(market: str, limit_per_file: int = 1000) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for path in candidate_files():
        for row in read_csv_rows(path, limit=limit_per_file):
            mk = infer_market(row, path, None)
            if market in MARKETS and mk != market:
                continue
            sym = normalize_symbol(first_value(row, SYMBOL_ALIASES, ""), market)
            if not sym:
                continue
            item = dict(row)
            item["market"] = market
            item["symbol"] = sym
            item["name"] = first_value(row, NAME_ALIASES, sym)
            item["_source_file"] = rel(path)
            collected.append(item)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for item in collected:
        key = f"{item.get('market')}|{item.get('symbol')}|{item.get('_source_file')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique[:2500]


def mode_list(modes: str) -> list[str]:
    if not modes or modes == "all":
        return list(MODES)
    parts = [p.strip().lower() for p in modes.split(",") if p.strip()]
    valid = [p for p in parts if p in MODES]
    return valid or ["balanced"]


def market_list(market: str) -> list[str]:
    return [market] if market in MARKETS else list(MARKETS)


def format_money(value: float | None, market: str) -> str:
    if value is None:
        return ""
    if market == "us":
        return f"${value:,.2f}"
    return f"{round(value):,}원"


def pct(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den * 100.0


def execution_status(current: float | None, entry: float | None, mode: str) -> str:
    if current is None or entry is None or entry == 0:
        return "체결 판단 불가"
    dist = (current - entry) / entry * 100.0
    if mode == "conservative":
        if current <= entry * 1.005:
            return "체결 가능"
        return "대기"
    if mode == "balanced":
        if abs(dist) <= 1.0:
            return "체결 가능"
        if dist < -1.0:
            return "기준가 아래"
        return "대기"
    if current <= entry * 1.03:
        return "공격 검토"
    return "추격 부담"


def snapshot_base(item: dict[str, Any], market: str, source: str, stamp: str) -> dict[str, Any]:
    current = first_number(item, CURRENT_ALIASES)
    entry = first_number(item, ENTRY_ALIASES) or current
    stop = first_number(item, STOP_ALIASES)
    target = first_number(item, TARGET_ALIASES)
    return {
        "snapshot_at": stamp,
        "source": source,
        "market": market,
        "symbol": normalize_symbol(first_value(item, SYMBOL_ALIASES, item.get("symbol", "")), market),
        "name": first_value(item, NAME_ALIASES, item.get("name", "")),
        "source_file": item.get("_source_file", ""),
        "swing_group": first_value(item, SWING_ALIASES, ""),
        "current_price": current if current is not None else "",
        "current_price_text": format_money(current, market),
        "entry_price": entry if entry is not None else "",
        "entry_text": format_money(entry, market),
        "stop_loss": stop if stop is not None else "",
        "stop_text": format_money(stop, market),
        "target_price": target if target is not None else "",
        "target_text": format_money(target, market),
        "expected_open": first_value(item, EXPECTED_OPEN_ALIASES, ""),
        "expected_close": first_value(item, EXPECTED_CLOSE_ALIASES, ""),
        "short_probability": first_value(item, PROB_SHORT_ALIASES, ""),
        "short_expected_price": first_value(item, EXP_SHORT_ALIASES, ""),
        "swing_probability": first_value(item, PROB_SWING_ALIASES, ""),
        "swing_expected_price": first_value(item, EXP_SWING_ALIASES, ""),
        "mid_probability": first_value(item, PROB_MID_ALIASES, ""),
        "mid_expected_price": first_value(item, EXP_MID_ALIASES, ""),
        "data_status": "standalone_recorder",
    }


def build_rows(market: str, modes: list[str], source: str, include_backfill: bool) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    stamp = now()
    virtual: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = []
    candidates = collect_candidates(market)
    for item in candidates:
        base = snapshot_base(item, market, source, stamp)
        if not base.get("symbol"):
            continue
        snapshots.append({"prediction_at": stamp, **base, "snapshot_kind": "current_candidate"})
        current = to_number(base.get("current_price"))
        entry = to_number(base.get("entry_price")) or current
        stop = to_number(base.get("stop_loss"))
        target = to_number(base.get("target_price"))
        for mode in modes:
            settings = MODE_SETTINGS[mode]
            budget = settings["budget_us"] if market == "us" else settings["budget_kr"]
            shares = int(budget // entry) if entry and entry > 0 else 0
            invested = shares * entry if shares else 0.0
            loss_total = (stop - entry) * shares if stop is not None and entry is not None and shares else None
            profit_total = (target - entry) * shares if target is not None and entry is not None and shares else None
            virtual.append({
                "created_at": stamp,
                **base,
                "snapshot_kind": "current_candidate",
                "mode": mode,
                "mode_label": MODE_LABELS[mode],
                "buy_rule": settings["buy_rule"],
                "sell_rule": "목표가·손절가·보유기간 종료 중 먼저 발생한 조건으로 청산",
                "hold_days": settings["hold_days"],
                "planned_entry": entry if entry is not None else "",
                "planned_entry_text": format_money(entry, market),
                "shares": shares,
                "shares_text": f"{shares}주" if market == "kr" else f"{shares} shares",
                "invested_amount": invested,
                "invested_text": format_money(invested, market),
                "expected_loss_amount": loss_total if loss_total is not None else "",
                "expected_loss_text": format_money(loss_total, market),
                "expected_profit_amount": profit_total if profit_total is not None else "",
                "expected_profit_text": format_money(profit_total, market),
                "account_loss_pct": pct(loss_total, budget) if loss_total is not None else "",
                "account_profit_pct": pct(profit_total, budget) if profit_total is not None else "",
                "execution_status": execution_status(current, entry, mode),
                "status": "기록 저장",
                "summary": "standalone recorder snapshot",
            })
    return virtual, snapshots


def row_key(row: dict[str, Any], fields: list[str]) -> str:
    return "|".join(str(row.get(f, "")).strip() for f in fields)


def append_rows(path: Path, rows: list[dict[str, Any]], key_fields: list[str]) -> dict[str, Any]:
    before = read_csv_rows(path)
    existing = {row_key(r, key_fields) for r in before}
    added = []
    for row in rows:
        k = row_key(row, key_fields)
        if k in existing:
            continue
        existing.add(k)
        added.append(row)
    merged = before + added
    write_csv_rows(path, merged)
    return {"file": rel(path), "beforeRows": len(before), "addedRows": len(added), "afterRows": len(merged)}


def outcome_files() -> list[Path]:
    pats = ["data/history/outcome_history.csv", "reports/*outcome*.csv", "reports/*validation*.csv"]
    files = []
    seen = set()
    for pat in pats:
        for path in REPO_ROOT.glob(pat):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return files


def outcome_lookup() -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for path in outcome_files():
        for row in read_csv_rows(path, limit=5000):
            market = infer_market(row, path, None)
            sym = normalize_symbol(first_value(row, SYMBOL_ALIASES, ""), market)
            if not sym:
                continue
            date = first_value(row, DATE_ALIASES, "")
            key = f"{market}|{sym}"
            old = lookup.get(key)
            if old is None or date >= str(old.get("_date", "")):
                r = dict(row)
                r["_date"] = date
                r["_source_file"] = rel(path)
                lookup[key] = r
    return lookup


def result_from_outcome(row: dict[str, Any] | None) -> str:
    if not row:
        return "검증 대기"
    text = first_value(row, RESULT_ALIASES, "")
    low = text.lower()
    if low in {"success", "win", "true", "1", "성공", "적중"}:
        return "성공"
    if low in {"fail", "failure", "loss", "false", "0", "실패", "불일치"}:
        return "실패"
    if low in {"neutral", "hold", "중립"}:
        return "중립"
    return text or "검증 대기"


def evaluate() -> dict[str, Any]:
    hist = read_csv_rows(VIRTUAL_HISTORY_FILE)
    outcomes = outcome_lookup()
    evaluated = []
    matched = 0
    stamp = now()
    for row in hist:
        market = str(row.get("market", "")).lower()
        symbol = normalize_symbol(row.get("symbol", ""), market if market in MARKETS else "kr")
        outcome = outcomes.get(f"{market}|{symbol}")
        if outcome:
            matched += 1
        realized = first_number(outcome or {}, RETURN_ALIASES)
        evaluated.append({
            "evaluated_at": stamp,
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
            "outcome_result": result_from_outcome(outcome),
            "outcome_date": outcome.get("_date", "") if outcome else "",
            "realized_return_pct": realized if realized is not None else "",
            "evaluation_source": outcome.get("_source_file", "outcome 미매칭") if outcome else "outcome 미매칭",
        })
    write_csv_rows(VIRTUAL_EVALUATION_FILE, evaluated)
    return {"file": rel(VIRTUAL_EVALUATION_FILE), "rows": len(evaluated), "matchedRows": matched}


def auto_correction() -> dict[str, Any]:
    rows = read_csv_rows(VIRTUAL_EVALUATION_FILE)
    groups: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    for row in rows:
        ret = to_number(row.get("realized_return_pct"))
        if ret is None:
            continue
        mode = row.get("mode", "")
        swing = row.get("swing_group", "")
        groups[("mode", mode, "")].append(ret)
        groups[("swing_group", swing, "")].append(ret)
        groups[("mode+swing_group", mode, swing)].append(ret)
    summary = []
    stamp = now()
    for (typ, a, b), vals in groups.items():
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0)
        avg = sum(vals) / len(vals)
        item = {"summary_type": typ, "updated_at": stamp, "trades": len(vals), "win_rate": f"{wins/len(vals)*100:.1f}%", "avg_return": f"{avg:.2f}%"}
        if typ.startswith("mode"):
            item["mode"] = a
        if "swing" in typ:
            item["swing_group"] = b if typ == "mode+swing_group" else a
        item["suggestion"] = "표본 부족 · 추가 기록 필요" if len(vals) < 5 else ("현재 기준 유지 가능" if avg > 1 else "매수 조건 강화 또는 손절/목표가 재조정 필요" if avg < -1 else "중립 · 조건 미세조정 필요")
        summary.append(item)
    if not summary:
        summary.append({"summary_type": "status", "updated_at": stamp, "trades": 0, "win_rate": "검증 데이터 부족", "avg_return": "검증 데이터 부족", "suggestion": "가상 운용 스냅샷과 outcome_history가 쌓이면 자동 보정 요약을 계산합니다."})
    write_csv_rows(AUTO_CORRECTION_FILE, summary)
    return {"file": rel(AUTO_CORRECTION_FILE), "rows": len(summary), "items": summary[:20]}


def save_current_snapshot(market: str, modes: str, source: str, include_backfill: bool) -> dict[str, Any]:
    selected_modes = mode_list(modes)
    all_virtual: list[dict[str, Any]] = []
    all_snapshots: list[dict[str, Any]] = []
    for mk in market_list(market):
        virtual, snapshots = build_rows(mk, selected_modes, source, include_backfill)
        all_virtual.extend(virtual)
        all_snapshots.extend(snapshots)
    vr = append_rows(VIRTUAL_HISTORY_FILE, all_virtual, ["created_at", "market", "symbol", "mode", "source"])
    sr = append_rows(PREDICTION_SNAPSHOT_FILE, all_snapshots, ["prediction_at", "market", "symbol", "source"])
    ev = evaluate()
    ac = auto_correction()
    return {"status": "OK", "repoRoot": str(REPO_ROOT), "market": market, "modes": selected_modes, "virtualOperations": vr, "predictionSnapshots": sr, "evaluation": ev, "autoCorrection": ac}


def main() -> None:
    parser = argparse.ArgumentParser(description="Standalone MONE virtual operation and prediction history recorder.")
    parser.add_argument("--market", default="all", choices=["all", "kr", "us"])
    parser.add_argument("--modes", default="all")
    parser.add_argument("--source", default=os.environ.get("MONE_HISTORY_SOURCE", "scheduled"))
    parser.add_argument("--backfill-existing", action="store_true")
    args = parser.parse_args()
    result = save_current_snapshot(args.market, args.modes, args.source, args.backfill_existing)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
