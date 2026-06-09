#!/usr/bin/env python3
"""
MONE 로컬 데이터 수집기 — Windows 작업 스케줄러용
GitHub Actions 실패 시 2순위 폴백으로 동작.

실행: python scripts/local_data_collector.py [--push]
  --push: 수집 후 GitHub에 자동 push (git 설정 필요)

Windows 작업 스케줄러 설정:
  트리거: 매일 07:30, 16:30 (평일)
  프로그램: python.exe
  인수: C:\\dev\\agnas-stock-app\\scripts\\local_data_collector.py --push
  시작위치: C:\\dev\\agnas-stock-app
"""
from __future__ import annotations
import argparse, csv, json, os, subprocess, sys, time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(REPO_ROOT / "mone-web-app" / "backend"))

LOG_PATH = REPO_ROOT / "data" / "collector_log.json"
STATUS_PATH = REPO_ROOT / "reports" / "local_collector_status.json"


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def collect_ohlcv_fdr(symbols: list[str], days: int = 30) -> dict:
    """FinanceDataReader로 최근 N일 OHLCV 수집"""
    try:
        import FinanceDataReader as fdr
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "finance-datareader", "-q"])
        import FinanceDataReader as fdr

    from datetime import timedelta
    import pandas as pd

    end = datetime.today()
    start = end - timedelta(days=days + 10)

    ok, fail = 0, 0
    ohlcv_dir = REPO_ROOT / "data" / "market" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    for sym in symbols:
        try:
            df = fdr.DataReader(sym, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
            if df is None or df.empty:
                fail += 1
                continue
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
            df["date"] = df["date"].dt.strftime("%Y-%m-%d")
            df = df[["date", "open", "high", "low", "close", "volume"]].dropna()

            # 기존 파일과 병합
            path = ohlcv_dir / f"kr_{sym}_daily.csv"
            if path.exists():
                existing = pd.read_csv(path, encoding="utf-8-sig")
                existing.columns = [c.lower() for c in existing.columns]
                df = pd.concat([existing, df]).drop_duplicates("date", keep="last")
                df = df.sort_values("date").reset_index(drop=True)

            df.to_csv(path, index=False, encoding="utf-8-sig")
            ok += 1
        except Exception as e:
            log(f"  오류 [{sym}]: {e}")
            fail += 1

    return {"ok": ok, "fail": fail}


def get_kr_symbols() -> list[str]:
    path = REPO_ROOT / "data" / "sector_map_kr.csv"
    syms: list[str] = []
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                s = str(r.get("symbol", "")).strip()
                if s and s.isdigit():
                    syms.append(s)
    return syms[:100]


def generate_recommendations() -> dict:
    """generate_kr_recommendations.py 실행"""
    script = REPO_ROOT / "scripts" / "generate_kr_recommendations.py"
    if not script.exists():
        return {"status": "SKIP", "reason": "script not found"}
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "status": "OK" if result.returncode == 0 else "ERROR",
            "stderr": result.stderr[-500:],
        }
    except Exception as e:
        return {"status": "ERROR", "reason": str(e)}


def git_push(commit_msg: str) -> bool:
    """수집 데이터 GitHub push"""
    try:
        cmds = [
            ["git", "config", "user.email", "local-collector@mone.app"],
            ["git", "config", "user.name", "MONE Local Collector"],
        ]
        stage_cmds = [
            ["git", "add", "data/market/ohlcv/kr_*_daily.csv"],
            ["git", "add", "reports/mone_v36_final_recommendations_*.csv"],
            ["git", "add", "reports/local_collector_status.json"],
            ["git", "add", "reports/kis_current_price_kr.csv"],
        ]
        for cmd in cmds + stage_cmds:
            subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True)

        # 변경사항 있으면 커밋
        diff = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        if diff.returncode == 0:
            log("변경 없음 — push 건너뜀")
            return True

        subprocess.run(
            ["git", "commit", "-m", f"{commit_msg} [skip ci]"],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        result = subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode == 0:
            log("GitHub push 성공")
            return True
        else:
            log(f"push 실패: {result.stderr}")
            return False
    except Exception as e:
        log(f"git 오류: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true", help="수집 후 GitHub push")
    parser.add_argument("--days", type=int, default=30, help="OHLCV 수집 일수")
    parser.add_argument("--no-ohlcv", action="store_true", help="OHLCV 수집 건너뜀")
    args = parser.parse_args()

    start_time = time.time()
    status: dict = {"startedAt": datetime.now().isoformat(), "steps": {}}

    log("=" * 50)
    log("MONE 로컬 데이터 수집 시작")
    log(f"push: {args.push}, days: {args.days}")
    log("=" * 50)

    # Step 1: OHLCV 수집
    if not args.no_ohlcv:
        log("Step 1: OHLCV 수집...")
        symbols = get_kr_symbols()
        log(f"  대상 {len(symbols)}종목")
        ohlcv_result = collect_ohlcv_fdr(symbols, days=args.days)
        log(f"  완료: {ohlcv_result}")
        status["steps"]["ohlcv"] = ohlcv_result

    # Step 2: 추천 생성
    log("Step 2: 추천 생성...")
    rec_result = generate_recommendations()
    log(f"  결과: {rec_result['status']}")
    status["steps"]["recommendations"] = rec_result

    # 상태 저장
    status["elapsedSec"] = round(time.time() - start_time, 1)
    status["completedAt"] = datetime.now().isoformat()
    status["source"] = "local_task_scheduler"
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"상태 저장: {STATUS_PATH}")

    # Step 3: GitHub push (선택)
    if args.push:
        log("Step 3: GitHub push...")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        push_ok = git_push(f"chore: local collector update {now_str}")
        status["pushed"] = push_ok

    log(f"완료 ({status['elapsedSec']}초)")


if __name__ == "__main__":
    main()
