
FINAL v29 누적 업데이트 요약

기준 파일
- stock_app_fix_FINAL_v24_all_updates.zip
- Python / Streamlit 앱 구조 유지
- React/Vite로 바꾸지 않음

v25 뉴스 안정화
- core/news_cache_engine.py 추가
- data/news/news_cache.csv 생성/갱신
- reports/news_cache_summary.json 생성/갱신
- 종목별/시장별 뉴스 중복 제거 강화
- 기존 KIS/Finnhub/Google/RSS 뉴스 흐름은 유지하고, 표시 단계에서 캐시+중복 제거를 추가

v26 선택 후보 차트 흐름
- 매수 판단 화면에서 후보 표 아래에 "선택 종목 차트 · 기준가 흐름" 추가
- 후보 선택 시 진입 기준, 손절 기준, 1차 목표가, 일봉/주봉/월봉 차트 확인 가능

v27 보유/매도 화면 정리
- 매도 판단 화면 하단에 v29 보유·매도 핵심 요약 추가
- 보유 점검 수, 우선 매도/축소 체크 수, 상위 사유를 별도 요약

v28 가격 CSV 기반 백테스트 beta 보강
- core/backtest_beta_engine.py가 data/prices, data/price, data/ohlc, data/market, reports/*price*.csv, reports/*ohlc*.csv까지 탐색
- reports/backtest_beta_summary.csv/json 생성

v29 첫 화면/후보 화면 가독성 정리
- 첫 화면 안내 카드 추가
- 후보/표/카드 CSS 가독성 보강
- 매수 판단 화면을 후보표 → 선택 차트 → 기준가 확인 흐름으로 정리

자동 누적
1) 앱을 열면 하루 1회 포트폴리오/벤치마크/백테스트/뉴스캐시 요약을 안전 갱신
2) 브라우저를 닫아도 계속 누적하려면 아래 파일 실행
   start_auto_accumulator.bat

수동 갱신 명령
python update_final_metrics.py
python run_auto_accumulator.py
python app.py --runner v29_update

권장 작업스케줄러
- 장마감 후 1회: python update_final_metrics.py
- PC 켜져 있을 때 계속 누적: start_auto_accumulator.bat 실행 유지

검증 명령
python -m py_compile app.py
python -m py_compile buy_candidate_dashboard.py
python -m py_compile core/news_cache_engine.py
python -m py_compile core/portfolio_history_engine.py
python -m py_compile core/backtest_beta_engine.py
python update_final_metrics.py
