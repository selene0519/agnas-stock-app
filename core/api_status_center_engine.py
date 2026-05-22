"""v35 data/API status center.

Summarises whether key local reports exist, have rows, and are stale. This helps
distinguish real-time data from fallback/stored report data.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

REPORT_DIR = Path("reports")
OUT_CSV = REPORT_DIR / "api_data_status_center.csv"
OUT_JSON = REPORT_DIR / "api_data_status_center.json"

KEY_FILES: list[tuple[str, Path, int]] = [
    ("현재가", REPORT_DIR / "intraday_realtime_snapshot.csv", 30),
    ("현재가 요약", REPORT_DIR / "intraday_realtime_summary.csv", 60),
    ("호가", REPORT_DIR / "intraday_orderbook_snapshot.csv", 30),
    ("호가 요약", REPORT_DIR / "intraday_orderbook_summary.csv", 60),
    ("수급", REPORT_DIR / "intraday_flow_snapshot.csv", 30),
    ("업종 흐름", REPORT_DIR / "intraday_sector_flow_report.csv", 60),
    ("장중 수신률", REPORT_DIR / "intraday_data_coverage_diagnosis.csv", 60),
    ("뉴스 캐시", Path("data/news/news_cache.csv"), 240),
    ("포트폴리오 NAV", Path("data/portfolio_daily_nav.csv"), 1440),
    ("benchmark daily", Path("data/benchmark_daily.csv"), 1440),
    ("백테스트 beta", REPORT_DIR / "backtest_beta_summary.csv", 1440),
    ("예측 학습 요약", REPORT_DIR / "prediction_learning_summary.csv", 1440),
    ("리스크 우선 후보", REPORT_DIR / "risk_priority_candidates.csv", 240),
]


def _rows(path: Path) -> int:
    if not path.exists() or path.stat().st_size <= 0:
        return 0
    if path.suffix.lower() == ".json":
        return 1
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return int(len(pd.read_csv(path, encoding=enc, low_memory=False)))
        except Exception:
            continue
    return 0


def _mtime(path: Path) -> tuple[str, float | None]:
    if not path.exists():
        return "", None
    ts = path.stat().st_mtime
    dt = datetime.fromtimestamp(ts)
    age_min = (datetime.now().timestamp() - ts) / 60
    return dt.strftime("%Y-%m-%d %H:%M:%S"), round(age_min, 1)


def save_api_status_center() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for label, path, stale_min in KEY_FILES:
        exists = path.exists() and path.stat().st_size > 0
        modified, age_min = _mtime(path)
        nrows = _rows(path) if exists else 0
        if not exists:
            status = "없음"
        elif nrows <= 0:
            status = "비어 있음"
        elif age_min is not None and age_min > stale_min:
            status = "오래됨"
        else:
            status = "정상"
        rows.append({
            "항목": label,
            "상태": status,
            "rows": nrows,
            "수정시각": modified,
            "경과분": age_min if age_min is not None else "",
            "오래됨기준분": stale_min,
            "파일": str(path),
        })
    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    counts = df["상태"].value_counts().to_dict() if not df.empty else {}
    result = {
        "status": "OK",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": int(len(df)),
        "counts": counts,
        "csv": str(OUT_CSV),
        "note": "오래됨은 API 오류가 아니라 저장 리포트 기준 데이터일 가능성을 뜻합니다.",
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def read_api_status_center() -> dict[str, Any]:
    if not OUT_JSON.exists():
        return save_api_status_center()
    try:
        return json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return save_api_status_center()


if __name__ == "__main__":
    print(json.dumps(save_api_status_center(), ensure_ascii=False, indent=2, default=str))
