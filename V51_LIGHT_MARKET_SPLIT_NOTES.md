# v51 Light Market Split Update

## 핵심 변경
- 오늘 행동판을 국장/미장/통합으로 나눠서 확인할 수 있게 했습니다.
- 매수 위험·제외 화면도 국장/미장 분리 필터를 적용했습니다.
- 보유·매도 권장수량에서 None/nan/0주짜리 가짜 행을 제거했습니다.
- 뉴스 카드에 GNews 키 인식/수집 건수/오류 원인을 더 명확하게 표시했습니다.
- 화면에서 무거운 계산을 반복하지 않고 `v51_light` 리포트를 먼저 생성해 읽도록 했습니다.

## 실행
```powershell
.\START_HERE_V51_FIXED.bat
```

## 수동 갱신
```powershell
.\run_v51_daily_update.bat
```
