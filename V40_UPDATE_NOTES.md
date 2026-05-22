# v40 Streamlit Stabilized Analysis Upgrade

## 목적
Streamlit 구조를 유지하면서, 나중에 FastAPI/Next.js로 옮기기 쉽도록 계산 로직을 `core/v40_analysis_engine.py`로 분리했습니다.

## 추가 기능
- 재무·가치·KPI 기초 분석
- 시장·거시 요약 보강
- 퀀트 백테스트 요약 보강
- Black-Scholes 옵션 프라이싱 기초 계산기
- GBM 기반 몬테카를로 기초 시뮬레이션
- 일반모드/관리자모드 메뉴 중복 정리 유지
- pytest 전체 통과를 위한 누락 스키마 및 runner 보강

## 실행
```powershell
.\run_v40_full_update.bat
```
