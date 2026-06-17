#!/usr/bin/env python3
"""
MONE 로컬 데이터 수집기 - Windows 작업 스케줄러용
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
import argparse, csv, json, os, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).parents[1]
RENDER_API_BASE = "https://agnas-stock-app.onrender.com"
CACHE_REFRESH_SECRET = os.getenv("CACHE_REFRESH_SECRET", "mone-refresh")
sys.path.insert(0, str(REPO_ROOT / "mone-web-app" / "backend"))

LOG_PATH = REPO_ROOT / "data" / "collector_log.json"
STATUS_PATH = REPO_ROOT / "reports" / "local_collector_status.json"
GIT_AUTHOR_NAME = os.getenv("MONE_GIT_AUTHOR_NAME", "selene0519")
GIT_AUTHOR_EMAIL = os.getenv(
    "MONE_GIT_AUTHOR_EMAIL",
    "287042011+selene0519@users.noreply.github.com",
)
INVALID_SYMBOL_TOKENS = {"", "NAN", "NONE", "NULL", "N/A", "NA", "UNDEFINED"}


def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


def clean_symbol(value: object, market: str = "") -> str:
    text = str(value or "").strip().upper().replace("$", "")
    if text in INVALID_SYMBOL_TOKENS or text.lower() == "nan":
        return ""
    if market == "kr":
        digits = "".join(ch for ch in text if ch.isdigit())
        return digits.zfill(6) if digits and len(digits) <= 6 else ""
    return text.replace(".US", "")


def _render_refresh(market: str = "kr") -> bool:
    """
    GitHub push 완료 후 Render 백엔드에 캐시 즉시 갱신 요청.
    작업스케줄러 데이터가 앱에 1분 내 반영되도록 함.
    """
    try:
        url = f"{RENDER_API_BASE}/api/cache/refresh?market={market}&secret={CACHE_REFRESH_SECRET}"
        req = urllib.request.Request(url, method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode()
            log(f"  Render 캐시 갱신 완료: {body[:120]}")
            return True
    except Exception as e:
        log(f"  Render 캐시 갱신 실패 (Render 슬립 중일 수 있음): {e}")
        return False


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

    for raw_sym in symbols:
        sym = clean_symbol(raw_sym, "kr")
        if not sym:
            fail += 1
            continue
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
                s = clean_symbol(r.get("symbol", ""), "kr")
                if s:
                    syms.append(s)
    return syms[:100]


def generate_recommendations(market: str = "kr") -> dict:
    """국장(kr)/미장(us) 추천 생성 스크립트 실행"""
    script_map = {
        "kr": REPO_ROOT / "scripts" / "generate_kr_recommendations.py",
        "us": REPO_ROOT / "scripts" / "generate_us_recommendations.py",
    }
    script = script_map.get(market, script_map["kr"])
    if not script.exists():
        # 해당 마켓 스크립트 없으면 공통 스크립트 시도
        fallback = REPO_ROOT / "scripts" / "generate_kr_recommendations.py"
        if fallback.exists():
            script = fallback
        else:
            return {"status": "SKIP", "reason": f"script not found for market={market}"}
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
            "market": market,
            "stderr": result.stderr[-500:],
        }
    except Exception as e:
        return {"status": "ERROR", "reason": str(e)}


def git_push(commit_msg: str) -> bool:
    """수집 데이터 GitHub push"""
    try:
        git_env = os.environ.copy()
        git_env.update(
            {
                "GIT_AUTHOR_NAME": GIT_AUTHOR_NAME,
                "GIT_AUTHOR_EMAIL": GIT_AUTHOR_EMAIL,
                "GIT_COMMITTER_NAME": GIT_AUTHOR_NAME,
                "GIT_COMMITTER_EMAIL": GIT_AUTHOR_EMAIL,
            }
        )
        cmds = [
            ["git", "config", "user.email", GIT_AUTHOR_EMAIL],
            ["git", "config", "user.name", GIT_AUTHOR_NAME],
        ]
        stage_cmds = [
            ["git", "add", "data/market/ohlcv/kr_*_daily.csv"],
            ["git", "add", "data/market/ohlcv/us_*_daily.csv"],
            ["git", "add", "reports/mone_v36_final_recommendations_*.csv"],
            ["git", "add", "reports/mone_v36_final_trade_validation_*.csv"],
            ["git", "add", "reports/kr_recommendation_gen_status.json"],
            ["git", "add", "reports/us_recommendation_gen_status.json"],
            ["git", "add", "reports/local_collector_status.json"],
            ["git", "add", "reports/kis_current_price_kr.csv"],
            ["git", "add", "data/toss_holdings_kr.csv"],
            ["git", "add", "data/kis_holdings_kr.csv"],
            ["git", "add", "data/kis_2_holdings_kr.csv"],
            ["git", "add", "data/toss_holdings_us.csv"],
            ["git", "add", "data/kis_holdings_us.csv"],
            ["git", "add", "data/kis_2_holdings_us.csv"],
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
            log("변경 없음 - push 건너뜀")
            return True

        subprocess.run(
            ["git", "commit", "-m", f"{commit_msg} [skip ci]"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            env=git_env,
        )
        # 원격 최신 상태를 가져온 뒤 rebase
        subprocess.run(
            ["git", "fetch", "origin", "main"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            env=git_env,
            timeout=60,
        )
        rebase = subprocess.run(
            ["git", "rebase", "origin/main"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=git_env,
            timeout=60,
        )
        if rebase.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=str(REPO_ROOT), capture_output=True)
            log(f"rebase 실패 (push 중단): {rebase.stderr.strip()}")
            return False
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
            log(f"push 실패: {result.stderr.strip()}")
            return False
    except Exception as e:
        log(f"git 오류: {e}")
        return False


def get_us_symbols() -> list[str]:
    """data/sector_map_us.csv 또는 고정 US 심볼 목록"""
    path = REPO_ROOT / "data" / "sector_map_us.csv"
    syms = []
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                s = clean_symbol(r.get("symbol", ""), "us")
                if s:
                    syms.append(s)
    if not syms:
        # 기본 US 대형주 목록
        syms = ["AAPL","MSFT","GOOGL","AMZN","NVDA","META","TSLA","BRK-B",
                "JPM","V","UNH","JNJ","XOM","PG","HD","CVX","MA","BAC","ABBV","PFE"]
    for file_path in sorted((REPO_ROOT / "data" / "market" / "ohlcv").glob("us_*_daily.csv")):
        sym = clean_symbol(file_path.name.removeprefix("us_").removesuffix("_daily.csv"), "us")
        if sym and sym not in syms:
            syms.append(sym)
    return syms[:200]


def collect_ohlcv_us(symbols: list[str], days: int = 30) -> dict:
    """yfinance로 US 종목 OHLCV 수집"""
    try:
        import yfinance as yf
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "yfinance", "-q"])
        import yfinance as yf

    from datetime import timedelta
    end = datetime.today()
    start = end - timedelta(days=days + 10)
    ok, fail = 0, 0
    ohlcv_dir = REPO_ROOT / "data" / "market" / "ohlcv"
    ohlcv_dir.mkdir(parents=True, exist_ok=True)

    for raw_sym in symbols:
        sym = clean_symbol(raw_sym, "us")
        if not sym:
            fail += 1
            continue
        try:
            df = yf.download(sym, start=start.strftime("%Y-%m-%d"),
                             end=end.strftime("%Y-%m-%d"), progress=False, auto_adjust=True)
            if df is None or df.empty:
                fail += 1; continue
            df = df.reset_index()
            df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
            df["date"] = df["date"].dt.strftime("%Y-%m-%d")
            df = df[["date","open","high","low","close","volume"]].dropna()

            path = ohlcv_dir / f"us_{sym}_daily.csv"
            if path.exists():
                import pandas as pd
                existing = pd.read_csv(path, encoding="utf-8-sig")
                existing.columns = [c.lower() for c in existing.columns]
                import pandas as pd2
                df = pd.concat([existing, df]).drop_duplicates("date", keep="last")
                df = df.sort_values("date").reset_index(drop=True)
            df.to_csv(path, index=False, encoding="utf-8-sig")
            ok += 1
        except Exception as e:
            log(f"  오류 [{sym}]: {e}"); fail += 1
    return {"ok": ok, "fail": fail}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push",     action="store_true", help="수집 후 GitHub push")
    parser.add_argument("--days",     type=int, default=5,  help="OHLCV 수집 일수")
    parser.add_argument("--no-ohlcv", action="store_true",  help="OHLCV 수집 건너뜀")
    parser.add_argument("--market",   default="kr",         help="수집 대상 시장: kr / us / all")
    args = parser.parse_args()

    markets = ["kr", "us"] if args.market == "all" else [args.market]
    start_time = time.time()
    status: dict = {"startedAt": datetime.now().isoformat(), "market": args.market, "steps": {}}

    log("=" * 50)
    log(f"MONE 로컬 데이터 수집 시작 - market={args.market}")
    log(f"push: {args.push}, days: {args.days}")
    log("=" * 50)

    # Step 1: OHLCV 수집
    if not args.no_ohlcv:
        for mkt in markets:
            log(f"Step 1: OHLCV 수집 [{mkt.upper()}]...")
            if mkt == "kr":
                symbols = get_kr_symbols()
                ohlcv_result = collect_ohlcv_fdr(symbols, days=args.days)
            else:
                symbols = get_us_symbols()
                ohlcv_result = collect_ohlcv_us(symbols, days=args.days)
            log(f"  완료 [{mkt.upper()}]: {ohlcv_result}")
            status["steps"][f"ohlcv_{mkt}"] = ohlcv_result

    # Step 2: 추천 생성
    for mkt in markets:
        log(f"Step 2: 추천 생성 [{mkt.upper()}]...")
        rec_result = generate_recommendations(market=mkt)
        log(f"  결과: {rec_result['status']}")
        status["steps"][f"recommendations_{mkt}"] = rec_result

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
        if not push_ok:
            status["pushError"] = "push failed — see log above"
        STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")

        # Step 4: Render 캐시 즉시 갱신 (push 성공 시만)
        # market=all 로 고정: kr 전용 실행이어도 us lru_cache까지 함께 초기화
        if push_ok:
            log("Step 4: Render 캐시 즉시 갱신...")
            _render_refresh("all")
        else:
            log("push 실패 — Render 캐시 갱신 건너뜀")
            sys.exit(1)

    log(f"완료 ({status['elapsedSec']}초)")


if __name__ == "__main__":
    main()
