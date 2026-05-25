# -*- coding: utf-8 -*-
"""
MONE 데이터 반영 복구 스크립트
- app.py는 덮어쓰지 않음
- CSV merge conflict marker 제거
- predictions/watchlist/holdings 기반으로 v92/v91 홈 카드 리포트 재생성
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path.cwd()
if not (ROOT / "app.py").exists():
    # 사용자가 다른 위치에서 실행한 경우 기본 경로로 이동
    DEFAULT = Path(r"C:\Users\minbo\OneDrive\문서\GitHub\agnas-stock-app")
    if (DEFAULT / "app.py").exists():
        ROOT = DEFAULT

REPORT_DIR = ROOT / "reports"
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "history"
BACKUP_DIR = ROOT / "backups" / f"mone_data_restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def ensure_dirs() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def backup_path(path: Path) -> None:
    try:
        if not path.exists():
            return
        rel = path.relative_to(ROOT)
        dst = BACKUP_DIR / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir():
            shutil.copytree(path, dst, dirs_exist_ok=True)
        else:
            shutil.copy2(path, dst)
    except Exception:
        pass


def read_text_any(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_bytes().decode("utf-8", errors="ignore")


def read_csv_any(path: Path) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size <= 0:
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            return pd.read_csv(path, encoding=enc, dtype=str, low_memory=False).fillna("")
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
        except Exception:
            continue
    try:
        return pd.read_csv(path, encoding="utf-8-sig", dtype=str, engine="python", on_bad_lines="skip").fillna("")
    except Exception:
        return pd.DataFrame()


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def is_conflict_line(line: str) -> bool:
    s = line.strip()
    return s.startswith("<<<<<<<") or s == "=======" or s.startswith(">>>>>>>")


def remove_conflict_marker_lines(path: Path) -> bool:
    """CSV/JSON/TXT에서 Git conflict marker 줄만 제거. 구조가 다른 history는 별도 재생성."""
    if not path.exists() or path.stat().st_size <= 0:
        return False
    text = read_text_any(path)
    if "<<<<<<<" not in text and ">>>>>>>" not in text:
        return False

    backup_path(path)

    cleaned_lines = [line for line in text.splitlines() if not is_conflict_line(line)]
    cleaned = "\n".join(cleaned_lines).strip() + "\n"

    # CSV에서 중간에 반복되는 header 줄 제거
    if path.suffix.lower() == ".csv":
        lines = cleaned.splitlines()
        if lines:
            header = lines[0].lstrip("\ufeff")
            filtered = [lines[0]]
            for line in lines[1:]:
                if line.lstrip("\ufeff") == header:
                    continue
                filtered.append(line)
            cleaned = "\n".join(filtered).strip() + "\n"

    path.write_text(cleaned, encoding="utf-8-sig")
    return True


def clean_existing_conflict_files() -> list[str]:
    changed: list[str] = []
    for base in [REPORT_DIR, HISTORY_DIR]:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".csv", ".json", ".txt"}:
                if remove_conflict_marker_lines(path):
                    changed.append(str(path.relative_to(ROOT)))
    return changed


def to_num(v: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(v):
            return default
    except Exception:
        pass
    s = str(v).strip()
    if not s or s.lower() in {"nan", "none", "null", "-"}:
        return default
    s = s.replace(",", "").replace("원", "").replace("$", "").replace("%", "").strip()
    try:
        return float(s)
    except Exception:
        return default


def first_value(row: pd.Series, cols: list[str], default: str = "") -> str:
    for c in cols:
        if c in row.index:
            v = str(row.get(c, "")).strip()
            if v and v.lower() not in {"nan", "none", "null", "-"}:
                return v
    return default


def first_col(df: pd.DataFrame, cols: list[str], default: str = "") -> pd.Series:
    out = pd.Series([default] * len(df), index=df.index, dtype="object")
    for c in cols:
        if c in df.columns:
            s = df[c].astype(str).replace({"nan": "", "None": "", "NaN": ""}).fillna("")
            out = out.mask(out.astype(str).str.strip().eq(""), s)
    return out.astype(str)


def normalize_symbol(symbol: Any, market: str) -> str:
    s = str(symbol or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    if market == "한국주식" and s.isdigit():
        return s.zfill(6)
    return s.upper()


def load_predictions() -> pd.DataFrame:
    df = read_csv_any(ROOT / "predictions.csv")
    if df.empty:
        return df
    if "market" not in df.columns:
        df["market"] = ""
    if "ticker" not in df.columns:
        df["ticker"] = first_col(df, ["symbol", "종목코드", "code"], "")
    if "stock_name" not in df.columns:
        df["stock_name"] = first_col(df, ["name", "종목명", "ticker"], "")
    if "created_at" in df.columns:
        df["_created_dt"] = pd.to_datetime(df["created_at"], errors="coerce")
    else:
        df["_created_dt"] = pd.NaT
    if "target_date" in df.columns:
        df["_target_dt"] = pd.to_datetime(df["target_date"], errors="coerce")
    else:
        df["_target_dt"] = pd.NaT

    # 최신 target_date 우선
    valid_targets = df["_target_dt"].dropna()
    if len(valid_targets) > 0:
        latest_target = valid_targets.max()
        recent = df[df["_target_dt"] == latest_target].copy()
    else:
        recent = df.copy()

    return recent


def prediction_score(row: pd.Series) -> float:
    candidates = [
        "risk_confidence_score",
        "confidence_score_after_no_buy_filter",
        "confidence_score_after_market_filter",
        "confidence_score_after_adjustment",
        "confidence_score",
        "trade_fit_score",
        "quality_score",
        "fundamental_score",
        "supply_score",
        "technical_score",
    ]
    vals = [to_num(row.get(c, ""), 0.0) for c in candidates if c in row.index]
    return max(vals) if vals else 0.0


def no_buy_score(row: pd.Series) -> float:
    candidates = ["no_buy_score_after_disclosure", "no_buy_score", "risk_score", "overheat_score"]
    vals = [to_num(row.get(c, ""), 0.0) for c in candidates if c in row.index]
    return max(vals) if vals else 0.0


def build_cards_from_predictions(pred_recent: pd.DataFrame, market: str, kind: str, n: int = 5) -> pd.DataFrame:
    if pred_recent.empty:
        return pd.DataFrame(columns=[
            "시장", "종목코드", "종목명", "분류", "현재가", "기준가", "손절가", "목표가", "손익비",
            "신뢰도점수", "핵심근거", "주의점", "다음행동"
        ])

    df = pred_recent[pred_recent["market"].astype(str).eq(market)].copy()
    if df.empty:
        return pd.DataFrame()

    df["종목코드"] = [normalize_symbol(x, market) for x in first_col(df, ["ticker", "symbol", "종목코드", "code"], "")]
    df["종목명"] = first_col(df, ["stock_name", "name", "종목명", "ticker"], "")
    df["_score"] = df.apply(prediction_score, axis=1)
    df["_risk_score"] = df.apply(no_buy_score, axis=1)

    # 중복 종목 제거
    df = df.drop_duplicates(subset=["종목코드"], keep="last")

    if kind == "risk":
        pick = df.sort_values(["_risk_score", "_score"], ascending=False).head(n)
        category = "매수주의"
        next_action = "신규매수보다 관망 우선"
    elif kind == "flow":
        for c in ["foreign_institution_score", "supply_score"]:
            if c not in df.columns:
                df[c] = "0"
        df["_flow_score"] = df[["foreign_institution_score", "supply_score"]].apply(lambda r: max(to_num(r.iloc[0]), to_num(r.iloc[1])), axis=1)
        pick = df.sort_values(["_flow_score", "_score"], ascending=False).head(n)
        category = "수급확인"
        next_action = "거래대금·수급 확인"
    elif kind == "pullback":
        pick = df.sort_values(["_score", "risk_reward"], ascending=False).head(n)
        category = "눌림대기"
        next_action = "조건부 진입가 근처만 확인"
    else:
        pick = df.sort_values(["_score", "risk_reward"], ascending=False).head(n)
        category = "우선확인"
        next_action = "기준가·손절가·목표가 확인"

    rows = []
    for _, row in pick.iterrows():
        code = row.get("종목코드", "")
        name = row.get("종목명", "") or code
        decision = first_value(row, ["final_decision_after_disclosure", "risk_final_decision", "prediction_result"], "확인 필요")
        reason = first_value(row, ["buy_reason", "risk_final_decision_reason", "risk_reason"], "")
        rows.append({
            "시장": market,
            "종목코드": code,
            "종목명": name,
            "분류": category,
            "현재가": first_value(row, ["current_price_at_prediction", "prev_close", "current_price"], ""),
            "기준가": first_value(row, ["preferred_entry", "conservative_entry", "technical_entry", "entry_price", "buy_price"], ""),
            "손절가": first_value(row, ["stop_loss", "stop_loss_price", "stop"], ""),
            "목표가": first_value(row, ["breakout_buy", "target_price_1", "target_price", "tp1"], ""),
            "손익비": first_value(row, ["risk_reward", "risk_reward_ratio", "rr"], ""),
            "신뢰도점수": round(float(row.get("_score", 0.0)), 2),
            "핵심근거": reason or f"latest predictions.csv 기반: {decision}",
            "주의점": first_value(row, ["no_buy_reasons", "risk_warning_flags", "no_buy_market_reason"], "장중 가격·거래량 확인"),
            "다음행동": next_action,
        })

    return pd.DataFrame(rows)


def load_company_cards(market: str) -> pd.DataFrame:
    slug = "kr" if market == "한국주식" else "us"
    for name in [
        f"v92_company_integrated_{slug}.csv",
        f"v92_company_summary_cards_{slug}.csv",
        f"v92_company_cards_{slug}.csv",
        f"v92_kpi_cards_{slug}.csv",
        f"v91_company_integrated_{slug}.csv",
    ]:
        df = read_csv_any(REPORT_DIR / name)
        if not df.empty:
            # conflict marker remnants 제거
            for c in df.columns:
                df = df[~df[c].astype(str).str.startswith(("<<<<<<<", "=======", ">>>>>>>"), na=False)]
            if not df.empty:
                return df.head(10).copy()
    return pd.DataFrame()


def display_name(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return "-"
    row = df.iloc[0]
    name = first_value(row, ["종목명", "name", "stock_name", "종목", "ticker", "종목코드"], "-")
    code = first_value(row, ["종목코드", "ticker", "symbol", "code"], "")
    if code and name and code not in name:
        return f"{name} ({code})"
    return name or code or "-"


def build_summary(market: str, action: pd.DataFrame, pullback: pd.DataFrame, flow: pd.DataFrame, company: pd.DataFrame, risk: pd.DataFrame) -> pd.DataFrame:
    rows = [
        {"아이콘": "🎯", "카드": "오늘 우선 확인", "설명": "직전가·기준가·손절가를 먼저 확인할 후보", "건수": len(action), "TOP": display_name(action), "구분": "buy"},
        {"아이콘": "🪜", "카드": "눌림목 진입 후보", "설명": "추격보다 눌림 조건부 진입을 기다릴 후보", "건수": len(pullback), "TOP": display_name(pullback), "구분": "buy"},
        {"아이콘": "💚", "카드": "수급 급증 후보", "설명": "수급·거래대금 흐름을 우선 보는 후보", "건수": len(flow), "TOP": display_name(flow), "구분": "flow"},
        {"아이콘": "💎", "카드": "실적·저평가 후보", "설명": "실적과 밸류를 함께 확인할 후보", "건수": len(company), "TOP": display_name(company), "구분": "value"},
        {"아이콘": "🚫", "카드": "매수금지·주의", "설명": "신규매수보다 제외·관망이 우선인 후보", "건수": len(risk), "TOP": display_name(risk), "구분": "risk"},
    ]
    return pd.DataFrame(rows)


def build_snapshot_from_cards(market: str, cards: pd.DataFrame, company: pd.DataFrame) -> pd.DataFrame:
    base = cards.copy()
    if base.empty and not company.empty:
        base = company.copy()
    if base.empty:
        return pd.DataFrame(columns=["시장", "종목코드", "종목명", "분류", "현재가", "기준가", "손절가", "목표가", "손익비", "신뢰도점수", "뉴스요약", "재무요약", "다음행동", "가격출처"])

    for c in ["시장", "종목코드", "종목명", "분류", "현재가", "기준가", "손절가", "목표가", "손익비", "신뢰도점수", "다음행동"]:
        if c not in base.columns:
            base[c] = ""

    out = base[["시장", "종목코드", "종목명", "분류", "현재가", "기준가", "손절가", "목표가", "손익비", "신뢰도점수", "다음행동"]].copy()
    out["뉴스요약"] = "-"
    out["재무요약"] = "predictions.csv / company report 기반"
    out["가격출처"] = "복구 스크립트 생성"
    return out.head(20)


def rebuild_v92_reports() -> dict[str, Any]:
    pred_recent = load_predictions()
    if pred_recent.empty:
        return {"status": "ERROR", "message": "predictions.csv를 읽지 못했습니다."}

    stats: dict[str, Any] = {"status": "OK", "latest_rows": len(pred_recent), "markets": {}}

    for market, slug in [("한국주식", "kr"), ("미국주식", "us")]:
        action = build_cards_from_predictions(pred_recent, market, "action", 5)
        pullback = build_cards_from_predictions(pred_recent, market, "pullback", 5)
        flow = build_cards_from_predictions(pred_recent, market, "flow", 5)
        risk = build_cards_from_predictions(pred_recent, market, "risk", 5)
        company = load_company_cards(market)

        summary = build_summary(market, action, pullback, flow, company, risk)
        snapshot = build_snapshot_from_cards(market, action, company)

        outputs = {
            f"v92_action_cards_{slug}.csv": action,
            f"v92_pullback_cards_{slug}.csv": pullback,
            f"v92_flow_cards_{slug}.csv": flow,
            f"v92_risk_cards_{slug}.csv": risk,
            f"v92_today_summary_{slug}.csv": summary,
            f"v92_symbol_snapshot_{slug}.csv": snapshot,
            f"v91_action_cards_{slug}.csv": action,
            f"v91_pullback_cards_{slug}.csv": pullback,
            f"v91_flow_cards_{slug}.csv": flow,
            f"v91_risk_cards_{slug}.csv": risk,
            f"v91_today_summary_{slug}.csv": summary,
            f"v91_symbol_snapshot_{slug}.csv": snapshot,
        }

        for name, df in outputs.items():
            path = REPORT_DIR / name
            backup_path(path)
            write_csv(df, path)

        stats["markets"][slug] = {
            "action": len(action),
            "pullback": len(pullback),
            "flow": len(flow),
            "company": len(company),
            "risk": len(risk),
            "summary": len(summary),
            "snapshot": len(snapshot),
        }

    return stats


def rebuild_history_files() -> dict[str, Any]:
    pred = read_csv_any(ROOT / "predictions.csv")
    if pred.empty:
        return {"prediction_history": 0, "outcome_history": 0}

    hist_cols = [
        "created_at", "target_date", "market", "ticker", "stock_name",
        "prediction_result", "final_decision_after_disclosure", "risk_confidence_score",
        "confidence_score_after_no_buy_filter", "current_price_at_prediction",
        "preferred_entry", "stop_loss", "risk_reward",
    ]
    available = [c for c in hist_cols if c in pred.columns]
    hist = pred[available].copy()
    if "ticker" in hist.columns:
        hist["symbol"] = hist["ticker"]
    if "stock_name" in hist.columns:
        hist["name"] = hist["stock_name"]
    backup_path(HISTORY_DIR / "prediction_history.csv")
    write_csv(hist, HISTORY_DIR / "prediction_history.csv")

    # outcome_history는 기본 스키마만 안전하게 재생성. 기존 성과 계산은 후속 runner가 채우게 둠.
    if "target_date" in pred.columns:
        recent_date = str(pd.to_datetime(pred["target_date"], errors="coerce").dropna().max().date()) if len(pd.to_datetime(pred["target_date"], errors="coerce").dropna()) else ""
    else:
        recent_date = ""
    latest = load_predictions()
    rows = []
    for _, row in latest.head(50).iterrows():
        market = str(row.get("market", ""))
        ticker = normalize_symbol(row.get("ticker", row.get("symbol", "")), market)
        name = first_value(row, ["stock_name", "name", "ticker"], ticker)
        rows.append({
            "date": recent_date,
            "market": "KR" if market == "한국주식" else "US",
            "category": "예측",
            "symbol": ticker,
            "name": name,
            "base_price": first_value(row, ["current_price_at_prediction", "prev_close"], ""),
            "price_1d": "",
            "return_1d": "대기",
            "price_3d": "",
            "return_3d": "대기",
            "price_5d": "",
            "return_5d": "대기",
            "price_20d": "",
            "return_20d": "대기",
            "max_drawdown": "대기",
            "success": "대기",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    out = pd.DataFrame(rows)
    backup_path(HISTORY_DIR / "outcome_history.csv")
    write_csv(out, HISTORY_DIR / "outcome_history.csv")

    return {"prediction_history": len(hist), "outcome_history": len(out)}


def verify_outputs() -> pd.DataFrame:
    targets = [
        "watchlist_kr_growth.csv",
        "watchlist_us_growth.csv",
        "candidate_universe_kr.csv",
        "candidate_universe_us.csv",
        "predictions.csv",
        "holdings_us.csv",
        "data/holdings_kr.csv",
        "data/holdings_us.csv",
        "data/history/prediction_history.csv",
        "data/history/outcome_history.csv",
        "reports/v92_today_summary_kr.csv",
        "reports/v92_today_summary_us.csv",
        "reports/v92_action_cards_kr.csv",
        "reports/v92_action_cards_us.csv",
        "reports/v92_pullback_cards_kr.csv",
        "reports/v92_pullback_cards_us.csv",
        "reports/v92_flow_cards_kr.csv",
        "reports/v92_flow_cards_us.csv",
        "reports/v92_risk_cards_kr.csv",
        "reports/v92_risk_cards_us.csv",
    ]
    rows = []
    for rel in targets:
        p = ROOT / rel
        df = read_csv_any(p)
        text = read_text_any(p) if p.exists() and p.stat().st_size < 2_000_000 else ""
        rows.append({
            "file": rel,
            "exists": p.exists(),
            "bytes": p.stat().st_size if p.exists() else 0,
            "rows": len(df) if isinstance(df, pd.DataFrame) else 0,
            "cols": len(df.columns) if isinstance(df, pd.DataFrame) else 0,
            "has_conflict_marker": ("<<<<<<<" in text or ">>>>>>>" in text),
        })
    diag = pd.DataFrame(rows)
    write_csv(diag, ROOT / "MONE_DATA_RESTORE_DIAGNOSTIC.csv")
    return diag


def main() -> None:
    ensure_dirs()

    # 핵심 파일 백업
    for rel in [
        "app.py",
        "predictions.csv",
        "watchlist_kr_growth.csv",
        "watchlist_us_growth.csv",
        "candidate_universe_kr.csv",
        "candidate_universe_us.csv",
        "holdings_us.csv",
        "data/holdings_kr.csv",
        "data/holdings_us.csv",
    ]:
        backup_path(ROOT / rel)

    changed = clean_existing_conflict_files()
    report_stats = rebuild_v92_reports()
    history_stats = rebuild_history_files()
    diag = verify_outputs()

    result = {
        "status": "OK",
        "root": str(ROOT),
        "backup_dir": str(BACKUP_DIR),
        "conflict_marker_files_cleaned": len(changed),
        "rebuilt_reports": report_stats,
        "rebuilt_history": history_stats,
        "diagnostic_csv": str(ROOT / "MONE_DATA_RESTORE_DIAGNOSTIC.csv"),
    }

    (ROOT / "MONE_DATA_RESTORE_RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== MONE DATA RESTORE RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("\n=== DIAGNOSTIC ===")
    print(diag.to_string(index=False))


if __name__ == "__main__":
    main()
