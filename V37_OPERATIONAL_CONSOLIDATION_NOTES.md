# v37 Operational Consolidation Notes

## 핵심 방향
- 일반 모드: 매수/보유/매도 판단에 직접 도움이 되는 화면만 배치
- 관리자 모드: 원본 데이터, 진단, 복기, 시스템 점검, 설정 파일 확인 전용
- 중복 메뉴 제거 및 대분류/소분류 재배치

## 일반 모드 대분류
1. 오늘 실행
2. 매수
3. 보유·매도
4. 차트·수급
5. 뉴스·분석
6. 관심·설정

## 관리자 모드 대분류
1. 데이터 진단
2. 예측·복기
3. 원본·리포트
4. 시스템·설정
5. 기타 기존 기능

## 새로 추가한 일반 모드 화면
- 예산·권장수량
- 선택 종목 차트·수급
- 뉴스·내러티브
- 재무·가치·KPI
- 시장·거시
- 퀀트 백테스트
- 커스텀 스크리너

## 추가 파일
- core/operational_plus_engine.py
- run_v37_operational_update.py
- run_v37_operational_update.bat

## 실행
```powershell
python app.py --runner v37
```
또는
```powershell
.\run_v37_operational_update.bat
```
