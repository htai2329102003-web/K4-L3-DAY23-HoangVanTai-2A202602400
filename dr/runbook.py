"""BƯỚC 3c — SINH VIÊN VIẾT. Tự động hoá runbook §4 "Runbook: Region Chính Down".

7 bước trên slide, mỗi bước 1 dòng log có ts. Log này CHÍNH LÀ timeline của postmortem.
  1 xac_nhan_outage          — probe cả 2 region, đừng tin 1 lần fail (dùng nhiều lần
                              hoặc gọi health_checker.probe nếu đã viết xong 3a)
  2 thong_bao_incident       — ts của dòng này là mốc "operator biết tin", LUÔN LUÔN
                              SAU t_outage trong chaos-events (không thể trùng — operator
                              không thể biết ngay giây outage xảy ra). Ghi cả 2 ts vào
                              log để postmortem tính được "độ trễ thông báo".
  3 scale_gpu_pool           — gọi HÀM `failover.failover(...)` MỘT LẦN DUY NHẤT. Hàm
                              đó tự làm đủ 5 bước con (verify/restore/scale/wait/cutover)
                              và tự ghi log riêng vào reports/failover-events.jsonl.
  4 verify_state_replica     — KHÔNG gọi lại failover — chỉ ĐỌC kết quả (vector count +
                              weights ở region phụ) từ dict mà bước 3 trả về, để log vào
                              runbook-run.jsonl cho postmortem đọc 1 chỗ duy nhất.
  5 dns_cutover              — cũng chỉ đọc lại: kết quả cutover có ok hay không.
  6 verify_golden_signals    — 10 request thật vào region phụ: p95 latency + error rate
  7 post_incident            — elapsed_s + lệnh đo RTO

BÁN TỰ ĐỘNG, KHÔNG FULL-AUTO (§4: "failover đầu tiên nên là bán tự động — alert +
1-click confirm — tránh flapping gây failover 2 chiều liên tục"). Mặc định phải hỏi
người vận hành confirm; --auto chỉ dùng trong CI/khi chấm điểm.

Chạy:  python dr/runbook.py --primary a --target b --backend fs
"""
import argparse
import json
import math
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from dr import failover as fo  # noqa: E402
from dr import health_checker as hc  # noqa: E402

LOG = pathlib.Path("reports/runbook-run.jsonl")
URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}


def step(n, name, **kw):
    """Append one of the seven runbook timeline events."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": n, "name": name, **kw}
    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))
    return rec


def confirm(auto: bool, msg: str) -> bool:
    if auto:
        return True
    return input(f"{msg} [y/N] ").strip().lower() == "y"


def run(primary: str, target: str, backend: str, auto: bool) -> dict:
    if primary not in URL or target not in URL or primary == target:
        raise ValueError("primary va target phai la hai region khac nhau")
    started = time.time()
    observations = []
    for _ in range(3):
        observations.append({region: hc.probe(region, 2.0) for region in (primary, target)})
    primary_down = all(not observation[primary][0] for observation in observations)
    step(1, "xac_nhan_outage", primary=primary, target=target, observations=observations, confirmed=primary_down)
    if not primary_down:
        return {"ok": False, "error": "primary_not_confirmed_down"}
    outage_ts = None
    chaos_log = pathlib.Path("chaos/chaos-events.jsonl")
    if chaos_log.exists():
        for line in chaos_log.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("action") == "kill" and event.get("region") == primary:
                outage_ts = event.get("ts")
    step(2, "thong_bao_incident", primary=primary, outage_ts=outage_ts, notification_delay_s=None if outage_ts is None else round(time.time() - outage_ts, 3))
    if not confirm(auto, f"Fail over from region-{primary} to region-{target}?"):
        return {"ok": False, "error": "operator_declined"}
    result = fo.failover(target, backend, wait=60)
    step(3, "scale_gpu_pool", failover_ok=result.get("ok", False), failover_result=result)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "failover_failed"), "failover": result}
    replica = result.get("target_state", {})
    step(4, "verify_state_replica", target=target, state=replica, weights=replica.get("weights"), vector_count=replica.get("count"))
    step(5, "dns_cutover", target=target, ok=result.get("cutover", False))
    latencies = []
    errors = 0
    for _ in range(10):
        request_started = time.perf_counter()
        try:
            response = httpx.get(f"{URL[target]}/v1/infer", timeout=2.0)
            ok = response.status_code == 200
        except httpx.RequestError:
            ok = False
        latencies.append((time.perf_counter() - request_started) * 1000)
        errors += not ok
    p95_ms = sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1]
    step(6, "verify_golden_signals", requests=10, errors=errors, error_rate=errors / 10, p95_latency_ms=round(p95_ms, 2))
    elapsed = time.time() - started
    measure_command = "python tools/measure_rto.py --loadgen reports/drill-2-withdr.jsonl --target-rto 300"
    step(7, "post_incident", elapsed_s=round(elapsed, 3), measure_rto_command=measure_command)
    return {"ok": errors == 0, "failover": result, "golden_signals": {"requests": 10, "errors": errors, "error_rate": errors / 10, "p95_latency_ms": round(p95_ms, 2)}, "elapsed_s": elapsed}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--primary", default="a")
    p.add_argument("--target", default="b")
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--auto", action="store_true")
    a = p.parse_args()
    print(json.dumps(run(a.primary, a.target, a.backend, a.auto), indent=2))
