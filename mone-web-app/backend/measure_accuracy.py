import sys
sys.path.insert(0, '.')
from app.services.chart_accuracy import chart_analysis_accuracy

# symbol_limit=30, max_cutoffs=8 for larger sample
result = chart_analysis_accuracy(market='all', future_bars=20, symbol_limit=30, max_cutoffs=8)

print("=== accuracy report ===")
print("symbols:", result["symbolCount"])
print("samples:", result["sampleCount"])
print("actionable:", result["actionableCount"])
print("neutral_low:", result["neutralOrLowScoreCount"])
print("hit_rate:", result["directionalHitRatePct"])
print("bullish_hit:", result["bullishHitRatePct"])
print("bearish_hit:", result["bearishHitRatePct"])
print("avg_return:", result["avgFutureReturnPct"])

print()
print("=== ALL FAILURE CASES ===")
failed = [r for r in result["items"] if r.get("actionable") and r.get("directionalHit") is False]
print(f"total failures: {len(failed)}")
for r in failed:
    print(f"\n  [{r['market'].upper()}] {r['symbol']}")
    print(f"    date    : {r['asOf']} ~ {r['futureEnd']}")
    print(f"    signal  : {r['direction']} | score={r['confluenceScore']} | status={r['signalStatus']}")
    print(f"    result  : futureReturn={r['futureReturnPct']}% | max={r['maxReturnPct']}% | min={r['minReturnPct']}%")
    print(f"    reasons : {r['reasons']}")

print()
print("=== SUCCESS DISTRIBUTION ===")
ok = [r for r in result["items"] if r.get("actionable") and r.get("directionalHit") is True]
print(f"total successes: {len(ok)}")

bullish_ok = [r for r in ok if r["direction"] == "bullish"]
bearish_ok = [r for r in ok if r["direction"] == "bearish"]
print(f"  bullish: {len(bullish_ok)} | avg return: {round(sum(r['futureReturnPct'] for r in bullish_ok)/len(bullish_ok),2) if bullish_ok else 'N/A'}%")
print(f"  bearish: {len(bearish_ok)} | avg return: {round(sum(r['futureReturnPct'] for r in bearish_ok)/len(bearish_ok),2) if bearish_ok else 'N/A'}%")

print()
print("=== SCORE DISTRIBUTION (actionable) ===")
actionable = [r for r in result["items"] if r.get("actionable") and r.get("directionalHit") is not None]
bands = [(60,65),(65,70),(70,75),(75,80),(80,100)]
for lo, hi in bands:
    band = [r for r in actionable if lo <= r["confluenceScore"] < hi]
    hits = sum(1 for r in band if r["directionalHit"])
    print(f"  score {lo}~{hi}: {len(band)}건 | 적중 {hits}건 | {round(hits/len(band)*100,1) if band else 0}%")
