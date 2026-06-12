# Broker Bridge — 로컬 증권사 연동 가이드

Render/Vercel 서버가 증권사 API를 직접 호출하지 않습니다.  
로컬 PC에서 실제 보유종목을 조회한 뒤 MONE 백엔드에 업로드하는 방식입니다.

---

## 전체 흐름

```
[로컬 PC]
sync_kis_holdings.py   →  data/kis_holdings_kr.csv
sync_toss_holdings.py  →  data/toss_holdings_kr.csv
        ↓
local_broker_bridge_upload.py  →  POST /api/broker/local-bridge/upload
        ↓
[Render 백엔드]
/api/holdings-clean  (source: local_bridge, broker: kis|toss)
/api/final/portfolio-risk  (actualHoldings 포함)
```

---

## 1. 환경변수 설정

`.env.example`을 복사해서 `.env`를 만들고 값을 채웁니다.  
(`.env`는 Git에 올라가지 않습니다)

```bash
cp .env.example .env
```

```ini
# 한국투자증권
KIS_APP_KEY=your_app_key
KIS_APP_SECRET=your_app_secret
KIS_ACCOUNT_NO=12345678XX    # 10자리 (계좌번호 붙여쓰기)

# 토스증권
TOSS_CLIENT_ID=your_client_id
TOSS_CLIENT_SECRET=your_client_secret

# MONE 업로드용 토큰 (로그인 후 개발자도구 > localStorage > mone_user_token)
MONE_USER_TOKEN=eyJhbGci...
MONE_BACKEND_URL=https://agnas-stock-app.onrender.com
```

---

## 2. 한국투자증권 보유종목 조회

```bash
# 조회만
python scripts/sync_kis_holdings.py

# 조회 + MONE 자동 업로드
python scripts/sync_kis_holdings.py --upload

# 커스텀 백엔드 URL
python scripts/sync_kis_holdings.py --upload --backend-url https://agnas-stock-app.onrender.com

# 모의투자 모드
python scripts/sync_kis_holdings.py --mock
```

결과 파일: `data/kis_holdings_kr.csv`

---

## 3. 토스증권 보유종목 조회

```bash
# 조회만
python scripts/sync_toss_holdings.py

# 조회 + MONE 자동 업로드
python scripts/sync_toss_holdings.py --upload

# 특정 계좌 지정
python scripts/sync_toss_holdings.py --upload --account-seq 12345
```

결과 파일: `data/toss_holdings_kr.csv`

---

## 4. 수동 업로드 (이미 CSV가 있는 경우)

```bash
python scripts/local_broker_bridge_upload.py \
  --broker kis \
  --file data/kis_holdings_kr.csv \
  --backend-url https://agnas-stock-app.onrender.com \
  --user-token $MONE_USER_TOKEN \
  --mode replace_broker
```

---

## 5. Windows 작업 스케줄러 자동화 예시

```bat
@echo off
set MONE_USER_TOKEN=eyJhbGci...
set MONE_BACKEND_URL=https://agnas-stock-app.onrender.com

python scripts/sync_kis_holdings.py --upload >> logs/kis_sync.log 2>&1
python scripts/sync_toss_holdings.py --upload >> logs/toss_sync.log 2>&1
```

---

## CSV 컬럼 형식

```
symbol,name,market,quantity,avgPrice,currentPrice,valuation,pnl,pnlPct
005930,삼성전자,kr,10,70000,71500,715000,15000,2.14
```

| 컬럼 | 설명 |
|---|---|
| symbol | 종목코드 (KR: 6자리 숫자) |
| name | 종목명 |
| market | kr / us |
| quantity | 보유 수량 |
| avgPrice | 평균 매입가 |
| currentPrice | 현재가 |
| valuation | 평가금액 |
| pnl | 평가손익 (원) |
| pnlPct | 평가손익률 (%) |

---

## 보안

- `KIS_APP_KEY`, `KIS_APP_SECRET`, `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` → `.env` (Git 제외)
- 토큰 캐시 파일 → `data/*_token_cache.json` (Git 제외)
- 보유종목 스냅샷 → `data/kis_holdings_kr.csv`, `data/toss_holdings_kr.csv` (Git 제외)
- 주문 API 미호출 (조회 전용)
- Render 서버가 직접 증권사 API를 호출하지 않음
