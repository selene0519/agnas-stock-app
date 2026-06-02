"""
DSG → MONE 핵심 신호 엔진 (dsg_app_reference.py 선별 이식).

포함 기능:
- infer_kr_sector()     : 종목코드/이름/테마 기반 섹터 추론
- get_theme_names()     : 종목의 테마명 조회
- detect_leader_mode()  : 주도주/모멘텀 종목 정량 판정
- classify_pullback_state() : 눌림/돌파/추격 상태 정밀 분류

데이터 의존:
- data/sector_map_kr.csv          ← 통합 섹터맵 (stock_master + 수동 매핑)
- data/theme_map_kr.csv           ← 5093개 테마 매핑
- data/sector_map_manual_kr.csv   ← 수동 정밀 분류
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[4]
_DATA = _REPO / "data"

# ── 표준 섹터 목록
STANDARD_SECTORS_KR = [
    "Semiconductor", "Battery/EV", "Defense/Aerospace", "Shipbuilding", "Power/Utility",
    "Construction", "Auto", "Bio/Healthcare", "Bank/Finance", "Securities",
    "Insurance", "Cosmetics", "Entertainment/Media", "Game", "AI/Software",
    "Robot", "Telecom", "Oil/Chemical", "Steel/Metal", "Food/Beverage",
    "Retail", "Airline", "Shipping/Logistics", "Nuclear", "Renewable/Energy",
    "Display", "Consumer", "Holding", "Machinery/Equipment", "Materials/Parts",
    "Textile/Apparel", "Internet/Platform", "Other",
]

# 섹터 한국어 라벨
SECTOR_KR_LABEL: dict[str, str] = {
    "Semiconductor": "반도체",        "Battery/EV": "배터리/전기차",
    "Defense/Aerospace": "방산/항공", "Shipbuilding": "조선",
    "Power/Utility": "전력/유틸",     "Construction": "건설",
    "Auto": "자동차",                 "Bio/Healthcare": "바이오/헬스케어",
    "Bank/Finance": "은행/금융",       "Securities": "증권",
    "Insurance": "보험",              "Cosmetics": "화장품",
    "Entertainment/Media": "엔터/미디어", "Game": "게임",
    "AI/Software": "AI/소프트웨어",   "Robot": "로봇",
    "Telecom": "통신",                "Oil/Chemical": "정유/화학",
    "Steel/Metal": "철강/금속",        "Food/Beverage": "식품/음료",
    "Retail": "유통",                 "Airline": "항공",
    "Shipping/Logistics": "해운/물류","Nuclear": "원전",
    "Renewable/Energy": "신재생에너지","Display": "디스플레이",
    "Consumer": "소비재",             "Holding": "지주",
    "Machinery/Equipment": "기계/장비","Materials/Parts": "소재/부품",
    "Internet/Platform": "인터넷/플랫폼","Other": "기타",
}

# 키워드 → 섹터 룰
_SECTOR_KW: list[tuple[str, list[str]]] = [
    ("Semiconductor", [
        "반도체","하이닉스","삼성전자","원익","주성","이오테크","리노","ISC","테크윙",
        "피에스케이","한미반도체","동진쎄미","칩","웨이퍼","실리콘","디램","낸드",
        "하나마이크론","네패스","SFA반도체","엘비세미콘",
    ]),
    ("Battery/EV", [
        "배터리","전지","에너지솔루션","SDI","에코프로","엘앤에프","포스코퓨처",
        "전기차","양극재","음극재","전해액","분리막","리튬","일진머티리얼즈","천보",
    ]),
    ("Defense/Aerospace", [
        "방산","항공","에어로","우주","로템","넥스원","풍산","한화시스템","항공우주",
        "위아","SNT","빅텍","퍼스텍","스페코","한국항공","한화에어로","LIG넥스원",
    ]),
    ("Shipbuilding", [
        "조선","중공업","해양","엔진","미포","오션","선박","STX중공업","현대중공업",
        "삼성중공업","대우조선","한진중공업",
    ]),
    ("Power/Utility", [
        "전력","전기","일렉트릭","LS ELECTRIC","효성중공업","변압","전선",
        "대한전선","가온전선","제룡","한국전력","LS전선","일진전기","대원전선",
        "에너비스","도시가스","가스","한국가스",
    ]),
    ("Construction", [
        "건설","이앤씨","E&C","산업개발","엔지니어링","건축","시멘트","레미콘",
        "DL이앤씨","GS건설","현대건설","대우건설","태영건설","HDC현대산업개발",
        "아이에스동서","쌍용씨앤이","진흥기업","벽산","동양파일",
    ]),
    ("Auto", [
        "현대차","기아","모비스","자동차","타이어","만도","HL만도","성우하이텍","화신",
        "자동차부품","SP삼화","삼화","대원강업","유성기업","동아화성","세종공업",
        "서연이화","한일현대","평화산업","인팩","삼기","동원금속","NVH코리아",
        "화승엔터","디아이씨","에스엘","PKC","현성바이탈",
    ]),
    ("Bio/Healthcare", [
        "바이오","제약","약품","헬스","메디","의료","셀트리온","삼성바이오","유한양행",
        "한미약품","클래시스","녹십자","동아에스티","보령","대웅","JW중외","광동",
        "경동제약","종근당","일동제약","환인제약","삼일제약","제일약품","안국약품",
        "신풍제약","대화제약","유나이티드","동화약품","일성신약","건일제약",
    ]),
    ("Bank/Finance", [
        "은행","금융","KB금융","신한지주","하나금융","우리금융","기업은행","카카오뱅크",
        "BNK","DGB","JB금융","수협","산업은행",
    ]),
    ("Securities", ["증권","투자증권","미래에셋","NH투자","키움","한국금융","대신증권","삼성증권","한화투자"]),
    ("Insurance", ["보험","화재","생명","손해보험","메리츠","삼성화재","현대해상","DB손보"]),
    ("Cosmetics", [
        "화장품","코스맥스","콜마","아모레","LG생활건강","클리오","실리콘투",
        "한국화장품","코리아나","토니모리","에이블씨엔씨","잇츠한불",
    ]),
    ("Entertainment/Media", [
        "엔터","미디어","스튜디오","하이브","JYP","에스엠","와이지","콘텐츠","CJ ENM",
        "NEW","쇼박스","덱스터","자이언트스텝","CJ CGV","메가박스","롯데컬처",
    ]),
    ("Game", ["게임","게임즈","넷마블","크래프톤","엔씨","펄어비스","위메이드","카카오게임","컴투스","선데이토즈","웹젠"]),
    ("AI/Software", [
        "소프트","AI","인공지능","데이터","클라우드","보안","더존","안랩","한글과컴퓨터",
        "NAVER","카카오","솔루션","시스템","IT","정보","넥서스","이글루","지니언스",
    ]),
    ("Robot", ["로봇","레인보우","두산로보","유일로보","로보티즈","로보스타","뉴로메카","협동로봇"]),
    ("Telecom", ["통신","텔레콤","SK텔레콤","KT","LG유플러스","위성","케이블","딜라이브"]),
    ("Oil/Chemical", [
        "정유","화학","케미","석유","S-Oil","GS","롯데케미","금호석유","한화솔루션",
        "효성화학","SK이노베이션","SK에너지","OCI","태광산업","코오롱인더","SKC",
        "동성화학","이수화학","KPX","SH에너지","삼남석유","미원상사","미원화학",
    ]),
    ("Steel/Metal", [
        "철강","금속","제철","POSCO","포스코","동국제강","고려아연","풍산",
        "제강","강업","철관","주철","와이어","선재","봉강","냉연","열연","특수강",
        "만호제강","고려제강","동일제강","대한제강","한국철강","세아베스틸",
        "현대제철","일진제강","삼화강봉","원일특강","DSR제강","고강도","영흥",
    ]),
    ("Food/Beverage", [
        "식품","음식","제당","농심","오리온","하이트","롯데칠성","삼양식품",
        "CJ제일제당","대상","동원","남양유업","매일유업","빙그레","크라운","해태",
        "삼립","SPC","진라","미원","샘표","청정원","팔도","농협식품",
    ]),
    ("Retail", [
        "유통","쇼핑","이마트","롯데쇼핑","신세계","현대백화점","BGF","GS리테일",
        "홈플러스","CU","GS25","세이브존","롯데마트","노브랜드",
    ]),
    ("Airline", ["항공","대한항공","아시아나","제주항공","티웨이","진에어","에어부산","에어서울"]),
    ("Shipping/Logistics", [
        "해운","물류","팬오션","HMM","대한해운","CJ대한통운","한진","택배","포워딩",
        "선박관리","흥아","SM상선","고려해운","장금상선",
    ]),
    ("Nuclear", ["원전","두산에너빌리티","한전기술","우진","비에이치아이","하나기술","보성파워텍"]),
    ("Renewable/Energy", [
        "태양광","풍력","신재생","OCI","씨에스윈드","동국S&C",
        "에너지","수소","연료전지","태양","그린","신에너지","한화큐셀",
    ]),
    ("Display", ["디스플레이","OLED","LCD","덕산","AP시스템","비아트론","LG디스플레이","삼성디스플레이","이녹스첨단소재"]),
    ("Textile/Apparel", [
        "방직","방적","섬유","직물","의류","패션","의복","니트","원단","봉제",
        "경방","전방","일신방","태광산업","코오롱인더","BYC","비비안","신원",
        "한세실업","영원무역","F&F","LF","한섬","유니클로","베이직하우스",
        "휠라","골프","스포츠","아웃도어","블랙야크","K2","밀레","코오롱스포츠",
    ]),
    ("Consumer", [
        "생활용품","화학생활","가전","주방","위생","지류","종이","잡화","문구",
        "락앤락","삼광글라스","OX","유한킴벌리","깨끗한나라","대한펄프",
        "삼익악기","악기","오르간","피아노","스포츠용품","낚시","레저",
    ]),
    ("Machinery/Equipment", [
        "기계","기공","공업","정밀","기술","테크놀로지","테크","장비","산업",
        "두산","현대엘리베","엘리베이터","공작기계","프레스","주조","단조",
        "연마","절삭","금형","금형가공","제일연마","일진다이아","이구산업",
        "SNT모티브","SG","SHD","혜인","유니온","DI동일",
    ]),
    ("Materials/Parts", [
        "소재","부품","전자","전기전자","PCB","회로","모듈","센서","필름","코일","모터","커넥터",
        "주철관","관이음","배관","파이프","한국주철관","동관","동파이프",
        "세라믹","유리","내화물","SK네트웍스","LS네트웍스",
    ]),
    ("Internet/Platform", ["인터넷","플랫폼","커머스","페이","쿠팡","네이버","카카오페이","토스","뱅크샐러드"]),
    ("Holding", [
        "홀딩스","지주","지주회사","DL","CJ","코오롱","동양","LG","SK","GS","한화","롯데",
        "현대","효성","태광","동부","세아","LS","삼천리","대성",
    ]),
]

# 우선주 접미사 패턴 (name에서 제거해서 모회사 이름 추론)
_PREF_SUFFIX = ("3우B", "2우B", "1우B", "3우", "2우", "1우", "우B", "우")


def _strip_pref(name: str) -> str:
    """우선주 접미사 제거 → 보통주(모회사) 이름 반환"""
    n = name.strip()
    for suf in _PREF_SUFFIX:
        if n.endswith(suf):
            return n[: -len(suf)].strip()
    return n

# ── CSV 캐시
_sector_map_cache: dict[str, str] = {}
_theme_map_cache: dict[str, list[str]] = {}
_cache_loaded = False


def _load_caches() -> None:
    global _sector_map_cache, _theme_map_cache, _cache_loaded
    if _cache_loaded:
        return
    # sector_map_kr.csv
    p = _DATA / "sector_map_kr.csv"
    if p.exists():
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with p.open(encoding=enc) as f:
                    _BAD = {"", "unknown", "other", "미분류", "nan", "none", "-"}
                    for row in csv.DictReader(f):
                        sym = str(row.get("symbol", "")).strip()
                        sec = str(row.get("sector", "")).strip()
                        if sym and sec and sec.lower() not in _BAD:
                            _sector_map_cache[sym] = sec
                            _sector_map_cache[sym.lstrip("0")] = sec
                break
            except Exception:
                continue
    # theme_map_kr.csv
    p = _DATA / "theme_map_kr.csv"
    if p.exists():
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with p.open(encoding=enc) as f:
                    for row in csv.DictReader(f):
                        code = str(row.get("code", "")).strip().zfill(6)
                        theme = str(row.get("theme_name", "")).strip()
                        if code and theme:
                            _theme_map_cache.setdefault(code, [])
                            if theme not in _theme_map_cache[code]:
                                _theme_map_cache[code].append(theme)
                break
            except Exception:
                continue
    _cache_loaded = True


# ── 섹터 추론

def infer_kr_sector(code: str = "", name: str = "") -> str:
    """
    종목코드 + 이름으로 섹터 추론.
    우선순위: CSV 맵 → 이름 키워드 → 우선주 모회사 추론 → 테마
    """
    _load_caches()
    code = re.sub(r"\D", "", str(code or "")).zfill(6)[-6:]
    name_text = str(name or "").strip()

    # 1. CSV 맵 (가장 정확)
    if code in _sector_map_cache:
        return _sector_map_cache[code]

    # 2. 이름 키워드 매칭
    lower_name = name_text.lower()
    for sector, keywords in _SECTOR_KW:
        if any(str(kw).lower() in lower_name for kw in keywords):
            return sector

    # 3. 우선주이면 모회사 이름으로 재시도
    base_name = _strip_pref(name_text)
    if base_name != name_text and base_name:
        lower_base = base_name.lower()
        for sector, keywords in _SECTOR_KW:
            if any(str(kw).lower() in lower_base for kw in keywords):
                return sector
        # CSV에서 모회사 코드로 검색 (이름 일치)
        for cached_code, cached_sector in _sector_map_cache.items():
            pass  # 이름→코드 역조회는 _name_cache에서 처리

    # 4. 테마 기반 추론
    themes = _theme_map_cache.get(code, [])
    for theme in themes:
        lower_theme = theme.lower()
        for sector, keywords in _SECTOR_KW:
            if any(str(kw).lower() in lower_theme for kw in keywords):
                return sector

    return "Other"


def get_theme_names(code: str, limit: int = 5) -> list[str]:
    """종목코드의 테마명 목록 반환 (최대 limit개)"""
    _load_caches()
    code6 = re.sub(r"\D", "", str(code or "")).zfill(6)
    return _theme_map_cache.get(code6, [])[:limit]


def sector_label_kr(sector: str) -> str:
    """영문 섹터 코드 → 한국어 라벨"""
    return SECTOR_KR_LABEL.get(sector, sector)


# ── 주도주 감지

def detect_leader_mode(
    score: float,
    sector_score: float,
    market_regime: str,
    close: float,
    ma20: float,
    ma60: float,
    ret20: float,
    ret60: float,
    vol: float,
    vol_ma20: float,
    news_score: float = 5.0,
) -> tuple[bool, str]:
    """
    정량 조건 기반 주도주/모멘텀 종목 판별.
    is_leader=True → '가격이 높아도 추격 가능한 종목'으로 처리.
    """
    checks = [
        score >= 75,                                            # 종합점수 충분
        sector_score >= 65,                                     # 섹터 강도
        market_regime in ("BULL", "SIDE"),                      # 약세장 제외
        close > ma20 and (ma20 is None or ma60 is None or ma20 >= ma60),  # 정배열
        (ret20 >= 5) or (ret60 >= 12),                          # 모멘텀
        vol >= vol_ma20 * 0.9 if vol_ma20 and vol_ma20 > 0 else True,  # 거래량 유지
        news_score >= 5,                                        # 뉴스 중립 이상
    ]
    passed = sum(bool(c) for c in checks)
    is_leader = passed >= 5   # 7개 중 5개 이상
    reason = f"주도주 조건 {passed}/7개 충족"
    return is_leader, reason


# ── 눌림목 상태 정밀 분류

def classify_pullback_state(
    recent_highs: list[float],   # 최근 20일 고가 리스트
    recent_lows: list[float],    # 최근 20일 저가 리스트
    recent_closes: list[float],  # 최근 20일 종가 리스트
    recent_opens: list[float],   # 최근 20일 시가 리스트
    close: float,
    ma5: float,
    ma20: float,
    ma60: float,
    rsi: float,
    macd: float,
    macd_signal: float,
    vol: float,
    vol_ma20: float,
    entry: float,
    resistance_room_pct: float,  # 저항까지 남은 거리 %
    risk_reward: float,
    is_leader: bool = False,
) -> tuple[str, str, str]:
    """
    눌림목 상태를 7단계로 분류.
    반환: (state_label, reason, action)

    state_label 종류:
      "눌림 확인 완료" — 분할 진입 가능
      "눌림 진행 중"   — 관심 유지, 반등 확인 전 매수 금지
      "눌림 전"        — 아직 조정 부족
      "돌파 확인 대기" — 저항 근처, 종가 돌파 확인 필요
      "추격매수 위험"  — 진입가 이격 또는 RSI 과열
      "눌림 실패"      — 지지선 이탈, 추세 훼손
      "진입가 대기"    — 조건 미충족
    """
    if not recent_closes or len(recent_closes) < 5:
        return "판단불가", "OHLCV 부족", "데이터 확보 후 재확인"

    recent_high = max(recent_highs[-20:]) if recent_highs else close
    pullback_pct = (recent_high - close) / recent_high * 100 if recent_high > 0 else 0

    prev_low   = recent_lows[-2]  if len(recent_lows)   >= 2 else close
    prev_close = recent_closes[-2] if len(recent_closes) >= 2 else close
    today_low  = recent_lows[-1]  if recent_lows  else close
    today_open = recent_opens[-1] if recent_opens else close
    today_close = close

    close_recovered = today_close >= today_open or today_close >= prev_close * 0.995

    # 리더 여부에 따른 기준 차별화
    if is_leader:
        support_zone   = (close >= ma5 * 0.98 and close <= ma20 * 1.05) or \
                          (close >= ma20 * 0.98 and close <= ma20 * 1.04)
        enough_pullback  = pullback_pct >= 2
        deep_failed_level = ma20 * 0.97
        entry_gap_limit  = 8
        min_entry_close  = 3
    else:
        support_zone     = close >= ma20 * 0.97 and close <= ma20 * 1.04
        enough_pullback   = pullback_pct >= 4
        deep_failed_level = ma60 * 0.98 if ma60 else ma20 * 0.95
        entry_gap_limit  = 5
        min_entry_close  = 2.5

    volume_cooled   = vol <= vol_ma20 * 1.15 if vol_ma20 and vol_ma20 > 0 else True
    rebound_signal  = (
        close_recovered
        and today_low >= min(prev_low, ma20 * 0.97)
        and rsi >= 45
        and macd >= macd_signal * 0.98
    )
    entry_distance_pct = abs(close - entry) / entry * 100 if entry and entry > 0 else 0

    # ── 판정 순서
    if close < deep_failed_level or (ma60 and close < ma20 and close < ma60):
        return "눌림 실패", "주요 이동평균/지지선 이탈 → 추세 훼손 가능성", "신규매수 금지, 다음 지지선 재확인"

    if entry_distance_pct >= entry_gap_limit or (rsi >= 74 and resistance_room_pct < 3):
        return "추격매수 위험", "진입가 이격 또는 RSI/저항 조건상 손익비 약화", "신규매수 금지, 눌림 또는 거래량 동반 재돌파 대기"

    if resistance_room_pct <= 3 and vol >= (vol_ma20 * 0.95 if vol_ma20 else vol):
        return "돌파 확인 대기", "저항선 근처 — 종가 돌파 + 거래량 확인 필요", "종가 기준 돌파 + 거래량 유지 전까지 진입 금지"

    if (enough_pullback and support_zone and volume_cooled
            and rebound_signal and risk_reward >= 1.5
            and entry_distance_pct <= min_entry_close):
        return "눌림 확인 완료", "조정 후 지지권에서 회복 신호 + 손익비 확인", "우선진입가 근처 분할 접근 가능"

    if enough_pullback and support_zone and volume_cooled:
        return "눌림 진행 중", "조정·거래량 진정은 보이나 반등 확인 부족", "관심 유지, 반등 캔들/종가 회복 확인 전 매수 금지"

    if pullback_pct < (2 if is_leader else 4) and close > ma20 * (1.03 if is_leader else 1.04):
        return "눌림 전", "아직 충분한 조정 없이 가격이 높은 위치", "추격매수 금지, 5일선~20일선 재접근 대기"

    return "진입가 대기", "추세 유지 중이나 눌림·돌파 확인 부족", "진입가 이격률 + 거래량 재확인"


# ── quant_scanner에서 직접 사용하는 래퍼

def get_pullback_state_from_ohlcv(
    ohlcv_rows: list[dict[str, Any]],
    indicators: dict[str, Any],
    entry: float,
    is_leader: bool = False,
) -> tuple[str, str]:
    """
    OHLCV rows + indicators 딕셔너리를 받아 눌림 상태 반환.
    반환: (state_label, reason)
    """
    def _col(rows, *keys):
        result = []
        for row in rows:
            for k in keys:
                v = row.get(k)
                try:
                    f = float(v)
                    if f > 0:
                        result.append(f)
                        break
                except Exception:
                    pass
        return result

    recent = ohlcv_rows[-20:] if len(ohlcv_rows) >= 20 else ohlcv_rows
    highs  = _col(recent, "high",  "High")
    lows   = _col(recent, "low",   "Low")
    closes = _col(recent, "close", "Close")
    opens  = _col(recent, "open",  "Open")

    def _f(key: str, default: float = 0.0) -> float:
        v = indicators.get(key)
        try:
            f = float(v)
            return f if not __import__("math").isnan(f) else default
        except Exception:
            return default

    close  = closes[-1] if closes else 0.0
    ma5    = _f("ma5", close)
    ma20   = _f("ma20", close)
    ma60   = _f("ma60", close)
    rsi    = _f("rsi14", 50)
    macd   = _f("macd", 0)
    macd_s = _f("macdSignal", 0)
    vol    = _f("volumeValue", 0) / close if close > 0 else _f("volumeRatio20", 0)
    vol_ma = 1.0  # 정규화된 비율 사용

    # 저항까지 거리: 52주 고점 기준
    d52 = _f("distanceTo52wHigh", -5)
    resistance_room_pct = abs(d52) if d52 <= 0 else 0.0

    rr = _f("rrActual", 2.0)

    state, reason, _ = classify_pullback_state(
        recent_highs=highs, recent_lows=lows,
        recent_closes=closes, recent_opens=opens,
        close=close, ma5=ma5, ma20=ma20, ma60=ma60,
        rsi=rsi, macd=macd, macd_signal=macd_s,
        vol=vol, vol_ma20=vol_ma,
        entry=entry, resistance_room_pct=resistance_room_pct,
        risk_reward=rr, is_leader=is_leader,
    )
    return state, reason


# ── 섹터 강도 (sector_strength) ─────────────────────────────────────────────
#
# DSG의 sector_strength()를 MONE용으로 재구현.
# yfinance / pandas 없이 로컬 OHLCV CSV + live quote cache 만으로 동작.
#
# 섹터별 대표 종목 (KR) — OHLCV 파일이 존재하는 종목만
SECTOR_REPS_KR: dict[str, list[str]] = {
    "Semiconductor":       ["005930", "000660"],
    "Defense/Aerospace":   ["047810", "012450", "079550"],
    "Shipbuilding":        ["009540", "010140", "329180"],
    "Battery/EV":          ["373220", "005380", "051910"],
    "Power/Utility":       ["015760", "006260"],
    "Construction":        ["375500", "000720"],
    "Bio/Healthcare":      ["068270", "207940", "000100"],
    "Bank/Finance":        ["105560", "055550", "086790"],
    "Auto":                ["000270", "012330", "005380"],
    "Oil/Chemical":        ["010950", "078930"],
    "Steel/Metal":         ["005490", "004020"],
    "Nuclear":             ["034020"],
    "Robot":               ["454910"],
    "AI/Software":         ["035420", "035720"],
    "Entertainment/Media": ["352820", "041510"],
    "Airline":             ["003490"],
    "Holding":             ["003550", "000810"],
}

# 섹터별 대표 종목 (US)
SECTOR_REPS_US: dict[str, list[str]] = {
    "AI/Semiconductor": ["NVDA", "AMD", "AVGO", "MU"],
    "Mega Tech":        ["AAPL", "MSFT", "GOOGL", "META", "AMZN"],
    "Software/Growth":  ["PLTR", "NET", "DDOG", "SNOW"],
    "EV/Auto":          ["TSLA", "GM"],
    "Energy":           ["XOM", "CVX"],
    "Finance":          ["JPM", "BAC", "GS"],
    "Bio/Healthcare":   ["JNJ", "UNH", "PFE"],
}


def _read_ohlcv_closes(market: str, code: str, days: int = 20) -> list[float]:
    """OHLCV CSV에서 최근 N일 종가 리스트 반환 (오래된 순)."""
    candidates = [
        _DATA / "market" / "ohlcv" / f"{market}_{code}_daily.csv",
        _DATA / "stockapp" / f"{market}_{code}_daily.csv",
        _DATA.parent / "reports" / f"{market}_{code}_daily.csv",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for enc in ("utf-8-sig", "utf-8", "cp949"):
            try:
                with path.open(encoding=enc) as f:
                    rows = list(csv.DictReader(f))
                closes: list[float] = []
                for row in rows:
                    raw = row.get("close") or row.get("Close") or row.get("종가")
                    try:
                        v = float(str(raw).replace(",", ""))
                        if v > 0:
                            closes.append(v)
                    except Exception:
                        pass
                if closes:
                    return closes[-days:]
            except Exception:
                continue
    return []


def _live_quote_price(market: str, code: str) -> float | None:
    """mone_live_quote_cache.csv 에서 현재가 조회."""
    p = _DATA / "mone_live_quote_cache.csv"
    if not p.exists():
        return None
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with p.open(encoding=enc) as f:
                for row in csv.DictReader(f):
                    if str(row.get("symbol", "")).strip().lstrip("0") == code.lstrip("0") \
                            and str(row.get("market", "")).strip().lower() == market.lower():
                        raw = row.get("current_price") or row.get("현재가", "")
                        try:
                            return float(str(raw).replace(",", "").replace("원", "").replace("$", "").strip())
                        except Exception:
                            return None
            break
        except Exception:
            continue
    return None


def _pct_change(closes: list[float], period: int = 5) -> float | None:
    """최근 period일 수익률(%) 반환."""
    if len(closes) < period + 1:
        if len(closes) >= 2:
            period = len(closes) - 1
        else:
            return None
    base = closes[-(period + 1)]
    last = closes[-1]
    if base <= 0:
        return None
    return (last - base) / base * 100.0


def sector_strength(
    market: str = "kr",
    period: int = 5,
) -> list[dict[str, Any]]:
    """
    섹터별 강도를 계산해 내림차순으로 반환.

    Parameters
    ----------
    market : "kr" | "us"
    period : 비교 기준일 수 (기본 5일)

    Returns
    -------
    list of dict:
        sector, sectorLabel, avg_change_pct, sector_score, rep_count
    예) [{"sector": "Defense/Aerospace", "sectorLabel": "방산/항공",
          "avg_change_pct": 3.2, "sector_score": 66.0, "rep_count": 3}, ...]
    """
    reps_map = SECTOR_REPS_KR if market.lower() == "kr" else SECTOR_REPS_US
    results: list[dict[str, Any]] = []

    for sector, codes in reps_map.items():
        changes: list[float] = []
        for code in codes:
            closes = _read_ohlcv_closes(market.lower(), code, days=period + 5)
            # live quote로 최신가 보정
            live = _live_quote_price(market.lower(), code)
            if live and closes:
                closes = closes[:-1] + [live]   # 마지막 값을 live 가격으로 교체
            elif live:
                closes = [live]
            chg = _pct_change(closes, period)
            if chg is not None:
                changes.append(chg)

        if not changes:
            continue
        avg = sum(changes) / len(changes)
        # score: 50 = 보합, +1% ≈ +5점 (100점 기준)
        score = max(0.0, min(100.0, round(50.0 + avg * 5.0, 1)))
        results.append({
            "sector":          sector,
            "sectorLabel":     SECTOR_KR_LABEL.get(sector, sector),
            "avg_change_pct":  round(avg, 2),
            "sector_score":    score,
            "rep_count":       len(changes),
        })

    results.sort(key=lambda x: x["sector_score"], reverse=True)
    return results
