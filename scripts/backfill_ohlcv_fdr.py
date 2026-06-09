"""
MONE OHLCV 2년치 백필 스크립트 (FinanceDataReader)
- KR: PyKRX/FinanceDataReader로 2년 일봉 수집
- 기존 파일에 없는 날짜만 추가 (중복 없이)
- 저장: data/market/ohlcv/kr_{symbol}_daily.csv
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# 프로젝트 루트
REPO_ROOT = Path(__file__).parents[1]
OHLCV_DIR = REPO_ROOT / "data" / "market" / "ohlcv"
OHLCV_DIR.mkdir(parents=True, exist_ok=True)

# 수집 기간
END_DATE = datetime.today()
START_DATE = END_DATE - timedelta(days=730)  # 2년

def get_kr_symbols() -> list[str]:
    """data/sector_map_kr.csv에서 심볼 목록"""
    import csv
    path = REPO_ROOT / "data" / "sector_map_kr.csv"
    symbols = []
    if path.exists():
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sym = str(row.get("symbol", "")).strip()
                if sym and sym.isdigit():
                    symbols.append(sym)
    return symbols[:100]  # 최대 100개

def fetch_fdr(symbol: str) -> pd.DataFrame | None:
    """FinanceDataReader로 KR 종목 일봉 수집"""
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(symbol, START_DATE.strftime("%Y-%m-%d"), END_DATE.strftime("%Y-%m-%d"))
        if df is None or df.empty:
            return None
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        # date 컬럼이 없으면 index 복구 시도
        if "date" not in df.columns:
            df = df.reset_index()
            df.columns = [c.lower() for c in df.columns]
        if "date" not in df.columns:
            return None
        cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in df.columns]
        df = df[cols].copy()
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df = df.dropna(subset=["close"])
        df = df[df["close"] > 0]
        return df
    except Exception as e:
        print(f"  FDR 실패 [{symbol}]: {e}")
        return None

def merge_with_existing(symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """기존 CSV와 병합 (중복 제거, 날짜 정렬)"""
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    if path.exists():
        try:
            existing = pd.read_csv(path, encoding="utf-8-sig")
            existing.columns = [c.lower() for c in existing.columns]
            # 공통 컬럼만 사용
            common_cols = [c for c in ["date", "open", "high", "low", "close", "volume"] if c in existing.columns and c in new_df.columns]
            existing = existing[common_cols]
            new_sub = new_df[[c for c in common_cols if c in new_df.columns]]
            combined = pd.concat([existing, new_sub], ignore_index=True)
            combined["date"] = pd.to_datetime(combined["date"]).dt.strftime("%Y-%m-%d")
            combined = combined.drop_duplicates(subset=["date"], keep="last")
            combined = combined.sort_values("date").reset_index(drop=True)
            return combined
        except Exception as ex:
            print(f"  병합 실패 [{symbol}]: {ex}")
    return new_df

def save(symbol: str, df: pd.DataFrame) -> int:
    path = OHLCV_DIR / f"kr_{symbol}_daily.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return len(df)

def main():
    try:
        import FinanceDataReader  # noqa: F401
    except ImportError:
        print("FinanceDataReader 설치 중...")
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "finance-datareader", "-q"])

    symbols = get_kr_symbols()
    print(f"백필 대상: {len(symbols)}종목 / {START_DATE.date()} ~ {END_DATE.date()}")

    results = {"ok": 0, "skip": 0, "fail": 0}
    for i, sym in enumerate(symbols, 1):
        print(f"[{i:3d}/{len(symbols)}] {sym} ...", end=" ", flush=True)
        df = fetch_fdr(sym)
        if df is None or df.empty:
            print("SKIP")
            results["skip"] += 1
            continue
        merged = merge_with_existing(sym, df)
        rows = save(sym, merged)
        print(f"OK ({rows}행)")
        results["ok"] += 1

    print(f"\n완료: 성공={results['ok']} 건너뜀={results['skip']} 실패={results['fail']}")

if __name__ == "__main__":
    main()
