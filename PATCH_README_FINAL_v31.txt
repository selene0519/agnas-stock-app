NEXORA / stock_app FINAL v31 patch

기준 파일:
- stock_app_FINAL_v30_autostart_status.zip

이번 패치 목적:
1) 사용자가 지적한 차트 이동평균선 표시를 MA5에서 MA10 중심으로 변경
2) 강한 관찰 후보가 스윙 후보 화면에 섞여 보이는 문제 분리
3) 강한 관찰 후보 화면에서 확장 화면 오류 안내만 보이던 원인 수정

반영 내역:
- 차트 기본 이동평균선 표시: MA5 -> MA10
  - 관심종목 차트
  - 후보 선택 차트
  - 종목 검색/차트
  - 기술적 시그널 문구: MA10/MA20 기준으로 변경
- MA10 계산 보강
  - calculate_indicators(): MA10 생성 추가
  - ensure_chart_moving_averages(): MA10 생성 추가
- 스윙 후보표 화면 정리
  - 스윙 후보표 내부에서 강한 관찰 후보 테이블을 직접 표시하지 않음
  - 강한 관찰 후보 개수가 있으면 별도 메뉴에서 확인하라는 안내만 표시
- 강한 관찰 후보 전용 화면 보정
  - _render_report_data_table()의 include_display_names 누락 변수 수정
  - 강한 관찰 후보 화면은 aggressive_score 기준 정렬 후 별도 표로 표시

검증:
- python -m py_compile app.py 통과
- 전체 Python 파일 py_compile 통과
- ZIP 압축 검사 통과

아직 미반영/추가 개선 가능 항목:
1) 노트북이 완전히 꺼져도 자동누적되는 클라우드/서버형 구조
2) 예측 복기 고도화: 확률 구간별 실제 성공률, 섹터별/종목별 정확도, 틀리는 조건 자동 추출
3) 리스크 우선 판단 강화: 손익비 1:2 미만 경고, 변동성 큰 종목 비중 축소, 시장 약세 시 단일종목 확신도 감점
4) UI 전체 중복 정리: 관리자/일반 화면 완전 분리, 긴 표 핵심 요약 우선 표시, 모바일 화면 대응
5) API/데이터 상태판 강화: API 제한, 가격 누락, 뉴스 실패, fallback 사용 여부를 화면별로 더 명확히 표시
6) 뉴스/공시 고도화: 호재/악재 강도와 실제 주가 반응 복기 연결
7) 보유종목 매도 자동점검 고도화: 보유기간, 익절분할, trailing stop, 손절 재조정 히스토리 반영

실행:
- 앱 실행: streamlit run app.py
- 자동누적 수동 실행: .\start_auto_accumulator.bat
- Windows 자동 시작 등록: .\install_autostart.bat
- 자동 시작 해제: .\uninstall_autostart.bat
