# Cascade 3× — baseline vs GMS shadow-failover

Two paired runs on 2026-05-01: same workload (mooncake-trace replay at concurrency 24), same engine config, same image. The only difference is whether the failover surface is enabled.

In each run, three workers were killed 60 s apart at T+600/660/720 s (after a 10 min steady-state ramp + run), then the system was observed for ~15 min of recovery.

## Side-by-side

| | **Baseline** (failover OFF, K8s restart only) | **GMS Shadow Failover** (PR #8572) |
|---|---|---|
| Total requests | 2,439 | 2,074 |
| Completed (HTTP 200) | 1,806 | 1,985 |
| **Truly failed** | **633** (26%) | **89** (4%) — **7× fewer** |
| In original SLA (TTFT≤5s, ITL≤10ms) | 659 | 505 |
| Slow but completed | 1,147 | 1,480 |
| In relaxed goodput (TTFT≤15s, ITL≤30ms) | 1,751 (97% of completions) | 1,973 (99%) |
| **First in-SLA after kill #1** | +2.86 s | **+1.43 s** |
| **First in-SLA after kill #2** | **+433 s** (~7 min) | **+0.31 s** |
| **First in-SLA after kill #3** | **+372 s** (~6 min) | **+6.75 s** |
| Cascade-window completions blackout? | **Yes** (~5 min total silence post-kill) | No |
| Pre-kill TTFT p50 | ~750 ms | ~700 ms |
| Pre-kill ITL avg | ~9 ms | ~10 ms |
| Run-wide TTFT avg | 1,548 ms | 1,322 ms |
| Run-wide tok/s/user avg | 96.5 | 84.8 |
| Total decode throughput | 966 tok/s | 1,066 tok/s |

## What the charts show

The most striking comparison is `http_status_over_time`. The baseline chart has a **wall of red** spanning ~5 minutes (T=0 → T=+300 s) with a visible *zero-completions* gap at T+300 s where every worker is mid-restart. The failover chart has three thin red bars exactly at the kill moments and continuous green/orange completion bars throughout — the system never goes silent.

Per setup, see:
- [`baseline/README.md`](baseline/README.md) + [`baseline/charts/`](baseline/charts/)
- [`failover/README.md`](failover/README.md) + [`failover/charts/`](failover/charts/)

## Methodology

- **Workload**: aiperf 0.7.0 mooncake-trace replay against an internal long-context dataset (~200K input tokens, multi-turn conversations).
- **SLA**: `time_to_first_token:15000 inter_token_latency:30` (3× the original demo's `5000/10` to widen the goodput band; we then re-classify completions in post into working / slow / truly-failed using HTTP status + stream completion).
- **Kill mechanism**: `kubectl exec -- kill -9 $(pgrep -f "orted|mpi4py.futures.server")` against the worker pod's `main` (baseline) or `engine-0` (failover) container. MPI children dying cascades to parent python via `MPI_ABORT`.
- **"First working after kill"** = first request whose `request_end_ns` exceeds the kill timestamp AND has HTTP 200 + non-empty stream. **"First in-SLA"** = same but also meets the original 5 s / 10 ms thresholds.
- **Concurrency 24** chosen so per-worker load (c=8) matches the prior single-worker demos, allowing engine saturation to look the same in both setups pre-kill.

## Bottom line

For a **cascading-failure scenario** (3 workers down within 2 minutes), GMS shadow-failover reduces real failure count by **7×** and reduces post-kill recovery-to-quality time from **~7 minutes** to **~7 seconds** — a 60× wall-clock improvement. The visible chart difference is dramatic: a 5-minute outage replaced with a barely-perceptible blip.
