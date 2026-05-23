FINAL v24 패치 요약

포함된 업데이트
1) v20 뉴스 최신성 필터 유지
- 샘플뉴스 제외
- 오래된 뉴스 숨김
- 최대 5개, 중복 제거
- 미장 영어뉴스 한글 설명

2) v21 기술적 시그널 유지
- RSI/MACD/ATR/볼린저 밴드
- 스윙 고점/저점
- LONG/SHORT/NEUTRAL 방향 배지

3) v22 보유/매도 리스크 + 예산·권장수량 유지
- 포트폴리오 리스크 요약
- 예산/현금/손실허용률 기반 권장수량 계산

4) v23 포트폴리오 이력 저장 유지
- data/portfolio/portfolio_daily_nav.csv
- data/portfolio/position_daily_snapshot.csv
- reports/portfolio_risk_metrics.json

5) v24 최종 추가
- data/market/benchmark_daily.csv 자동 생성/갱신
- yfinance가 가능하면 KOSPI/KOSDAQ/S&P500/NASDAQ benchmark history 자동 수집
- local actual_results 등에 지수 행이 있으면 benchmark로 변환
- 베타/알파 계산 기반 마련
- 간단 백테스트 Beta 요약 생성
  reports/backtest_beta_summary.csv
  reports/backtest_beta_summary.json

수동 실행 명령
python save_portfolio_history.py
python save_benchmark_history.py
python save_backtest_beta.py
python update_final_metrics.py

권장 작업스케줄러
장마감 후 1회:
python update_final_metrics.py

확인 명령
python -m py_compile app.py
python -m py_compile buy_candidate_dashboard.py
python -m py_compile core\portfolio_history_engine.py
python -m py_compile core\backtest_beta_engine.py
python -m pytest .\tests -q
python daily_system_check.py
