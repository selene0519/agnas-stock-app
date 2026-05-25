# MONE v91 Integrated Operations Update

v91은 v86~v91 로드맵을 한 번에 합친 통합판입니다.

## 포함 내용
- v86 데이터 안정성: 현재가/수급/재무/뉴스 fallback 중심 리포트 유지
- v87 결과 추적: data/history/outcome_history.csv 생성 및 대기 행 추가
- v88 신뢰도 점수: v91_confidence_cards_kr/us.csv 생성
- v89 종목 내러티브: 요약/근거/주의/다음행동 4문장 구조
- v90 운영 대시보드: v91_operational_dashboard_kr/us.csv 생성
- v91 백업/복구 준비: backups/v91_backup_manifest.json 생성

## 일반 화면 원칙
- 첫 화면 5개 카드 고정
- 일반 화면은 카드 중심
- 원본 CSV/API 진단/rows는 관리자 모드로 분리

## 실행
```powershell
.un_v91_daily_update.bat
.\START_APP_NO_SYNC_V91_FIXED.bat
```

## 확인
```powershell
dir .eports91_*
Import-Csv .eports91_data_status.csv | Select-Object 시장,항목,행수,상태,설명 | Format-Table -Auto
Import-Csv .eports91_confidence_cards_kr.csv | Select-Object 종목코드,종목명,신뢰도점수,데이터충분도 | Format-Table -Auto
```
