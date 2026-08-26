"""Point-in-time validation and promotion gate for biotech evidence.

Only forward snapshots collected from official sources can create events. Event
returns start at the next trading session to avoid same-day lookahead. A signal
cannot affect recommendation scores until its chronological holdout clears all
sample, clustering, residual-alpha, and cost gates.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.services import data_loader as data

SNAPSHOT_PATH = data.REPO_ROOT / "data" / "biotech_evidence_snapshots.jsonl"
EVENT_PATH = data.REPO_ROOT / "data" / "biotech_evidence_events.jsonl"
VALIDATION_PATH = data.REPO_ROOT / "reports" / "biotech_evidence_validation.json"
BENCHMARKS = {"kr": "KOSPI", "us": "SPY"}
ROUND_TRIP_COST_PCT = {"kr": 0.41, "us": 0.20}
RISK_STATUSES = {"SUSPENDED", "TERMINATED", "WITHDRAWN"}
DIRECTIONAL_EVENT_TYPES = {"CLINICAL_RISK_STARTED": -1, "CLINICAL_RISK_CLEARED": 1}
MIN_ROWS = 30
MIN_DATES = 12
MIN_SYMBOLS = 5
MIN_TRAIN_DATES = 8
MIN_HOLDOUT_DATES = 4
HOLDOUT_SHARE = 0.30
EVALUATION_HORIZON = 5


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    text = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
    temp.write_text(text + ("\n" if text else ""), encoding="utf-8")
    temp.replace(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _hash_id(*parts: Any) -> str:
    raw = "|".join(_text(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _snapshot_from_item(item: dict[str, Any], captured_at: str) -> dict[str, Any]:
    market = _text(item.get("market")).lower()
    symbol = _text(item.get("symbol")).upper()
    clinical = item.get("clinicalTrials") if isinstance(item.get("clinicalTrials"), dict) else {}
    pubmed = item.get("pubMed") if isinstance(item.get("pubMed"), dict) else {}
    studies: dict[str, dict[str, Any]] = {}
    for study in clinical.get("studies") or []:
        if not isinstance(study, dict):
            continue
        nct_id = _text(study.get("nctId"))
        if not nct_id:
            continue
        studies[nct_id] = {
            "overallStatus": _text(study.get("overallStatus")).upper(),
            "phases": sorted(_text(value).upper() for value in study.get("phases") or [] if _text(value)),
            "completionDate": _text(study.get("completionDate")),
            "hasResults": bool(study.get("hasResults")),
            "leadSponsor": _text(study.get("leadSponsor")),
        }
    pmids = sorted(
        _text(row.get("pmid"))
        for row in pubmed.get("publications") or []
        if isinstance(row, dict) and _text(row.get("pmid"))
    )
    as_of = _text(item.get("asOfDate"))[:10]
    content = {
        "clinicalStatus": _text(clinical.get("status")),
        "verifiedStudyCount": int(clinical.get("verifiedStudyCountInFetchedPage") or 0),
        "activeStudyCount": int(clinical.get("activeStudyCountInFetchedPage") or 0),
        "phase3StudyCount": int(clinical.get("phase3StudyCountInFetchedPage") or 0),
        "riskStudyCount": int(clinical.get("riskStatusStudyCountInFetchedPage") or 0),
        "studies": studies,
        "pubMedStatus": _text(pubmed.get("status")),
        "publicationCountRecent5y": pubmed.get("publicationCountRecent5y"),
        "pmids": pmids,
    }
    content_hash = _hash_id(json.dumps(content, ensure_ascii=False, sort_keys=True))
    return {
        "snapshotId": _hash_id(market, symbol, as_of, content_hash),
        "capturedAt": captured_at,
        "asOfDate": as_of,
        "market": market,
        "symbol": symbol,
        "company": _text(item.get("company")),
        "queryCompany": _text(item.get("queryCompany")),
        "sourceStatus": _text(item.get("status")),
        "contentHash": content_hash,
        **content,
    }


def _event(
    current: dict[str, Any],
    event_type: str,
    reference_id: str,
    *,
    direction: int = 0,
    previous_value: Any = None,
    current_value: Any = None,
) -> dict[str, Any]:
    event_date = _text(current.get("asOfDate"))[:10]
    event_id = _hash_id(
        current.get("market"), current.get("symbol"), event_date,
        event_type, reference_id, previous_value, current_value,
    )
    return {
        "eventId": event_id,
        "eventDate": event_date,
        "capturedAt": current.get("capturedAt"),
        "market": current.get("market"),
        "symbol": current.get("symbol"),
        "company": current.get("company"),
        "eventType": event_type,
        "referenceId": reference_id,
        "direction": int(direction),
        "previousValue": previous_value,
        "currentValue": current_value,
        "evaluationStatus": "NON_DIRECTIONAL" if direction == 0 else "PENDING",
        "evaluationHorizonSessions": EVALUATION_HORIZON,
        "pointInTime": True,
    }


def derive_events(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    if previous is None:
        return [_event(current, "BASELINE_CAPTURE", "baseline")]
    events: list[dict[str, Any]] = []
    old_studies = previous.get("studies") if isinstance(previous.get("studies"), dict) else {}
    new_studies = current.get("studies") if isinstance(current.get("studies"), dict) else {}
    for nct_id, new_study in sorted(new_studies.items()):
        if not isinstance(new_study, dict):
            continue
        old_study = old_studies.get(nct_id) if isinstance(old_studies.get(nct_id), dict) else None
        if old_study is None:
            events.append(_event(current, "CLINICAL_STUDY_ADDED", nct_id))
            continue
        old_status = _text(old_study.get("overallStatus")).upper()
        new_status = _text(new_study.get("overallStatus")).upper()
        if old_status != new_status:
            if new_status in RISK_STATUSES and old_status not in RISK_STATUSES:
                event_type, direction = "CLINICAL_RISK_STARTED", -1
            elif old_status in RISK_STATUSES and new_status not in RISK_STATUSES:
                event_type, direction = "CLINICAL_RISK_CLEARED", 1
            else:
                event_type, direction = "CLINICAL_STATUS_CHANGED", 0
            events.append(_event(
                current, event_type, nct_id, direction=direction,
                previous_value=old_status, current_value=new_status,
            ))
        if not bool(old_study.get("hasResults")) and bool(new_study.get("hasResults")):
            events.append(_event(current, "CLINICAL_RESULTS_POSTED", nct_id))
    old_pmids = set(previous.get("pmids") or [])
    for pmid in sorted(set(current.get("pmids") or []) - old_pmids):
        events.append(_event(current, "PUBMED_PUBLICATION_ADDED", pmid))
    return events


def _price_rows(market: str, symbol: str) -> list[dict[str, Any]]:
    path = data.REPO_ROOT / "data" / "market" / "ohlcv" / f"{market}_{symbol}_daily.csv"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError:
        return []
    valid = [row for row in rows if _text(row.get("date")) and _float(row.get("close")) not in {None, 0.0}]
    return sorted(valid, key=lambda row: _text(row.get("date")))


def evaluate_event(event: dict[str, Any]) -> dict[str, Any]:
    row = dict(event)
    direction = int(row.get("direction") or 0)
    if direction == 0:
        row["evaluationStatus"] = "NON_DIRECTIONAL"
        return row
    market = _text(row.get("market")).lower()
    symbol = _text(row.get("symbol")).upper()
    event_date = _text(row.get("eventDate"))[:10]
    stock = _price_rows(market, symbol)
    benchmark_symbol = BENCHMARKS.get(market, "")
    benchmark = _price_rows(market, benchmark_symbol) if benchmark_symbol else []
    eligible = [item for item in stock if _text(item.get("date")) > event_date]
    if len(eligible) < EVALUATION_HORIZON or not benchmark:
        row["evaluationStatus"] = "PENDING"
        row["pendingReason"] = "NEXT_SESSION_OR_HORIZON_NOT_AVAILABLE"
        return row
    entry = eligible[0]
    exit_row = eligible[EVALUATION_HORIZON - 1]
    entry_date = _text(entry.get("date"))
    exit_date = _text(exit_row.get("date"))
    benchmark_by_date = {_text(item.get("date")): item for item in benchmark}
    benchmark_entry = benchmark_by_date.get(entry_date)
    benchmark_exit = benchmark_by_date.get(exit_date)
    if benchmark_entry is None or benchmark_exit is None:
        row["evaluationStatus"] = "PENDING"
        row["pendingReason"] = "BENCHMARK_DATE_NOT_AVAILABLE"
        return row
    stock_entry = _float(entry.get("open")) or _float(entry.get("close"))
    stock_exit = _float(exit_row.get("close"))
    bench_entry = _float(benchmark_entry.get("open")) or _float(benchmark_entry.get("close"))
    bench_exit = _float(benchmark_exit.get("close"))
    if not all(value not in {None, 0.0} for value in (stock_entry, stock_exit, bench_entry, bench_exit)):
        row["evaluationStatus"] = "PENDING"
        row["pendingReason"] = "INVALID_PRICE"
        return row
    raw_return = (float(stock_exit) / float(stock_entry) - 1.0) * 100.0
    benchmark_return = (float(bench_exit) / float(bench_entry) - 1.0) * 100.0
    residual = raw_return - benchmark_return
    cost = ROUND_TRIP_COST_PCT.get(market, 0.20)
    row.update({
        "evaluationStatus": "EVALUATED",
        "entryDate": entry_date,
        "exitDate": exit_date,
        "entryPrice": round(float(stock_entry), 6),
        "exitPrice": round(float(stock_exit), 6),
        "rawReturnPct": round(raw_return, 4),
        "benchmarkSymbol": benchmark_symbol,
        "benchmarkReturnPct": round(benchmark_return, 4),
        "residualAlphaPct": round(residual, 4),
        "roundTripCostPct": cost,
        "signedNetResidualAlphaPct": round(direction * residual - cost, 4),
        "lookaheadRule": "entry_at_next_trading_session_open",
    })
    return row


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def _ci95(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    mean = statistics.fmean(values)
    std = statistics.stdev(values)
    # Small holdouts need Student-t, not the optimistic normal 1.96 cutoff.
    critical_by_df = {
        1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
        6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060,
        26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
    }
    df = len(values) - 1
    critical = critical_by_df.get(df, 1.96 if df >= 120 else 1.98)
    margin = critical * std / math.sqrt(len(values))
    return [round(mean - margin, 4), round(mean + margin, 4)]


def _gate_for_group(market: str, event_type: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    values_by_date: dict[str, list[float]] = {}
    per_symbol: dict[str, int] = {}
    for row in rows:
        day = _text(row.get("eventDate"))
        value = _float(row.get("signedNetResidualAlphaPct"))
        if day and value is not None:
            values_by_date.setdefault(day, []).append(value)
        symbol = _text(row.get("symbol")).upper()
        if symbol:
            per_symbol[symbol] = per_symbol.get(symbol, 0) + 1
    date_means = {day: statistics.fmean(values) for day, values in values_by_date.items() if values}
    dates = sorted(date_means)
    split = max(1, math.floor(len(dates) * (1.0 - HOLDOUT_SHARE))) if dates else 0
    if len(dates) > 1:
        split = min(split, len(dates) - 1)
    train_dates = set(dates[:split])
    holdout_dates = set(dates[split:])
    # Same-day rows share a market shock. Each date is one inference unit.
    train_values = [date_means[day] for day in dates if day in train_dates]
    holdout_values = [date_means[day] for day in dates if day in holdout_dates]
    per_date = {day: len(values) for day, values in values_by_date.items()}
    max_date_share = max(per_date.values(), default=0) / len(rows) if rows else 0.0
    max_symbol_share = max(per_symbol.values(), default=0) / len(rows) if rows else 0.0
    enough = (
        len(rows) >= MIN_ROWS and len(dates) >= MIN_DATES and len(per_symbol) >= MIN_SYMBOLS
        and len(train_dates) >= MIN_TRAIN_DATES and len(holdout_dates) >= MIN_HOLDOUT_DATES
    )
    train_mean = _mean(train_values)
    holdout_mean = _mean(holdout_values)
    holdout_ci = _ci95(holdout_values)
    positive_rate = (
        sum(1 for value in holdout_values if value > 0) / len(holdout_values)
        if holdout_values else None
    )
    clustered = max_date_share > 0.25 or max_symbol_share > 0.40
    promoted = bool(
        enough and not clustered and train_mean is not None and train_mean > 0
        and holdout_mean is not None and holdout_mean > 0
        and positive_rate is not None and positive_rate >= 0.55
        and holdout_ci is not None and holdout_ci[0] > 0
    )
    status = "PROMOTED" if promoted else ("REJECTED" if enough else "INSUFFICIENT")
    adjustment = 0.0
    if promoted and holdout_mean is not None:
        adjustment = round(max(0.5, min(2.0, holdout_mean * 0.25)), 2)
    return {
        "key": f"{market}:{event_type}",
        "market": market,
        "eventType": event_type,
        "direction": DIRECTIONAL_EVENT_TYPES.get(event_type, 0),
        "status": status,
        "promotionEligible": promoted,
        "scoreMagnitude": adjustment,
        "sampleCount": len(rows),
        "effectiveDateSampleCount": len(dates),
        "distinctEventDates": len(dates),
        "distinctSymbols": len(per_symbol),
        "trainDateCount": len(train_dates),
        "holdoutDateCount": len(holdout_dates),
        "trainMeanSignedNetResidualAlphaPct": round(train_mean, 4) if train_mean is not None else None,
        "holdoutMeanSignedNetResidualAlphaPct": round(holdout_mean, 4) if holdout_mean is not None else None,
        "holdoutPositiveRate": round(positive_rate, 4) if positive_rate is not None else None,
        "holdoutCi95": holdout_ci,
        "maxSingleDateShare": round(max_date_share, 4),
        "maxSingleSymbolShare": round(max_symbol_share, 4),
        "clustered": clustered,
        "minimums": {
            "samples": MIN_ROWS,
            "eventDates": MIN_DATES,
            "symbols": MIN_SYMBOLS,
            "trainDates": MIN_TRAIN_DATES,
            "holdoutDates": MIN_HOLDOUT_DATES,
        },
        "costModel": "signed_stock_minus_benchmark_residual_alpha_less_round_trip_cost",
        "inferenceUnit": "event_date_mean",
        "entryRule": "next_trading_session_open_after_capture",
    }


def build_validation(events: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [
        row for row in events
        if _text(row.get("evaluationStatus")) == "EVALUATED"
        and _text(row.get("eventType")) in DIRECTIONAL_EVENT_TYPES
        and _float(row.get("signedNetResidualAlphaPct")) is not None
    ]
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in evaluated:
        key = (_text(row.get("market")).lower(), _text(row.get("eventType")))
        groups.setdefault(key, []).append(row)
    gates = [_gate_for_group(market, event_type, rows) for (market, event_type), rows in sorted(groups.items())]
    for market in ("kr", "us"):
        for event_type in sorted(DIRECTIONAL_EVENT_TYPES):
            if not any(row["market"] == market and row["eventType"] == event_type for row in gates):
                gates.append(_gate_for_group(market, event_type, []))
    promoted = [row for row in gates if row.get("promotionEligible")]
    return {
        "status": "PROMOTED" if promoted else "RESEARCH_ONLY",
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "evaluatedDirectionalEventCount": len(evaluated),
        "promotionCount": len(promoted),
        "operationalScoreAdjustmentAllowed": bool(promoted),
        "gates": sorted(gates, key=lambda row: row["key"]),
        "policy": {
            "pointInTimeOnly": True,
            "sameDayEntryAllowed": False,
            "automaticInverse": False,
            "maxAbsoluteScoreAdjustment": 2.0,
            "nonDirectionalEvidenceScoreAdjustment": 0.0,
        },
    }


def validate_and_save() -> dict[str, Any]:
    events = [evaluate_event(row) for row in _read_jsonl(EVENT_PATH)]
    _write_jsonl(EVENT_PATH, events)
    validation = build_validation(events)
    _write_json(VALIDATION_PATH, validation)
    return validation


def persist_point_in_time(payload: dict[str, Any]) -> dict[str, Any]:
    captured_at = _text(payload.get("generatedAt")) or datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshots = _read_jsonl(SNAPSHOT_PATH)
    events = _read_jsonl(EVENT_PATH)
    snapshot_ids = {_text(row.get("snapshotId")) for row in snapshots}
    event_ids = {_text(row.get("eventId")) for row in events}
    previous_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in sorted(snapshots, key=lambda value: (_text(value.get("capturedAt")), _text(value.get("snapshotId")))):
        previous_by_key[(_text(row.get("market")), _text(row.get("symbol")))] = row
    added_snapshots = 0
    added_events = 0
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        current = _snapshot_from_item(item, captured_at)
        key = (_text(current.get("market")), _text(current.get("symbol")))
        if current["snapshotId"] in snapshot_ids:
            previous_by_key[key] = current
            continue
        previous = previous_by_key.get(key)
        snapshots.append(current)
        snapshot_ids.add(current["snapshotId"])
        added_snapshots += 1
        for event in derive_events(previous, current):
            if event["eventId"] not in event_ids:
                events.append(event)
                event_ids.add(event["eventId"])
                added_events += 1
        previous_by_key[key] = current
    _write_jsonl(SNAPSHOT_PATH, snapshots)
    _write_jsonl(EVENT_PATH, events)
    validation = validate_and_save()
    return {
        "status": "OK",
        "addedSnapshots": added_snapshots,
        "addedEvents": added_events,
        "snapshotCount": len(snapshots),
        "eventCount": len(events),
        "validation": validation,
    }


def read_validation() -> dict[str, Any]:
    payload = _read_json(VALIDATION_PATH, {})
    if isinstance(payload, dict) and payload:
        return payload
    return build_validation(_read_jsonl(EVENT_PATH))


def score_decision(
    item: dict[str, Any],
    validation: dict[str, Any] | None = None,
    *,
    events: list[dict[str, Any]] | None = None,
    as_of: date | None = None,
) -> dict[str, Any]:
    validation = validation or read_validation()
    market = _text(item.get("market")).lower()
    symbol = _text(item.get("symbol")).upper()
    clinical = item.get("clinicalTrials") if isinstance(item.get("clinicalTrials"), dict) else {}
    risk_count = int(clinical.get("riskStatusStudyCountInFetchedPage") or 0)
    event_rows = events if events is not None else _read_jsonl(EVENT_PATH)
    today = as_of or date.today()
    recent: list[tuple[date, dict[str, Any]]] = []
    for event in event_rows:
        if _text(event.get("market")).lower() != market or _text(event.get("symbol")).upper() != symbol:
            continue
        event_type = _text(event.get("eventType"))
        if event_type not in DIRECTIONAL_EVENT_TYPES:
            continue
        try:
            event_day = date.fromisoformat(_text(event.get("eventDate"))[:10])
        except ValueError:
            continue
        age = (today - event_day).days
        if 0 <= age <= 30:
            recent.append((event_day, event))
    recent.sort(key=lambda pair: (pair[0], _text(pair[1].get("capturedAt")), _text(pair[1].get("eventId"))))
    signal = recent[-1][1] if recent else None
    event_type = _text((signal or {}).get("eventType"))
    direction = DIRECTIONAL_EVENT_TYPES.get(event_type, 0)
    gate_key = f"{market}:{event_type}" if event_type else f"{market}:NO_RECENT_DIRECTIONAL_EVENT"
    gate = next((row for row in validation.get("gates") or [] if row.get("key") == gate_key), None)
    promoted = bool(gate and gate.get("promotionEligible"))
    magnitude = _float((gate or {}).get("scoreMagnitude")) or 0.0
    adjustment = direction * magnitude if promoted and signal else 0.0
    if adjustment:
        reason = "RECENT_POINT_IN_TIME_BIOTECH_EVENT_GATE_PROMOTED"
    elif signal:
        reason = "RECENT_BIOTECH_EVENT_VISIBLE_BUT_NOT_PROMOTED"
    elif risk_count > 0:
        reason = "STATIC_CLINICAL_RISK_VISIBLE_BUT_NOT_A_NEW_EVENT"
    else:
        reason = "NO_RECENT_DIRECTIONAL_BIOTECH_EVENT"
    return {
        "scoreAdjustment": round(max(-2.0, min(2.0, adjustment)), 2),
        "promotionEligible": bool(adjustment),
        "promotionStatus": _text((gate or {}).get("status")) or "INSUFFICIENT",
        "reason": reason,
        "gateKey": gate_key,
        "signalEventId": (signal or {}).get("eventId"),
        "signalEventType": event_type or None,
        "signalEventDate": (signal or {}).get("eventDate"),
        "sampleCount": int((gate or {}).get("sampleCount") or 0),
        "distinctEventDates": int((gate or {}).get("distinctEventDates") or 0),
        "researchOnly": not bool(adjustment),
    }
