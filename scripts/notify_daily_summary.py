"""
MONE 일일 요약 텔레그램 알림.

추천 데이터 생성 후 자동 호출:
  - 국장/미장 오늘 진입 후보 TOP 3
  - 이번 주 국장 실적발표 일정 (Alpha Vantage)
  - 이번 주 미장 실적발표 일정 (Finnhub)
  - 주요 경제 지표 일정 (Finnhub)
  - DART 주요 공시

환경변수:
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
  FINNHUB_API_KEY
  DART_API_KEY
  ALPHA_VANTAGE_KEY
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT     = Path(__file__).resolve().parents[1]
REPORTS  = ROOT / "reports"
MODES    = ("conservative", "balanced", "aggressive")
HORIZONS = ("short", "swing", "mid")

BOT_TOKEN  = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID    = os.environ.get("TELEGRAM_CHAT_ID", "")
FINNHUB_KEY   = os.environ.get("FINNHUB_API_KEY", "")
DART_KEY      = os.environ.get("DART_API_KEY", "")
AV_KEY        = os.environ.get("ALPHA_VANTAGE_KEY", "")
GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "")
DRY_RUN       = os.environ.get("NOTIFY_DRY_RUN", "0") == "1"


# ── 텔레그램 전송 ─────────────────────────────────────────────────────────────

def _send(text: str) -> bool:
    if DRY_RUN:
        print("[DRY_RUN] 전송 생략:\n" + text[:300])
        return True
    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 없음 — 전송 생략")
        return False
    try:
        data = json.dumps({
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as e:
        print(f"텔레그램 전송 오류: {e}")
        return False


# ── CSV 읽기 ──────────────────────────────────────────────────────────────────

def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open("r", encoding=enc, newline="") as f:
                return list(csv.DictReader(f))
        except Exception:
            continue
    return []


def _num(v: Any) -> float:
    try:
        return float(str(v or "").replace(",", "").strip())
    except Exception:
        return 0.0


# ── 추천 종목 요약 ────────────────────────────────────────────────────────────

def _collect_recommendations(market: str) -> list[dict]:
    """모든 전략/기간에서 추천 종목 수집 후 EV/점수 기준 정렬."""
    seen: dict[str, dict] = {}
    for mode in MODES:
        for horizon in HORIZONS:
            path = REPORTS / f"mone_v36_final_recommendations_{market}_{mode}_{horizon}.csv"
            for row in _read_csv(path):
                sym = str(row.get("symbol", "")).strip()
                if not sym:
                    continue
                ev = _num(row.get("expectedValue") or row.get("ev") or 0)
                score = _num(row.get("finalScore") or row.get("score") or 0)
                bucket = str(row.get("decisionBucket") or "").strip()
                block = str(row.get("tradeBlockStatus") or "").upper()
                if block in ("BLOCK", "CAUTION") or ev < 0:
                    continue
                key = f"{sym}_{market}"
                if key not in seen or ev > _num(seen[key].get("ev", 0)):
                    seen[key] = {
                        "symbol": sym,
                        "name": str(row.get("name") or row.get("companyName") or sym),
                        "market": market,
                        "mode": mode,
                        "horizon": horizon,
                        "ev": ev,
                        "score": score,
                        "entry": _num(row.get("entry") or row.get("entryPrice") or 0),
                        "stop": _num(row.get("stop") or row.get("stopPrice") or 0),
                        "target": _num(row.get("target") or row.get("targetPrice") or 0),
                        "current": _num(row.get("currentPrice") or 0),
                        "bucket": bucket,
                    }
    return sorted(seen.values(), key=lambda x: x["ev"], reverse=True)


def _fmt_mode(m: str) -> str:
    return {"conservative": "보수", "balanced": "균형", "aggressive": "공격"}.get(m, m)

def _fmt_horizon(h: str) -> str:
    return {"short": "단기", "swing": "스윙", "mid": "중기"}.get(h, h)

def _fmt_price(v: float, market: str) -> str:
    if v <= 0:
        return "-"
    return f"${v:,.2f}" if market == "us" else f"{round(v):,}원"


def build_recommendation_section(market: str) -> str:
    items = _collect_recommendations(market)
    top = [i for i in items if i["bucket"] == "오늘 진입"][:3]
    if not top:
        top = items[:3]

    label = "🇰🇷 국장" if market == "kr" else "🇺🇸 미장"
    if not top:
        return f"{label} 오늘 진입 후보 없음\n"

    lines = [f"<b>{label} 오늘 진입 후보</b>"]
    for i, r in enumerate(top, 1):
        tag = "🟢" if r["bucket"] == "오늘 진입" else "🟡"
        lines.append(
            f"{tag} {i}. <b>{r['name']}</b> ({r['symbol']})"
            f" [{_fmt_mode(r['mode'])} · {_fmt_horizon(r['horizon'])}]"
        )
        if r["current"] > 0:
            lines.append(f"   현재 {_fmt_price(r['current'], market)}")
        lines.append(
            f"   진입 {_fmt_price(r['entry'], market)} "
            f"| 손절 {_fmt_price(r['stop'], market)} "
            f"| 목표 {_fmt_price(r['target'], market)}"
        )
        lines.append(f"   EV <b>{r['ev']:+.1f}%</b>  점수 {r['score']:.0f}점")

        # 종목별 최신 뉴스 1줄
        news_list = (
            _finnhub_company_news(r["symbol"]) if market == "us"
            else _gnews_company_news(r["name"], r["symbol"])
        )
        if news_list:
            art   = news_list[0]
            title = _shorten(art.get("headline") or art.get("title") or "", 50)
            src   = art.get("source") or ""
            if isinstance(src, dict):
                src = src.get("name", "")
            if title:
                lines.append(f"   📰 <i>{title}</i>" + (f" ({src})" if src else ""))

    return "\n".join(lines)


# ── 종목별 뉴스 + 시장 뉴스 ──────────────────────────────────────────────────

def _finnhub_company_news(symbol: str, days: int = 3) -> list[dict]:
    """Finnhub 종목별 최신 뉴스 (미장용)."""
    if not FINNHUB_KEY:
        return []
    today = datetime.now()
    frm   = (today - timedelta(days=days)).strftime("%Y-%m-%d")
    to    = today.strftime("%Y-%m-%d")
    data  = _finnhub_get(f"/company-news?symbol={symbol}&from={frm}&to={to}")
    if not data or not isinstance(data, list):
        return []
    return data[:2]


def _gnews_company_news(name: str, symbol: str) -> list[dict]:
    """GNews 종목별 최신 뉴스 (국장용)."""
    if not AV_KEY and not GNEWS_API_KEY:
        return []
    query = urllib.parse.quote(name or symbol)
    url = (
        f"https://gnews.io/api/v4/search"
        f"?q={query}&lang=ko&max=2&apikey={GNEWS_API_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MONE/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data.get("articles", [])[:2]
    except Exception:
        return []


def _finnhub_market_news(category: str = "general") -> list[dict]:
    """Finnhub 시장 전체 뉴스."""
    data = _finnhub_get(f"/news?category={category}")
    if not data or not isinstance(data, list):
        return []
    return data[:4]


def _gnews_market_news() -> list[dict]:
    """GNews 국장 시장 뉴스."""
    if not GNEWS_API_KEY:
        return []
    url = (
        f"https://gnews.io/api/v4/top-headlines"
        f"?topic=business&lang=ko&country=kr&max=4&apikey={GNEWS_API_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MONE/1.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        return data.get("articles", [])[:4]
    except Exception:
        return []


def _shorten(text: str, max_len: int = 50) -> str:
    text = str(text or "").strip()
    return text if len(text) <= max_len else text[:max_len - 1] + "…"


def build_stock_news_for(items: list[dict], market: str) -> str:
    """추천 종목별 최신 뉴스 1줄씩."""
    lines = []
    for r in items[:3]:
        sym  = r["symbol"]
        name = r["name"]
        news_list = (
            _finnhub_company_news(sym) if market == "us"
            else _gnews_company_news(name, sym)
        )
        if not news_list:
            continue
        art = news_list[0]
        title = _shorten(
            art.get("headline") or art.get("title") or "", 50
        )
        src = art.get("source") or art.get("source", {})
        if isinstance(src, dict):
            src = src.get("name", "")
        if title:
            lines.append(f"   📰 <i>{title}</i> ({src})")
        # 해당 종목 섹션 아래 삽입될 수 있도록 종목명 태그
        r["_news_line"] = lines[-1] if lines else ""
    return ""  # 종목 카드 안에 삽입하는 방식으로 변경


def build_market_news_section(market: str) -> str:
    """시장 전체 뉴스 요약."""
    if market == "us":
        articles = _finnhub_market_news("general")
        label = "🌐 <b>미장 시장 뉴스</b>"
    else:
        articles = _gnews_market_news()
        label = "🌐 <b>국장 시장 뉴스</b>"

    if not articles:
        return ""

    lines = [f"\n{label}"]
    for art in articles[:4]:
        title = _shorten(
            art.get("headline") or art.get("title") or "", 55
        )
        src = art.get("source") or ""
        if isinstance(src, dict):
            src = src.get("name", "")
        if title:
            lines.append(f"  • {title}" + (f" ({src})" if src else ""))
    return "\n".join(lines) if len(lines) > 1 else ""


# ── Alpha Vantage 실적 캘린더 (KR) ───────────────────────────────────────────

def build_kr_earnings_section() -> str:
    """Alpha Vantage EARNINGS_CALENDAR로 국장 실적발표 일정 조회.
    KRX 종목은 005930.KS (KOSPI) / 000660.KQ (KOSDAQ) 형태.
    """
    if not AV_KEY:
        return ""
    today = datetime.now()
    end   = today + timedelta(days=14)

    # 추천/보유 종목 심볼 수집
    symbols: list[str] = []
    for mode in MODES:
        for horizon in HORIZONS:
            for row in _read_csv(REPORTS / f"mone_v36_final_recommendations_kr_{mode}_{horizon}.csv"):
                s = str(row.get("symbol", "")).strip()
                if s and s not in symbols:
                    symbols.append(s)
    holdings_path = ROOT / "holdings_kr.csv"
    for row in _read_csv(holdings_path):
        s = str(row.get("symbol", "")).strip()
        if s and s not in symbols:
            symbols.append(s)

    if not symbols:
        return ""

    hits: list[dict] = []
    # 각 종목별로 조회 (상위 15개만 — API 호출 횟수 절약)
    for sym in symbols[:15]:
        # KOSPI: 6자리 → .KS, KOSDAQ 종목은 구분이 어려워 .KS 우선
        av_sym = f"{sym}.KS"
        url = (
            f"https://www.alphavantage.co/query"
            f"?function=EARNINGS_CALENDAR&symbol={av_sym}&horizon=3month&apikey={AV_KEY}"
        )
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MONE/1.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                content = r.read().decode("utf-8")
            # CSV 형식으로 반환됨
            reader = csv.DictReader(content.splitlines())
            for row in reader:
                report_date = row.get("reportDate", "")
                if not report_date:
                    continue
                try:
                    rd = datetime.strptime(report_date, "%Y-%m-%d")
                except Exception:
                    continue
                if today <= rd <= end:
                    hits.append({
                        "symbol": sym,
                        "name": row.get("name", sym),
                        "date": report_date,
                        "estimate": row.get("estimate", ""),
                        "currency": row.get("currency", "KRW"),
                    })
        except Exception:
            continue

    if not hits:
        return ""

    hits.sort(key=lambda x: x["date"])
    lines = ["\n📅 <b>국장 실적발표 일정 (2주 이내)</b>"]
    for h in hits[:6]:
        est = f" — EPS 예상 {h['estimate']}" if h.get("estimate") else ""
        lines.append(f"  • {h['date']} <b>{h['name']}</b> ({h['symbol']}){est}")
    return "\n".join(lines)


# ── Finnhub 실적 캘린더 (US) ─────────────────────────────────────────────────

def _finnhub_get(path: str) -> Any:
    if not FINNHUB_KEY:
        return None
    url = f"https://finnhub.io/api/v1{path}&token={FINNHUB_KEY}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"Finnhub 오류: {e}")
        return None


def _av_us_earnings(today: datetime, end: datetime) -> list[dict]:
    """Alpha Vantage로 미장 실적발표 조회 (Finnhub 폴백용)."""
    if not AV_KEY:
        return []
    today_s = today.strftime("%Y-%m-%d")
    end_s   = end.strftime("%Y-%m-%d")
    # 심볼 없이 전체 조회 → US 주요 종목 CSV 반환
    url = f"https://www.alphavantage.co/query?function=EARNINGS_CALENDAR&horizon=3month&apikey={AV_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MONE/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            content = r.read().decode("utf-8")
        results = []
        for row in csv.DictReader(content.splitlines()):
            sym = str(row.get("symbol", ""))
            rd  = str(row.get("reportDate", "")).strip()
            # KR 종목(.KS/.KQ) 제외, US 종목만
            if ".KS" in sym or ".KQ" in sym or not rd:
                continue
            if today_s <= rd <= end_s:
                est = row.get("estimate", "")
                if est:
                    results.append({
                        "date": rd,
                        "symbol": sym,
                        "estimate": est,
                        "currency": row.get("currency", "USD"),
                    })
        return sorted(results, key=lambda x: x["date"])[:8]
    except Exception as e:
        print(f"Alpha Vantage US 폴백 오류: {e}")
        return []


def build_earnings_section() -> str:
    today = datetime.now()
    end   = today + timedelta(days=5)

    # 1차: Finnhub
    data  = _finnhub_get(
        f"/calendar/earnings?from={today.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}"
    )
    important = []
    source = "Finnhub"
    if data:
        all_items = data.get("earningsCalendar", []) or []
        important = [
            x for x in all_items
            if x.get("epsEstimate") and abs(_num(x.get("epsEstimate"))) > 0
        ][:8]

    # 2차: Finnhub 실패 또는 결과 없으면 Alpha Vantage 폴백
    if not important:
        print("Finnhub 미장 실적 없음 → Alpha Vantage 폴백")
        av_items = _av_us_earnings(today, end)
        if av_items:
            source = "Alpha Vantage"
            lines = [f"\n📅 <b>이번 주 미장 실적발표</b> <i>(via {source})</i>"]
            for x in av_items:
                lines.append(f"  • {x['date']} <b>{x['symbol']}</b> — EPS 예상 ${x['estimate']}")
            return "\n".join(lines)
        return ""

    lines = [f"\n📅 <b>이번 주 미장 실적발표</b>"]
    for x in important:
        date = x.get("date", "")
        sym  = x.get("symbol", "")
        eps  = x.get("epsEstimate")
        hour = "장전" if x.get("hour") == "bmo" else ("장후" if x.get("hour") == "amc" else "")
        tag  = f" ({hour})" if hour else ""
        lines.append(f"  • {date} <b>{sym}</b>{tag} — EPS 예상 ${eps}")
    return "\n".join(lines)


def build_economic_section() -> str:
    today = datetime.now()
    end   = today + timedelta(days=3)
    data  = _finnhub_get(
        f"/calendar/economic?from={today.strftime('%Y-%m-%d')}&to={end.strftime('%Y-%m-%d')}"
    )
    if not data:
        return ""
    items = data.get("economicCalendar", []) or []
    # 중요도 HIGH만
    high = [x for x in items if str(x.get("impact", "")).upper() == "HIGH"][:5]
    if not high:
        return ""
    lines = ["\n📊 <b>주요 경제지표 (HIGH impact)</b>"]
    for x in high:
        date  = x.get("time", x.get("date", ""))[:10]
        event = x.get("event", "")
        country = x.get("country", "")
        lines.append(f"  • {date} [{country}] {event}")
    return "\n".join(lines)


# ── DART 주요 공시 (KR) ───────────────────────────────────────────────────────

def build_dart_section() -> str:
    if not DART_KEY:
        return ""
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    try:
        params = urllib.parse.urlencode({
            "crtfc_key": DART_KEY,
            "bgn_de": yesterday,
            "end_de": today,
            "sort": "date",
            "sort_mth": "desc",
            "page_count": 10,
        })
        url = f"https://opendart.fss.or.kr/api/list.json?{params}"
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"DART 오류: {e}")
        return ""

    items = data.get("list", []) or []
    # 중요 공시 키워드 필터
    keywords = ("실적", "배당", "유상증자", "합병", "대규모", "자기주식", "소송", "계약")
    important = [
        x for x in items
        if any(kw in str(x.get("report_nm", "")) for kw in keywords)
    ][:5]
    if not important:
        return ""
    lines = ["\n📢 <b>국장 주요 공시</b>"]
    for x in important:
        corp = x.get("corp_name", "")
        title = x.get("report_nm", "")[:30]
        date = x.get("rcept_dt", "")
        lines.append(f"  • {date} <b>{corp}</b> — {title}")
    return "\n".join(lines)


# ── 메인 ──────────────────────────────────────────────────────────────────────

def _parse_market_arg() -> str:
    """CLI: python notify_daily_summary.py --market kr|us|all"""
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--market" and i + 1 < len(args):
            return args[i + 1].lower()
        if a.startswith("--market="):
            return a.split("=", 1)[1].lower()
    return "all"


def main() -> None:
    market = _parse_market_arg()
    if market not in ("kr", "us", "all"):
        market = "all"

    now = datetime.now().strftime("%Y-%m-%d %H:%M KST")
    mkt_label = {"kr": "🇰🇷 국장", "us": "🇺🇸 미장", "all": "국장+미장"}[market]
    print(f"[{now}] 일일 요약 알림 시작 (market={market})")

    sections = [f"🤖 <b>MONE {mkt_label} 투자 점검</b>\n{now}"]

    # 국장 블록
    if market in ("kr", "all"):
        kr_mkt = build_market_news_section("kr")
        if kr_mkt:
            sections.append(kr_mkt)
        kr_rec = build_recommendation_section("kr")
        if kr_rec:
            sections.append("\n" + kr_rec)
        kr_earn = build_kr_earnings_section()
        if kr_earn:
            sections.append(kr_earn)
        dart = build_dart_section()
        if dart:
            sections.append(dart)

    # 미장 블록
    if market in ("us", "all"):
        us_mkt = build_market_news_section("us")
        if us_mkt:
            sections.append(us_mkt)
        us_rec = build_recommendation_section("us")
        if us_rec:
            sections.append("\n" + us_rec)
        us_earn = build_earnings_section()
        if us_earn:
            sections.append(us_earn)

    # 공통 매크로 (경제지표) — 미장 포함 시에만
    if market in ("us", "all"):
        economic = build_economic_section()
        if economic:
            sections.append(economic)

    sections.append("\n<a href='https://mone-by-agnas.vercel.app'>📱 MONE 앱 열기</a>")

    message = "\n".join(sections)
    # 텔레그램 최대 4096자 제한
    if len(message) > 4000:
        message = message[:3980] + "\n...(생략)"
    print(f"메시지 길이: {len(message)}자")

    ok = _send(message)
    print("전송 완료" if ok else "전송 실패")


if __name__ == "__main__":
    main()
