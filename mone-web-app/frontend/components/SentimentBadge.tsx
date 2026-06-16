"use client";

import { useEffect, useState } from "react";
import { fetchSentiment, sentimentColor, sentimentLabel, type SentimentResult } from "@/lib/sentimentUtils";

export function SentimentBadge({
  symbol,
  market = "kr",
  name = "",
  displayConfidence = false,
}: {
  symbol: string;
  market?: "kr" | "us";
  name?: string;
  displayConfidence?: boolean;
}) {
  const [sentiment, setSentiment] = useState<SentimentResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      const result = await fetchSentiment(symbol, market, name);
      setSentiment(result);
      setLoading(false);
    };
    load();
  }, [symbol, market, name]);

  if (loading) {
    return (
      <span className="inline-flex items-center rounded-full border border-slate-700/40 bg-slate-800/40 px-2 py-0.5 text-[10px] text-slate-500">
        분석중...
      </span>
    );
  }

  if (!sentiment || sentiment.source === "error") {
    return null;
  }

  const label = sentimentLabel(sentiment.sentiment);
  const colors = sentimentColor(sentiment.sentiment);
  const displayText = displayConfidence
    ? `${label} (${sentiment.confidence}%)`
    : label;

  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${colors}`}>
      {displayText}
    </span>
  );
}
