"""v36 cloud auto-accumulation readiness checker.

The app cannot keep collecting while a powered-off notebook is offline. This
checker prepares the repository for GitHub Actions/VPS style scheduled runs and
reports what still needs to be configured by the user.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

REPORT_DIR = Path("reports")
OUT_JSON = REPORT_DIR / "cloud_readiness_status.json"
OUT_CSV = REPORT_DIR / "cloud_readiness_checklist.csv"
REQUIRED_FILES = [
    Path("run_cloud_accumulator.py"),
    Path("requirements.txt"),
    Path(".github/workflows/nexora-auto-accumulator.yml"),
    Path("CLOUD_AUTO_ACCUMULATION_GUIDE.md"),
]
OPTIONAL_SECRETS = ["FINNHUB_API_KEY", "KIS_APP_KEY", "KIS_APP_SECRET", "KIS_ACCOUNT_NO"]


def save_cloud_readiness_status() -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for path in REQUIRED_FILES:
        rows.append({"구분": "필수파일", "항목": str(path), "상태": "있음" if path.exists() else "없음", "비고": ""})
    for key in OPTIONAL_SECRETS:
        rows.append({"구분": "환경변수/Secret", "항목": key, "상태": "설정됨" if os.environ.get(key) else "사용자 설정 필요", "비고": "GitHub Actions 또는 VPS 환경에서 설정"})
    try:
        import pandas as pd
        pd.DataFrame(rows).to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    except Exception:
        pass
    missing_files = [str(p) for p in REQUIRED_FILES if not p.exists()]
    missing_secret_count = sum(1 for key in OPTIONAL_SECRETS if not os.environ.get(key))
    status = "READY_LOCAL" if not missing_files else "MISSING_FILES"
    if not missing_files and missing_secret_count:
        status = "READY_AFTER_SECRETS"
    result = {
        "status": status,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "missing_files": missing_files,
        "missing_secret_count": missing_secret_count,
        "checklist_csv": str(OUT_CSV),
        "guide": "CLOUD_AUTO_ACCUMULATION_GUIDE.md",
        "note": "노트북이 꺼져도 자동누적하려면 이 폴더를 GitHub/VPS에 올리고 API 키를 Secrets로 설정해야 합니다.",
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return result


def read_cloud_readiness_status() -> dict[str, Any]:
    if not OUT_JSON.exists():
        return save_cloud_readiness_status()
    try:
        return json.loads(OUT_JSON.read_text(encoding="utf-8"))
    except Exception:
        return save_cloud_readiness_status()


if __name__ == "__main__":
    print(json.dumps(save_cloud_readiness_status(), ensure_ascii=False, indent=2, default=str))
