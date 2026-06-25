/**
 * Sentiment analysis utilities for news/disclosure sentiment display
 */

export type SentimentType = "positive" | "negative" | "neutral";
export type SentimentSource = "claude_api" | "keyword_fallback" | "error";

export interface SentimentResult {
  sentiment: SentimentType;
  confidence: number; // 0-100
  source: SentimentSource;
  reasoning?: string;
  penalty?: number;
  reasons?: string[];
}

export function sentimentColor(sentiment: SentimentType): string {
  if (sentiment === "positive") return "border-emerald-500/40 bg-emerald-500/10 text-emerald-300";
  if (sentiment === "negative") return "border-red-500/40 bg-red-500/10 text-red-300";
  return "border-slate-600 bg-slate-800/60 text-slate-400";
}

export function sentimentLabel(sentiment: SentimentType): string {
  if (sentiment === "positive") return "호재";
  if (sentiment === "negative") return "악재";
  return "중립";
}

export async function fetchSentiment(
  symbol: string,
  market: "kr" | "us" = "kr",
  name: string = "",
): Promise<SentimentResult | null> {
  try {
    const params = new URLSearchParams({ market, name });
    const res = await fetch(`/mone-api/api/sentiment/${symbol}?${params}`, { method: "GET" });
    if (!res.ok) return null;
    const data = await res.json();
    if (!data.ok) return null;
    return {
      sentiment: data.sentiment || "neutral",
      confidence: data.confidence || 0,
      source: data.source || "error",
      reasoning: data.reasoning,
      penalty: data.penalty,
      reasons: data.reasons,
    };
  } catch {
    return null;
  }
}
