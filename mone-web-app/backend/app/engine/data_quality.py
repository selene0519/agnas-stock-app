"""
data_quality.py — MONE 데이터 품질 판정 엔진

mode=quick (기본): OHLCV 샘플 30개, final_engine 호출 생략 → 30초 내 응답 보장
mode=full : 전체 파일 검사 + final_engine 실행 (느릴 수 있음)
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.engine import session
from app.engine.symbols import normalize_market
from app.services import data_loader as data
from app.services import final_engine

# quick 모드에서 검사할 OHLCV 파일 최대 수
_MAX_OHLCV_SAMPLE = 30

# 날짜 컬럼 후보 (우선순위순)
_DATE_COLS = [
    "generatedAt", "recommendationDate", "asOfDate", "asOf",
    "createdAt", "date", "tradeDate", "priceDate", "updatedAt",
    "baseDate", "dataDate", "recordDate", "reportDate",
]

# OHLCV 심볼 유효성 검사 — 이 값이면 파일 선택 제외
_INVALID_OHLCV_SYMBOLS = {"NAN", "NONE", "NULL", "N/A", "NA", "", "UNDEFINED"}

# 결측률 검사 대상 컬럼
_QUALITY_COLS = [
    "symbol", "name", "currentPrice", "close",
    "entryPrice", "targetPrice", "stopPrice",
    "finalRankScore", "probability", "generatedAt",
]


def _repo_path(*parts: str) -> Path:
    return Path(data.REPO_ROOT, *parts)


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return paths[0] if paths else None


def _market_today_str(market: str, now: datetime | None = None) -> str:
    value = now or datetime.now(session.KST)
    if value.tzinfo is None:
        value = value.replace(tzinfo=session.KST)
    value = value.astimezone(session.NY) if normalize_market(market) == "us" else value.astimezone(session.KST)
    return value.strftime("%Y-%m-%d")


def _best_required_today_existing(paths: list[Path], market: str) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return paths[0] if paths else None

    status_rank = {
        "NORMAL": 0,
        "OK": 0,
        "PREVIOUS_CLOSE_BASIS": 1,
        "INTRADAY_OBSERVE": 1,
        "PARTIAL": 2,
        "STALE": 3,
        "NO_DATA": 4,
        "ERROR": 5,
    }

    def sort_key(path: Path) -> tuple[int, float]:
        try:
            result = session.evaluate_file_status(path, market, required_today=True)
            rank = status_rank.get(str(result.get("status") or "").upper(), 6)
            mtime = path.stat().st_mtime
        except Exception:
            rank = 6
            mtime = 0.0
        return (rank, -mtime)

    return sorted(existing, key=sort_key)[0]


def _read_csv_safe(path: Path) -> list[dict[str, str]]:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _parse_date_str(s: str | None) -> str | None:
    if not s:
        return None
    s = str(s).strip()[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        return None


def _deep_csv_inspect(path: Path, market: str) -> dict[str, Any]:
    """CSV 내부 데이터 품질을 상세 검사한다."""
    if not path.is_file():
        return {"deepStatus": "NO_DATA", "deepReason": "파일 없음"}

    rows = _read_csv_safe(path)
    row_count = len(rows)

    if row_count == 0:
        return {
            "deepStatus": "EMPTY_RESULT",
            "deepReason": "파일 존재하지만 row 0개",
            "rowCount": 0,
            "emptyResult": True,
        }

    # 최신 내부 날짜 — 대소문자 구분 없이 컬럼 탐색
    latest_date: str | None = None
    date_col_found: str | None = None
    warnings_inner: list[str] = []
    # date 컬럼 미발견 → mtime 폴백 정보 (info 레벨, 치명 아님)
    date_missing_info: dict[str, Any] | None = None

    header_lower = {k.lower(): k for k in rows[0].keys()} if rows else {}

    for col in _DATE_COLS:
        actual_col = header_lower.get(col.lower()) or col
        dates = [_parse_date_str(r.get(actual_col)) for r in rows]
        dates = [d for d in dates if d]
        if dates:
            latest_date = max(dates)
            date_col_found = actual_col
            break

    # 폴백: 파일 mtime — info 레벨로 기록
    if not latest_date:
        try:
            latest_date = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
            date_missing_info = {
                "severity": "info",
                "file": str(path),
                "note": "latestDataDate was inferred from file mtime",
            }
        except Exception:
            warnings_inner.append("date_parse_failed")

    # STALE 여부: 내부 날짜 기준
    stale_reason: str | None = None
    today_str = _market_today_str(market)
    if latest_date and latest_date < today_str and not session.is_market_holiday(market):
        stale_reason = f"CSV 내부 최신 날짜 {latest_date}가 오늘({today_str})보다 과거"

    # 유효 심볼 & 중복
    symbols = [str(r.get("symbol", "")).strip() for r in rows]
    valid_symbols = [s for s in symbols if s]
    dup_count = len(valid_symbols) - len(set(valid_symbols))

    # 결측률
    missing_rate: dict[str, float] = {}
    for col in _QUALITY_COLS:
        if col in (rows[0] if rows else {}):
            missing = sum(1 for r in rows if not str(r.get(col, "")).strip())
            missing_rate[col] = round(missing / row_count * 100, 1)

    # 시장 구분 검사 — CSV 내부 market 컬럼 혼입만 카운트
    # (OHLCV 폴더에 다른 시장 파일이 있다는 이유만으로는 증가시키지 않음)
    invalid_market_count = 0
    mixed_market_count = 0
    if any("market" in r for r in rows[:1]):
        mkt_values = [str(r.get("market", "")).strip().lower() for r in rows]
        expected = normalize_market(market).lower()
        invalid_market_count = sum(1 for m in mkt_values if m and m not in {"kr", "us"})
        mixed_market_count = sum(1 for m in mkt_values if m and m != expected)

    # 종합 상태
    warnings: list[str] = list(warnings_inner)
    deep_status = "NORMAL"

    if stale_reason:
        deep_status = "STALE"
        warnings.append(stale_reason)

    sym_missing = missing_rate.get("symbol", 0)
    price_missing = missing_rate.get("currentPrice", missing_rate.get("close", 0))
    if sym_missing > 20 or price_missing > 30:
        deep_status = "PARTIAL" if deep_status == "NORMAL" else deep_status
        warnings.append(f"symbol 결측 {sym_missing}%, 가격 결측 {price_missing}%")

    if dup_count > row_count * 0.2:
        deep_status = "PARTIAL" if deep_status == "NORMAL" else deep_status
        warnings.append(f"심볼 중복 {dup_count}개")

    if mixed_market_count > 0:
        deep_status = "PARTIAL" if deep_status == "NORMAL" else deep_status
        warnings.append(f"혼합 시장 데이터 {mixed_market_count}개")

    return {
        "deepStatus": deep_status,
        "deepReason": warnings[0] if warnings else "정상",
        "rowCount": row_count,
        "validSymbolCount": len(set(valid_symbols)),
        "duplicatedSymbolCount": dup_count,
        "latestDataDate": latest_date,
        "missingRateByColumn": missing_rate,
        "invalidMarketCount": invalid_market_count,
        "mixedMarketCount": mixed_market_count,
        "emptyResult": False,
        "warnings": warnings,
        # info 레벨 — 최상위 warnings 에 노출하지 않음
        "dateMissingInfo": date_missing_info,
    }


def _candidate_files(market: str) -> list[dict[str, Any]]:
    normalized_market = normalize_market(market)
    return [
        {
            "name": "KIS 현재가 snapshot",
            "role": "price_priority_1",
            "path": _best_required_today_existing(
                [
                    _repo_path("data", "market", "snapshots", f"{normalized_market}_kis_current.json"),
                    _repo_path("data", "market", "quotes", f"{normalized_market}_latest_quotes.csv"),
                    _repo_path("reports", f"kis_current_snapshot_{normalized_market}.csv"),
                    _repo_path("reports", f"kis_current_price_{normalized_market}.csv"),
                    _repo_path("data", "stockapp", f"kis_current_price_{normalized_market}.csv"),
                ],
                normalized_market,
            ),
        },
        {
            "name": "Intraday snapshot",
            "role": "price_priority_2",
            "path": _best_required_today_existing(
                [
                    _repo_path("data", "market", "intraday", f"{normalized_market}_intraday_snapshot.csv"),
                    _repo_path("reports", f"{normalized_market}_intraday_report.csv"),
                    _repo_path("reports", f"intraday_quote_snapshot_{normalized_market}.csv"),
                    _repo_path("reports", f"intraday_realtime_snapshot_{normalized_market}.csv"),
                ],
                normalized_market,
            ),
        },
        {
            "name": "OHLCV daily",
            "role": "price_priority_3",
            "path": _repo_path("data", "market", "ohlcv"),
        },
        {
            "name": "Premarket report",
            "role": "price_priority_4",
            "path": _first_existing(
                [
                    _repo_path("data", "reports", f"{normalized_market}_premarket_report.csv"),
                    _repo_path("reports", f"{normalized_market}_premarket_report.csv"),
                    _repo_path("reports", "predictions.csv"),
                ]
            ),
        },
        {
            "name": "Fallback dataset",
            "role": "price_priority_5",
            "path": _first_existing(
                [
                    _repo_path("reports"),
                    _repo_path("data"),
                ]
            ),
        },
    ]


def _filter_ohlcv_files(
    files: list[Path], market: str
) -> tuple[list[Path], dict[str, Any]]:
    """
    OHLCV 파일 목록에서 market 접두사가 맞고 심볼이 유효한 파일만 반환.
    반환: (valid_files, filter_info)
      filter_info = {
        mismatch_count, mismatch_samples(최대10),
        invalid_count,  invalid_samples(최대5)
      }
    """
    market_prefix = market.lower() + "_"
    valid: list[Path] = []
    mismatch_names: list[str] = []
    invalid_names: list[str] = []
    for f in files:
        stem_parts = f.stem.split("_")
        if not f.name.startswith(market_prefix):
            mismatch_names.append(f.name)
            continue
        sym = stem_parts[1].upper() if len(stem_parts) >= 2 else ""
        if sym in _INVALID_OHLCV_SYMBOLS or not sym:
            invalid_names.append(f.name)
            continue
        valid.append(f)
    return valid, {
        "mismatch_count": len(mismatch_names),
        "mismatch_samples": mismatch_names[:10],
        "invalid_count": len(invalid_names),
        "invalid_samples": invalid_names[:5],
    }


def _status_for_path(
    path: Path | None, market: str, role: str, max_files: int = 0
) -> dict[str, Any]:
    """
    max_files > 0 이면 OHLCV 디렉토리 검사를 해당 수만큼 제한한다 (quick 모드).
    """
    if path is None:
        return {"status": "NO_DATA", "reason": "경로 없음", "path": None, "role": role}
    if path.is_dir():
        all_files = [item for item in path.glob("*.csv") if item.is_file()]
        if not all_files:
            return {"status": "NO_DATA", "reason": "CSV 없음", "path": str(path), "role": role}

        warning_summary: dict[str, int] = {}
        warning_samples: dict[str, list[str]] = {}

        if role == "price_priority_3":
            # OHLCV 디렉토리: market 접두사 + 유효 심볼 필터
            filtered, filter_info = _filter_ohlcv_files(all_files, market)
            files_to_use = filtered if filtered else all_files
            total_file_count = len(files_to_use)
            # quick 모드: 파일 수 제한 (mtime 기준 최신 N개만)
            if max_files > 0 and len(files_to_use) > max_files:
                files_to_use = sorted(
                    files_to_use, key=lambda f: f.stat().st_mtime, reverse=True
                )[:max_files]
            if filter_info["mismatch_count"]:
                warning_summary["market_mismatch_file"] = filter_info["mismatch_count"]
                warning_samples["market_mismatch_file"] = filter_info["mismatch_samples"]
            if filter_info["invalid_count"]:
                warning_summary["invalid_ohlcv_file"] = filter_info["invalid_count"]
                warning_samples["invalid_ohlcv_file"] = filter_info["invalid_samples"]
        else:
            files_to_use = all_files
            total_file_count = len(files_to_use)

        newest = max(files_to_use, key=lambda item: item.stat().st_mtime)
        result = session.evaluate_file_status(newest, market, required_today=role in {"price_priority_1", "price_priority_2"})
        result["path"] = str(newest)
        result["role"] = role
        result["fileCount"] = total_file_count
        result["checkedFileCount"] = len(files_to_use)
        result["mtimeDate"] = datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d")
        if warning_summary:
            result["warningSummary"] = warning_summary
            result["warningSamples"] = warning_samples
        if role == "price_priority_3" and result["status"] == "STALE":
            result["status"] = "PARTIAL"
            result["reason"] = "OHLCV 최신 파일이 당일은 아니지만 백테스트용 보조 데이터로 사용 가능"
        return result
    result = session.evaluate_file_status(path, market, required_today=role in {"price_priority_1", "price_priority_2"})
    result["role"] = role
    return result


def _recommendation_csv_inspect(market: str) -> dict[str, Any]:
    """현재 추천 CSV(balanced/swing)를 내부까지 검사한다."""
    normalized = normalize_market(market)
    csv_path = _repo_path("reports", f"mone_v36_final_recommendations_{normalized}_balanced_swing.csv")
    if not csv_path.exists():
        return {"status": "NO_DATA", "reason": "추천 CSV 없음", "path": str(csv_path)}

    mtime_result = session.evaluate_file_status(csv_path, normalized, required_today=True)
    deep = _deep_csv_inspect(csv_path, normalized)
    price_state = session.get_price_session(normalized)
    price_session = str(price_state.get("priceSession") or "")

    combined_status = mtime_result["status"]
    if deep.get("deepStatus") == "STALE" and combined_status == "NORMAL":
        combined_status = "STALE"
    elif deep.get("emptyResult"):
        combined_status = "EMPTY_RESULT"
    elif deep.get("deepStatus") in {"PARTIAL", "ERROR"}:
        combined_status = deep["deepStatus"]
    previous_close_basis = (
        normalized == "us"
        and combined_status == "STALE"
        and price_session in {"us_premarket", "us_intraday"}
        and bool(deep.get("latestDataDate"))
    )
    if previous_close_basis:
        combined_status = "PREVIOUS_CLOSE_BASIS"

    return {
        "status": combined_status,
        "basisStatus": "recommendation_previous_close_basis" if previous_close_basis else "",
        "basisLabel": "US recommendation uses previous close while live session is open" if previous_close_basis else "",
        "priceSession": price_session,
        "latestFileModifiedAt": mtime_result.get("mtimeDate"),
        "latestDataDate": deep.get("latestDataDate"),
        "rowCount": deep.get("rowCount", 0),
        "validSymbolCount": deep.get("validSymbolCount", 0),
        "duplicatedSymbolCount": deep.get("duplicatedSymbolCount", 0),
        "missingRateByColumn": deep.get("missingRateByColumn", {}),
        "invalidMarketCount": deep.get("invalidMarketCount", 0),
        "mixedMarketCount": deep.get("mixedMarketCount", 0),
        "emptyResult": deep.get("emptyResult", False),
        "warnings": [] if previous_close_basis else deep.get("warnings", []),
        "info": ["recommendation_previous_close_basis"] if previous_close_basis else [],
        # info 레벨 — 상위로 전달해 warningsDetail 에 합산
        "dateMissingInfo": deep.get("dateMissingInfo"),
        "path": str(csv_path),
        "role": "recommendation_csv",
    }


def data_quality(market: str = "kr", mode: str = "quick") -> dict[str, Any]:
    """
    mode="quick" (기본): OHLCV 샘플 30개, final_engine 호출 생략 — 30초 내 응답
    mode="full" : 전체 파일 검사 + final_engine 실행
    """
    warnings: list[str] = []
    try:
        return _data_quality_inner(market, mode)
    except Exception as exc:
        warnings.append(f"internal_error:{exc!r:.200}")
        return {
            "status": "OK",
            "market": normalize_market(market),
            "dataStatus": "PARTIAL",
            "killSwitch": False,
            "latestDataDate": None,
            "rowCount": 0,
            "candidateCount": 0,
            "fullScan": mode == "full",
            "warnings": warnings,
        }


def _data_quality_inner(market: str, mode: str) -> dict[str, Any]:
    normalized_market = normalize_market(market)
    quick = mode != "full"
    max_ohlcv = _MAX_OHLCV_SAMPLE if quick else 0

    state = session.get_price_session(normalized_market)

    files = []
    for item in _candidate_files(normalized_market):
        try:
            status = _status_for_path(
                item["path"], normalized_market, item["role"],
                max_files=max_ohlcv if item["role"] == "price_priority_3" else 0,
            )
            files.append({**item, **status, "path": status.get("path") or (str(item["path"]) if item["path"] else None)})
        except Exception as exc:
            files.append({"name": item.get("name", ""), "role": item.get("role", ""), "path": None,
                          "status": "ERROR", "reason": str(exc)[:200]})

    rec_csv_inspect: dict[str, Any] = {}
    try:
        rec_csv_inspect = _recommendation_csv_inspect(normalized_market)
        files.append(rec_csv_inspect)
    except Exception as exc:
        rec_csv_inspect = {"status": "ERROR", "reason": str(exc)[:200], "rowCount": 0,
                           "emptyResult": True, "warnings": [], "role": "recommendation_csv"}
        files.append(rec_csv_inspect)

    # quick 모드: final_engine 호출 생략 — CSV 메타에서 후보 수 추정
    rows: list[dict] = []
    price_status = "NO_DATA"
    recommendation_status: str
    if quick:
        rc = rec_csv_inspect.get("rowCount", 0)
        if rc > 0 and not rec_csv_inspect.get("emptyResult"):
            recommendation_status = str(rec_csv_inspect.get("status") or "NORMAL")
            price_status = "PARTIAL"
        elif rec_csv_inspect.get("emptyResult"):
            recommendation_status = "EMPTY_RESULT"
        else:
            recommendation_status = "NO_DATA"
    else:
        try:
            recommendations = final_engine.final_recommendations(normalized_market, "balanced", "swing", 30)
            rows = recommendations.get("items") or []
            row_status = session.worst_status(row.get("dataStatus") for row in rows)
            price_status = session.worst_status(row.get("priceDataStatus") for row in rows)
            if rows and row_status == "NORMAL":
                recommendation_status = "NORMAL"
            elif rows:
                recommendation_status = "PARTIAL"
            elif rec_csv_inspect.get("emptyResult"):
                recommendation_status = "EMPTY_RESULT"
            else:
                recommendation_status = "NO_DATA"
        except Exception as exc:
            rows = []
            price_status = "ERROR"
            recommendation_status = "ERROR"
            files.append({"name": "Recommendation engine", "role": "engine", "path": None,
                          "status": "ERROR", "reason": str(exc)[:200]})

    # ── 세션 타입 파악 ────────────────────────────────────────────────────────
    price_session_str = state.get("priceSession", "")
    is_after_close = any(x in price_session_str for x in ("after_close", "AFTER_CLOSE", "장마감"))
    is_review = bool(state.get("isReviewMode"))

    # ── 파일 상태를 realtime / data 로 분리 ──────────────────────────────────
    realtime_roles = {"price_priority_1", "price_priority_2"}
    # price_priority_4(프리마켓 리포트)·price_priority_5(fallback dataset)는 있으면
    # 참고하는 보조 소스일 뿐 필수 데이터가 아니므로, 파일이 없다는 이유로
    # 전체 dataStatus를 끌어내리면 안 된다.
    optional_fallback_roles = {"price_priority_4", "price_priority_5"}
    realtime_files = [f for f in files if f.get("role") in realtime_roles]
    data_files     = [
        f for f in files
        if f.get("role") not in realtime_roles and f.get("role") not in optional_fallback_roles
    ]

    def _effective_realtime_status(items: list[dict[str, Any]]) -> str:
        statuses = [str(f.get("status") or "NO_DATA").upper() for f in items]
        if any(status in {"NORMAL", "OK", "GOOD"} for status in statuses):
            return "NORMAL"
        if any(status == "PARTIAL" for status in statuses):
            return "PARTIAL"
        if any(status == "STALE" for status in statuses):
            return "STALE"
        return session.worst_status(statuses)

    realtime_status = _effective_realtime_status(realtime_files)
    data_status_raw = session.worst_status(f.get("status") for f in data_files)
    data_status_combined = session.worst_status([data_status_raw, recommendation_status])
    # quick 모드: final_engine 미호출로 rows=[] — realtime 파일 실제 상태로 price_status 반영
    if quick and realtime_status not in ("NO_DATA", "ERROR"):
        price_status = realtime_status

    # ── rec_has_data ──────────────────────────────────────────────────────────
    rec_has_data = (rec_csv_inspect.get("rowCount", 0) > 0
                    and rec_csv_inspect.get("validSymbolCount", 0) > 0
                    and not rec_csv_inspect.get("emptyResult"))

    # ── warningsDetail & top_warnings 빌드 ───────────────────────────────────
    warnings_detail: dict[str, Any] = {}
    top_warnings: list[str] = []

    # 1) date_column_missing — info 레벨 (top_warnings 에는 올리지 않음)
    date_missing_files: list[str] = []
    for f in [rec_csv_inspect] + files:
        dmi = f.get("dateMissingInfo")
        if dmi and dmi.get("file"):
            fp = dmi["file"]
            if fp not in date_missing_files:
                date_missing_files.append(fp)
    if date_missing_files:
        warnings_detail["date_column_missing"] = {
            "severity": "info",
            "count": len(date_missing_files),
            "files": date_missing_files,
            "note": "latestDataDate was inferred from file mtime or fallback source",
        }

    # 2) market_mismatch_file — info only, not a top warning
    total_mismatch = 0
    mismatch_samples: list[str] = []
    total_invalid_ohlcv = 0
    for f in files:
        ws = f.get("warningSummary") or {}
        ws_samp = f.get("warningSamples") or {}
        cnt = ws.get("market_mismatch_file", 0)
        total_mismatch += cnt
        for s in ws_samp.get("market_mismatch_file", []):
            if s not in mismatch_samples:
                mismatch_samples.append(s)
        total_invalid_ohlcv += ws.get("invalid_ohlcv_file", 0)
    if total_mismatch:
        warnings_detail["market_mismatch_file"] = {
            "severity": "info",
            "count": total_mismatch,
            "samples": mismatch_samples[:10],
            "note": f"Ignored because requested market={normalized_market}",
        }
    if total_invalid_ohlcv:
        top_warnings.append(f"invalid_ohlcv_file:{total_invalid_ohlcv}")
        warnings_detail["invalid_ohlcv_file"] = {
            "severity": "warning",
            "count": total_invalid_ohlcv,
            "samples": [
                sample
                for f in files
                for sample in (f.get("warningSamples") or {}).get("invalid_ohlcv_file", [])
            ][:10],
            "nextAction": "Delete invalid OHLCV files and fix the collector symbol guard.",
        }

    # 3) rec_csv 자체 warnings (date_column_missing 제외 — 이미 warningsDetail에 있음)
    for info in rec_csv_inspect.get("info", []):
        if info == "recommendation_previous_close_basis":
            warnings_detail["recommendation_previous_close_basis"] = {
                "severity": "info",
                "status": rec_csv_inspect.get("status"),
                "latestDataDate": rec_csv_inspect.get("latestDataDate"),
                "priceSession": price_session_str,
                "note": "US recommendation CSV is based on the previous close during an open live session.",
                "nextAction": "Observe intraday with live quote snapshot or regenerate recommendations after close.",
            }
    for w in rec_csv_inspect.get("warnings", []):
        if "date_column_missing" not in w:
            top_warnings.append(w)

    # ── combined 판정 & after_close 처리 ─────────────────────────────────────
    if is_after_close or is_review:
        combined = data_status_combined
        # 장마감/복기 모드: 실시간 가격 없음은 info 레벨 — killSwitch 사유 아님
        if any(f.get("status") == "NO_DATA" for f in realtime_files):
            warnings_detail["realtime_price_missing_after_close"] = {
                "severity": "info",
                "priceSession": price_session_str,
                "priceDataStatus": "AFTER_CLOSE",
                "note": (
                    "Realtime price snapshot is not required after close "
                    "when OHLCV/recommendation data is available"
                ),
            }
        if combined == "NO_DATA" and rec_has_data:
            combined = "PARTIAL"
        if is_review and combined in {"NO_DATA", "ERROR"}:
            combined = "PARTIAL" if rec_has_data else combined
    else:
        combined = session.worst_status([data_status_combined, realtime_status])
        if combined == "NO_DATA" and rec_has_data:
            combined = "PARTIAL_PRICE"
        if any(f.get("status") == "NO_DATA" for f in realtime_files):
            top_warnings.append("realtime_price_missing")
            warnings_detail["us_realtime_price_missing" if normalized_market == "us" else "realtime_price_missing"] = {
                "severity": "warning",
                "priceSession": price_session_str,
                "priceDataStatus": "NO_DATA",
                "missingFiles": [
                    str(f.get("path") or "")
                    for f in realtime_files
                    if f.get("status") == "NO_DATA"
                ],
                "nextAction": (
                    "Run US intraday/current price collector"
                    if normalized_market == "us"
                    else "Run intraday/current price collector"
                ),
            }

    # ── killSwitch 결정 ───────────────────────────────────────────────────────
    # 추천 데이터가 있으면 killSwitch=False
    if rec_has_data:
        kill_switch = combined in {"ERROR"}
    elif is_review:
        kill_switch = False
    else:
        kill_switch = session.is_kill_status(combined)

    display_combined = "PARTIAL" if combined == "PARTIAL_PRICE" else combined

    # mixedMarketCount — OHLCV 폴더 파일 존재가 아닌, CSV 내부 혼합만 카운트
    mixed_market_count = rec_csv_inspect.get("mixedMarketCount", 0)

    # quick 모드: candidateCount는 CSV rowCount로 대체
    candidate_count = len(rows) if not quick else rec_csv_inspect.get("rowCount", 0)

    # OHLCV 샘플 검사 수 집계
    ohlcv_checked = next(
        (f.get("checkedFileCount", f.get("fileCount", 0)) for f in files if f.get("role") == "price_priority_3"),
        0,
    )
    ohlcv_total = next(
        (f.get("fileCount", 0) for f in files if f.get("role") == "price_priority_3"),
        0,
    )

    root_causes: list[str] = []
    next_actions: list[str] = []

    def add_gap(key: str, action: str = "") -> None:
        if key not in root_causes:
            root_causes.append(key)
        if action and action not in next_actions:
            next_actions.append(action)

    invalid_detail = warnings_detail.get("invalid_ohlcv_file") or {}
    if invalid_detail:
        add_gap("invalid_ohlcv_file", str(invalid_detail.get("nextAction") or "Delete invalid OHLCV files."))

    realtime_key = "us_realtime_price_missing" if normalized_market == "us" else "realtime_price_missing"
    realtime_detail = warnings_detail.get(realtime_key) or {}
    if realtime_detail:
        add_gap(realtime_key, str(realtime_detail.get("nextAction") or "Run intraday/current price collector."))

    previous_close_detail = warnings_detail.get("recommendation_previous_close_basis") or {}
    if previous_close_detail:
        add_gap(
            "recommendation_previous_close_basis",
            str(previous_close_detail.get("nextAction") or "Observe intraday or regenerate recommendations after close."),
        )

    if not root_causes and display_combined not in {"NORMAL", "OK", "GOOD"}:
        if is_review or is_after_close:
            add_gap(
                f"{normalized_market}_closed_session_review_basis",
                "No action required unless live-session data is expected.",
            )
        else:
            add_gap(f"data_status_{str(display_combined).lower()}")

    summary_parts: list[str] = []
    if root_causes:
        summary_parts.append(f"{normalized_market.upper()} dataStatus={display_combined}: {', '.join(root_causes)}")
    else:
        summary_parts.append(f"{normalized_market.upper()} dataStatus={display_combined}")
    if price_session_str:
        summary_parts.append(f"session={price_session_str}")
    if rec_csv_inspect.get("latestDataDate"):
        summary_parts.append(f"recommendationDate={rec_csv_inspect.get('latestDataDate')}")

    return {
        "status": "OK",
        "market": normalized_market,
        "priceSession": state["priceSession"],
        "session": state,
        "dataStatus": display_combined,
        "priceDataStatus": price_status if (rows or quick) else ("NO_REALTIME" if is_after_close else "NO_DATA"),
        "killSwitch": kill_switch,
        "reviewMode": is_review,
        "afterCloseReviewAvailable": is_after_close and rec_has_data,
        "message": "시장 휴장일 - 지난 운용 복기 모드" if is_review else "데이터 상태 점검 완료",
        "files": files,
        "candidateCount": candidate_count,
        "updatedAt": datetime.now(session.KST).isoformat(),
        "latestFileModifiedAt": rec_csv_inspect.get("latestFileModifiedAt"),
        "latestDataDate": rec_csv_inspect.get("latestDataDate"),
        "rowCount": rec_csv_inspect.get("rowCount", 0),
        "validSymbolCount": rec_csv_inspect.get("validSymbolCount", 0),
        "duplicatedSymbolCount": rec_csv_inspect.get("duplicatedSymbolCount", 0),
        "missingRateByColumn": rec_csv_inspect.get("missingRateByColumn", {}),
        "invalidMarketCount": rec_csv_inspect.get("invalidMarketCount", 0),
        "mixedMarketCount": mixed_market_count,
        "emptyResult": rec_csv_inspect.get("emptyResult", False),
        "recommendationStatus": rec_csv_inspect.get("status"),
        "recommendationBasisStatus": rec_csv_inspect.get("basisStatus", ""),
        "recommendationBasisLabel": rec_csv_inspect.get("basisLabel", ""),
        "rootCauses": root_causes,
        "nextActions": next_actions,
        "summary": " / ".join(summary_parts),
        "staleReason": next((w for w in top_warnings if "stale" in w.lower()), None),
        "warnings": top_warnings,
        "warningsDetail": warnings_detail,
        "checkedFiles": [f.get("path") for f in files if f.get("path")],
        # 스캔 범위 정보
        "fullScan": not quick,
        "checkedFilesSample": ohlcv_checked,
        "totalOhlcvFiles": ohlcv_total,
    }


def admin_pipeline(market: str = "kr") -> dict[str, Any]:
    normalized_market = normalize_market(market)
    quality = data_quality(normalized_market)
    status = quality.get("dataStatus", "NO_DATA")
    files = quality.get("files", [])

    def step(name: str, ok: bool, details: str) -> dict[str, Any]:
        return {
            "step": name,
            "status": "OK" if ok else "FAILED",
            "updated_at": datetime.now(session.KST).strftime("%H:%M:%S"),
            "details": details,
        }

    latest_data_date = quality.get("latestDataDate", "")
    row_count = quality.get("rowCount", 0)

    def read_json_status(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)[:160], "file": str(path)}

    def latest_file_date(patterns: list[str]) -> str | None:
        matches: list[Path] = []
        for pattern in patterns:
            matches.extend(_repo_path(*pattern.split("/")).parent.glob(Path(pattern).name))
        newest = max((path.stat().st_mtime for path in matches if path.exists()), default=0)
        return datetime.fromtimestamp(newest, session.KST).date().isoformat() if newest else None

    def latest_ohlcv_date() -> str | None:
        latest: str | None = None
        for path in _repo_path("data", "market", "ohlcv").glob(f"{normalized_market}_*_daily.csv"):
            rows = _read_csv_safe(path)
            if not rows:
                continue
            day = _parse_date_str(rows[-1].get("date") or rows[-1].get("Date"))
            if day and (latest is None or day > latest):
                latest = day
        return latest

    collector_path = _repo_path("reports", "local_collector_status.json")
    collector = read_json_status(collector_path)
    collector_pushed = collector.get("pushed") if collector else None
    collector_error = collector.get("lastError") or collector.get("error") or collector.get("stderr")
    if not collector:
        local_collector_status = "UNKNOWN"
        local_push_reason = "local_status_only"
    elif collector_pushed is True:
        local_collector_status = "PUSHED"
        local_push_reason = "pushed"
    elif collector_error:
        local_collector_status = "FAILED"
        local_push_reason = "git_push_failed" if "git" in str(collector_error).lower() else "local_collector_ran_but_not_pushed"
    elif collector_pushed is False:
        local_collector_status = "NOT_PUSHED"
        local_push_reason = collector.get("pushReason") or "no_changes_to_push"
    else:
        local_collector_status = "UNKNOWN"
        local_push_reason = "unknown"

    github_status_payload = {}
    for rel in ("reports/kis_live_refresh_status.json", "reports/auto_sync_status.json"):
        github_status_payload = read_json_status(_repo_path(*rel.split("/")))
        if github_status_payload:
            break
    github_status = github_status_payload.get("status") or "UNKNOWN"
    github_last_update = github_status_payload.get("updatedAt") or github_status_payload.get("timestamp")
    active_gaps = list(quality.get("rootCauses") or quality.get("warnings") or [])
    next_actions = list(quality.get("nextActions") or [])
    if github_status == "UNKNOWN":
        next_actions.append("GitHub status unavailable")
    if local_collector_status in {"UNKNOWN", "FAILED", "NOT_PUSHED"}:
        next_actions.append(f"local collector: {local_push_reason}")

    recommendation_latest_date = latest_data_date or latest_file_date([f"reports/mone_v36_final_recommendations_{normalized_market}_*.csv"])
    snapshot_latest_date = latest_file_date([
        f"reports/kis_current_price_{normalized_market}.csv",
        f"reports/intraday_quote_snapshot_{normalized_market}.csv",
        f"data/current_prices_{normalized_market}.csv",
        f"cache/quotes_cache.json",
    ])
    ohlcv_latest_date = latest_ohlcv_date()
    render_latest_file_date = latest_file_date([
        f"reports/mone_v36_final_recommendations_{normalized_market}_*.csv",
        f"reports/mone_v36_final_trade_validation_{normalized_market}_*.csv",
        "reports/local_collector_status.json",
    ])

    steps = [
        step("GitHub Actions 실행 확인", any(f.get("status") != "NO_DATA" for f in files), "원천 파일 존재 여부 확인"),
        step("CSV/JSON 생성 확인", any(f.get("path") for f in files), "백엔드가 읽을 수 있는 파일 경로 확인"),
        step("최신성 검증", status not in {"STALE", "ERROR"}, f"현재 등급: {status} / 내부 날짜: {latest_data_date or '미확인'}"),
        step("추천 결과 존재", row_count > 0, f"추천 row {row_count}개 (EMPTY_RESULT={quality.get('emptyResult')})"),
        step("FastAPI 로딩 확인", quality.get("candidateCount", 0) > 0, f"추천 후보 {quality.get('candidateCount', 0)}개"),
        step("프론트 킬스위치 매핑", True, f"killSwitch={quality.get('killSwitch')} reviewMode={quality.get('reviewMode')}"),
    ]

    return {
        "status": "OK",
        "market": normalized_market,
        "githubActionsStatus": github_status,
        "githubActionsLastUpdate": github_last_update,
        "localCollectorStatus": local_collector_status,
        "localCollectorLastUpdate": collector.get("completedAt") or collector.get("updatedAt") or collector.get("startedAt"),
        "localCollectorPushed": collector_pushed,
        "localCollectorLastError": collector_error,
        "localCollectorPushReason": local_push_reason,
        "renderLatestFileDate": render_latest_file_date,
        "recommendationLatestDate": recommendation_latest_date,
        "snapshotLatestDate": snapshot_latest_date,
        "ohlcvLatestDate": ohlcv_latest_date,
        "currentPriceSourceStatus": quality.get("priceDataStatus"),
        "recommendationStatus": quality.get("recommendationStatus"),
        "dataStatus": quality.get("dataStatus"),
        "activeGaps": active_gaps,
        "nextActions": list(dict.fromkeys(next_actions)),
        "checkedFiles": quality.get("checkedFiles") or [f.get("path") for f in files if f.get("path")],
        "updatedAt": datetime.now(session.KST).isoformat(),
        "summary": {
            "market": normalized_market,
            "githubActionsStatus": github_status,
            "localCollectorStatus": local_collector_status,
            "localCollectorPushed": collector_pushed,
            "recommendationLatestDate": recommendation_latest_date,
            "ohlcvLatestDate": ohlcv_latest_date,
            "dataStatus": quality.get("dataStatus"),
            "activeGaps": active_gaps,
            "nextActions": list(dict.fromkeys(next_actions)),
        },
        "dataQuality": quality,
        "pipeline": steps,
        "files": files,
        "generatedAt": datetime.now(session.KST).isoformat(),
    }
