# MONE v68 — 뉴스·재무·시장 대분류 정리

## 핵심 변경
- 뉴스·재무·시장 대분류만 집중 개선
- 국장 뉴스는 한국어/국내 소스 우선: 연합뉴스, 인베스팅닷컴 한국, 한국경제, 매일경제, 이데일리 등 Google News RSS fallback 포함
- 미장 뉴스는 간략 한글 해석을 기본 제공
- GNews 결과가 0건이어도 Google News RSS fallback으로 재시도
- 기업분석 카드: 재무/KPI 데이터가 있으면 카드로 표시, 없으면 왜 부족한지 명확히 표시
- 시장·거시 카드: 지수/거시 지표를 카드형으로 표시
- 종목 내러티브: 뉴스·재무·후보 데이터를 합쳐 규칙 기반 설명 생성

## 실행
- START_HERE_V68_FIXED.bat
- START_APP_NO_SYNC_V68_FIXED.bat
- run_v68_daily_update.bat
