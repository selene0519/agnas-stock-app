# MONE Virtual Trade Journal v1 Spec

## Purpose

MONE should remember recommendations as if a cautious virtual trader acted on them, without sending real orders. The journal is not a marketing backtest. It is an immutable decision log that records what MONE knew at the recommendation time, how a virtual trade would have been filled, how it ended, and which failure pattern should feed later calibration suggestions.

This spec covers:

- forward paper trading from current recommendations
- historical replay that blocks future data during recommendation generation
- market-analog replay that finds past market movements similar to the current market and records what happened next
- conservative fill and exit rules
- structured postmortem tags plus human-readable review text
- calibration suggestions that require human approval before affecting strategy weights

Non-goals:

- no real broker order placement
- no automatic strategy-weight mutation
- no use of future data during historical recommendation generation

## Existing Code Touchpoints

Use the current validation stack where possible:

- `mone-web-app/backend/app/services/signal_ledger.py`: recommendation snapshots and validation result patterns
- `mone-web-app/backend/app/services/operation_history.py`: existing virtual operation CSV flow, to be replaced or wrapped by the stricter journal
- `mone-web-app/backend/app/engine/backtest_v2.py`: conservative fill model and stop-first same-day behavior
- `mone-web-app/backend/app/engine/outcome_analyzer.py`: outcome reason classifier, to be expanded into journal failure tags
- `mone-web-app/backend/app/engine/self_correction_v2.py`: correction parameter builder, to consume only approved/eligible journal-derived summaries

## Source Types

Every journal row must store `source_type` from day one.

| source_type | Meaning | Calibration weight |
|---|---|---:|
| `FORWARD_PAPER_TRADE` | Created from real current recommendations after the fact cannot be known yet | 1.0 |
| `MANUAL_REVIEWED` | Forward paper trade reviewed or corrected by the user | 1.2 |
| `HISTORICAL_REPLAY` | Created by replaying a past date using only data available as of `as_of_date` | 0.3 to 0.5 |
| `BACKTEST_EXPERIMENT` | Research-only run, not part of the trusted journal | 0.1 to 0.2 |

`source_type` must never be inferred from filename alone.

## Journal Sessions

Every journal row also stores `journal_session` so MONE can keep the AI's plan separate from the later paper-trade outcome.

| journal_session | Meaning | Evaluation policy |
|---|---|---|
| `PREMARKET_PLAN` | The AI's before-market plan and watchpoints | Stored as a plan; excluded from trade evaluation and calibration by default |
| `INTRADAY_CHECK` | Optional intraday check-in | Stored as a check; excluded from trade evaluation and calibration by default |
| `AFTER_CLOSE_TRADE` | After-close paper trade snapshot | Eligible for evaluation and calibration |
| `FOLLOWUP_EVALUATION` | Later review or corrected evaluation | Eligible for evaluation and calibration |

`session_note` is generated at capture time from the frozen recommendation fields. It is human-readable journal text, but structured fields remain the source of truth.

## Journal Candidate Filter

The journal should not record every ranked symbol. It should record the best actionable candidates per `market + mode + horizon`.

Default v1 filter:

| Field | Required rule |
|---|---|
| `market` | `kr` or `us` |
| `mode` | `conservative`, `balanced`, or `aggressive` |
| `horizon` | `short`, `swing`, or `mid` |
| `finalRankScore` or `finalScore` | `>= 68.0` |
| `expectedValue` | `>= 1.0` |
| `rrActual` or `riskRewardRatio` | `>= 1.5` |
| `probability` | `>= 60.0` when present |
| `riskScore` | `>= 45.0` when present |
| `eventRiskScore` | `<= 60.0` when present |
| `dataStatus` | allow `NORMAL` and `PARTIAL`; reject `STALE`, `ERROR`, `NO_DATA` |
| `tradeBlockStatus` | reject `BLOCK`, `CAUTION`, `EV_NEGATIVE`, `ENSEMBLE_LOW` |
| price levels | numeric `entry`, `stop`, `target` required; `target > entry > stop` |
| decision | allow `오늘 진입`, `조건부 진입`, `대기 관찰` only |

Ranking after filtering:

1. `decisionBucket` priority: `오늘 진입`, then `조건부 진입`, then `대기 관찰`
2. `expectedValue` descending
3. `finalRankScore` descending
4. `rrActual` / `riskRewardRatio` descending

Default cap:

- `Top 5` per `market + mode + horizon`
- hard cap `Top 10` only when the user explicitly requests broader journal coverage

Rejected rows should be counted in a daily summary with `reject_reason`, but should not become trade journal rows.

## Immutable Snapshot Rules

At creation time, store the recommendation as an immutable snapshot.

Required fields:

```text
journal_id
source_type
as_of_date
generated_at
market
mode
horizon
symbol
name
decision_bucket
entry_type
entry_price
stop_price
target_price
current_price_at_signal
final_rank_score
expected_value
risk_reward_ratio
probability
data_status
data_confidence
price_source
market_regime_at_signal
sector
raw_recommendation_json
```

Rules:

- Do not overwrite a journal row when strategy code changes.
- Corrections create new calibration records, not mutated historical recommendations.
- Historical replay must store `as_of_date` and the data cutoff used to generate the recommendation.
- Future OHLCV may be read only by evaluation code after the snapshot is already fixed.

## Entry Model

Supported `entry_type` values:

| entry_type | Use when | Fill rule |
|---|---|---|
| `NEXT_OPEN` | `decisionBucket = 오늘 진입` and the recommendation is generated after market close or as a daily batch | fill at next trading day's open plus slippage |
| `LIMIT_TOUCH` | conditional/waiting entries, including `조건부 진입` and `대기 관찰` | fill only if `low <= entry <= high` within the entry window |
| `NO_FILL_CANCELLED` | entry was not touched before the entry window expired | mark as cancelled, excluded from return |

Default entry windows:

| horizon | entry window |
|---|---:|
| `short` | 3 trading days |
| `swing` | 5 trading days |
| `mid` | 10 trading days |

Slippage and cost defaults:

| market | buy slippage | sell slippage | tax/commission |
|---|---:|---:|---:|
| `kr` | 0.10% | 0.10% | 0.21% |
| `us` | 0.10% | 0.10% | 0.10% |

## Exit Model

Default evaluation windows:

| horizon | evaluation window |
|---|---:|
| `short` | 5 trading days after fill |
| `swing` | 20 trading days after fill |
| `mid` | 60 trading days after fill |

Exit order:

1. If target and stop are both touched on the same daily candle, stop wins.
2. If only target is touched, exit at target.
3. If only stop is touched, exit at stop.
4. If neither is touched by the evaluation window end, exit at the last close and classify the time exit.

Daily OHLCV cannot tell intraday event order, so stop-first is mandatory until minute-level data exists.

## Outcome Taxonomy

Required `outcome` values:

```text
PENDING
CANCELLED_NOT_FILLED
TARGET_HIT
STOP_HIT
TIME_EXIT_NEAR_TARGET
TIME_EXIT_NEAR_STOP
TIME_EXIT_MID
TIME_EXIT_FLAT
DATA_PENDING
DATA_INVALID
```

Time-exit classification uses post-fill MFE/MAE:

```text
target_progress = mfe_pct / target_distance_pct
stop_progress = abs(mae_pct) / stop_distance_pct
```

Rules:

- `TIME_EXIT_NEAR_TARGET`: `target_progress >= 0.80` and `stop_progress < 0.80`
- `TIME_EXIT_NEAR_STOP`: `stop_progress >= 0.80` and `target_progress < 0.80`
- If both are `>= 0.80`, choose `TIME_EXIT_NEAR_STOP` when final net PnL is negative; otherwise choose `TIME_EXIT_MID`.
- `TIME_EXIT_FLAT`: `abs(net_pnl_pct) <= 0.5`, `target_progress < 0.40`, and `stop_progress < 0.40`
- `TIME_EXIT_MID`: remaining completed time exits

## Failure Tags

Each evaluated row should have one primary `failure_reason` and optional `secondary_tags`.

Initial primary tags:

```text
NONE
REGIME_MISMATCH
ENTRY_TIMING
FALSE_SIGNAL
OVEREXTENDED_ENTRY
VOLATILITY_SPIKE
DATA_QUALITY
SECTOR_WEAKNESS
THESIS_VALID_BUT_SLOW
TARGET_TOO_FAR
STOP_TOO_TIGHT
```

Default mapping:

| Condition | primary failure_reason |
|---|---|
| `TARGET_HIT` with positive net PnL | `NONE` |
| `STOP_HIT` and regime changed from risk-on/neutral to risk-off | `REGIME_MISMATCH` |
| `CANCELLED_NOT_FILLED` and later MFE would have been strong | `ENTRY_TIMING` |
| `STOP_HIT` with weak MFE and no regime/sector explanation | `FALSE_SIGNAL` |
| Entry filled quickly but MAE is large before any favorable move | `OVEREXTENDED_ENTRY` |
| MAE/MFE ratio is high or ATR/volatility spike is detected | `VOLATILITY_SPIKE` |
| source data was `PARTIAL`, validation confidence low, or OHLCV missing | `DATA_QUALITY` |
| sector return materially lags market during holding window | `SECTOR_WEAKNESS` |
| `TIME_EXIT_NEAR_TARGET` or positive `TIME_EXIT_MID` without target hit | `THESIS_VALID_BUT_SLOW` |
| `TIME_EXIT_NEAR_TARGET` with target not hit | `TARGET_TOO_FAR` |
| `STOP_HIT` after meaningful MFE, especially with tight stop distance | `STOP_TOO_TIGHT` |

The human-readable `review_text` must be generated from these structured fields, not used as the only source of truth.

### v1 tag coverage

`REGIME_MISMATCH` is active when exit regime deteriorates to risk-off after a risk-on or neutral signal. `SECTOR_WEAKNESS` is active as a secondary tag from a conservative heuristic when a stopped trade shows weak favorable movement and sector metadata exists. Full sector-relative return attribution remains a future enhancement.

## Journal Evaluation Fields

Required evaluation fields:

```text
status
outcome
filled
fill_date
fill_price
exit_date
exit_price
gross_pnl_pct
net_pnl_pct
mfe_pct
mae_pct
bars_held
entry_window_days
evaluation_window_days
target_progress
stop_progress
failure_reason
secondary_tags
regime_at_entry
regime_at_exit
signal_confidence
data_confidence
review_text
evaluated_at
```

`status` values:

```text
OPEN
PENDING
EVALUATED
CANCELLED
DATA_PENDING
DATA_INVALID
```

## Historical Replay Data Firewall

Historical replay is allowed only if recommendation generation and evaluation are separated.

Generation phase:

- input cutoff is `as_of_date`
- OHLCV, price, regime, sector, financial, news, and universe inputs must be filtered to `date <= as_of_date`
- recommendation rows are written before any future outcome fields are computed
- no full-period percentile, average, rank, or universe statistic may use rows after `as_of_date`

Evaluation phase:

- may read bars after `as_of_date`
- may only update evaluation fields, never the frozen recommendation snapshot
- must preserve `source_type = HISTORICAL_REPLAY`

Any replay row that cannot prove its cutoff should be marked `DATA_INVALID` and excluded from calibration.

### v1 replay method

The current historical replay implementation is `synthetic_cutoff_ohlcv_v1`: it generates candidates from OHLCV available at `as_of_date`, not from a full point-in-time run of the production MONE recommendation engine. Treat it as a future-data firewall and evaluation harness, not as proof that MONE would have selected the same symbols on that historical date.

## Market Analog Replay

MONE can compare the current market movement with past benchmark movement using only benchmark data available up to the comparison date.

Default benchmark sources:

| market | benchmark candidates |
|---|---|
| `kr` | `KOSPI`, then `KOSDAQ` |
| `us` | `SPY`, then `QQQ`, then `SP500` |

The analog vector includes:

```text
ret_1d_pct
ret_5d_pct
ret_20d_pct
ret_60d_pct
vol_20d_pct
ma20_gap_pct
ma60_gap_pct
drawdown_20d_pct
range_20d_pct
volume_20d_ratio
regime
```

Flow:

```text
current benchmark vector
-> nearest historical benchmark vectors before as_of_date
-> historical_replay(as_of_date = analog date)
-> evaluate future bars after the snapshot
-> summarize win rate, average PnL, outcomes, and failure reasons
```

This answers: "When the market previously moved like this, what did MONE's cutoff replay select, how did those candidates move afterward, and what failure pattern was observed?"

## Calibration Flow

Calibration must be suggestion-first, approval-later.

Flow:

```text
journal rows
-> evaluated outcomes
-> failure pattern summary by market/mode/horizon/source_type
-> calibration suggestions
-> human approval
-> strategy parameter version
```

Minimum sample rules:

| source_type | minimum evaluated samples before suggestions |
|---|---:|
| `FORWARD_PAPER_TRADE` | 30 |
| `MANUAL_REVIEWED` | 20 |
| `HISTORICAL_REPLAY` | 100 |
| `BACKTEST_EXPERIMENT` | never auto-suggest; research only |

Suggestion examples:

- `REGIME_MISMATCH` share above 20%: increase regime penalty or require regime confirmation.
- `ENTRY_TIMING` share above 25%: widen entry window or adjust limit entry distance.
- `TARGET_TOO_FAR` share above 20%: reduce target multiplier.
- `STOP_TOO_TIGHT` share above 15%: widen stop or ATR multiplier.
- `DATA_QUALITY` share above 10%: exclude low-confidence rows from top-N journal entry.

Approved changes must store:

```text
approval_id
approved_by
approved_at
source_summary_id
before_params_json
after_params_json
reason
```

## API Shape

Proposed backend endpoints:

```text
POST /api/journal/virtual-trades/capture
GET  /api/journal/virtual-trades
POST /api/journal/virtual-trades/evaluate
GET  /api/journal/failure-patterns
GET  /api/journal/calibration-suggestions
GET  /api/journal/auto-capture/status
POST /api/journal/auto-capture/run
POST /api/journal/calibration-suggestions/{id}/approve
POST /api/journal/calibration-suggestions/apply-approved
POST /api/journal/historical-replay
POST /api/journal/market-analogs/run
```

`capture` parameters:

```json
{
  "market": "kr",
  "mode": "balanced",
  "horizon": "swing",
  "source_type": "FORWARD_PAPER_TRADE",
  "limit": 5
}
```

`historical-replay` parameters:

```json
{
  "market": "kr",
  "mode": "balanced",
  "horizon": "swing",
  "as_of_date": "2025-06-30",
  "limit": 5
}
```

## Storage

Preferred v1 storage:

- SQLite table or CSV fallback named `virtual_trade_journal`
- separate table or CSV fallback named `virtual_trade_evaluations`
- separate table or CSV fallback named `calibration_suggestions`
- separate table or CSV fallback named `calibration_approvals`

Do not pack everything into one mutable CSV if SQLite is available. CSV fallback is acceptable for local/dev compatibility.

Primary key:

```text
journal_id = sha256(source_type | as_of_date | generated_at | market | mode | horizon | symbol | entry_price | stop_price | target_price)
```

Natural duplicate guard:

```text
source_type + as_of_date + market + mode + horizon + symbol
```

Allow a second row for the same symbol/date only if entry/stop/target changed and `generated_at` differs.

## Implementation Phases

Phase 1: spec-compatible capture

- create strict candidate filter
- store immutable `source_type` snapshots
- expose capture/list APIs
- start a low-load auto-capture scheduler that reads latest recommendation CSVs after market close

Phase 2: evaluator

- implement `NEXT_OPEN` and `LIMIT_TOUCH`
- stop-first same-candle behavior
- outcome taxonomy and MFE/MAE fields

Phase 3: postmortem tags

- add structured failure classifier
- generate `review_text` from tags and key metrics
- add failure pattern summary API

Phase 4: calibration suggestions

- aggregate by `market + mode + horizon + source_type`
- enforce source weights and minimum samples
- generate suggestions but do not apply them automatically
- approved suggestions can be manually applied to `reports/self_correction_params.json`
- applied approvals are logged in `data/virtual_trade_calibration_applications.csv`

Phase 5: historical replay

- add `as_of_date` data firewall
- create replay rows with `source_type = HISTORICAL_REPLAY`
- prevent replay rows from being mixed with forward rows unless explicitly requested
- add market-analog replay summaries that connect similar past market movement to future outcome/failure summaries

## Acceptance Criteria

- A captured row includes `source_type` and frozen recommendation fields.
- A historical replay row can prove `as_of_date` cutoff.
- Future data is not read before the recommendation snapshot is written.
- Same daily candle target/stop collision resolves to stop.
- `TIME_EXIT` rows are split into near-target, near-stop, mid, or flat.
- Failure summaries are queryable by structured tags, not by parsing narrative text.
- Calibration suggestions are visible but not applied without approval.
- `FORWARD_PAPER_TRADE` and `HISTORICAL_REPLAY` performance can be reported separately.
- Market-analog replay can explain similar past market movement and what happened afterward without using future data during analog selection.

## Auto Capture Defaults

The backend should capture journal rows without requiring daily admin login.

Default scheduler behavior:

- enabled by `MONE_VTJ_AUTO_CAPTURE=true` by default
- check interval: `MONE_VTJ_AUTO_CAPTURE_INTERVAL_MIN`, default `30`
- KR capture window: KST `16:40-23:59`, same calendar date
- US capture window: KST `07:10-15:00`, previous US trading date
- scheduled capture uses latest recommendation CSVs first and should not trigger expensive recommendation recomputation
- status and duplicate guards live in `reports/virtual_trade_journal_status.json`

Manual override:

```text
POST /api/journal/auto-capture/run
```

Manual runs may set `includeEngine=true`, but scheduled runs should keep it `false`.
