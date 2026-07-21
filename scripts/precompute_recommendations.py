"""추천(final_recommendations)을 mode×horizon×market 전 조합 미리 계산한다.

무료 Render 인스턴스(512MB)에서 실시간 스코어링이 90초 타임아웃·OOM을 일으켜,
무거운 계산은 GitHub Actions(메모리·시간 여유)에서 이 스크립트로 돌려
reports/reco_cache/{market}_{mode}_{horizon}.json 으로 커밋한다.
런타임(final_engine._load_precomputed)은 이 파일을 읽기만 한다.

사용:
  python scripts/precompute_recommendations.py
  python scripts/precompute_recommendations.py --market kr --limit 120
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mone-web-app" / "backend"))

# 미리계산 스크립트 자신은 라이브 계산을 해야 하므로 precompute 로드를 끈다.
os.environ["MONE_DISABLE_PRECOMPUTE"] = "1"

MODES = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

# 프론트(StocksPage·explorationTaxonomy)가 실제로 읽는 필드만 남긴다.
# 원본 아이템은 456개 필드(23KB)로, raw/virtualPlans 등 내부·상세용 대형 필드가
# 대부분이라 리스트 서빙에는 불필요하다. 상세는 별도 엔드포인트(recommendation_detail).
ITEM_KEEP = {
    # 식별
    "symbol", "name", "market", "code", "ticker", "companyName", "id",
    # 가격/현재가
    "currentPrice", "currentPriceText", "currentPriceSource", "price", "priceSource",
    "priceSourceFile", "close", "averagePrice", "avgPrice", "avg_price", "qty", "quantity",
    # 진입/손절/목표
    "entry", "entryPrice", "entryText", "stop", "stopPrice", "stopText",
    "target", "targetPrice", "targetText", "targetReason",
    # 상태/날짜
    "dataStatus", "dataDate", "dataQualityStatus", "priceDataStatus", "sourceStatus",
    "statuses", "latestDataDate", "ohlcvLatestDate", "latestFileModifiedAt", "generatedAt",
    "recoGeneratedAt", "recommendationDate", "predictionDate", "sourceDate", "updatedAt",
    # 점수/EV/검증
    "finalScore", "finalRankScore", "expectedValue", "evNegative", "expectedValueText",
    "rr", "rrActual", "discoveryScore", "discoveryTags", "validatedExpectancy",
    "validatedWinRate", "validatedSampleCount", "calibratedWinRate", "walkforwardMetrics",
    "opportunityScore", "entryScore", "riskScore", "upsideScore", "momentumScore",
    "qualityScore", "rrScore", "scores", "supply_score", "supplySignal",
    "resistanceDistancePct", "maConvergence", "overextensionRisk", "surgeLabel",
    # 렌즈/태그 (explorationTaxonomy가 동적으로 읽음)
    "strategyTags", "strategyTagCodes", "strategyTagLabels", "displayTags", "styleTags",
    "liquidityTags", "pricePositionTags", "freshnessTags",
    # 분류/표시
    "sector", "sectorLabel", "group", "groups", "source", "suggestion", "buyTiming",
    "newEntryDecision", "patternAction", "patternStrategyAction", "cautionReasons",
    # 거래 안전/차단
    "tradeBlockStatus", "tradeBlockReason", "isTradeBlocked", "reviewOnly", "isBlocked",
    "riskStatus", "action", "recommended", "desc", "label", "isSearchOnly",
}


def _slim_item(item: dict) -> dict:
    if not isinstance(item, dict):
        return item
    return {k: v for k, v in item.items() if k in ITEM_KEEP}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["kr", "us", "all"], default="all")
    ap.add_argument("--limit", type=int, default=120)
    args = ap.parse_args()

    from app.services import final_engine as fe
    from app.services import signal_ledger as sl

    out_dir = ROOT / "reports" / "reco_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    markets = ["kr", "us"] if args.market == "all" else [args.market]

    ok = 0
    for market in markets:
        for mode in MODES:
            for horizon in HORIZONS:
                t = time.time()
                try:
                    res = fe.final_recommendations(market, mode, horizon, limit=args.limit)
                    res = dict(res)
                    # Freeze a small, stable set of forecasts before slimming the
                    # cache payload.  Validation later reads this immutable ledger,
                    # never a forecast recomputed after the outcome is known.
                    snapshot_items = list(res.get("items") or [])[: min(20, args.limit)]
                    snapshot = sl.record_recommendation_snapshots(
                        snapshot_items,
                        source=f"precompute:{market}_{mode}_{horizon}",
                    )
                    res["forecastSnapshot"] = {
                        "date": snapshot.get("snapshotDate"),
                        "added": snapshot.get("added", 0),
                        "duplicates": snapshot.get("duplicates", 0),
                        "method": "HISTORICAL_ANALOG_EMPIRICAL",
                    }
                    res["items"] = [_slim_item(it) for it in (res.get("items") or [])]
                    res["servedFrom"] = "precompute"
                    res["precomputedAt"] = fe._now()
                    path = out_dir / f"{market}_{mode}_{horizon}.json"
                    path.write_text(json.dumps(res, ensure_ascii=False, default=str), encoding="utf-8")
                    ok += 1
                    print(f"[precompute] {market}_{mode}_{horizon}: {res.get('count')}건 "
                          f"({time.time() - t:.1f}s)", flush=True)
                except Exception as exc:
                    print(f"[precompute] {market}_{mode}_{horizon} 오류: "
                          f"{type(exc).__name__}: {exc}", flush=True)
    print(f"[precompute] 완료: {ok}/{len(markets) * len(MODES) * len(HORIZONS)} 조합")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
