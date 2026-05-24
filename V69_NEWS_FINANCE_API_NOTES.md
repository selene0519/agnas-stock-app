# MONE v69 — News / Finance API Live Connection

## 핵심
- 국장 재무: DART corp_code 매핑 + 재무제표 원자료 수집 시도
- 미장 재무: Finnhub metric + SEC companyfacts 연결
- 뉴스: GNews/RSS + 선택적 Apify Actor 연결 구조 추가
- 화면: 뉴스·재무·시장 대분류가 v69 리포트를 우선 읽도록 변경

## 필요한 로컬/GitHub Secrets
- GNEWS_API_KEY
- FINNHUB_API_KEY
- DART_API_KEY
- APIFY_TOKEN 선택
- APIFY_NEWS_ACTOR_ID 선택
- SEC_USER_AGENT 선택

## 실행
- START_HERE_V69_FIXED.bat
- run_v69_daily_update.bat
