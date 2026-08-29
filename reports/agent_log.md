# AI Agent Decision Log

## Decision 1 — Strict contracts instead of silent coercion

- Hypothesis: CSV-like strings and malformed timestamps can pass the starter range checks while still violating the contract.
- Agent proposal: validate declared types before range/freshness checks and return severity, action and identifiable row indices.
- Evidence/test: `pytest -q` passed 19 tests, including numeric-string, malformed timestamp, missing column, stale timestamp and duplicate quarantine cases.
- Accept / reject / revise: Accept.
- Why: type drift is a deterministic data-quality failure, not a value to silently coerce.

## Decision 2 — GX checkpoint with local evidence action

- Hypothesis: individual `batch.validate()` calls do not demonstrate an operational GX validation flow.
- Agent proposal: use an ephemeral Suite, Validation Definition, Checkpoint and a local Action that writes complete result evidence; derive remediation rows from the same contract policy.
- Evidence/test: a reset healthy copy passed GX; `duplicate_pk` made GX exit 1 and exported identifiable rows to the local quarantine path.
- Accept / reject / revise: Accept.
- Why: it proves an executable severity-aware flow without introducing network credentials or a fake notification.

## Decision 3 — Prevent SCD revenue multiplication in SQL

- Hypothesis: joining every active customer version can multiply completed-order revenue.
- Agent proposal: rank active versions by latest `valid_from`, retain one row per customer, add a singular data test and a two-version dbt unit test.
- Evidence/test: `dbt build --project-dir dbt_project --profiles-dir dbt_project` passed 19 resources; the dedicated unit test passed; a duplicate-PK temp drill made dbt fail as expected.
- Accept / reject / revise: Accept.
- Why: data tests validate warehouse state, while the fixture unit test protects the transformation logic itself.

## Decision 4 — Context-aware anomaly detection only with real context

- Hypothesis: mapping the static 600-row fixture to the wall-clock Saturday segment creates a false positive.
- Agent proposal: stable API uses `same_segment_history` when the caller supplies it; the baseline runner uses its robust all-history path because the fixture has no trustworthy traffic-segment metadata.
- Evidence/test: isolated healthy reset returned `False (auto:mad, score=0.17)`; `volume_drop` returned `True (auto:mad, score=10.29)`; same-weekday and zero-MAD cases pass unit tests.
- Accept / reject / revise: Accept after revising the runner context.
- Why: context must be evidence-backed, not inferred from unrelated wall-clock metadata.

## Decision 5 — Multi-signal observability and honest unavailable metrics

- Hypothesis: mean-only drift, direct-only column lineage and one-window burn checks miss meaningful failures; invented embedding metrics would be misleading.
- Agent proposal: implement KS/quantile drift, cycle-safe transitive column BFS, two-window burn policy and real embedding-norm API support; report incoming embedding metrics as unavailable when source vectors do not exist.
- Evidence/test: 19 pytest cases cover equal-mean shape shift, transitive cycle, transient versus sustained burn and embedding-norm shift; Streamlit dashboard responded HTTP 200.
- Accept / reject / revise: Accept.
- Why: the dashboard distinguishes an unavailable signal from a healthy signal and preserves actionable evidence.

## Decision 6 — Investigate the observed stale batch without inventing an upstream cause

- Hypothesis: the current input itself provides a real freshness incident even though no separate mystery dataset exists.
- Agent proposal: use only current contract, GX, dbt, anomaly, lineage and SLO evidence; report the confirmed stale-batch condition, label scheduler/connector causality as unconfirmed, and prove recovery in an isolated reset copy.
- Evidence/test: orders freshness was 1274.171 minutes versus 30 allowed; KB freshness was 1279.169 minutes versus 60 allowed; both freshness SLOs breached. dbt passed 19/19 and GX passed structural checks. Isolated recovery returned zero contract failures, 5.01-minute orders freshness, GX exit 0 and dbt exit 0.
- Accept / reject / revise: Accept.
- Why: it completes the incident lifecycle honestly while preserving the distinction between observed data state and unavailable upstream operational logs.
