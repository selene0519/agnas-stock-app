#!/usr/bin/env python3
"""DART 기업개황 수집 — 사업 내용·업종·설립일 등 '이 회사가 뭘 하는가'.

왜 필요한가:
  앱은 차트·공시·수급·재무를 보지만 **회사가 무슨 사업을 하는지**를 한 줄도
  보여주지 않았다. 추천 카드에 종목코드와 이름만 있으면 사용자는 그 회사가
  뭘 파는 회사인지 모른 채 판단하게 된다.

  기존 자료로 부족한 이유: `data/sector_map_kr.csv`에 sector/industry가 있지만
  그건 분류 라벨("전기전자")이지 사업 내용이 아니다.

무엇을 받는가 (DART `company.json`):
  corp_name, induty_code(업종코드), est_dt(설립일), ceo_nm, adres,
  hm_url, stock_name  등 기업 개황.
  ※ DART 기업개황에는 서술형 '사업의 내용'(사업보고서 II장) 전문이 없다.
     그건 별도 문서 파싱이 필요하므로 여기서는 **개황 + 업종명**까지만 받고,
     서술형 요약은 induty_code -> 업종명 매핑으로 대체한다. 있는 것을 정직하게
     보여주고, 없는 것을 지어내지 않는다.

실행: python scripts/fetch_dart_company_profile.py [--limit N]
쓰기: data/fundamental/dart_company_profile_kr.csv
      reports/dart_company_profile_status.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parents[1]
CORP_MAP = ROOT / "data" / "fundamental" / "dart_corp_map.csv"
OHLCV_DIR = ROOT / "data" / "market" / "ohlcv"
OUT = ROOT / "data" / "fundamental" / "dart_company_profile_kr.csv"
STATUS = ROOT / "reports" / "dart_company_profile_status.json"

DART_KEY = os.environ.get("DART_API_KEY", "")
BASE_URL = "https://opendart.fss.or.kr/api"

FIELDNAMES = [
    "symbol", "corp_code", "corp_name", "stock_name",
    "industryCode", "industryName", "establishedDate", "ceo",
    "homepage", "address", "businessSummary", "updatedAt",
]

# 한국표준산업분류(KSIC) 대분류 앞 2자리 → 사람이 읽는 업종명.
# DART induty_code는 KSIC 기반이라 앞 2자리로 대분류를 안정적으로 얻을 수 있다.
# 표를 하드코딩하는 대신 코드 자체도 같이 남기므로, 매핑이 낡아도
# 화면은 "업종코드 xx"로 정직하게 표시할 수 있다.
KSIC_MAJOR = {
    "01": "농업", "03": "어업", "05": "광업", "06": "광업",
    "10": "식료품 제조", "11": "음료 제조", "13": "섬유제품 제조",
    "14": "의복 제조", "17": "펄프·종이 제조", "18": "인쇄·기록매체",
    "19": "코크스·석유정제", "20": "화학물질·화학제품 제조",
    "21": "의료용 물질·의약품 제조", "22": "고무·플라스틱 제조",
    "23": "비금속 광물제품 제조", "24": "1차 금속 제조",
    "25": "금속가공제품 제조", "26": "전자부품·컴퓨터·통신장비 제조",
    "27": "의료·정밀·광학기기 제조", "28": "전기장비 제조",
    "29": "기타 기계·장비 제조", "30": "자동차·트레일러 제조",
    "31": "기타 운송장비 제조", "32": "가구 제조", "33": "기타 제품 제조",
    "35": "전기·가스·증기 공급", "36": "수도업", "41": "종합 건설",
    "42": "전문직별 공사", "45": "자동차 판매", "46": "도매·상품중개",
    "47": "소매업", "49": "육상 운송", "50": "수상 운송", "51": "항공 운송",
    "52": "운송 관련 서비스", "55": "숙박업", "56": "음식점·주점",
    "58": "출판업", "59": "영상·오디오 제작", "61": "통신업",
    "62": "컴퓨터 프로그래밍·시스템 통합", "63": "정보서비스업",
    "64": "금융업", "65": "보험업", "66": "금융·보험 관련 서비스",
    "68": "부동산업", "70": "연구개발업", "71": "전문 서비스업",
    "72": "건축기술·엔지니어링", "73": "기타 전문·과학·기술 서비스",
    "74": "사업시설 관리", "75": "사업지원 서비스", "85": "교육 서비스",
    "86": "보건업", "87": "사회복지 서비스", "90": "창작·예술·여가",
    "91": "스포츠·오락 관련 서비스", "94": "협회·단체", "96": "기타 개인 서비스",
}


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with path.open(encoding=enc, newline="") as f:
                return [dict(r) for r in csv.DictReader(f)]
        except Exception:
            continue
    return []


def _industry_name(code: str) -> str:
    code = str(code or "").strip()
    if not code:
        return ""
    return KSIC_MAJOR.get(code[:2], "")


def _build_corp_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _read_csv(CORP_MAP):
        sym = str(row.get("stock_code", "")).strip()
        code = str(row.get("corp_code", "")).strip()
        if sym and code and sym.isdigit():
            out[sym.zfill(6)] = code.zfill(8)
    return out


def _target_symbols() -> list[str]:
    """OHLCV가 있는 KR 종목 = 앱이 실제로 다루는 유니버스."""
    syms: set[str] = set()
    for f in OHLCV_DIR.glob("kr_*_daily.csv"):
        name = f.stem
        if name.startswith("kr_") and name.endswith("_daily"):
            sym = name[3:-6]
            if sym.isdigit():
                syms.add(sym.zfill(6))
    return sorted(syms)


def fetch_profile(corp_code: str) -> dict:
    try:
        resp = requests.get(f"{BASE_URL}/company.json",
                            params={"crtfc_key": DART_KEY, "corp_code": corp_code},
                            timeout=15)
        data = resp.json()
    except Exception:
        return {}
    if data.get("status") != "000":
        return {}
    return data


def _summary(profile: dict, industry_name: str) -> str:
    """사람이 읽는 한 줄 요약. **없는 걸 지어내지 않는다.**

    DART 기업개황에는 서술형 '사업의 내용'이 없으므로, 확실히 아는 것만
    엮는다: 업종 + 설립연도. 업종조차 모르면 빈 문자열을 반환해서
    화면이 "정보 없음"을 정직하게 그리게 한다.
    """
    if not industry_name:
        return ""
    est = str(profile.get("est_dt") or "").strip()
    if len(est) >= 4 and est[:4].isdigit():
        return f"{industry_name} · {est[:4]}년 설립"
    return industry_name


def run(limit: int | None) -> dict:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if not DART_KEY:
        result = {"updatedAt": now, "status": "SKIPPED",
                  "reason": "DART_API_KEY 없음", "total": 0, "fetched": 0}
        STATUS.parent.mkdir(parents=True, exist_ok=True)
        STATUS.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    corp_map = _build_corp_map()
    symbols = _target_symbols()
    if limit:
        symbols = symbols[:limit]

    existing = {str(r.get("symbol", "")).zfill(6): r for r in _read_csv(OUT)}
    rows: dict[str, dict] = dict(existing)
    fetched = 0
    missing_corp = 0

    for sym in symbols:
        corp_code = corp_map.get(sym)
        if not corp_code:
            missing_corp += 1
            continue
        # 기업개황은 잘 안 바뀐다. 이미 있으면 다시 받지 않는다
        # (DART 일 호출 한도를 재무 수집과 나눠 쓴다).
        if sym in existing and str(existing[sym].get("corp_name") or "").strip():
            continue
        profile = fetch_profile(corp_code)
        time.sleep(0.15)
        if not profile:
            continue
        industry_code = str(profile.get("induty_code") or "").strip()
        industry_name = _industry_name(industry_code)
        rows[sym] = {
            "symbol": sym,
            "corp_code": corp_code,
            "corp_name": profile.get("corp_name", ""),
            "stock_name": profile.get("stock_name", ""),
            "industryCode": industry_code,
            "industryName": industry_name,
            "establishedDate": profile.get("est_dt", ""),
            "ceo": profile.get("ceo_nm", ""),
            "homepage": profile.get("hm_url", ""),
            "address": profile.get("adres", ""),
            "businessSummary": _summary(profile, industry_name),
            "updatedAt": now,
        }
        fetched += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows([{k: r.get(k, "") for k in FIELDNAMES}
                     for r in sorted(rows.values(), key=lambda r: str(r.get("symbol")))])

    result = {
        "updatedAt": now, "status": "OK",
        "total": len(symbols), "fetched": fetched,
        "cached": len(symbols) - fetched - missing_corp,
        "missingCorpCode": missing_corp,
        "outputRows": len(rows),
        "withSummary": sum(1 for r in rows.values()
                           if str(r.get("businessSummary") or "").strip()),
    }
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    res = run(args.limit)
    print(f"=== DART 기업개황 수집: {res['status']} ===")
    if res["status"] == "SKIPPED":
        print(f"  {res['reason']}")
        return 0
    print(f"  대상 {res['total']} / 신규 {res['fetched']} / 캐시 {res['cached']}"
          f" / corp_code 없음 {res['missingCorpCode']}")
    print(f"  저장 {res['outputRows']}행 (사업요약 보유 {res['withSummary']}행)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
