# v62 GNews 0건 수정

- `GNEWS_API_KEY`를 기본 뉴스 키로 사용합니다.
- GNews search + top-headlines를 모두 시도합니다.
- 국장/미장 검색어를 넓히고, lang/country 조건 제거 fallback을 추가했습니다.
- API 성공이지만 0건일 때 진단 행과 시도 내역을 남깁니다.
- 뉴스 카드가 완전히 비지 않도록 0건 진단 카드를 표시합니다.

실행:

```powershell
.\START_HERE_V62_FIXED.bat
```

수동 갱신:

```powershell
.\run_v62_daily_update.bat
```
