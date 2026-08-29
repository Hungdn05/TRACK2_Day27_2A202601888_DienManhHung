# Solution Defense

## Detection layers

- The contract validator is deterministic: it rejects missing columns, nulls, strict type drift, invalid values, ranges, lengths and stale timestamps. It reports severity, action and identifiable bad rows.
- Great Expectations runs the same business-critical expectations as a Suite, Validation Definition and Checkpoint. Its local Action preserves a complete validation result, while the contract layer produces a remediation quarantine.
- `detect_metric(method="auto")` uses same-segment MAD when available, then robust MAD, then z-score only for short history. A known event is documented in the reason but does not suppress a data-quality alert.
- Distribution drift uses KS distance plus normalized quantile movement, so it catches shape changes even when the mean is unchanged.

## Why dbt data tests and unit tests are both needed

Data tests query a materialized dataset and expose invalid production data such as duplicate active customer versions. A unit test supplies small static parent fixtures and asserts the SQL transformation result before the full mart is materialized. The SCD test proves that two active customer versions cannot double revenue.

## Alert policy and limits

The error-budget calculator reports actual/allowed bad rate, burn rate and remaining budget. Multi-window paging requires both windows to confirm a burn: 14.4x is fast burn, 6x is sustained burn, and a one-window spike is only informational. The starter incoming KB has no embedding vectors, so the dashboard reports that signal as unavailable rather than fabricating an embedding metric; the stable API evaluates real precomputed norms when supplied.

## Evidence expected at submission

Healthy baseline, duplicate PK, volume drop and stale KB are verified from isolated copies of the lab. No separate mystery dataset was provided, so the incident report investigates the repository's observed stale batch, cites independent contract/dbt/anomaly/SLO evidence, and separates the confirmed stale condition from unobservable scheduler causality.
