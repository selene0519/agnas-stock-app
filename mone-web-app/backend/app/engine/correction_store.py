"""
correction_store.py — self_correction_params JSON 저장/로드/버전 관리 (7-D 지원)

저장 경로: reports/self_correction_params.json
백업 경로: reports/self_correction_params_v{N}.json
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _reports_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "reports"


def _params_path() -> Path:
    return _reports_dir() / "self_correction_params.json"


def load_params() -> dict[str, Any]:
    """현재 보정 파라미터 로드. 없으면 빈 구조 반환."""
    path = _params_path()
    if not path.exists():
        return {"version": 0, "generatedAt": None, "markets": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 0, "generatedAt": None, "markets": {}}


def load_correction(market: str, mode: str, horizon: str) -> dict[str, Any]:
    """market/mode/horizon 조합에 해당하는 보정값 반환. 없으면 기본값."""
    params = load_params()
    key = f"{market}_{mode}_{horizon}"
    return params.get("markets", {}).get(key, _default_correction(market, mode, horizon))


def save_params(new_params: dict[str, Any]) -> Path:
    """
    새 보정 파라미터를 저장한다.
    기존 파일은 버전 번호를 붙여 백업한다.
    """
    reports = _reports_dir()
    reports.mkdir(parents=True, exist_ok=True)
    path = _params_path()

    # 기존 파일 백업
    if path.exists():
        old = load_params()
        old_ver = int(old.get("version", 0))
        backup = reports / f"self_correction_params_v{old_ver}.json"
        shutil.copy2(path, backup)

    new_params["savedAt"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(new_params, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _default_correction(market: str, mode: str, horizon: str) -> dict[str, Any]:
    """보정값이 없을 때 사용하는 안전한 기본값 (보정 없음)."""
    return {
        "market": market,
        "mode": mode,
        "horizon": horizon,
        "sampleCount": 0,
        "confidence": 0.0,
        "weightAdjustments": {},
        "priceAdjustments": {
            "entryAggressiveness": 0.0,
            "targetMultiplier": 0.0,
            "stopAtrMultiplier": 0.0,
        },
        "filterAdjustments": {
            "maxDistanceToEntryPct": 0.0,
            "minRiskRewardRatio": 0.0,
        },
        "topFailureReasons": [],
        "appliedAt": None,
    }


def list_versions() -> list[dict[str, Any]]:
    """저장된 모든 버전 목록 반환."""
    reports = _reports_dir()
    versions = []
    for p in sorted(reports.glob("self_correction_params_v*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            versions.append({
                "version": data.get("version"),
                "generatedAt": data.get("generatedAt"),
                "savedAt": data.get("savedAt"),
                "file": p.name,
            })
        except Exception:
            pass
    current_path = _params_path()
    if current_path.exists():
        try:
            cur = json.loads(current_path.read_text(encoding="utf-8"))
            versions.append({
                "version": cur.get("version"),
                "generatedAt": cur.get("generatedAt"),
                "savedAt": cur.get("savedAt"),
                "file": "self_correction_params.json",
                "current": True,
            })
        except Exception:
            pass
    return sorted(versions, key=lambda x: x.get("version") or 0)
