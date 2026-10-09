# Postmortem: Drill 2 A to B failover

This is blameless. The drill measures the system and process required to recover, not an individual's action.

## Timeline

| ISO time | Event | Evidence |
|---|---|---|
| 2026-10-09T07:04:19.160Z | A outage begins | `chaos/chaos-events.jsonl:5` |
| 2026-10-09T07:04:20.062Z | First user failure | `reports/drill-2-withdr.jsonl:54` |
| 2026-10-09T07:04:40.073Z | Health checker marks A unhealthy | `reports/health-events.jsonl:2` |
| 2026-10-09T07:05:10.558Z | Operator announces cutover | `reports/runbook-run.jsonl:2` |
| 2026-10-09T07:05:17.747Z | DNS cutover to B | `reports/failover-events.jsonl:5` |
| 2026-10-09T07:05:21.326Z | First successful B request resolves incident | `reports/drill-2-withdr.jsonl:76` |

## RTO/RPO and gap analysis

- RTO target: 300s. Actual: 62.2s. Gap: 237.8s below the target.
- RPO target: 300s. Actual: 14.01s and 7 documents lost. Gap: 285.99s below the target.
- Largest measured stage: incident activation plus snapshot restore, 30.72s after health detection.

## Root cause: five whys

1. Users failed because A stopped while edge still routed to A.
2. Edge did not move immediately because health checking waits for consecutive readiness failures.
3. B was not initially ready because it was deliberately warm, empty, and had no weights.
4. B needed snapshot restore and warm-to-full pool transition before readiness passed.
5. Recovery appeared after DNS cutover because edge cache and the next load-generator request add delay.

## Action items

| # | Action item | Owner | Deadline | Expected effect |
|---|---|---|---|---|
| 1 | Evaluate a 1s health interval with anti-flap controls | SRE on-call | Before next drill | Up to 12s less detection floor; more probe load |
| 2 | Automate alert delivery to reduce activation delay | Incident Commander | Before next drill | Reduce the 30.72s stage; no RPO change |

## Required answers

1. Interval times threshold is 5.0s times 3, so the detection floor is 15.0s, about 24.1 percent of the 62.2s RTO.
2. A 1s interval with threshold 3 reduces the theoretical floor by 12.0s, but increases probe load and flapping risk.
3. For a six-hour permanent A outage, 7 documents lost means seven updates after the last snapshot are unavailable in B and can produce stale retrieval or inference results.
