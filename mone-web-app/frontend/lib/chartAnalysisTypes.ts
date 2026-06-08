/**
 * MONE Phase 6 Chart Analysis Types — Blueprint V4.5
 * Matches backend chart_analysis_engine.py data structures.
 *
 * Core Analysis (T): uses only closed candle data up to time T
 * Forward Projection (T+H): visualization coordinates in future area only
 */

// ─── Primitive types ─────────────────────────────────────────────────────────

export type SignalStatus = "none" | "developing" | "confirmed" | "invalidated" | "expired";
export type SignalDirection = "bullish" | "bearish" | "neutral";
export type DataQualityStatus = "normal" | "stale" | "partial" | "error";
export type ZoneType = "supply" | "demand";
export type ProjectionLineKind = "support" | "resistance" | "retracement";

// ─── Core analysis types ─────────────────────────────────────────────────────

export interface Pivot {
  index: number;
  price: number;
  type: "H" | "L";
  date: string;
}

export interface Trendline {
  slope: number;
  intercept: number;
  startIndex: number;
  endIndex: number;
  startPrice: number;
  endPrice: number;
}

export interface SupplyDemandZone {
  id: string;
  zoneType: ZoneType;
  top: number;
  bottom: number;
  strengthScore: number;
  isMitigated: boolean;
}

export interface RetracementLevel {
  ratio: number;
  price: number;
  label: string;
  isKey: boolean;
}

export interface OverlapSignal {
  price: number;
  ratio: number;
  isKey: boolean;
  zoneStrength: number;
  label: string;
}

// ─── Confluence ───────────────────────────────────────────────────────────────

export interface ConfluenceComponents {
  overlap: number;         // retracement × zone overlap
  momentum: number;        // trendline direction + MA alignment
  volume: number;          // recent volume vs 20-day avg
  marketCondition: number; // market regime
  dataQuality: number;     // data freshness
  penalty: number;         // RSI overbought etc.
}

// ─── Forward Projection ───────────────────────────────────────────────────────

export interface ProjectionLine {
  fromIndex: number;
  toIndex: number;      // current index (T) + horizonBars
  fromPrice: number;
  toPrice: number;
  kind: ProjectionLineKind;
  sourceStatus: SignalStatus;
  active: boolean;      // false → render faded (diverged or mitigated)
}

export interface ProjectionZone {
  zoneId: string;
  fromIndex: number;
  toIndex: number;
  top: number;
  bottom: number;
  zoneType: ZoneType;
  active: boolean;
}

export interface ChartProjectionState {
  horizonBars: number;
  projectedTrendlines: ProjectionLine[];
  projectedZones: ProjectionZone[];
  projectedRetracements: ProjectionLine[];
  notes: string[];      // compliance fixed labels (자본시장법)
}

// ─── Main state (API response) ───────────────────────────────────────────────

export interface ChartAnalysisState {
  ok: boolean;
  symbol: string;
  market: string;
  timeframe: string;
  evaluatedAt: number;
  inputCandleCount: number;
  dataQuality: DataQualityStatus;
  warnings: string[];
  lookaheadSafe: boolean;

  // Core Analysis (T only)
  completedPivots: Pivot[];
  supportLine: Trendline | null;
  resistanceLine: Trendline | null;
  breakoutDirection: "UP" | "DOWN" | null;
  breakoutStatus: SignalStatus;
  retracements: RetracementLevel[];
  primaryRetracementLevel: number | null;
  zones: SupplyDemandZone[];
  overlapSignals: OverlapSignal[];

  // FSM state
  confluenceScore: number;          // 0~100
  confluenceDirection: SignalDirection;
  signalStatus: SignalStatus;
  confluenceComponents: ConfluenceComponents;
  confluenceReasons: string[];

  // Signal lifecycle
  confirmedIndex: number | null;
  createdIndex: number | null;
  expiresAtIndex: number | null;
  invalidationReason: string | null;

  // Risk suggestion
  cappedFraction: number;   // always 0 unless confirmed
  riskStatus: string;

  // Integration score for recommendations (0~100)
  chartSignalScore: number;
  chartSignalTag: string;

  // Forward Projection (T+H)
  projection: ChartProjectionState | null;

  // Market context
  regime?: string;
  regimeLabel?: string;
}

// ─── Recommendation card extension ───────────────────────────────────────────

/** Fields added to recommendation cards after Phase 6 integration */
export interface ChartSignalFields {
  chartSignalScore: number;
  chartSignalTag: string;
  chartSignalStatus: SignalStatus;
  chartSignalDirection: SignalDirection;
  chartConfluenceScore: number;
  chartOverlapSignals: Array<{
    price: number;
    ratio: number;
    isKey: boolean;
    label: string;
  }>;
}
