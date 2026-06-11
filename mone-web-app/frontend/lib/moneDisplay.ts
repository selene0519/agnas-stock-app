import type { Horizon, Mode } from "@/lib/api";

export const KR_NAME_MAP: Record<string, string> = {
  "000100": "유한양행",
  "000270": "기아",
  "000660": "SK하이닉스",
  "000720": "현대건설",
  "000810": "삼성화재",
  "000990": "DB하이텍",
  "001440": "대한전선",
  "003490": "대한항공",
  "003550": "LG",
  "003620": "KG모빌리티",
  "003670": "포스코퓨처엠",
  "004020": "현대제철",
  "005070": "코스모신소재",
  "005380": "현대차",
  "005490": "POSCO홀딩스",
  "005930": "삼성전자",
  "006260": "LS",
  "006340": "대원전선",
  "006360": "GS건설",
  "006400": "삼성SDI",
  "007660": "이수페타시스",
  "009150": "삼성전기",
  "009540": "HD한국조선해양",
  "010120": "LS ELECTRIC",
  "010130": "고려아연",
  "010140": "삼성중공업",
  "010950": "S-Oil",
  "011070": "LG이노텍",
  "011200": "HMM",
  "012330": "현대모비스",
  "012450": "한화에어로스페이스",
  "015760": "한국전력",
  "017670": "SK텔레콤",
  "018260": "삼성에스디에스",
  "028670": "팬오션",
  "030200": "KT",
  "032640": "LG유플러스",
  "032830": "삼성생명",
  "034020": "두산에너빌리티",
  "034730": "SK",
  "035420": "NAVER",
  "035720": "카카오",
  "035900": "JYP Ent.",
  "036930": "주성엔지니어링",
  "039030": "이오테크닉스",
  "039440": "에스티아이",
  "041510": "에스엠",
  "042660": "한화오션",
  "042700": "한미반도체",
  "047810": "한국항공우주",
  "051910": "LG화학",
  "055550": "신한지주",
  "058470": "리노공업",
  "064350": "현대로템",
  "066970": "엘앤에프",
  "067310": "하나마이크론",
  "068270": "셀트리온",
  "078930": "GS",
  "079550": "LIG넥스원",
  "086280": "현대글로비스",
  "086520": "에코프로",
  "086790": "하나금융지주",
  "086900": "메디톡스",
  "089030": "테크윙",
  "090360": "로보스타",
  "095340": "ISC",
  "096770": "SK이노베이션",
  "103590": "일진전기",
  "105560": "KB금융",
  "108320": "LX세미콘",
  "108490": "로보티즈",
  "121600": "나노신소재",
  "128940": "한미약품",
  "131970": "두산테스나",
  "138040": "메리츠금융지주",
  "145020": "휴젤",
  "196170": "알테오젠",
  "207940": "삼성바이오로직스",
  "214150": "클래시스",
  "214450": "파마리서치",
  "222800": "심텍",
  "240810": "원익IPS",
  "247540": "에코프로비엠",
  "259960": "크래프톤",
  "267260": "HD현대일렉트릭",
  "272210": "한화시스템",
  "277810": "레인보우로보틱스",
  "278280": "천보",
  "278470": "에이피알",
  "293490": "카카오게임즈",
  "298040": "효성중공업",
  "326030": "SK바이오팜",
  "329180": "HD현대중공업",
  "352820": "하이브",
  "353200": "대덕전자",
  "373220": "LG에너지솔루션",
  "375500": "DL이앤씨",
  "402340": "SK스퀘어",
  "403870": "HPSP",
  "454910": "두산로보틱스",
};

export const US_NAME_MAP: Record<string, string> = {
  AAOI: "Applied Optoelectronics",
  AAPL: "Apple",
  ACHR: "Archer Aviation",
  AI: "C3.ai",
  ALAB: "Astera Labs",
  AMAT: "Applied Materials",
  AMZN: "Amazon",
  ANET: "Arista Networks",
  APP: "AppLovin",
  ASTS: "AST SpaceMobile",
  AVAV: "AeroVironment",
  AVGO: "Broadcom",
  BBAI: "BigBear.ai",
  BMNR: "BitMine Immersion Technologies",
  "BTC-USD": "Bitcoin",
  CAT: "Caterpillar",
  CEG: "Constellation Energy",
  CELH: "Celsius",
  COHR: "Coherent",
  COIN: "Coinbase",
  COST: "Costco",
  CRCL: "Circle Internet Group",
  CRDO: "Credo Technology",
  CRM: "Salesforce",
  CRWD: "CrowdStrike",
  DDOG: "Datadog",
  DUOL: "Duolingo",
  ELF: "e.l.f. Beauty",
  ESTC: "Elastic",
  ETN: "Eaton",
  EXAS: "Exact Sciences",
  GE: "GE Aerospace",
  GLD: "Gold ETF",
  GOOG: "Alphabet",
  GOOGL: "Alphabet",
  HIMS: "Hims & Hers",
  HOOD: "Robinhood",
  HUT: "Hut 8",
  IBIT: "iShares Bitcoin Trust",
  INTC: "Intel",
  ISRG: "Intuitive Surgical",
  IWM: "Russell 2000 ETF",
  JOBY: "Joby Aviation",
  KLAC: "KLA",
  KTOS: "Kratos Defense",
  LITE: "Lumentum",
  LLY: "Eli Lilly",
  LRCX: "Lam Research",
  LUNR: "Intuitive Machines",
  MARA: "MARA Holdings",
  MDB: "MongoDB",
  MELI: "MercadoLibre",
  META: "Meta Platforms",
  MPWR: "Monolithic Power",
  MRVL: "Marvell",
  MSFT: "Microsoft",
  MSTR: "MicroStrategy",
  MU: "Micron",
  NBIS: "Nebius Group",
  NET: "Cloudflare",
  NOW: "ServiceNow",
  NVDA: "NVIDIA",
  NVO: "Novo Nordisk",
  ON: "ON Semiconductor",
  ORCL: "Oracle",
  PANW: "Palo Alto Networks",
  PATH: "UiPath",
  PLTR: "Palantir",
  QQQ: "Nasdaq 100 ETF",
  QUBT: "Quantum Computing",
  RDDT: "Reddit",
  RGTI: "Rigetti",
  RIOT: "Riot Platforms",
  RKLB: "Rocket Lab",
  RXRX: "Recursion",
  S: "SentinelOne",
  SE: "Sea Limited",
  SHOP: "Shopify",
  SIMO: "Silicon Motion",
  SMCI: "Super Micro Computer",
  SMH: "VanEck Semiconductor ETF",
  SMR: "NuScale Power",
  SNDK: "SanDisk",
  SNOW: "Snowflake",
  SOUN: "SoundHound AI",
  SOXX: "Semiconductor ETF",
  SPY: "S&P 500 ETF",
  STX: "Seagate",
  TEM: "Tempus AI",
  TER: "Teradyne",
  TLT: "20Y Treasury ETF",
  TMDX: "TransMedics",
  TSLA: "Tesla",
  TSM: "TSMC",
  VRT: "Vertiv",
  VRTX: "Vertex",
  WDC: "Western Digital",
  WMT: "Walmart",
  XLE: "Energy ETF",
  XLF: "Financial ETF",
  ZS: "Zscaler",
};

export function normalizeMarket(value: any, symbol?: string): "kr" | "us" {
  const raw = String(value || "").toLowerCase();
  if (raw === "kr" || raw === "kospi" || raw === "kosdaq") return "kr";
  if (raw === "us" || raw === "nasdaq" || raw === "nyse" || raw === "amex") return "us";
  return String(symbol || "").match(/^\d{6}$/) ? "kr" : "us";
}

export function normalizeSymbol(item: any): string {
  return String(item?.symbol || item?.code || item?.ticker || "").trim().toUpperCase();
}

function isBadName(raw: string, symbol: string) {
  if (!raw || raw === "-" || raw.toLowerCase() === "nan") return true;
  if (raw.toUpperCase() === symbol.toUpperCase()) return true;
  return /[�占癰沃嶺筌ìíëê]/.test(raw);
}

export function displayName(itemOrSymbol: any, maybeMarket?: string, maybeRaw?: string): string {
  const symbol = typeof itemOrSymbol === "string" ? itemOrSymbol.toUpperCase() : normalizeSymbol(itemOrSymbol);
  const market = normalizeMarket(typeof itemOrSymbol === "string" ? maybeMarket : itemOrSymbol?.market, symbol);
  const raw = String(typeof itemOrSymbol === "string" ? maybeRaw || "" : itemOrSymbol?.name || itemOrSymbol?.company || itemOrSymbol?.companyName || "").trim();
  const mapped = market === "kr" ? KR_NAME_MAP[symbol] : US_NAME_MAP[symbol];
  if (!isBadName(raw, symbol)) return raw;
  if (mapped) return mapped;
  return symbol || "-";
}

export function itemKey(item: any): string {
  const symbol = normalizeSymbol(item);
  const market = normalizeMarket(item?.market, symbol);
  return `${market}-${symbol}`;
}

export function dedupeBySymbol<T extends Record<string, any>>(items: T[] = []): T[] {
  const seen = new Set<string>();
  const out: T[] = [];
  for (const raw of items || []) {
    const symbol = normalizeSymbol(raw);
    if (!symbol) continue;
    const market = normalizeMarket(raw.market, symbol);
    const key = `${market}-${symbol}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...raw, symbol, market, name: displayName(raw) } as T);
  }
  return out;
}

export function toNumber(value: any): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const text = String(value ?? "").replace(/,/g, "").replace(/[^0-9.-]/g, "");
  if (!text || text === "-" || text === ".") return null;
  const n = Number(text);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: any, market: string = "kr", fallback = "-"): string {
  const n = toNumber(value);
  if (n === null || n <= 0) return fallback;
  return normalizeMarket(market) === "us"
    ? `$${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
    : `${Math.round(n).toLocaleString("ko-KR")}원`;
}

export function firstText(...values: any[]): string {
  for (const value of values) {
    if (value === undefined || value === null) continue;
    const text = String(value).trim();
    if (text && text !== "-" && text !== "NaN" && text !== "null" && text !== "undefined") return text;
  }
  return "-";
}

export function priceText(item: any, key: "current" | "entry" | "stop" | "target" | "expected", fallback = "-"): string {
  const market = normalizeMarket(item?.market, normalizeSymbol(item));
  const candidates: Record<string, any[]> = {
    current: [item?.currentPriceText, item?.priceText, item?.currentText, item?.currentPrice, item?.price],
    entry: [item?.entryText, item?.entryPriceText, item?.entryPrice, item?.entry],
    stop: [item?.stopText, item?.stopPriceText, item?.stopLoss, item?.stopPrice, item?.stop],
    target: [item?.targetText, item?.targetPriceText, item?.targetPrice, item?.target],
    expected: [item?.expectedPriceText, item?.expectedText, item?.expectedPrice, item?.expected],
  };
  for (const value of candidates[key]) {
    const text = String(value ?? "").trim();
    if (!text || text === "-") continue;
    if (/[원$]/.test(text)) return text;
    const formatted = formatMoney(value, market, "");
    if (formatted) return formatted;
  }
  return fallback;
}

export function pctText(value: any, fallback = "-"): string {
  const text = String(value ?? "").trim();
  if (text && text !== "-" && text.includes("%")) return text;
  const n = toNumber(value);
  if (n === null) return fallback;
  const signed = n > 0 ? "+" : "";
  return `${signed}${n.toFixed(2)}%`;
}

export function probabilityText(item: any, fallback = "-"): string {
  return firstText(item?.probabilityText, item?.probText, item?.probability ? pctText(item.probability) : null, item?.prob5d ? pctText(item.prob5d) : null, fallback);
}

export function modeLabel(mode: Mode | string): string {
  if (mode === "conservative") return "보수";
  if (mode === "aggressive") return "공격";
  if (mode === "balanced") return "균형";
  return String(mode || "-");
}

export function horizonLabel(horizon: Horizon | string): string {
  if (horizon === "short") return "단기";
  if (horizon === "swing") return "스윙";
  if (horizon === "mid" || horizon === "long") return "중기";
  return String(horizon || "-");
}

export function statusBadge(status?: string): string {
  const value = String(status || "").toUpperCase();
  if (["OK", "NORMAL", "MATCH", "EXECUTED", "WIN"].includes(value)) return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (["ERROR", "NO_DATA", "LOSS", "HIGH"].includes(value)) return "border-red-500/30 bg-red-500/10 text-red-300";
  return "border-amber-500/30 bg-amber-500/10 text-amber-300";
}

export type DataTrustState = "normal" | "partial" | "stale" | "error";

export function dataTrustState(item: any): DataTrustState {
  const raw = [
    item?.dataStatus,
    item?.dataQuality,
    item?.priceStatus,
    item?.ohlcvStatus,
    item?.financialDataStatus,
    item?.sourceStatus,
  ].map((value) => String(value || "").toUpperCase()).filter(Boolean);
  const text = raw.join(" ");
  if (/(ERROR|NO_DATA|NO_PRICE|FAIL|BROKEN)/.test(text)) return "error";
  if (/(STALE|OLD|DELAY)/.test(text)) return "stale";
  if (/(PARTIAL|DATA_PENDING|PENDING|FALLBACK|MISSING|CAUTION)/.test(text)) return "partial";
  return "normal";
}

export function dataTrustLabel(item: any): string {
  const state = dataTrustState(item);
  if (state === "normal") return "정상";
  if (state === "partial") return "일부 데이터 기준";
  if (state === "stale") return "지연 데이터 기준";
  return "데이터 오류 - 신규 판단 주의";
}

export function dataTrustBadgeClass(item: any): string {
  const state = dataTrustState(item);
  if (state === "normal") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (state === "partial") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (state === "stale") return "border-orange-500/30 bg-orange-500/10 text-orange-300";
  return "border-red-500/40 bg-red-500/10 text-red-300";
}

export function dataTrustNotice(item: any): string {
  const state = dataTrustState(item);
  if (state === "error") return "데이터 오류로 후보 신뢰도를 낮췄습니다. 전일/부분 데이터 기준일 수 있습니다.";
  if (state === "stale") return "지연 데이터 기준입니다. 최신 가격 확인 전까지 모의 수량을 보수적으로 봅니다.";
  if (state === "partial") return "일부 데이터 기준입니다. 가격·재무·수급 연결 상태를 함께 확인하세요.";
  return "";
}

export function shouldHideSizingForTrust(item: any): boolean {
  const state = dataTrustState(item);
  return state === "stale" || state === "error";
}

export function sourceStatusLabel(status?: string): string {
  const value = String(status || "").trim();
  const upper = value.toUpperCase();
  if (!value || upper === "MATCH" || upper === "OK" || upper === "NORMAL") return "조건일치";
  if (upper.includes("PARTIAL")) return "일부 조건일치";
  if (upper.includes("STALE")) return "지연 데이터";
  if (upper.includes("ERROR") || upper.includes("NO_DATA")) return "데이터 확인 필요";
  if (/(strategy_horizon|quant_scanner|ohlcv_status|from_source|_v\d+)/i.test(value)) {
    return "전략·기간 조건과 현재가 데이터를 반영했습니다.";
  }
  return value;
}

export function strategyTagLabel(tag?: string): string {
  const value = String(tag || "").trim();
  const upper = value.toUpperCase();
  const labels: Record<string, string> = {
    BB_SQUEEZE: "변동성 압축",
    PULLBACK_BUY: "눌림목",
    STABLE_LOW_RISK: "안정형",
    LOW_RISK_STABLE: "안정형",
    CAUTION: "주의",
    MOMENTUM: "모멘텀",
    FINANCIAL_WEAK: "재무 미확보",
    FINANCIAL_DATA_PENDING: "재무 미확보",
    DATA_PENDING: "재무 미확보",
    MA_CONVERGENCE: "이격도 수렴",
    VOLUME_BREAKOUT: "거래량 증가",
    BREAKOUT_52W: "52주 신고가 돌파",
    NEAR_52W_HIGH: "신고가 근접",
    UNDERVALUED_GROWTH: "저평가 성장주",
    GOLDEN_CROSS: "골든크로스",
    DEATH_CROSS: "데드크로스",
    MID_GOLDEN_CROSS: "중기 골든크로스",
    MID_DEATH_CROSS: "중기 데드크로스",
    TRAILING_STOP_ALERT: "트레일링 손절 주의",
    BREAKOUT: "돌파",
  };
  if (labels[upper]) return labels[upper];
  if (upper.includes("FINANCIAL") && (upper.includes("WEAK") || upper.includes("PENDING"))) return "재무 미확보";
  return value.replaceAll("_", " ");
}

export function sortByValue(items: any[]): any[] {
  return [...items].sort((a, b) => {
    const av = toNumber(a.valuation || a.valuationText || a.currentPrice) || 0;
    const bv = toNumber(b.valuation || b.valuationText || b.currentPrice) || 0;
    return bv - av;
  });
}

export type DataFreshnessState = "fresh" | "caution" | "old" | "unknown";

function normalizeDataDateValue(value: any): string {
  const raw = String(value ?? "").trim();
  if (!raw || raw === "-" || raw.toLowerCase() === "nan") return "";
  if (/^\d{8}$/.test(raw)) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  if (/^\d{4}-\d{2}-\d{2}/.test(raw)) return raw.slice(0, 10);
  return raw;
}

function parseDataDate(value: any): Date | null {
  const normalized = normalizeDataDateValue(value);
  if (!normalized) return null;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return null;
  return date;
}

function businessDaysBetween(from: Date, to: Date): number {
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  const end = new Date(to.getFullYear(), to.getMonth(), to.getDate());
  if (start >= end) return 0;
  let days = 0;
  for (let cursor = new Date(start); cursor < end; cursor.setDate(cursor.getDate() + 1)) {
    const day = cursor.getDay();
    if (day !== 0 && day !== 6) days += 1;
  }
  return days;
}

export function dataFreshnessInfo(item: any, now = new Date()): {
  state: DataFreshnessState;
  label: string;
  basisText: string;
  latestDate: string;
} {
  const status = String(item?.dataStatus || item?.status || "").toUpperCase();
  const latestDate = normalizeDataDateValue(
    item?.latestDataDate ||
      item?.dataDate ||
      item?.sourceDate ||
      item?.ohlcvLatestDate ||
      item?.priceDate ||
      item?.tradeDate ||
      item?.date,
  );
  const generatedAt = firstText(item?.recoGeneratedAt, item?.generatedAt, item?.updatedAt, item?.createdAt, "");

  // ohlcvLatestDate 없으면 recoGeneratedAt 날짜를 대체 사용
  const effectiveDate = latestDate || (status !== "NO_DATA" ? normalizeDataDateValue(generatedAt) : "");

  if (!effectiveDate || status === "NO_DATA") {
    return {
      state: "unknown",
      label: "확인 필요",
      basisText: generatedAt !== "-" ? `추천 생성: ${generatedAt.slice(0, 16).replace("T", " ")}` : "데이터 기준: 확인 필요",
      latestDate: "",
    };
  }

  const date = parseDataDate(effectiveDate);
  if (!date) {
    return { state: "unknown", label: "확인 필요", basisText: `데이터 기준: ${effectiveDate}`, latestDate: effectiveDate };
  }

  const age = businessDaysBetween(date, now);
  const state: DataFreshnessState = age <= 0 ? "fresh" : age === 1 ? "caution" : "old";
  const label = state === "fresh" ? "최신" : state === "caution" ? "주의" : "오래됨";
  const basisText = latestDate
    ? `데이터 기준: ${latestDate}`
    : `추천 생성: ${generatedAt.slice(0, 16).replace("T", " ")}`;
  return {
    state,
    label,
    basisText,
    latestDate: effectiveDate,
  };
}

export function dataFreshnessBadgeClass(state: DataFreshnessState): string {
  if (state === "fresh") return "border-emerald-500/30 bg-emerald-500/10 text-emerald-300";
  if (state === "caution") return "border-amber-500/30 bg-amber-500/10 text-amber-300";
  if (state === "old") return "border-orange-500/30 bg-orange-500/10 text-orange-300";
  return "border-red-500/30 bg-red-500/10 text-red-300";
}

export function moneReasonLines(item: any): string[] {
  const explicit = firstText(
    item?.moneReason,
    item?.decisionReason,
    item?.reason,
    item?.patternStrategy?.reason,
    item?.patternReason,
    item?.entryReason,
    item?.summary,
    "",
  );
  if (explicit !== "-") {
    const split = explicit
      .replace(/\r?\n/g, " ")
      .split(/(?:[.!?。]| · | \| )\s*/)
      .map((line) => line.trim())
      .filter((line) => line.length >= 4 && !/^[-–—]+$/.test(line));
    if (split.length) return split.slice(0, 3);
  }

  const lines: string[] = [];
  const finalScore = toNumber(item?.finalScore);
  const upsideScore = toNumber(item?.upsideScore);
  const entryScore = toNumber(item?.entryScore);
  const current = toNumber(item?.currentPrice ?? item?.price);
  const entry = toNumber(item?.entryPrice ?? item?.entry);
  const risk = String(item?.riskStatus || item?.tradeBlockStatus || item?.riskLevel || "").toUpperCase();
  const gapPct = current && entry ? Math.abs((current - entry) / entry) * 100 : null;

  if ((upsideScore ?? finalScore ?? 0) >= 65 || String(item?.trend || item?.direction || "").toUpperCase().includes("UP")) {
    lines.push("상승 추세가 유지되고 있습니다.");
  } else {
    lines.push("추세 조건을 확인하며 선별 접근이 필요합니다.");
  }

  if ((entryScore ?? 0) >= 60 || (gapPct !== null && gapPct <= 5)) {
    lines.push("기준가 근처에서 진입 접근성이 높습니다.");
  } else {
    lines.push("기준가와 현재가 차이를 확인한 뒤 접근하세요.");
  }

  if (!risk || ["NONE", "OK", "NORMAL", "LOW"].includes(risk)) {
    lines.push("위험 패턴은 아직 감지되지 않았습니다.");
  } else {
    lines.push("위험 상태가 있어 손절 기준을 먼저 확인해야 합니다.");
  }

  return lines.slice(0, 3);
}
