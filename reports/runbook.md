# Runbook: primary region down

Scope: fail over A to B with the filesystem snapshot. On-call performs the runbook; the Incident Commander (IC) owns the decision to stop or roll back.

| # | Step | PowerShell command | Completion signal | Owner |
|---|---|---|---|---|
| 1 | Confirm outage | `curl.exe http://127.0.0.1:8001/readyz` three times | A is not ready three times; inspect B with `curl.exe http://127.0.0.1:8002/v1/state` | On-call |
| 2 | Open incident and start RTO clock | `Get-Content chaos\chaos-events.jsonl -Tail 1` | A kill event exists; runbook log records `thong_bao_incident` and `outage_ts` | On-call |
| 3 | Wait for health detection | `Get-Content reports\health-events.jsonl` | Event has `region:"a"` and `to:"UNHEALTHY"`; do not fail over before it | On-call |
| 4 | Restore, scale, and wait ready | `& .\.venv\Scripts\python.exe dr/runbook.py --primary a --target b --backend fs` | Confirm `y`; failover log has verify, restore, scale, and `4_wait_ready` with `ok:true` | On-call |
| 5 | DNS cutover | Performed only by step 4; do not edit `edge\active_region` manually | `5_dns_cutover` follows ready; `Get-Content edge\active_region` is `b` | On-call |
| 6 | Verify golden signals | `curl.exe http://127.0.0.1:8080/v1/infer` | Response has `edge_region:"b"` and `region:"b"`; runbook records 10 real requests | On-call |
| 7 | Measure and review | `& .\.venv\Scripts\python.exe tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300` | `valid:true`, no warnings, recovery by B, and RTO PASS | IC |

## Rollback

Do not roll traffic back merely because A responds again. Only the IC may authorize rollback after A has stable `/readyz` 200, synchronized state and weights, and B has a sustained serving or golden-signal problem. Open a new change incident and run the same controlled procedure in reverse; never manually edit `edge\active_region`.
