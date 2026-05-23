"""v50 안정판 운영 엔진.

v46~v50의 목표를 하나로 묶은 보수적 안정화 모듈입니다.
- v46: 자동 운영 상태 확인
- v47: 뉴스·내러티브 카드 정리
- v48: 재무·가치·KPI 상태/요약 카드
- v49: 보유/매도/권장수량 보강
- v50: 일반모드 안정판용 구조 점검 리포트

이 모듈은 주문을 실행하지 않습니다. 로컬/GitHub Actions에서 CSV/JSON 리포트만 생성합니다.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

try:
    from core.v43_operational_engine import (
        ROOT, DATA_DIR, REPORT_DIR, read_csv_safe, read_json_safe, write_json,
        get_secret, to_num, first, label_for_symbol, discover_symbol_names, market_slug,
        save_gnews_reports,
    )
except Exception:  # pragma: no cover
    ROOT = Path(__file__).resolve().parents[1]
    DATA_DIR = ROOT / "data"
    REPORT_DIR = ROOT / "reports"
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    def read_csv_safe(path: Path) -> pd.DataFrame:
        try:
            return pd.read_csv(path) if path.exists() and path.stat().st_size else pd.DataFrame()
        except Exception:
            return pd.DataFrame()

    def read_json_safe(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() and path.stat().st_size else {}
        except Exception:
            return {}

    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    def get_secret(name: str) -> str:
        return str(os.environ.get(name, "") or "").strip()

    def to_num(value: Any, default: float = math.nan) -> float:
        try:
            s = re.sub(r"[^0-9.\-]", "", str(value or ""))
            return float(s) if s not in {"", "-", "."} else default
        except Exception:
            return default

    def first(row: Any, cols: Iterable[str], default: Any = "-") -> Any:
        for c in cols:
            if c in getattr(row, "index", []):
                v = row.get(c)
                if pd.notna(v) and str(v).strip() not in {"", "-", "nan", "None"}:
                    return v
        return default

    def market_slug(market: str) -> str:
        return "kr" if str(market) == "한국주식" else "us"

    def label_for_symbol(symbol: str, market: str, names: dict[str, str] | None = None) -> str:
        return str(symbol)

    def discover_symbol_names(market: str) -> dict[str, str]:
        return {}

    def save_gnews_reports() -> dict[str, Any]:
        return {"status": "NO_ENGINE"}

try:
    from core.v45_calibrated_decision_engine import run_v45_update
except Exception:  # pragma: no cover
    run_v45_update = None

OPERATION_CSV = REPORT_DIR / "v50_operation_center.csv"
OPERATION_JSON = REPORT_DIR / "v50_operation_center.json"
NEWS_CSV = REPORT_DIR / "v50_news_narrative_cards.csv"
NEWS_JSON = REPORT_DIR / "v50_news_narrative_cards.json"
FUND_CSV = REPORT_DIR / "v50_fundamental_kpi_cards.csv"
FUND_JSON = REPORT_DIR / "v50_fundamental_kpi_cards.json"
POSITION_CSV = REPORT_DIR / "v50_position_plan.csv"
POSITION_JSON = REPORT_DIR / "v50_position_plan.json"
STRUCTURE_CSV = REPORT_DIR / "v50_structure_check.csv"
STATUS_JSON = REPORT_DIR / "v50_stability_status.json"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def _file_status(path: Path, stale_hours: float = 72.0) -> dict[str, Any]:
    exists = path.exists()
    size = path.stat().st_size if exists else 0
    age_h = round((datetime.now().timestamp() - path.stat().st_mtime) / 3600, 2) if exists else None
    if not exists:
        status = "없음"
        action = "자동누적 또는 해당 갱신 버튼을 실행하세요."
    elif size <= 0:
        status = "비어 있음"
        action = "파일은 있지만 내용이 없습니다. API 키/원천 데이터를 확인하세요."
    elif age_h is not None and age_h > stale_hours:
        status = "오래됨"
        action = "GitHub Actions 또는 로컬 동기화 상태를 확인하세요."
    else:
        status = "정상"
        action = "사용 가능합니다."
    return {
        "상태": status,
        "파일": _rel(path),
        "크기": int(size),
        "최근갱신_시간전": "-" if age_h is None else age_h,
        "다음 행동": action,
    }


def _secret_status(names: list[str]) -> str:
    present = [n for n in names if get_secret(n)]
    if present:
        return "설정됨: " + ", ".join(present)
    return "미설정"


def _git_status() -> tuple[str, str]:
    if not (ROOT / ".git").exists():
        return "로컬 폴더", "현재 폴더가 git 저장소가 아닙니다. GitHub Desktop 저장소 폴더에서 실행하면 pull 동기화가 가능합니다."
    try:
        res = subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            return "확인 필요", (res.stderr or res.stdout or "git status 실패").strip()[:200]
        if res.stdout.strip():
            return "변경 있음", "로컬 변경사항이 있습니다. GitHub Desktop에서 Commit/Push 여부를 확인하세요."
        return "정상", "git 저장소가 정상이며 로컬 변경사항이 없습니다."
    except FileNotFoundError:
        return "git 없음", "Git for Windows가 PATH에 없습니다. 동기화 없이 앱은 실행 가능하지만 자동 pull은 안 됩니다."
    except Exception as exc:
        return "확인 필요", f"{type(exc).__name__}: {exc}"


def build_operation_center() -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    checks = [
        ("GitHub 자동실행", REPORT_DIR / "cloud_accumulator_last_run.json", "GitHub Actions 마지막 자동누적 결과"),
        ("v45 보정판", REPORT_DIR / "v45_status.json", "추천 보정/행동판 상태"),
        ("v50 안정판", STATUS_JSON, "v50 통합 점검 상태"),
        ("뉴스 수집", REPORT_DIR / "gnews_summary.json", "GNews/News API 수집 결과"),
        ("뉴스 캐시", DATA_DIR / "news" / "gnews_cache.csv", "뉴스 캐시"),
        ("재무·KPI", REPORT_DIR / "v40_fundamental_kpi_summary.csv", "재무·가치·KPI 리포트"),
        ("백테스트", REPORT_DIR / "v43_strategy_backtest_summary.csv", "전략 백테스트"),
        ("실전복기", REPORT_DIR / "v44_recommendation_outcomes.csv", "추천 후 실제 성과 추적"),
        ("권장수량", POSITION_CSV, "v50 보유/매도/권장수량 계획"),
    ]
    for name, path, desc in checks:
        stat = _file_status(path)
        rows.append({"구분": name, "설명": desc, **stat})
    git_s, git_msg = _git_status()
    rows.append({"구분": "로컬 Git 동기화", "설명": "PC 앱 폴더의 GitHub 동기화 상태", "상태": git_s, "파일": ".git", "크기": "-", "최근갱신_시간전": "-", "다음 행동": git_msg})
    rows.append({"구분": "뉴스 API 키", "설명": "GNews/News API 키 인식 여부", "상태": "정상" if (get_secret("GNEWS_API_KEY") or get_secret("NEWS_API_KEY")) else "미설정", "파일": "GitHub Secrets 또는 .env", "크기": "-", "최근갱신_시간전": "-", "다음 행동": _secret_status(["GNEWS_API_KEY", "NEWS_API_KEY"])})
    rows.append({"구분": "재무 API 키", "설명": "DART/Finnhub 키 인식 여부", "상태": "정상" if (get_secret("DART_API_KEY") or get_secret("FINNHUB_API_KEY")) else "미설정", "파일": "GitHub Secrets 또는 .env", "크기": "-", "최근갱신_시간전": "-", "다음 행동": _secret_status(["DART_API_KEY", "FINNHUB_API_KEY"])})
    rows.append({"구분": "LLM API 키", "설명": "뉴스 한글 요약/감성분석 고도화용", "상태": "선택" if (get_secret("OPENAI_API_KEY") or get_secret("ANTHROPIC_API_KEY")) else "미설정", "파일": "GitHub Secrets 또는 .env", "크기": "-", "최근갱신_시간전": "-", "다음 행동": _secret_status(["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]) + " / 없어도 기본 뉴스 정리는 가능합니다."})
    df = pd.DataFrame(rows)
    df.to_csv(OPERATION_CSV, index=False, encoding="utf-8-sig")
    write_json(OPERATION_JSON, {"updated_at": _now(), "rows": rows})
    return df


def _load_news_sources() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for p in [REPORT_DIR / "gnews_latest_kr.csv", REPORT_DIR / "gnews_latest_us.csv", DATA_DIR / "news" / "gnews_cache.csv", REPORT_DIR / "operational_news_narrative_kr.csv", REPORT_DIR / "operational_news_narrative_us.csv"]:
        df = read_csv_safe(p)
        if not df.empty:
            df["_source_file"] = _rel(p)
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    for c in ["title", "제목", "summary", "description", "설명", "url", "publishedAt", "감성", "sentiment", "market", "시장"]:
        if c not in df.columns:
            df[c] = ""
    return df.drop_duplicates(subset=[c for c in ["title", "제목", "url"] if c in df.columns], keep="first")


def _news_interpretation(title: str, desc: str, sentiment: str) -> tuple[str, str]:
    text = f"{title} {desc}".lower()
    if sentiment in {"positive", "긍정", "bullish"} or any(k in text for k in ["beat", "surge", "upgrade", "growth", "record", "호실적", "수주", "상향"]):
        return "긍정 재료", "좋은 뉴스라도 거래량·현재가 위치가 따라오는지 확인한 뒤 접근하세요."
    if sentiment in {"negative", "부정", "bearish"} or any(k in text for k in ["miss", "lawsuit", "downgrade", "fall", "risk", "probe", "악재", "소송", "하향"]):
        return "주의 재료", "단기 변동성이 커질 수 있으므로 신규매수보다 관망 또는 비중 축소 판단이 우선입니다."
    return "중립/확인 필요", "뉴스만으로 판단하지 말고 가격·거래량·수급이 같이 움직이는지 확인하세요."


def build_news_narrative_cards(fetch_if_key: bool = True) -> pd.DataFrame:
    fetch_result: dict[str, Any] | None = None
    if fetch_if_key and (get_secret("GNEWS_API_KEY") or get_secret("NEWS_API_KEY")):
        try:
            fetch_result = save_gnews_reports()
        except Exception as exc:
            fetch_result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}
    df = _load_news_sources()
    rows: list[dict[str, Any]] = []
    if df.empty:
        rows.append({
            "시장": "전체", "제목": "수집된 뉴스가 없습니다", "요약": "GNEWS_API_KEY/NEWS_API_KEY가 없거나 API 호출 결과가 비어 있습니다.",
            "감성": "확인 필요", "초보자 해석": "뉴스가 없으면 뉴스 재료는 매수 판단에서 제외하고 가격·거래량·수급 중심으로 보세요.",
            "다음 행동": "GitHub Secrets의 GNEWS_API_KEY 확인 → Actions 실행 → start 앱 동기화 확인", "출처": "-", "링크": "-",
        })
    else:
        for _, r in df.head(40).iterrows():
            title = str(first(r, ["title", "제목"], "") or "").strip()
            desc = str(first(r, ["description", "summary", "설명", "요약"], "") or "").strip()
            if not title and not desc:
                continue
            market = str(first(r, ["market", "시장"], "전체") or "전체")
            sentiment = str(first(r, ["sentiment", "감성"], "중립") or "중립")
            label, guide = _news_interpretation(title, desc, sentiment)
            rows.append({
                "시장": market, "제목": title[:180], "요약": desc[:260], "감성": sentiment,
                "초보자 해석": label, "다음 행동": guide, "출처": str(r.get("_source_file", "-")), "링크": str(first(r, ["url", "링크"], "-")),
            })
    out = pd.DataFrame(rows)
    out.to_csv(NEWS_CSV, index=False, encoding="utf-8-sig")
    write_json(NEWS_JSON, {"updated_at": _now(), "rows": rows, "fetch_result": fetch_result})
    return out


def build_fundamental_kpi_cards() -> pd.DataFrame:
    sources = [
        REPORT_DIR / "v40_fundamental_kpi_summary.csv",
        REPORT_DIR / "fundamental_cache.csv",
        DATA_DIR / "fundamental_cache.csv",
        REPORT_DIR / "valuation_kpi_summary.csv",
    ]
    frames: list[pd.DataFrame] = []
    for p in sources:
        df = read_csv_safe(p)
        if not df.empty:
            df["_source_file"] = _rel(p)
            frames.append(df)
    rows: list[dict[str, Any]] = []
    if not frames:
        rows.append({
            "종목": "-", "재무상태": "데이터 없음", "가치평가": "확인 필요", "KPI": "-",
            "초보자 해석": "재무 데이터가 아직 연결되지 않았습니다. 단기 매매는 가능하지만 장기 보유 판단에는 재무 확인이 필요합니다.",
            "다음 행동": "DART_API_KEY/FINNHUB_API_KEY 확인 후 GitHub Actions 또는 v50 갱신 실행", "출처": "-",
        })
    else:
        all_df = pd.concat(frames, ignore_index=True)
        for _, r in all_df.head(80).iterrows():
            market = str(first(r, ["시장", "market"], "") or "")
            sym = str(first(r, ["종목코드", "symbol", "ticker", "code", "종목"], "") or "")
            name = str(first(r, ["종목명", "name", "company"], "") or "")
            label = name or sym or "-"
            per = first(r, ["PER", "per", "pe", "P/E"], "-")
            pbr = first(r, ["PBR", "pbr"], "-")
            roe = first(r, ["ROE", "roe"], "-")
            growth = first(r, ["매출성장률", "growth", "revenue_growth", "성장률"], "-")
            debt = first(r, ["부채비율", "debt_ratio", "debt"], "-")
            status = "확인 가능" if any(str(x) not in {"", "-", "nan", "None"} for x in [per, pbr, roe, growth, debt]) else "값 부족"
            rows.append({
                "종목": label_for_symbol(sym, market or "미국주식") if sym else label,
                "재무상태": status,
                "가치평가": f"PER {per} / PBR {pbr}",
                "KPI": f"ROE {roe} / 성장률 {growth} / 부채 {debt}",
                "초보자 해석": "재무가 확인되는 종목은 단기 차트와 함께 보되, 값 부족 종목은 추격매수를 피하고 수급·가격 기준을 더 엄격히 보세요.",
                "다음 행동": "재무값이 비어 있으면 API 키와 종목코드 매핑을 확인하세요.",
                "출처": str(r.get("_source_file", "-")),
            })
    out = pd.DataFrame(rows)
    out.to_csv(FUND_CSV, index=False, encoding="utf-8-sig")
    write_json(FUND_JSON, {"updated_at": _now(), "rows": rows})
    return out


def _load_current_prices() -> dict[str, float]:
    prices: dict[str, float] = {}
    candidates = list(REPORT_DIR.glob("*intraday*snapshot*.csv")) + list(REPORT_DIR.glob("*quote*.csv")) + list(REPORT_DIR.glob("*realtime*.csv")) + list(DATA_DIR.glob("**/*price*.csv"))
    for p in candidates[:60]:
        df = read_csv_safe(p)
        if df.empty:
            continue
        for _, r in df.iterrows():
            sym = str(first(r, ["종목코드", "symbol", "ticker", "code"], "") or "").strip().upper()
            if not sym:
                continue
            price = to_num(first(r, ["현재가", "current_price", "price", "close", "Close", "last"], math.nan))
            if not math.isnan(price) and price > 0:
                prices[sym] = price
                # Korean codes can be zero-padded; keep raw too.
                m = re.search(r"(\d{6})", sym)
                if m:
                    prices[m.group(1)] = price
    return prices


def _load_holdings() -> pd.DataFrame:
    paths = list(DATA_DIR.glob("**/*holding*.csv")) + list(DATA_DIR.glob("**/*portfolio*.csv")) + list(REPORT_DIR.glob("**/*holding*.csv"))
    frames: list[pd.DataFrame] = []
    for p in paths[:50]:
        df = read_csv_safe(p)
        if not df.empty:
            df["_source_file"] = _rel(p)
            frames.append(df)
    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame()


def build_position_plan() -> pd.DataFrame:
    holdings = _load_holdings()
    prices = _load_current_prices()
    rows: list[dict[str, Any]] = []
    if holdings.empty:
        rows.append({
            "구분": "보유종목", "종목": "-", "시장": "-", "보유수량": "-", "평단가": "-", "현재가": "-", "수익률": "-",
            "권장행동": "보유 데이터 없음", "권장수량": 0, "예상금액": "-", "초보자 안내": "보유종목 CSV가 없으면 보유/매도 수량 계산은 제한됩니다.",
        })
    else:
        for _, r in holdings.head(200).iterrows():
            market = str(first(r, ["시장", "market"], "한국주식") or "한국주식")
            sym_raw = str(first(r, ["종목코드", "symbol", "ticker", "code", "종목"], "") or "").strip()
            sym = re.search(r"(\d{6})", sym_raw)
            sym_key = sym.group(1) if sym else re.sub(r"[^A-Za-z0-9.\-]", "", sym_raw).upper()
            name = str(first(r, ["종목명", "name", "company"], "") or "")
            qty = to_num(first(r, ["보유수량", "quantity", "qty", "수량"], 0), 0)
            avg = to_num(first(r, ["평단가", "avg_price", "average_price", "평균단가"], math.nan))
            price = prices.get(sym_key, math.nan)
            ret = ((price - avg) / avg * 100.0) if not math.isnan(price) and not math.isnan(avg) and avg > 0 else math.nan
            action = "보유 점검"
            rec_qty = 0
            guide = "현재가/수익률을 확인한 뒤 손절·목표가 기준으로 판단하세요."
            if math.isnan(price):
                guide = "현재가 미수신입니다. run_intraday_refresh 또는 GitHub 동기화 후 다시 확인하세요."
            elif ret <= -7:
                action = "손절/축소 검토"
                rec_qty = max(1, math.floor(qty * 0.3)) if qty > 0 else 0
                guide = "손실이 커진 상태입니다. 손절 기준 이탈인지 먼저 확인하세요."
            elif ret >= 12:
                action = "일부 익절 검토"
                rec_qty = max(1, math.floor(qty * 0.25)) if qty > 0 else 0
                guide = "수익 구간입니다. 목표가 근처라면 일부 익절도 검토할 수 있습니다."
            amount = price * rec_qty if not math.isnan(price) and rec_qty else math.nan
            rows.append({
                "구분": "보유/매도", "종목": name or label_for_symbol(sym_key, market), "시장": market,
                "보유수량": int(qty) if qty == int(qty) else qty, "평단가": "-" if math.isnan(avg) else round(avg, 2),
                "현재가": "-" if math.isnan(price) else round(price, 2), "수익률": "-" if math.isnan(ret) else f"{ret:.2f}%",
                "권장행동": action, "권장수량": rec_qty, "예상금액": "-" if math.isnan(amount) else round(amount, 2), "초보자 안내": guide,
            })
    out = pd.DataFrame(rows)
    out.to_csv(POSITION_CSV, index=False, encoding="utf-8-sig")
    write_json(POSITION_JSON, {"updated_at": _now(), "rows": rows})
    return out


def build_structure_check() -> pd.DataFrame:
    expected = [
        ("일반모드", "오늘 실행", "오늘 해야 할 행동만 요약"),
        ("일반모드", "매수", "매수 후보/위험/스크리너"),
        ("일반모드", "보유·매도", "보유 유지/축소/매도 판단"),
        ("일반모드", "차트·수급", "차트는 이곳 한 화면에서만 확인"),
        ("일반모드", "뉴스·재무·시장", "뉴스/재무/거시 데이터 해석"),
        ("일반모드", "퀀트", "전략 검증/복기/리스크 점검"),
        ("관리자모드", "데이터 진단", "원본·오류·리포트 점검"),
    ]
    rows = [{"모드": a, "대분류": b, "역할": c, "v50 기준": "유지"} for a, b, c in expected]
    df = pd.DataFrame(rows)
    df.to_csv(STRUCTURE_CSV, index=False, encoding="utf-8-sig")
    return df


def run_v50_update(fetch_news: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = {"status": "OK", "updated_at": _now(), "version": "v50"}
    if run_v45_update is not None:
        try:
            result["v45"] = run_v45_update()
        except Exception as exc:
            result["status"] = "PARTIAL"
            result["v45_error"] = f"{type(exc).__name__}: {exc}"
    for name, fn in [
        ("operation", build_operation_center),
        ("news", lambda: build_news_narrative_cards(fetch_if_key=fetch_news)),
        ("fundamental", build_fundamental_kpi_cards),
        ("position", build_position_plan),
        ("structure", build_structure_check),
    ]:
        try:
            df = fn()
            result[name] = {"rows": int(len(df))}
        except Exception as exc:
            result["status"] = "PARTIAL"
            result[f"{name}_error"] = f"{type(exc).__name__}: {exc}"
    result["paths"] = {
        "operation": _rel(OPERATION_CSV),
        "news": _rel(NEWS_CSV),
        "fundamental": _rel(FUND_CSV),
        "position": _rel(POSITION_CSV),
        "structure": _rel(STRUCTURE_CSV),
    }
    write_json(STATUS_JSON, result)
    # Rebuild operation center once more so it can include the v50 status file after it is written.
    try:
        build_operation_center()
    except Exception:
        pass
    return result


if __name__ == "__main__":
    print(json.dumps(run_v50_update(), ensure_ascii=False, indent=2, default=str))
