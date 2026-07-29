#!/usr/bin/env bash
# CI가 생성한 앱 데이터만 골라 stage → commit → push.
#
# mone-auto-accumulator가 60분 타임아웃에 걸려(월요일 주간 스텝 + 25분짜리
# 레거시 cloud update) 워크플로를 3개로 쪼개면서, 131줄짜리 커밋 로직이
# 3중 복붙될 뻔해서 여기로 뺐다. 스테이징 목록이 갈라지면 어떤 워크플로는
# 산출물을 조용히 안 올리게 된다 — 실제로 예측 원장이 그렇게 유실됐었다.
#
# 사용법:
#   scripts/ci_commit_app_data.sh "<commit message>" [--verify-vtj]
#
# --verify-vtj : VTJ 산출물이 변경됐는데 stage 안 됐으면 실패시킨다
#                (VTJ를 생성하는 워크플로에서만 의미가 있다)
set -uo pipefail

COMMIT_MESSAGE="${1:?commit message required}"
VERIFY_VTJ=0
[ "${2:-}" = "--verify-vtj" ] && VERIFY_VTJ=1

: "${GITHUB_REF_NAME:?GITHUB_REF_NAME required}"

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

stage_app_data() {
  # Add only files the app must read from GitHub raw.
  # Do NOT add whole reports/ or whole data/ because that brings old logs, backtests, alerts, and temporary files.
  git add predictions.csv runner_status_kr.json runner_status_us.json 2>/dev/null || true
  git add paper_trading_log.csv paper_trading_summary.csv 2>/dev/null || true

  # Core candidate / latest run outputs.
  git add reports/swing_candidates_kr*.csv reports/swing_candidates_us*.csv 2>/dev/null || true
  git add reports/latest_kr_* reports/latest_us_* 2>/dev/null || true
  git add reports/stockapp_*.csv reports/stockapp_*.json 2>/dev/null || true

  # MONE v3.6 app-facing reports.
  git add reports/mone_v36_*.csv reports/mone_v36_*.json 2>/dev/null || true
  git add reports/reco_cache/*.json 2>/dev/null || true
  git add reports/kr_recommendation_gen_status.json reports/us_recommendation_gen_status.json 2>/dev/null || true
  git add reports/strategy_win_rates.json reports/dart_financial_data_kr.csv reports/dart_financial_status.json 2>/dev/null || true
  # 기업개황(사업 내용). allowlist에 빠지면 수집 스텝이 성공해도 산출물이
  # 매번 버려진다 — 레거시 산출물 68개가 그렇게 2개월간 사라진 전례가 있다.
  git add data/fundamental/dart_company_profile_kr.csv reports/dart_company_profile_status.json 2>/dev/null || true
  git add reports/lens_journal_kr.csv reports/lens_calibration_kr.json reports/regime_lens_candidates_kr.json 2>/dev/null || true
  git add reports/lens_prediction_ledger_kr.csv reports/lens_live_journal_kr.csv 2>/dev/null || true
  git add reports/lens_promotion_status_kr.json 2>/dev/null || true
  git add reports/leader_breakout_candidates_kr.json reports/leader_breakout_candidates_us.json 2>/dev/null || true
  git add reports/relative_strength_leaders_kr.json reports/relative_strength_leaders_us.json 2>/dev/null || true
  git add reports/kr_supply_flow_history.csv reports/disclosures_kr_history.csv 2>/dev/null || true
  git add reports/smart_rank_kr.json reports/high_conviction_kr.json 2>/dev/null || true
  git add reports/high_conviction_ledger_kr.csv reports/high_conviction_pnl_kr.json 2>/dev/null || true
  git add data/sector_map_kr.csv data/sector_map_us.csv 2>/dev/null || true
  git add data/kr_supply_flow.csv data/kr_excluded_symbols.csv 2>/dev/null || true
  git add reports/kr_close_ohlcv_refresh_status.json reports/kr_close_ohlcv_coverage_audit.csv reports/kr_close_validation_status.json 2>/dev/null || true
  git add reports/us_close_ohlcv_refresh_status.json 2>/dev/null || true
  python scripts/guard_ohlcv_no_shrink.py || true
  git add data/market/ohlcv/kr_*_daily.csv 2>/dev/null || true
  git add data/market/ohlcv/us_*_daily.csv 2>/dev/null || true
  git add reports/operational_readiness*.json reports/operation_health*.json 2>/dev/null || true
  git add reports/api_data_status_center*.csv reports/api_data_status_center*.json 2>/dev/null || true
  git add reports/gnews_*.csv reports/gnews_*.json reports/news_*.csv reports/news_*.json 2>/dev/null || true
  git add reports/fundamental_*.csv reports/fundamental_*.json 2>/dev/null || true
  # portfolio_risk_summary.json 은 개인 포트폴리오 파생 데이터라 커밋하지 않는다(.gitignore).

  # Live quote snapshots. KIS-only rows are separated from fallback rows.
  git add reports/kis_live_refresh_status.json 2>/dev/null || true
  git add reports/kis_current_price_*.csv 2>/dev/null || true
  git add reports/intraday_realtime_snapshot*.csv reports/intraday_quote_snapshot*.csv 2>/dev/null || true
  git add data/stockapp/kis_current_price_*.csv 2>/dev/null || true
  git add data/stockapp/intraday_realtime_snapshot*.csv data/stockapp/intraday_quote_snapshot*.csv 2>/dev/null || true
  git add mone-web-app/backend/cache/quotes_cache.json 2>/dev/null || true

  # Data files used by the app as source/cache.
  git add data/history data/calendar data/stockapp data/market data/news data/disclosures 2>/dev/null || true
  # 시총/거래대금 유니버스 확장 결과(월요일 build_universe). build_universe는 레포 루트
  # candidate_universe_{market}.csv 에 쓰는데 그동안 git add 목록에 없어 커밋 누락 → 5월 이후 동결됨.
  git add candidate_universe_kr.csv candidate_universe_us.csv 2>/dev/null || true
  git add data/signal_ledger.csv data/signal_outcomes.csv data/recommendation_snapshots.csv data/recommendation_validation_results.csv 2>/dev/null || true
  git add data/virtual_trade_journal.csv data/virtual_trade_evaluations.csv data/virtual_trade_calibration_*.csv data/postmortem_ledger.csv data/attribution_feedback.json reports/virtual_trade_journal_status.json reports/virtual_trade_self_learning_status.json 2>/dev/null || true
  git add data/paper/paper_stops.json 2>/dev/null || true
  git add reports/self_correction_params.json reports/self_correction_params_v*.json 2>/dev/null || true
  git add reports/walkforward_results_kr.csv reports/walkforward_summary_kr.json 2>/dev/null || true
  git add reports/walkforward_results_us.csv reports/walkforward_summary_us.json 2>/dev/null || true
  git add reports/backtest_summary.json 2>/dev/null || true
  git add reports/ensemble_calibration_*.json 2>/dev/null || true
  git add reports/live_calibration_kr.json 2>/dev/null || true
  # 예측 원장 — accumulator가 캡처해놓고 stage를 안 해서 결과가 매번
  # 버려지고 있었다. 정산(mone-settle-validations)만 stage 하고 있었음.
  git add reports/virtual_prediction_ledger.csv reports/recommendation_capture_status.json 2>/dev/null || true
  git add reports/data_freshness_status.json 2>/dev/null || true
  git add reports/factor_attribution.json 2>/dev/null || true
  # kelly_position_sizes.json 은 개인 보유 기반이라 커밋 제외(.gitignore).
  git add reports/factor_based_filter_adjustments.json 2>/dev/null || true

  # Keep ignore rules up to date, but never commit secrets, caches, node_modules, or Next build artifacts.
  git add .gitignore mone-web-app/.gitignore mone-web-app/frontend/.gitignore 2>/dev/null || true
  git reset -- .env .env.local "*.env" "*token_cache*.json" "**/*token_cache*.json" 2>/dev/null || true
  git reset -- mone-web-app/backend/.env mone-web-app/backend/.env.* mone-web-app/frontend/.env.local mone-web-app/frontend/.env.* 2>/dev/null || true
  git reset -- mone-web-app/frontend/.next mone-web-app/frontend/node_modules node_modules 2>/dev/null || true
  git reset -- data/backtest data/alerts logs backups mone-web-app_backup_before_v3_5 mone-web-app_backup_before_v3_5_2 mone-web-app_backup_before_v3_5_3 mone-web-app_backup_before_v3_6_1_operational 2>/dev/null || true
  git reset -- 'reports/daily_summary_*' 'reports/summary_*' 'reports/order_plan_*_202*.csv' 'reports/test_*.csv' 2>/dev/null || true
}

verify_vtj_outputs_staged() {
  local failed=0
  local path
  for path in \
    data/virtual_trade_journal.csv \
    data/virtual_trade_evaluations.csv \
    data/virtual_trade_calibration_approvals.csv \
    data/virtual_trade_calibration_applications.csv \
    data/attribution_feedback.json \
    reports/virtual_trade_journal_status.json \
    reports/virtual_trade_self_learning_status.json
  do
    [ -e "${path}" ] || continue
    [ -n "$(git status --porcelain -- "${path}")" ] || continue

    if git diff --cached --quiet -- "${path}"; then
      echo "::error::VTJ output exists but was not staged: ${path}"
      failed=1
    elif ! git diff --quiet -- "${path}"; then
      echo "::error::VTJ output still has unstaged changes after staging: ${path}"
      failed=1
    fi
  done
  return "${failed}"
}

for attempt in 1 2 3; do
  echo "Commit attempt ${attempt}: align HEAD with origin/${GITHUB_REF_NAME} before staging generated data."
  git fetch origin "${GITHUB_REF_NAME}"
  git reset --mixed "origin/${GITHUB_REF_NAME}"
  stage_app_data
  if [ "${VERIFY_VTJ}" = "1" ]; then
    verify_vtj_outputs_staged
  fi

  echo "=== staged files ==="
  git diff --cached --name-only

  if git diff --cached --quiet; then
    echo "No app data/report changes to commit."
    exit 0
  fi

  git commit -m "${COMMIT_MESSAGE}"
  if git push origin "HEAD:${GITHUB_REF_NAME}"; then
    exit 0
  fi

  echo "Push race detected; retrying from latest origin/${GITHUB_REF_NAME}."
  sleep 5
done

echo "Failed to push generated data after retries."
exit 1
