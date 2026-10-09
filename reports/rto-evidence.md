# RTO/RPO Evidence: Lab 23

All values below come from timestamps in the cited log lines.

## Drill 1: no DR

| Metric | Value | Evidence |
|---|---:|---|
| Outage | 2026-10-09T05:00:15Z | `chaos/chaos-events.jsonl:1` |
| First user failure | 0.8s | `reports/drill-1-nodr.jsonl:71` |
| Recovery | none | `reports/drill-1-nodr.jsonl:74` |
| RTO verdict | NO_RECOVERY | `reports/drill-1-nodr.jsonl:71` |

## Drill 2: DR enabled

| Milestone | Seconds from outage | Evidence |
|---|---:|---|
| Outage, time zero | 0.0s | `chaos/chaos-events.jsonl:5` |
| First user failure | 0.9s | `reports/drill-2-withdr.jsonl:54` |
| Health detection for A | 20.9s | `reports/health-events.jsonl:2` |
| Snapshot restore complete | 51.6s | `reports/failover-events.jsonl:2` |
| B ready | 58.3s | `reports/failover-events.jsonl:4` |
| DNS cutover | 58.6s | `reports/failover-events.jsonl:5` |
| Measured RTO, first successful B request | 62.2s | `reports/drill-2-withdr.jsonl:76` |

| Metric | Actual | Target | Verdict |
|---|---:|---:|---|
| Inference RTO | 62.2s | 300s | PASS |
| Vector DB RPO | 14.01s / 7 documents lost | 300s | PASS |

## RTO breakdown

The measured components total 20.91 + 30.72 + 6.71 + 3.83 = 62.17s, rounded to the measured RTO of 62.2s.

| Component | Seconds | Source | Reduction option |
|---|---:|---|---|
| Health detection | 20.91s | `chaos/chaos-events.jsonl:5`, `reports/health-events.jsonl:2` | Lower interval with anti-flap safeguards |
| Incident activation and snapshot restore | 30.72s | `reports/health-events.jsonl:2`, `reports/failover-events.jsonl:2` | Faster alert/triage and restore |
| GPU pool warm-up | 6.71s | `reports/failover-events.jsonl:3`, `reports/failover-events.jsonl:4` | Warm standby |
| DNS cutover and cache to recovery | 3.83s | `reports/failover-events.jsonl:4`, `reports/failover-events.jsonl:5`, `reports/drill-2-withdr.jsonl:76` | Review TTL/cache policy |

Health configuration was interval 5.0s and threshold 3, a 15.0s detection floor, in `reports/health-events.jsonl:2`. Restore recorded RPO 14.01s and 7 documents lost in `reports/failover-events.jsonl:2`.
