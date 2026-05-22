# NEXORA Cloud Auto-Accumulation Guide

이 폴더는 로컬 노트북 자동누적뿐 아니라 GitHub Actions/VPS에서 1회 실행형 자동누적을 돌릴 수 있도록 준비되어 있습니다.

## 현재 가능한 것

- `run_cloud_accumulator.py`: 클라우드/CI에서 1회 실행 후 종료
- `.github/workflows/nexora-auto-accumulator.yml`: GitHub Actions 예약 실행 예시
- `reports/cloud_readiness_status.json`: 준비 상태 점검 결과

## 사용 전 필요한 것

1. 이 폴더를 GitHub 저장소에 업로드합니다.
2. GitHub 저장소 Settings → Secrets and variables → Actions에 필요한 API 키를 등록합니다.
   - `FINNHUB_API_KEY`
   - `KIS_APP_KEY`
   - `KIS_APP_SECRET`
   - `KIS_ACCOUNT_NO`
3. Actions 탭에서 `NEXORA Auto Accumulator`를 수동 실행하거나 cron이 돌 때까지 기다립니다.

## 주의

- 클라우드 자동누적은 API 키와 저장소 권한 설정이 필요합니다.
- 무료 API는 호출 제한이 있으므로 cron 주기를 너무 촘촘하게 잡지 않는 것이 좋습니다.
- 실제 주문 기능은 포함하지 않습니다. 리포트와 누적 데이터만 갱신합니다.
