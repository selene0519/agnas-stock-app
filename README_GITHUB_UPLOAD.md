# AGNAS Stock App - GitHub Upload Safe Package

이 ZIP은 GitHub에 올려도 되는 코드 중심 패키지입니다.

## 포함됨
- 앱 코드: `app.py`, `core/`, `runners/`
- 테스트: `tests/`
- 실행 스크립트: `run_*.py`, `*.bat`
- GitHub Actions 준비 파일: `.github/workflows/`
- 예시 환경 파일: `.env.example`

## 제외됨
- 실제 API 키와 로컬 설정: `.env`, `finnhub_config.json`, `kis_config.json`, `secrets.toml`
- 로그/백업/실행 결과: `logs/`, `backups/`, `reports/*.csv`, `reports/*.json`
- 개인 포트폴리오/수집 데이터: `data/**/*.csv`, `data/**/*.json`
- 파이썬 캐시: `__pycache__/`, `.pytest_cache/`

## 업로드 후 해야 할 일
1. GitHub 저장소에서 `Add file` → `Upload files`를 누릅니다.
2. 이 ZIP을 압축 해제한 뒤, 안의 파일과 폴더 전체를 업로드합니다.
3. API 키는 코드에 넣지 말고 GitHub `Settings` → `Secrets and variables` → `Actions`에 넣습니다.
4. PC에서 실행할 때는 `.env.example`을 복사해 `.env`로 만든 뒤, 본인 API 키를 입력합니다.
