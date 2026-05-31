
from __future__ import annotations

import csv
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from fastapi.routing import APIRoute


def _app_root() -> Path:
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        if parent.name == "mone-web-app" and (parent / "backend").exists():
            return parent
    for parent in [here.parent, *here.parents]:
        if (parent / "backend").exists() and (parent / "frontend").exists():
            return parent
    return here.parents[3]


def _roots() -> List[Path]:
    app = _app_root()
    candidates = [app, app / "data", app / "reports", app.parent, app.parent / "data", app.parent / "reports"]
    out: List[Path] = []
    for p in candidates:
        try:
            if p.exists() and p not in out:
                out.append(p)
        except Exception:
            pass
    return out


def _safe_rel(path: Path) -> str:
    for root in _roots():
        try:
            return str(path.relative_to(root))
        except Exception:
            pass
    return str(path)


def _count_csv(path: Path, max_rows: int = 20000) -> int:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                reader = csv.reader(f)
                next(reader, None)
                count = 0
                for count, _ in enumerate(reader, start=1):
                    if count >= max_rows:
                        break
                return count
        except Exception:
            continue
    return 0


def _find_files(patterns: List[str], max_files: int = 200) -> List[Path]:
    found: List[Path] = []
    for root in _roots():
        for pattern in patterns:
            try:
                for p in root.glob(pattern):
                    if len(found) >= max_files:
                        return found
                    if p.exists() and p.is_file() and p.stat().st_size > 0 and p not in found:
                        found.append(p)
            except Exception:
                continue
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[:max_files]


def _item(name: str, patterns: List[str]) -> Dict[str, Any]:
    try:
        paths = _find_files(patterns)
        newest = paths[0] if paths else None
        records = 0
        for p in paths[:5]:
            records += _count_csv(p) if p.suffix.lower() == ".csv" else 1
        return {
            "name": name,
            "status": "OK" if paths else "NO_DATA",
            "path": _safe_rel(newest) if newest else "",
            "records": records,
            "modified": datetime.fromtimestamp(newest.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S") if newest else "",
            "fileCount": len(paths),
        }
    except Exception as exc:
        return {"name": name, "status": "ERROR", "path": "", "records": 0, "modified": "", "fileCount": 0, "error": f"{type(exc).__name__}: {exc}"}


def _github_payload() -> Dict[str, Any]:
    app = _app_root()
    repo = app if (app / ".git").exists() else app.parent
    is_repo = (repo / ".git").exists()
    branch = remote = ""
    if is_repo:
        try:
            branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            pass
        try:
            lines = subprocess.check_output(["git", "remote", "-v"], cwd=repo, text=True, stderr=subprocess.DEVNULL).strip().splitlines()
            remote = lines[0] if lines else ""
        except Exception:
            pass
    return {"status": "OK", "isGitRepo": is_repo, "branch": branch, "remote": remote, "root": str(repo)}


def _audit_payload() -> Dict[str, Any]:
    specs = {
        "candidateKR": ["candidate_universe_kr.csv", "reports/*candidate*kr*.csv", "data/**/*candidate*kr*.csv"],
        "candidateUS": ["candidate_universe_us.csv", "reports/*candidate*us*.csv", "data/**/*candidate*us*.csv"],
        "watchlist": ["daily_watch_selection.json", "*watch*.csv", "data/**/*watch*.csv", "reports/**/*watch*.csv"],
        "ohlcv": ["data/market/ohlcv/*.csv", "data/**/*ohlcv*.csv", "reports/**/*ohlcv*.csv"],
        "companyKR": ["reports/*company*kr*.csv", "reports/*financial*kr*.csv", "reports/*statement*kr*.csv", "data/**/*financial*kr*.csv"],
        "companyUS": ["reports/*company*us*.csv", "reports/*financial*us*.csv", "reports/*statement*us*.csv", "data/**/*financial*us*.csv"],
        "virtual": ["data/history/*virtual*.csv", "data/history/*trading*.csv", "paper_trading*.csv", "reports/*backtest*.csv", "reports/*trade*.csv"],
        "predictions": ["predictions.csv", "data/history/prediction*.csv", "reports/*prediction*.csv"],
        "news": ["reports/*news*.csv", "data/**/*news*.csv"],
        "disclosures": ["data/disclosures/*.csv", "reports/*disclosure*.csv", "data/**/*disclosure*.csv"],
    }
    return {
        "status": "OK",
        "root": str(_app_root()),
        "searchRoots": [str(x) for x in _roots()],
        "items": [_item(name, patterns) for name, patterns in specs.items()],
        "github": _github_payload(),
    }


def register_mone_v71_audit_final(app):
    replace_paths = {"/api/data/audit", "/api/health/github"}
    app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and getattr(r, "path", "") in replace_paths)]

    @app.get("/api/data/audit")
    def data_audit():
        try:
            return _audit_payload()
        except Exception as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "root": str(_app_root()), "searchRoots": [str(x) for x in _roots()], "items": []}

    @app.get("/api/health/github")
    def health_github():
        try:
            return _github_payload()
        except Exception as exc:
            return {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}", "isGitRepo": False, "branch": "", "remote": "", "root": str(_app_root())}
