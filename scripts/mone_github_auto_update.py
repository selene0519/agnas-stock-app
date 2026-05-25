from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
HISTORY = ROOT / "data" / "history"
BACKUPS = ROOT / "backups"
LOGS = ROOT / "logs"
VERSION = "v93"
ALIAS_VERSION = "v92"  # keep existing app pages working while v93 is adopted

MARKETS = {"kr": "한국주식", "us": "미국주식"}


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_dirs() -> None:
    for p in (REPORTS, HISTORY, BACKUPS, LOGS):
        p.mkdir(parents=True, exist_ok=True)
        keep = p / ".gitkeep"
        if not keep.exists():
            try:
                keep.write_text("", encoding="utf-8")
            except Exception:
                pass


def read_csv_safe(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc).fillna("")
        except Exception:
            continue
    return pd.DataFrame()


def write_csv_safe(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def row_count(path: Path) -> int:
    try:
        return int(len(read_csv_safe(path)))
    except Exception:
        return 0


def latest_existing(patterns: list[str]) -> Path | None:
    candidates: list[Path] = []
    for pat in patterns:
        candidates.extend(REPORTS.glob(pat))
    candidates = [p for p in candidates if p.exists() and p.stat().st_size > 0 and row_count(p) > 0]
    if not candidates:
        return None

    def key(p: Path) -> tuple[int, float]:
        m = re.search(r"v(\d+)_", p.name)
        ver = int(m.group(1)) if m else 0
        return ver, p.stat().st_mtime

    return sorted(candidates, key=key, reverse=True)[0]


def copy_latest_to_target(src: Path | None, target_name: str, aliases: bool = True) -> dict[str, Any]:
    out = {"target": target_name, "source": str(src.name) if src else "", "rows": 0, "status": "MISSING_SOURCE"}
    target = REPORTS / target_name
    if src is None:
        return out
    try:
        df = read_csv_safe(src)
        if df.empty:
            return out
        write_csv_safe(df, target)
        out.update({"rows": len(df), "status": "COPIED"})
        if aliases and target_name.startswith(f"{VERSION}_"):
            alias_name = target_name.replace(f"{VERSION}_", f"{ALIAS_VERSION}_", 1)
            alias = REPORTS / alias_name
            # Keep v92 alias fresh because current UI may still read v92.
            write_csv_safe(df, alias)
        return out
    except Exception as exc:
        out["status"] = f"ERROR:{type(exc).__name__}:{exc}"
        return out


def run_base_update() -> dict[str, Any]:
    """Run the strongest available local update script. Never fail the whole action."""
    candidates = [
        [sys.executable, "run_v92_daily_update.py"],
        [sys.executable, "run_v91_daily_update.py"],
        [sys.executable, "run_v85_daily_update.py"],
        [sys.executable, "run_cloud_accumulator.py"],
        [sys.executable, "app.py", "--runner", "auto"],
    ]
    for cmd in candidates:
        if not (ROOT / cmd[1]).exists():
            continue
        try:
            proc = subprocess.run(
                cmd,
                cwd=ROOT,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=25 * 60,
                env=os.environ.copy(),
            )
            (LOGS / f"{VERSION}_base_update.log").write_text(proc.stdout[-20000:], encoding="utf-8")
            return {"command": " ".join(cmd), "returncode": proc.returncode, "status": "OK" if proc.returncode == 0 else "NONZERO"}
        except Exception as exc:
            (LOGS / f"{VERSION}_base_update_error.log").write_text(str(exc), encoding="utf-8")
            return {"command": " ".join(cmd), "returncode": -1, "status": f"ERROR:{type(exc).__name__}:{exc}"}
    return {"command": "", "returncode": 0, "status": "SKIPPED_NO_UPDATE_SCRIPT"}


def get_col(row: pd.Series | dict[str, Any], names: list[str], default: str = "") -> str:
    for n in names:
        try:
            v = row.get(n, "")  # type: ignore[attr-defined]
        except Exception:
            v = ""
        if str(v).strip() and str(v).strip().lower() not in {"nan", "none"}:
            return str(v).strip()
    return default


def to_float(v: Any, default: float = 0.0) -> float:
    try:
        text = str(v).replace(",", "").replace("%", "").replace("원", "").replace("$", "").strip()
        if not text or text in {"-", "nan", "None"}:
            return default
        return float(text)
    except Exception:
        return default


def build_confidence_cards(slug: str) -> pd.DataFrame:
    snap = read_csv_safe(REPORTS / f"{VERSION}_symbol_snapshot_{slug}.csv")
    if snap.empty:
        snap = read_csv_safe(REPORTS / f"{ALIAS_VERSION}_symbol_snapshot_{slug}.csv")
    company = read_csv_safe(REPORTS / f"{VERSION}_company_integrated_{slug}.csv")
    if company.empty:
        company = read_csv_safe(REPORTS / f"{ALIAS_VERSION}_company_integrated_{slug}.csv")
    summary = read_csv_safe(REPORTS / f"{VERSION}_today_summary_{slug}.csv")
    market = MARKETS.get(slug, slug)

    source = company if not company.empty else snap
    rows: list[dict[str, Any]] = []
    if source.empty:
        return pd.DataFrame(columns=["시장", "종목코드", "종목명", "신뢰도점수", "데이터충분도", "핵심근거", "주의점", "다음행동", "업데이트시각"])

    for _, r in source.head(30).iterrows():
        code = get_col(r, ["종목코드", "symbol", "ticker", "종목"], "-")
        name = get_col(r, ["종목명", "name", "회사명", "TOP"], code)
        flow = to_float(get_col(r, ["수급점수", "flow_score", "supply_score"], "0"), 0)
        total = to_float(get_col(r, ["종합점수", "신뢰도점수", "total_score", "score"], "0"), 0)
        per = get_col(r, ["PER", "PER표시", "per"], "")
        pbr = get_col(r, ["PBR", "PBR표시", "pbr"], "")
        roe = get_col(r, ["ROE", "ROE표시", "roe"], "")
        price = get_col(r, ["현재가", "last_price", "current_price", "전종가", "기준가"], "")
        filled = sum(bool(x) and x not in {"-", "0", "0.0"} for x in [code, name, price, per, pbr, roe])
        score = 45 + min(20, max(0, total) * 0.25) + min(15, max(0, flow) * 0.2) + filled * 3
        score = max(35, min(88, round(score, 1)))
        enough = "충분" if filled >= 5 else "보통" if filled >= 3 else "낮음"
        core = get_col(r, ["핵심요약", "핵심근거", "해석", "초보자 해석"], "가격·수급·재무 데이터를 함께 확인")
        caution = get_col(r, ["주의점", "주의", "오류", "재무상태"], "실시간값은 장중 수신 여부에 따라 달라질 수 있음")
        action = get_col(r, ["다음행동", "다음 행동", "권장행동"], "현재가와 기준가 괴리를 먼저 확인")
        rows.append({
            "시장": market,
            "종목코드": code,
            "종목명": name,
            "신뢰도점수": score,
            "데이터충분도": enough,
            "핵심근거": core,
            "주의점": caution,
            "다음행동": action,
            "업데이트시각": now_text(),
        })
    return pd.DataFrame(rows)


def build_operational_dashboard(slug: str) -> pd.DataFrame:
    market = MARKETS.get(slug, slug)
    files = {
        "오늘 우선 확인": REPORTS / f"{VERSION}_today_summary_{slug}.csv",
        "선택 종목": REPORTS / f"{VERSION}_symbol_snapshot_{slug}.csv",
        "신뢰도 카드": REPORTS / f"{VERSION}_confidence_cards_{slug}.csv",
        "미래확률": REPORTS / f"{VERSION}_future_probability_{slug}.csv",
        "뉴스": REPORTS / f"{VERSION}_news_summary_{slug}.csv",
    }
    rows = []
    for section, path in files.items():
        cnt = row_count(path)
        status = "정상" if cnt > 0 else "확인필요"
        if section == "뉴스" and cnt == 0:
            action = "뉴스 API/최근 저장 뉴스 확인"
        elif cnt == 0:
            action = "이전 정상 리포트 또는 원천 CSV 확인"
        else:
            action = "앱에서 카드 확인"
        rows.append({"시장": market, "구역": section, "행수": cnt, "상태": status, "내용": f"{section} {cnt}건", "다음행동": action, "업데이트시각": now_text()})
    return pd.DataFrame(rows)


def mirror_core_reports() -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    report_types = {
        "today_summary": ["v*_today_summary_{slug}.csv"],
        "symbol_snapshot": ["v*_symbol_snapshot_{slug}.csv", "intraday_realtime_snapshot*.csv"],
        "action_cards": ["v*_action_cards_{slug}.csv"],
        "pullback_cards": ["v*_pullback_cards_{slug}.csv"],
        "flow_cards": ["v*_flow_cards_{slug}.csv", "v*_flow_clean_{slug}.csv", "intraday_flow_snapshot*.csv"],
        "company_integrated": ["v*_company_integrated_{slug}.csv", "v*_kpi_cards_{slug}.csv"],
        "risk_cards": ["v*_risk_cards_{slug}.csv"],
        "future_probability": ["v*_future_probability_{slug}.csv"],
        "news_summary": ["v*_news_summary_{slug}.csv"],
        "position_cards": ["v*_position_cards_{slug}.csv"],
        "narrative_cards": ["v*_narrative_cards_{slug}.csv"],
    }
    for slug in ("kr", "us"):
        for typ, pats in report_types.items():
            resolved = [p.format(slug=slug) for p in pats]
            src = latest_existing(resolved)
            if src and src.name.startswith(f"{VERSION}_"):
                # Already target; still make v92 alias for app compatibility.
                target = REPORTS / f"{ALIAS_VERSION}_{typ}_{slug}.csv"
                try:
                    write_csv_safe(read_csv_safe(src), target)
                except Exception:
                    pass
                operations.append({"target": f"{VERSION}_{typ}_{slug}.csv", "source": src.name, "rows": row_count(src), "status": "ALREADY"})
            else:
                operations.append(copy_latest_to_target(src, f"{VERSION}_{typ}_{slug}.csv"))
    return operations


def append_prediction_history() -> dict[str, Any]:
    path = HISTORY / "prediction_history.csv"
    existing = read_csv_safe(path)
    new_rows: list[dict[str, Any]] = []
    today = datetime.now().strftime("%Y-%m-%d")
    for slug, market in MARKETS.items():
        summary = read_csv_safe(REPORTS / f"{VERSION}_today_summary_{slug}.csv")
        if summary.empty:
            continue
        for _, r in summary.iterrows():
            category = get_col(r, ["카드", "category"], "오늘확인")
            top = get_col(r, ["TOP", "종목명", "name"], "-")
            decision = get_col(r, ["구분", "decision"], "watch")
            code_match = re.search(r"\(([^)]+)\)", top)
            symbol = code_match.group(1).strip() if code_match else get_col(r, ["종목코드", "symbol", "ticker"], top)
            new_rows.append({
                "date": today,
                "market": market,
                "category": category,
                "symbol": symbol,
                "name": top,
                "decision": decision,
                "version": VERSION,
                "source_file": f"{VERSION}_today_summary_{slug}.csv",
                "created_at": now_text(),
            })
    incoming = pd.DataFrame(new_rows)
    if incoming.empty:
        if existing.empty:
            write_csv_safe(pd.DataFrame(columns=["date", "market", "category", "symbol", "name", "decision", "version", "source_file", "created_at"]), path)
        return {"rows_added": 0, "total": row_count(path), "status": "NO_NEW_ROWS"}
    if not existing.empty:
        all_df = pd.concat([existing, incoming], ignore_index=True).fillna("")
        dedup_cols = [c for c in ["date", "market", "category", "symbol", "version"] if c in all_df.columns]
        before = len(all_df)
        all_df = all_df.drop_duplicates(subset=dedup_cols, keep="last") if dedup_cols else all_df.drop_duplicates()
        added = len(all_df) - len(existing)
    else:
        all_df = incoming
        added = len(incoming)
    write_csv_safe(all_df, path)
    return {"rows_added": max(0, int(added)), "total": len(all_df), "status": "OK"}


def generate_v93_reports() -> dict[str, Any]:
    ensure_dirs()
    base = run_base_update()
    ops = mirror_core_reports()

    generated: list[dict[str, Any]] = []
    for slug in ("kr", "us"):
        conf = build_confidence_cards(slug)
        write_csv_safe(conf, REPORTS / f"{VERSION}_confidence_cards_{slug}.csv")
        write_csv_safe(conf, REPORTS / f"{ALIAS_VERSION}_confidence_cards_{slug}.csv")
        dash = build_operational_dashboard(slug)
        write_csv_safe(dash, REPORTS / f"{VERSION}_operational_dashboard_{slug}.csv")
        write_csv_safe(dash, REPORTS / f"{ALIAS_VERSION}_operational_dashboard_{slug}.csv")
        generated.extend([
            {"file": f"{VERSION}_confidence_cards_{slug}.csv", "rows": len(conf)},
            {"file": f"{VERSION}_operational_dashboard_{slug}.csv", "rows": len(dash)},
        ])

    status_rows = []
    for slug, market in MARKETS.items():
        for item in ["today_summary", "symbol_snapshot", "confidence_cards", "operational_dashboard", "future_probability", "news_summary"]:
            path = REPORTS / f"{VERSION}_{item}_{slug}.csv"
            cnt = row_count(path)
            status_rows.append({
                "시장": market,
                "항목": item,
                "행수": cnt,
                "상태": "정상" if cnt > 0 else "미생성",
                "설명": f"{path.name} {cnt} rows",
                "업데이트시각": now_text(),
            })
    write_csv_safe(pd.DataFrame(status_rows), REPORTS / f"{VERSION}_data_status.csv")
    write_csv_safe(pd.DataFrame(status_rows), REPORTS / f"{ALIAS_VERSION}_data_status.csv")

    hist = append_prediction_history()
    manifest = {
        "status": "OK",
        "version": VERSION,
        "updated_at": now_text(),
        "base_update": base,
        "copied": ops,
        "generated": generated,
        "history": hist,
        "note": "GitHub Actions update package. Local app can be opened later after Fetch/Pull.",
    }
    (REPORTS / f"{VERSION}_github_actions_status.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (BACKUPS / f"{VERSION}_backup_manifest.json").write_text(json.dumps({
        "updated_at": now_text(),
        "important_files": {
            str(p.relative_to(ROOT)): {"exists": p.exists(), "bytes": p.stat().st_size if p.exists() else 0, "rows": row_count(p) if p.suffix.lower() == ".csv" else None}
            for p in [
                HISTORY / "prediction_history.csv",
                REPORTS / f"{VERSION}_today_summary_kr.csv",
                REPORTS / f"{VERSION}_today_summary_us.csv",
                REPORTS / f"{VERSION}_confidence_cards_kr.csv",
                REPORTS / f"{VERSION}_operational_dashboard_kr.csv",
            ]
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    try:
        # Local convenience only. In GitHub Actions, secrets are env vars.
        try:
            from dotenv import load_dotenv
            load_dotenv(ROOT / ".env")
        except Exception:
            pass
        manifest = generate_v93_reports()
        print(json.dumps(manifest, ensure_ascii=False, indent=2)[:12000])
    except Exception as exc:
        ensure_dirs()
        err = {"status": "ERROR", "version": VERSION, "updated_at": now_text(), "error": f"{type(exc).__name__}: {exc}"}
        (REPORTS / f"{VERSION}_github_actions_status.json").write_text(json.dumps(err, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(err, ensure_ascii=False, indent=2))
        raise


if __name__ == "__main__":
    main()
