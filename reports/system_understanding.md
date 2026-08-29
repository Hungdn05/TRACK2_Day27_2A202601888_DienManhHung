# System Understanding

## Critical paths

| Source | Owner | Consumer | Reliability signal | Blast radius |
|---|---|---|---|---|
| `orders` | commerce-data | `fct_daily_revenue`, CEO dashboard | PK/type/amount contract, freshness, row-count anomaly | Revenue reporting and executive decisions |
| `customers` | commerce-data | `fct_daily_revenue` | active-version uniqueness, dbt unit test | Revenue inflation when an SCD join duplicates orders |
| `kb_documents` | support-ai | active KB, RAG index, Support Agent | schema, publish freshness, text-length and embedding-norm drift | Outdated or degraded policy answers |

## Operating policy

- Critical contract failures block the batch; rows named by a failed check are exported for quarantine and investigation.
- Warning failures remain visible in the report and dashboard; they are never converted into a false `SUCCESS`.
- Anomaly alerts require an actionable signal: same-weekday robust baselines avoid treating the normal weekend pattern as an incident.
- The incident workflow begins with evidence from contract, dbt, anomaly, lineage and SLO signals. It does not inspect a mystery fault generator.
