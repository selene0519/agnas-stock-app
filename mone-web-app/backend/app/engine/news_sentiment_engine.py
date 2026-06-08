"""
MONE Phase 6 — News & Disclosure Sentiment Engine
공시(DART/SEC)와 뉴스 제목에서 종목별 감성 신호를 추출해
quant_scanner의 newsRiskPenalty를 실제 데이터로 대체한다.

설계 원칙:
- 비차단(non-blocking): 오류 시 RSI 대리 값으로 폴백
- 캐시 우선: 6시간 유효, 갱신은 build_sentiment_cache() 호출
- 과신 방지: 공시 신호 > 뉴스 신호, 근거 없는 확장 금지
"""
from __future__ import annotations

import csv
import json
import re
import time
from pathlib import Path
from typing import Any

# ── 경로 ─────────────────────────────────────────────────────────────────
import os
_APP_DIR = Path(__file__).resolve().parents[4]  # backend/app/engine → backend/app → backend → mone-web-app → repo root
REPO_ROOT = Path(os.environ.get("MONE_REPO_ROOT", _APP_DIR)).resolve()
REPORT_DIR = REPO_ROOT / "reports"
DISCLOSURE_DIR = REPO_ROOT / "data" / "disclosures"
CACHE_TTL_SEC = 6 * 3600  # 6시간

# ── 공시 키워드 분류 ──────────────────────────────────────────────────────
# penalty: 0~20 (높을수록 나쁨)
_DISCLOSURE_RULES: list[tuple[list[str], float, str]] = [
    # 강한 매도 신호 (KR)
    (["유상증자", "주주배정", "일반공모증자"], 15.0, "유상증자(주식 희석)"),
    (["불성실공시", "공시변경"], 12.0, "불성실공시"),
    (["상장폐지", "관리종목지정", "투자주의종목"], 18.0, "상장폐지/관리종목"),
    (["횡령", "배임", "사기", "검찰", "기소"], 16.0, "법적 리스크"),
    (["감자", "주식병합"], 14.0, "감자(자본 축소)"),
    (["정정신고서제출요구"], 10.0, "정정신고 요구"),
    (["손실", "부도", "파산", "기업회생"], 18.0, "재무 위기"),
    # 중간 신호 (KR)
    (["소송", "분쟁", "제재"], 8.0, "법적 분쟁"),
    (["임원변경", "대표이사변경"], 4.0, "경영진 변동"),
    # 강한 매수 신호 (KR)
    (["자기주식취득결정", "자기주식매입", "자사주매입"], -6.0, "자사주매입(주주환원)"),
    (["무상증자"], -4.0, "무상증자(주주친화)"),
    (["실적개선", "흑자전환", "최대실적"], -5.0, "실적 개선"),
    (["계약체결", "수주", "협약체결"], -3.0, "수주/계약"),
    (["임상시험계획승인", "품목허가", "FDA"], -3.0, "임상/허가 승인"),
    # 중립 (KR)
    (["기재정정", "분기보고서", "반기보고서", "사업보고서"], 0.0, "정기보고"),
    # SEC / 영어 공시 (US)
    (["SEC investigation", "SEC probe", "SEC charges", "SEC enforcement"], 16.0, "SEC 조사/제재"),
    (["class action", "shareholder lawsuit", "securities fraud"], 14.0, "집단소송"),
    (["delisted", "delisting", "going concern"], 18.0, "상장폐지 위험"),
    (["bankruptcy", "Chapter 11", "Chapter 7", "insolvency"], 18.0, "파산"),
    (["restatement", "material weakness", "accounting error"], 14.0, "회계 오류"),
    (["DOJ", "DOJ investigation", "criminal charges", "indicted"], 15.0, "형사 조사"),
    (["buyback", "share repurchase", "stock buyback"], -5.0, "자사주매입"),
    (["dividend increase", "special dividend"], -4.0, "배당 증가"),
    (["acquisition", "merger agreement", "definitive agreement"], -3.0, "M&A 계약"),
    (["FDA approval", "approved by FDA", "NDA approval"], -5.0, "FDA 승인"),
]

# ── 뉴스 감성 키워드 ──────────────────────────────────────────────────────
_NEWS_POSITIVE: list[str] = [
    "상승", "급등", "신고가", "매수", "호재", "흑자", "실적 개선", "반등",
    "돌파", "강세", "외국인 순매수", "기관 순매수", "수출 증가", "성장",
    "투자확대", "수주", "계약", "승인", "허가", "반등",
    # English
    "surges", "jumps", "rally", "bullish", "upgrade", "beat", "record high",
    "breakthrough", "approved", "contract", "buyback", "dividend",
]
_NEWS_NEGATIVE: list[str] = [
    "하락", "급락", "매도", "악재", "적자", "손실", "리콜", "소송",
    "약세", "외국인 순매도", "기관 순매도", "수출 감소", "위기",
    "파산", "검찰", "횡령", "제재", "경고", "경계",
    # English
    "plunges", "drops", "falls", "declines", "decline", "slides", "tumbles",
    "crash", "slumps", "downgrade", "cuts price", "lowers price", "cut price",
    "price target cut", "price target lower", "reduces price",
    "loss", "losses", "lawsuit", "probe", "investigation", "regulatory",
    "violation", "fine", "recall", "bankruptcy", "fraud",
    "warning", "concern", "risk", "rejected", "blocked", "halted",
    "suspended", "delisted", "underperform", "underperforms",
    "more than market", "below expectations", "misses",
    "weakness", "headwind", "selloff", "sell-off", "pressured",
    "weighs on", "underperforming",
]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size < 10:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _norm_sym(s: str, market: str) -> str:
    raw = str(s or "").strip()
    if market == "kr":
        digits = re.sub(r"\D", "", raw)
        return digits.zfill(6) if digits else ""
    return raw.upper()


def _score_disclosure_title(title: str) -> tuple[float, str]:
    """공시 제목 → (penalty_delta, reason). 여러 규칙 중 가장 큰 절댓값 적용."""
    best_delta = 0.0
    best_reason = ""
    for keywords, delta, reason in _DISCLOSURE_RULES:
        for kw in keywords:
            if kw in title:
                if abs(delta) > abs(best_delta):
                    best_delta = delta
                    best_reason = reason
                break
    return best_delta, best_reason


def _score_news_title(title: str, name: str, *, symbol_matched: bool = False) -> float:
    """뉴스 제목 감성 점수 반환 (-3~+5).
    symbol_matched=True이면 종목코드로 이미 매칭된 기사 → 이름 확인 생략.
    """
    title_lower = title.lower()
    if not symbol_matched:
        if name and len(name) >= 2 and name not in title and name.lower() not in title_lower:
            return 0.0  # 종목명 미언급 → 무관 뉴스
    pos = sum(1 for kw in _NEWS_POSITIVE if kw in title or kw in title_lower)
    neg = sum(1 for kw in _NEWS_NEGATIVE if kw in title or kw in title_lower)
    if neg > pos:
        return min(5.0, (neg - pos) * 2.5)
    if pos > neg:
        return max(-3.0, -(pos - neg) * 1.5)
    return 0.0


def _parse_news_date(row: dict[str, str]) -> str:
    """뉴스 행의 게시시간을 YYYY-MM-DD 형식으로 반환. 파싱 실패 시 ''."""
    raw = str(row.get("게시시간", "") or row.get("publishedAt", "") or row.get("published_at", "")).strip()
    if not raw:
        return ""
    if raw.isdigit():
        try:
            import datetime
            return datetime.datetime.fromtimestamp(int(raw)).strftime("%Y-%m-%d")
        except Exception:
            return ""
    return raw[:10]  # ISO 형식 앞 10자


def _build_symbol_sentiment(
    market: str,
    symbols: list[tuple[str, str]],  # [(symbol, name), ...]
    as_of_date: str = "",
) -> dict[str, dict[str, Any]]:
    """종목별 감성 점수 계산. 결과 dict key = symbol."""
    result: dict[str, dict[str, Any]] = {}

    # ── 공시 스캔 ──────────────────────────────────────────────────────────
    disc_path = DISCLOSURE_DIR / f"disclosures_{market}.csv"
    disc_rows = _read_csv_rows(disc_path)
    disc_by_sym: dict[str, list[dict[str, str]]] = {}
    for row in disc_rows:
        sym = _norm_sym(row.get("symbol", "") or row.get("종목코드", ""), market)
        if sym:
            disc_by_sym.setdefault(sym, []).append(row)

    # ── 뉴스 스캔 ──────────────────────────────────────────────────────────
    news_path = REPORT_DIR / f"news_summary_{market}.csv"
    news_rows = _read_csv_rows(news_path)

    # 종목코드별 뉴스 인덱스 (날짜 필터 적용)
    news_by_sym: dict[str, list[dict[str, str]]] = {}
    for row in news_rows:
        sym = _norm_sym(row.get("종목코드", "") or row.get("symbol", ""), market)
        if not sym:
            continue
        if as_of_date:
            row_date = _parse_news_date(row)
            if row_date and row_date > as_of_date:
                continue  # 신호 날짜 이후 기사 제외
        news_by_sym.setdefault(sym, []).append(row)

    for symbol, name in symbols:
        sym_norm = _norm_sym(symbol, market)
        reasons: list[str] = []
        penalty = 0.0

        # 1) 공시 신호 (최근 30일 행만)
        disc_hits = disc_by_sym.get(sym_norm, [])
        for row in disc_hits[:10]:
            title = row.get("title", "") or row.get("공시제목", "")
            delta, reason = _score_disclosure_title(title)
            if delta != 0.0:
                penalty = max(-6.0, min(18.0, penalty + delta))
                if reason and reason not in reasons:
                    reasons.append(reason)

        # 2) 뉴스 신호: 종목코드 매칭 우선, 없으면 이름 매칭
        news_adj = 0.0
        sym_news = news_by_sym.get(sym_norm, [])
        if sym_news:
            # 종목코드로 직접 매칭된 뉴스 (이름 확인 불필요)
            for row in sym_news[:20]:
                title = row.get("제목", "") or row.get("title", "")
                news_adj += _score_news_title(title, name, symbol_matched=True)
        else:
            # 일반 뉴스에서 종목명 언급 검색 (날짜 필터 + 최대 30건)
            filtered_news = news_rows
            if as_of_date:
                filtered_news = [r for r in news_rows if not _parse_news_date(r) or _parse_news_date(r) <= as_of_date]
            for row in filtered_news[:30]:
                title = row.get("제목", "") or row.get("title", "")
                news_adj += _score_news_title(title, name)
        news_adj = max(-3.0, min(5.0, news_adj))
        penalty += news_adj

        # 최종 clamp (0~20)
        penalty = max(0.0, min(20.0, penalty))

        # 태그 결정
        if penalty >= 12:
            tag = "HIGH_RISK"
        elif penalty >= 6:
            tag = "CAUTION"
        elif penalty <= -3:
            tag = "POSITIVE"
        else:
            tag = "NEUTRAL"

        result[sym_norm] = {
            "symbol": sym_norm,
            "name": name,
            "penalty": round(penalty, 1),
            "tag": tag,
            "reasons": reasons[:3],
            "disclosureHits": len(disc_hits),
            "newsAdj": round(news_adj, 1),
        }
    return result


def build_sentiment_cache(market: str, symbols: list[tuple[str, str]]) -> dict[str, Any]:
    """감성 캐시를 (재)빌드해 파일로 저장하고 반환한다."""
    cache_path = REPORT_DIR / f"news_sentiment_cache_{market}.json"
    data = _build_symbol_sentiment(market, symbols)
    payload: dict[str, Any] = {
        "market": market,
        "built_at": time.time(),
        "count": len(data),
        "data": data,
    }
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        with cache_path.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        pass
    return payload


def load_sentiment_cache(market: str) -> dict[str, dict[str, Any]]:
    """캐시 로드. 만료됐거나 없으면 빈 dict 반환 (폴백 트리거용)."""
    cache_path = REPORT_DIR / f"news_sentiment_cache_{market}.json"
    try:
        if not cache_path.exists():
            return {}
        with cache_path.open("r", encoding="utf-8") as f:
            payload = json.load(f)
        age = time.time() - float(payload.get("built_at", 0))
        if age > CACHE_TTL_SEC:
            return {}  # 만료
        return payload.get("data", {})
    except Exception:
        return {}


def score_news_sentiment(
    market: str,
    symbol: str,
    name: str,
    *,
    cache: dict[str, dict[str, Any]] | None = None,
    as_of_date: str = "",
) -> dict[str, Any]:
    """
    단일 종목 감성 점수 반환.
    cache를 외부에서 미리 로드해 전달하면 I/O 절감.

    반환:
        penalty   float  0~20  (quant_scanner newsRiskPenalty 대체)
        tag       str    NEUTRAL / POSITIVE / CAUTION / HIGH_RISK
        reasons   list[str]
    """
    sym_norm = _norm_sym(symbol, market)
    # 날짜 필터가 있으면 캐시 우회 (캐시는 날짜 비구분으로 저장됨)
    if not as_of_date:
        _cache = cache if cache is not None else load_sentiment_cache(market)
        if sym_norm in _cache:
            return _cache[sym_norm]
    # 캐시 미스 또는 날짜 필터 요청 → 즉시 계산
    result = _build_symbol_sentiment(market, [(symbol, name)], as_of_date=as_of_date)
    return result.get(sym_norm, {"penalty": 0.0, "tag": "NEUTRAL", "reasons": []})
