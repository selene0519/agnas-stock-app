# AI quant operations and rollout

The AI account is paper-only. A successful scheduled run or an `OK` API
response does not prove positive returns, complete data, or permission to place
broker orders. Do not bypass the existing forward-evidence, promotion, or
rollback gates to increase activity.

## Deployment prerequisites

- Merge the reviewed changes onto the current deployment branch; the isolated
  worktree may be behind newer data commits. Do not replace the newer ledger.
- Configure a persistent PostgreSQL `DATABASE_URL`, a stable random
  `MONE_AUTH_SECRET`, administrator credentials, and the existing OAuth
  provider settings. Production manual journals fail closed without Postgres.
  Local SQLite is for development only. Back up the database and test restore.
- The old shared manual-journal CSV is not automatically assigned to any user:
  its ownership is unknown. Migrate only after the owner and rows are verified.
- GitHub Actions needs a valid `GH_PAT` with repository contents write access.
  Configure `MONE_AUTOMATION_TOKEN` (or the legacy `MONE_ADMIN_SECRET`) on
  the backend and the matching workflow secret if the remote sync endpoint is
  used. The machine credential is restricted to explicitly allowed routes.
- Scheduled paper, capture, accumulator, and settlement workflows share a
  queued writer group and check out the current branch before running. Long
  queues can miss time-sensitive market windows; such runs fail closed and
  require operator attention. Verify the account supports `queue: max`.
- Journal and paper data committed by Actions must also reach the running
  backend via its configured synchronization or deployment mechanism. Verify
  that behavior after rollout; a successful Git push alone does not prove it.
  The accumulator now fails when its synchronous backend pull cannot be
  confirmed, including `NO_GIT_REMOTE` or `DEPLOYMENT_NO_GIT`. If the hosting
  environment intentionally deploys without Git metadata, establish and verify
  another delivery mechanism before changing that check; a cache clear alone
  does not deliver the new files. Data may already have been pushed when this
  step fails, so inspect the remote before retrying.

## Verify after rollout

1. Confirm two different signed-in users cannot read, edit, or delete each
   other's manual entries; restart the backend and verify persistence.
2. Confirm scheduled captures and paper cycles run in the correct market
   session, do not duplicate records, persist to Git, and reach the backend.
3. Check self-learning `learningProgress`: independent signal dates, current
   identity-window samples, blockers, shadow settlements, and promotion
   certificates. A successful run with zero eligible corrections is evidence
   collection, not a successful strategy improvement.
4. Compare cost-inclusive forward results and drawdown with appropriate market
   benchmarks by market, regime, risk profile and horizon. Do not infer a
   statistical edge from a handful of trades.
5. Exercise alerting, failed-job recovery, restore, and rollback without broker
   orders before considering any expansion of trading authority.

## Evidence limitations

- Paper discovery rejects stale or undated precomputed caches and checks the
  underlying price and signal dates separately; a recent cache generation time
  does not establish that its prices are current. Unknown market regime is not
  silently treated as sideways. A blocked discovery can therefore mean missing
  data rather than a broken scheduler.
- The current event context reads stored reports and sentiment caches. Its
  freshness and point-in-time coverage are not established, so the event
  context's score adjustment and learning eligibility are disabled while its
  tags remain available for review. Other independent news/risk paths are not
  certified by this restriction. Historical event requests return unavailable
  until point-in-time sources are supplied.
- An all-winning sample has no observed losing-trade denominator: its profit
  factor and payoff ratio are not shown as an invented finite value. Small
  samples, execution assumptions and fixed cost estimates do not establish
  a durable edge. Maintain independent forward results by regime, profile and
  horizon, and compare net returns and drawdowns against matching benchmarks.

The local file lock deliberately does not expire based on age. If a process
crashes while holding it, first verify every writer has stopped, then remove
only the specific stale lock file; restarting or deleting it while a writer is
active can corrupt shared data.
