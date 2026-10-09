"""BƯỚC 3b — SINH VIÊN VIẾT. Cutover sang region phụ.

5 bước, THỨ TỰ QUAN TRỌNG (§2 Kiến Trúc Tham Chiếu: DNS/LB, compute, state là 3 lớp riêng):
  1_verify_target    — /v1/state của region phụ: weights? vector count? pool_state?
  2_restore_snapshot — gọi state/snapshot.py get + state/snapshot.py rpo()
                       Log BẮT BUỘC: rpo_seconds, docs_lost, embed_model_version.
                       (§3: "backup index nhưng quên backup embedding model version
                        -> index không tương thích khi restore")
  3_scale_pool       — ghi "full" vào state/region-<t>/pool_state (warm -> full)
  4_wait_ready       — POLL /readyz tới khi 200. Region phụ có WARMUP_SECONDS —
                       đây là GPU pool warm-up của §4, nó nằm trong RTO của bạn.
  5_dns_cutover      — ghi region đích vào edge/active_region

BẪY: nếu bạn đổi edge/active_region TRƯỚC bước 4, user sẽ nhận 503 từ CẢ HAI region
và RTO của bạn dài hơn, không ngắn hơn. Nếu bước 4 timeout -> ABORT, KHÔNG cutover.

Mỗi bước ghi 1 dòng vào reports/failover-events.jsonl với ts + step.
Không có dòng 5_dns_cutover = tools/measure_rto.py không tìm được t_cutover = mất điểm.

Chạy:  python dr/failover.py --target b --backend fs
"""
import argparse
import json
import pathlib
import sys
import time

import httpx

sys.path.insert(0, ".")
from state import snapshot  # noqa: E402

URL = {"a": "http://127.0.0.1:8001", "b": "http://127.0.0.1:8002"}
LOG = pathlib.Path("reports/failover-events.jsonl")


def emit(**kw):
    """Append one timestamped event and mirror it to stdout."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rec = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **kw}
    with LOG.open("a", encoding="utf-8") as log:
        log.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))
    return rec


def state_of(region: str) -> dict:
    """Read a target's current state without interpreting liveness as readiness."""
    try:
        response = httpx.get(f"{URL[region]}/v1/state", timeout=2.0)
        response.raise_for_status()
        return response.json()
    except (httpx.RequestError, ValueError) as exc:
        return {"region": region, "error": type(exc).__name__}


def failover(target: str, backend: str, wait: float) -> dict:
    """Restore, warm, verify, then (and only then) cut traffic to the target."""
    if target not in URL:
        raise ValueError("target phai la 'a' hoac 'b'")
    if wait < 0:
        raise ValueError("wait phai >= 0")
    primary = "b" if target == "a" else "a"
    before = state_of(target)
    emit(step="1_verify_target", target=target, state=before)
    try:
        restored = snapshot.get(target, backend)
        rpo = snapshot.rpo(pathlib.Path(f"state/region-{primary}/vectors.sqlite"), pathlib.Path(f"state/region-{target}/vectors.sqlite"))
    except BaseException as exc:
        emit(step="2_restore_snapshot", target=target, ok=False, error=f"{type(exc).__name__}: {exc}", rpo_seconds=None, docs_lost=None, embed_model_version=None)
        return {"ok": False, "target": target, "error": str(exc), "cutover": False}
    emit(step="2_restore_snapshot", target=target, ok=True, snapshot_at=restored.get("snapshot_at"), rpo_seconds=rpo.get("rpo_seconds"), docs_lost=rpo.get("docs_lost"), embed_model_version=restored.get("embed_model_version"))
    pool_file = pathlib.Path(f"state/region-{target}/pool_state")
    pool_file.parent.mkdir(parents=True, exist_ok=True)
    pool_file.write_text("full\n", encoding="utf-8")
    emit(step="3_scale_pool", target=target, pool_state="full")
    deadline = time.time() + wait
    ready = False
    ready_detail, last_error = None, None
    while time.time() <= deadline:
        try:
            response = httpx.get(f"{URL[target]}/readyz", timeout=min(2.0, max(0.01, deadline - time.time())))
            ready_detail = response.json()
            if response.status_code == 200:
                ready = True
                break
            last_error = f"http_{response.status_code}"
        except (httpx.RequestError, ValueError) as exc:
            last_error = type(exc).__name__
        time.sleep(min(0.25, max(0.0, deadline - time.time())))
    emit(step="4_wait_ready", target=target, ok=ready, wait_s=wait, reason=None if ready else last_error, ready=ready_detail)
    if not ready:
        return {"ok": False, "target": target, "restored": restored, "rpo": rpo, "error": "target_not_ready", "cutover": False}
    after = state_of(target)
    active = pathlib.Path("edge/active_region")
    active.parent.mkdir(parents=True, exist_ok=True)
    active.write_text(target + "\n", encoding="utf-8")
    emit(step="5_dns_cutover", target=target, ok=True)
    return {"ok": True, "target": target, "restored": restored, "rpo": rpo, "target_state": after, "cutover": True}


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="b", choices=["a", "b"])
    p.add_argument("--backend", default="fs", choices=["fs", "minio"])
    p.add_argument("--wait", type=float, default=60)
    a = p.parse_args()
    print(json.dumps(failover(a.target, a.backend, a.wait), indent=2))
