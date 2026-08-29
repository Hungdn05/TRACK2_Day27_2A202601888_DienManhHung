# Incident Report

## Status
Resolved in a reproducible recovery rehearsal. This is an evidence-based incident report for the repository's current incoming batch; no external mystery dataset was provided.

## Severity
P2 — data freshness / support-quality degradation. Both revenue-source and KB freshness SLOs were breached, but no malformed records, transformation failure, volume anomaly or confirmed customer impact was observed.

## Summary
The current incoming orders and KB batches were stale even though their rows remained structurally valid. The newest `orders.updated_at` was 1,274.171 minutes old against a 30-minute limit, and newest `kb_documents.published_at` was 1,279.169 minutes old against a 60-minute limit. The pipeline could still appear successful because the GX suite and dbt checks validate structural/data-model correctness, while freshness was a warning-level contract signal.

## Detection

- Signal: `scripts/run_baseline.py` at `2026-08-29T09:38:47Z` returned one order freshness warning, one KB freshness warning, and breached both freshness SLOs.
- First observed time: the evidence establishes that the latest input timestamps were `2026-08-28T12:24:37Z` (orders) and `2026-08-28T12:19:37.069860Z` (KB). The exact time the upstream refresh stopped cannot be proven without orchestration logs.

## Root Cause

Confirmed data condition: upstream input batches were not refreshed within their declared freshness windows.

Detection-gap root cause: freshness was represented as a warning contract check and was not part of the GX structural expectation suite, so GX and dbt could pass while freshness SLOs were exhausted. The repository has no scheduler, connector or external job logs, so a more specific upstream cause is **unconfirmed** and is not claimed here.

## Evidence

1. Orders contract freshness: latest `updated_at=2026-08-28T12:24:37Z`; age `1274.171` minutes; allowed `30` minutes.
2. KB contract freshness: latest `published_at=2026-08-28T12:19:37.069860Z`; age `1279.169` minutes; allowed `60` minutes.
3. Baseline row-count detector was normal: `auto:mad`, score `0.17`; dbt build passed 19/19 resources, and GX structural checkpoint passed with no critical failures.
4. Freshness SLO evidence: revenue freshness burn rate `200x`, RAG freshness proxy burn rate `100x`; both had zero remaining error budget.

## Blast Radius

```text
stale orders.updated_at
-> stg_orders
-> fct_daily_revenue
-> ceo_revenue_dashboard

stale kb_documents.published_at
-> kb_active_docs
-> rag_index
-> support_agent
```

The immediate business risk is an outdated CEO revenue view and stale Support Agent policy answers. No data-integrity corruption was found in the current batch.

## Mitigation

Request/re-run the upstream orders and KB ingestion, preserving the previous batch for investigation. For the local lab, the documented reset/re-ingest workflow was exercised in an isolated copy so the submitted workspace data was not overwritten.

## Recovery

The isolated recovery reset produced 0 order contract failures and 0 KB contract failures. Orders freshness was `5.01` minutes; GX exited 0 and dbt build exited 0. This proves the pipeline can recover once fresh input is delivered, but is not evidence that an external production scheduler has been repaired.

## Verification

- [x] Contract health: recovery copy had zero order and KB failures.
- [x] dbt tests healthy: recovery `dbt build` exited 0.
- [x] Anomaly returned to expected range: healthy reset was `False (auto:mad, score=0.17)`.
- [x] SLO understood: stale current batch breached both freshness SLOs; the recovery batch passed freshness contracts.
- [x] Downstream output verified: lineage establishes both CEO dashboard and Support Agent blast paths; dbt materialized the revenue mart successfully.

## Prevention / Action Items

| Action | Owner | Deadline | Why |
|---|---|---|---|
| Alert on `revenue_freshness` and `rag_index_freshness_proxy` SLO breach | commerce-data / support-ai on-call | Before next scheduled batch | Structural validation alone cannot detect stale-but-valid data. |
| Persist upstream ingestion run ID and source watermark with every batch | data-platform | Next iteration | Distinguishes a stale source, stuck connector and scheduler failure. |
| Escalate freshness severity/action according to consumer impact | data reliability owner | Next iteration | Revenue and policy freshness need an actionable block/page policy. |
| Add a freshness expectation/checkpoint action to GX | commerce-data | Next iteration | Prevents a structural-only GX pass from masking stale data. |
