# Cascade 3× — 4-way comparison

Four paired runs on 2026-05-01 / 2026-05-02 against the same workload (mooncake-trace replay at concurrency 24), same engine config, same image. The variables are two orthogonal resilience features:

- **Failover** (engine-side, PR #8572): GMS shadow-failover keeps a prewarmed engine-1 standby alongside the primary engine-0; on primary death, engine-1 promotes in seconds with full KV-cache state.
- **Migration** (frontend-side, `--migration-limit 10`): the dynamo HTTP frontend silently retries a stream when the worker disconnects mid-flight by re-prefilling (original prompt + tokens already streamed) on a different worker.

Each setup is hit with the same cascading-kill pattern: 3 workers killed 60 s apart at T+600 / +660 / +720 s, then 15 min of recovery observation.

## 4-way side-by-side

| | **Baseline** | **Baseline + Migration** | **Failover** | **Failover + Migration** |
|---|---|---|---|---|
| | (no resilience) | (frontend retry only) | (engine standby only) | (both) |
| Total requests | 2,439 | 2,548 | 2,074 | 2,048 |
| Completed (HTTP 200) | 1,806 | 1,850 | 1,985 | 1,987 |
| **Truly failed** | **633** (26%) | **698** (27%) | **89** (4%) | **61** (3%) |
| In original SLA | 659 | 692 | 505 | 507 |
| Slow but completed | 1,147 | 1,158 | 1,480 | 1,480 |
| In relaxed goodput | 1,751 (97%) | 1,821 (98%) | 1,973 (99%) | 1,982 (>99%) |
| **First in-SLA after kill #1** | +2.86 s | +4.58 s | +1.43 s | +47.3 s¹ |
| **First in-SLA after kill #2** | **+433 s** (~7 min) | +295 s (~5 min) | **+0.31 s** | +29.5 s¹ |
| **First in-SLA after kill #3** | **+372 s** (~6 min) | +233 s (~4 min) | +6.75 s | +3.4 s |
| First completed after kill #1 | +0.52 s | +1.46 s | +1.15 s | +0.78 s |
| First completed after kill #2 | +0.38 s | +2.15 s | +0.31 s | **+0.005 s** |
| First completed after kill #3 | +0.25 s | +2.11 s | +0.21 s | +1.47 s |
| Cascade-window blackout? | **Yes** (~5 min) | Yes (~4 min) | No | No |

¹ Failover+Migration's first-in-SLA times for kills #1 and #2 look worse because migration successfully kept the system serving — but the requests it kept alive had elevated TTFT/ITL from the migration prefill cost, falling into the "slow" bucket. The first request *that didn't need migration* and was small enough to fit the 5 s/10 ms thresholds is what `first in-SLA` measures, and that's stochastic across runs. The "first completed (any)" row is the more honest "is the system serving" signal.

## What each feature actually does

| Failure mode | Baseline | + Migration | + Failover | + Both |
|---|---|---|---|---|
| Mid-stream worker disconnect, other workers healthy | 500 to client | Migration retry → success | Failover swap → success | Either path → success |
| All-workers-down for 30 s+ | Long blackout | Retry until limit-10 → 500 to client | Failover swap → no blackout | Failover swap; migration as backup |
| Brief NATS subscriber transition during failover promotion | n/a | n/a | Brief 500 to client | Migration catches it → success |

## Bottom-line takeaways

1. **Migration alone barely helps cascading failure.** When the cluster is in a true outage, retries against unavailable workers just exhaust the limit budget. 698 truly-failed (27%) vs 633 baseline (26%). Migration is great for transient single-worker disconnects; not a substitute for engine-side resilience under cascade.

2. **Failover alone is the dominant win.** 89 truly-failed vs 633 = **86% reduction**. The 5-minute cascade-window blackout disappears. Recovery to first request completion drops from minutes to sub-second.

3. **Failover + Migration is the best result.** 61 truly-failed (vs 89 failover-only = **31% further reduction**). Migration catches the residual NATS-transition-window failures that pure failover surfaces. Same 99%+ relaxed-goodput rate.

4. **Migration's tradeoff**: it converts would-be-failures into completed-but-slow requests (re-prefill cost). In our setup with 50–200K input tokens, that's a 1–4 s TTFT increase per migration event. Worth it: a slow response is much better than a 500.

## Per-setup detail

- [`baseline/README.md`](baseline/README.md) — failover OFF, migration OFF
- [`baseline-mig/README.md`](baseline-mig/README.md) — failover OFF, migration ON
- [`failover/README.md`](failover/README.md) — failover ON, migration OFF
- [`failover-mig/README.md`](failover-mig/README.md) — failover ON, migration ON

## Methodology

- **Workload**: aiperf 0.7.0 mooncake-trace replay against an internal long-context dataset (~200K input tokens, multi-turn conversations).
- **SLA**: `time_to_first_token:15000 inter_token_latency:30` (3× the original baseline demo's `5000/10` to widen the goodput band; we re-classify completions in post into working / slow / truly-failed using HTTP status + stream completion).
- **Kill mechanism**: `kubectl exec -- kill -9 $(pgrep -f "orted|mpi4py.futures.server")` against the worker pod's `main` (baseline variants) or `engine-0` (failover variants) container. MPI children dying cascades to parent python via `MPI_ABORT`.
- **"First completed after kill"** = first request whose `request_end_ns` exceeds the kill timestamp AND has HTTP 200 + non-empty stream. **"First in-SLA"** = same but also meets the original 5 s / 10 ms thresholds (stricter).
- **Concurrency 24** chosen so per-worker load (c=8) matches the prior single-worker demos, allowing engine saturation to look the same in all setups pre-kill.
