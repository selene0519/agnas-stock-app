import sys
sys.path.insert(0, '.')
from app.services.chart_accuracy import chart_analysis_accuracy

result = chart_analysis_accuracy(market='all', future_bars=20, symbol_limit=10, max_cutoffs=4)

print("=== baseline accuracy ===")
print("symbols:", result["symbolCount"])
print("samples:", result["sampleCount"])
print("actionable:", result["actionableCount"])
print("neutral_low:", result["neutralOrLowScoreCount"])
print("hit_rate:", result["directionalHitRatePct"])
print("bullish_hit:", result["bullishHitRatePct"])
print("bearish_hit:", result["bearishHitRatePct"])
print("avg_return:", result["avgFutureReturnPct"])

print()
print("--- failed cases (actionable but wrong direction) ---")
failed = [r for r in result["items"] if r.get("actionable") and r.get("directionalHit") is False]
for r in failed[:8]:
    print(f"  {r['market'].upper()} {r['symbol']} | {r['direction']} | score={r['confluenceScore']} | futureReturn={r['futureReturnPct']}% | {r['asOf']}")
    print(f"    reasons: {r['reasons'][:2]}")

print()
print("--- succeeded cases sample ---")
ok = [r for r in result["items"] if r.get("actionable") and r.get("directionalHit") is True]
for r in ok[:5]:
    print(f"  {r['market'].upper()} {r['symbol']} | {r['direction']} | score={r['confluenceScore']} | futureReturn={r['futureReturnPct']}% | {r['asOf']}")
