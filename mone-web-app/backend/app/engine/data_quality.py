from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from app.engine import session
from app.engine.symbols import normalize_market
from app.services import data_loader as data
from app.services import final_engine

# 날짜 컬럼 후보 (우선순위순)
_DATE_COLS = [
    "generatedAt", "recommendationDate", "asOfDate", "createdAt",
    "date", "tradeDate", "priceDate", "updatedAt",
]

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

    # 최신 내부 날짜
    latest_date: str | None = None
    for col in _DATE_COLS:
        dates = [_parse_date_str(r.get(col)) for r in rows]
        dates = [d for d in dates if d]
        if dates:
            latest_date = max(dates)
            break

    # STALE 여부: 내부 날짜 기준
    stale_reason: str | None = None
    today_str = datetime.now(session.KST).strftime("%Y-%m-%d")
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

    # 시장 구분 검사
    invalid_market_count = 0
    mixed_market_count = 0
    if any("market" in r for r in rows[:1]):
        mkt_values = [str(r.get("market", "")).strip().lower() for r in rows]
        expected = normalize_market(market).lower()
        invalid_market_count = sum(1 for m in mkt_values if m and m not in {"kr", "us"})
        mixed_market_count = sum(1 for m in mkt_values if m and m != expected)

    # 종합 상태
    warnings: list[str] = []
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
    }


def _candidate_files(market: str) -> list[dict[str, Any]]:
    normalized_market = normalize_market(market)
    return [
        {
            "name": "KIS 현재가 snapshot",
            "role": "price_priority_1",
            "path": _first_existing(
                [
                    _repo_path("data", "market", "snapshots", f"{normalized_market}_kis_current.json"),
                    _repo_path("data", "market", "quotes", f"{normalized_market}_latest_quotes.csv"),
                    _repo_path("reports", f"kis_current_snapshot_{normalized_market}.csv"),
                ]
            ),
        },
        {
            "name": "Intraday snapshot",
            "role": "price_priority_2",
            "path": _first_existing(
                [
                    _repo_path("data", "market", "intraday", f"{normalized_market}_intraday_snapshot.csv"),
                    _repo_path("reports", f"{normalized_market}_intraday_report.csv"),
                ]
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


def _status_for_path(path: Path | None, market: str, role: str) -> dict[str, Any]:
    if path is None:
        return {"status": "NO_DATA", "reason": "경로 없음", "path": None, "role": role}
    if path.is_dir():
        files = [item for item in path.glob("*.csv") if item.is_file()]
        if not files:
            return {"status": "NO_DATA", "reason": "CSV 없음", "path": str(path), "role": role}
        newest = max(files, key=lambda item: item.stat().st_mtime)
        result = session.evaluate_file_status(newest, market, required_today=role in {"price_priority_1", "price_priority_2"})
        result["path"] = str(newest)
        result["role"] = role
        result["fileCount"] = len(files)
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

    # 파일은 오늘인데 내부 날짜가 오래됐으면 STALE 상향
    combined_status = mtime_result["status"]
    if deep.get("deepStatus") == "STALE" and combined_status == "NORMAL":
        combined_status = "STALE"
    elif deep.get("emptyResult"):
        combined_status = "EMPTY_RESULT"
    elif deep.get("deepStatus") in {"PARTIAL", "ERROR"}:
        combined_status = deep["deepStatus"]

    return {
        "status": combined_status,
        "latestFileModifiedAt": mtime_result.get("mtimeDate"),
        "latestDataDate": deep.get("latestDataDate"),
        "rowCount": deep.get("rowCount", 0),
        "validSymbolCount": deep.get("validSymbolCount", 0),
        "duplicatedSymbolCount": deep.get("duplicatedSymbolCount", 0),
        "missingRateByColumn": deep.get("missingRateByColumn", {}),
        "invalidMarketCount": deep.get("invalidMarketCount", 0),
        "mixedMarketCount": deep.get("mixedMarketCount", 0),
        "emptyResult": deep.get("emptyResult", False),
        "warnings": deep.get("warnings", []),
        "path": str(csv_path),
        "role": "recommendation_csv",
    }


def data_quality(market: str = "kr") -> dict[str, Any]:
    normalized_market = normalize_market(market)
    state = session.get_price_session(normalized_market)

    files = []
    for item in _candidate_files(normalized_market):
        status = _status_for_path(item["path"], normalized_market, item["role"])
        files.append({**item, **status, "path": status.get("path") or (str(item["path"]) if item["path"] else None)})

    # 추천 CSV 상세 검사 (기존 engine 호출과 병행)
    rec_csv_inspect = _recommendation_csv_inspect(normalized_market)
    files.append(rec_csv_inspect)

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
        files.append({"name": "Recommendation engine", "role": "engine", "path": None, "status": "ERROR", "reason": str(exc)})

    file_status = session.worst_status(item.get("status") for item in files)
    combined = session.worst_status([file_status, recommendation_status])

    if state.get("isReviewMode"):
        kill_switch = False
        if combined in {"NO_DATA", "ERROR"}:
            combined = "PARTIAL" if rows else combined
    else:
        kill_switch = session.is_kill_status(combined)

    return {
        # 기존 필드 유지
        "status": "OK",
        "market": normalized_market,
        "priceSession": state["priceSession"],
        "session": state,
        "dataStatus": combined,
        "priceDataStatus": price_status,
        "killSwitch": kill_switch,
        "reviewMode": bool(state.get("isReviewMode")),
        "message": "시장 휴장일 - 지난 운용 복기 모드" if state.get("isReviewMode") else "데이터 상태 점검 완료",
        "files": files,
        "candidateCount": len(rows),
        "updatedAt": datetime.now(session.KST).isoformat(),
        # 신규 필드
        "latestFileModifiedAt": rec_csv_inspect.get("latestFileModifiedAt"),
        "latestDataDate": rec_csv_inspect.get("latestDataDate"),
        "rowCount": rec_csv_inspect.get("rowCount", 0),
        "validSymbolCount": rec_csv_inspect.get("validSymbolCount", 0),
        "duplicatedSymbolCount": rec_csv_inspect.get("duplicatedSymbolCount", 0),
        "missingRateByColumn": rec_csv_inspect.get("missingRateByColumn", {}),
        "invalidMarketCount": rec_csv_inspect.get("invalidMarketCount", 0),
        "mixedMarketCount": rec_csv_inspect.get("mixedMarketCount", 0),
        "emptyResult": rec_csv_inspect.get("emptyResult", False),
        "staleReason": rec_csv_inspect.get("warnings", [None])[0] if rec_csv_inspect.get("warnings") else None,
        "warnings": rec_csv_inspect.get("warnings", []),
        "checkedFiles": [f.get("path") for f in files if f.get("path")],
    }


def admin_pipeline(market: str = "kr") -> dict[str, Any]:
    quality = data_quality(market)
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
        "market": normalize_market(market),
        "dataQuality": quality,
        "pipeline": steps,
        "files": files,
        "generatedAt": datetime.now(session.KST).isoformat(),
    }
