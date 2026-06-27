"""
KRX 관리종목/SPAC/투자주의환기종목 명단 갱신.

FinanceDataReader의 StockListing('KRX')는 시장 전체를 한 번의 호출로 가져오면서
Dept 컬럼에 관리종목/SPAC/투자주의환기종목 분류를 포함한다 — 종목별 API 호출이
필요 없어 가볍다. 이 출력을 generate_kr_recommendations.py가 종목명 접미사 추정
필터(우선주/스팩) 외에 실제 거래소 분류 기준으로도 걸러낼 수 있게 한다.

출력: data/kr_excluded_symbols.csv (symbol, name, dept, asOf)
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "data" / "kr_excluded_symbols.csv"

EXCLUDED_DEPTS = {
    "관리종목(소속부없음)",
    "SPAC(소속부없음)",
    "투자주의환기종목(소속부없음)",
}


def main() -> None:
    try:
        import FinanceDataReader as fdr
    except Exception as exc:
        print(f"FinanceDataReader import 실패: {exc}")
        return

    try:
        df = fdr.StockListing("KRX")
    except Exception as exc:
        print(f"KRX 전체 종목 조회 실패: {exc}")
        return

    if df is None or df.empty or "Dept" not in df.columns:
        print("KRX 종목 목록이 비어있거나 Dept 컬럼이 없음 — 건너뜀")
        return

    today = datetime.now().date().isoformat()
    excluded = df[df["Dept"].isin(EXCLUDED_DEPTS)]
    rows = [
        {"symbol": str(row["Code"]).strip().zfill(6), "name": str(row["Name"]).strip(),
         "dept": str(row["Dept"]).strip(), "asOf": today}
        for _, row in excluded.iterrows()
    ]

    OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["symbol", "name", "dept", "asOf"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"관리종목/SPAC/투자주의환기종목 {len(rows)}건 → {OUTPUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
