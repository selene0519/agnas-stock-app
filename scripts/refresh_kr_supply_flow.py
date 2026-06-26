"""
KIS 투자자별 순매수(외국인/기관) 수급 데이터 갱신.

읽기 전용 시세조회 API(FHKST01010900)만 사용 — 주문/체결과 무관.
출력: data/kr_supply_flow.csv (symbol, asOf, signalScore, foreign5d, institution5d, foreign20d, institution20d)

predictions.csv(레거시 로컬 Streamlit 앱이 채우던 파일, 3주+ 갱신이 끊겼던 적 있음)에
의존하던 기존 수급 신호를 대체한다 — 이 스크립트는 GitHub Actions에서 직접 KIS API를
호출해 매번 새로 채운다.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
OUTPUT_CSV = ROOT / "data" / "kr_supply_flow.csv"
RATE_LIMIT_SLEEP_SEC = 0.15


def _kr_symbols() -> list[str]:
    symbols = []
    for path in sorted(OHLCV_DIR.glob("kr_*_daily.csv")):
        sym = path.stem[len("kr_"):-len("_daily")]
        if sym.isdigit() and len(sym) == 6:
            symbols.append(sym)
    return symbols


def main() -> None:
    from app.services import quotes

    if not quotes._kis_enabled():
        print("KIS_APP_KEY/KIS_APP_SECRET 미설정 — 건너뜀")
        return

    symbols = _kr_symbols()
    rows: list[dict] = []
    ok_count = 0
    for sym in symbols:
        result = quotes.fetch_investor_flow_kr(sym)
        if result.get("ok") and result.get("history"):
            score = quotes.investor_flow_supply_score(result["history"])
            if score.get("ok"):
                rows.append({
                    "symbol": sym,
                    "asOf": score["latestDate"],
                    "signalScore": score["score"],
                    "foreign5d": score["foreign_5d"],
                    "institution5d": score["institution_5d"],
                    "foreign20d": score["foreign_20d"],
                    "institution20d": score["institution_20d"],
                })
                ok_count += 1
        time.sleep(RATE_LIMIT_SLEEP_SEC)

    if rows:
        OUTPUT_CSV.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=["symbol", "asOf", "signalScore", "foreign5d", "institution5d", "foreign20d", "institution20d"])
            writer.writeheader()
            writer.writerows(rows)
    print(f"수급 데이터 갱신: {ok_count}/{len(symbols)}종목 성공 → {OUTPUT_CSV.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
