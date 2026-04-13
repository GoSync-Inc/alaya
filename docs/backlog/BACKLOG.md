# AlayaOS — Unified Backlog

Single source of truth for all tech debt, known limitations, and research items across all runs.

**Format:** `[RUN-N.NN]` prefix for traceability. Priority: P1 (next run), P2 (eventually), P3 (nice to have).

---

## CC-Research Items (from Master Plan brainstorm)

Referenced in `docs/superflow/plans/2026-04-07-alayaos-pivot.md`. Specs were planned but never written.

| ID | Title | Target Run | Status |
|----|-------|-----------|--------|
| BACKLOG-252 | Per-Query Context Cache | Run 3 (Search) | Deferred — Run 3 became Intelligence Pipeline |
| BACKLOG-254 | Cost Tracking & Analytics | Run 8q | Open |
| BACKLOG-255 | Per-User Memory System | Run 8a | Open |
| BACKLOG-256 | Autonomous Task Queue | Run 8d | Open |
| BACKLOG-257 | Context Compaction (long Slack threads) | Run 2 | Partially done — CortexChunker handles chunking |
| BACKLOG-258 | Resilient LLM Retry | Run 2 | Partially done — TaskIQ retry, but no cross-provider fallback |
| BACKLOG-259 | Org-Level Policy & Limits | Run 8m | Open |
| BACKLOG-260 | Team Memory Sync (delta sync, ETag) | Run 5 | Open |
| BACKLOG-261 | Deferred Tool Loading | Run 8p | Open |
| BACKLOG-263 | Multi-Agent Architecture | Run 8n | Open |
| BACKLOG-264 | Prompt Engineering (cache-aware sectioning) | Run 2 | Done — ephemeral cache_control in AnthropicAdapter |

---

## Run 1 + 1.1: Foundation + Hardening

No open items — all addressed during Run 2.

---

## Run 2: Extraction Pipeline

| ID | P | Title | Details |
|----|---|-------|---------|
| RUN2.01 | P2 | LLM cross-provider fallback | TaskIQ retries same provider. No fallback to OpenAI/Ollama on Anthropic outage. |
| RUN2.02 | P3 | Consolidation agent stub | `job_enrich` is a no-op stub. Deferred — Integrator (Run 3) replaced this. |

---

## Run 3: Intelligence Pipeline

### P1 — Should fix in next run

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN3.01 | P1 | Entity dedup: soft-delete only, no claim/relation reassignment | `integrator/engine.py` | Dedup soft-deletes entity_b, merges aliases, but does NOT reassign claims/relations from B to A. Needs `UPDATE l2_claims SET entity_id = A WHERE entity_id = B`. |
| RUN3.02 | P1 | Integration tests all skipped (18) | `tests/test_rls.py`, `test_composite_fk.py` | Need conftest with temp DB, migrations, seed data. |
| RUN3.03 | P1 | Redis health check "unavailable" | `api/routers/health.py` | May not use `Settings.REDIS_URL` consistently. |

### P2 — Should fix eventually

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN3.04 | P2 | `update_type` fallback for unknown slugs | `integrator/engine.py` | LLM may return slugs not in EntityTypeDefinition. Silently dropped. |
| RUN3.05 | P2 | INTEGRATOR_MAX_WAIT_SECONDS 1800 vs spec 300 | `config.py` | Intentional — 300s too aggressive for low-volume. Revisit with usage data. |
| RUN3.06 | P2 | Entity cache warmed with score=0 | `integrator/engine.py` | `last_seen_at: 0` → no meaningful sorted set ordering for Crystallizer. Use `entity.updated_at`. |
| RUN3.07 | P2 | DateNormalizer not wired into Writer | `date_normalizer.py` | Only used in Integrator enrichment, not in `write_claim` for date-type claims. |
| RUN3.08 | P2 | No explicit workspace assertion in Integrator scope | `integrator/engine.py` | RLS protects in practice, but no assert that dirty-set IDs match workspace. |

### P3 — Nice to have

| ID | P | Title | Details |
|----|---|-------|---------|
| RUN3.09 | P3 | README not updated | Waiting for CLI (Run 4) before updating README for external users. |
| RUN3.10 | P3 | Eval script needs `--real` flag | `scripts/eval_extraction.py` — FakeLLM comparison not useful. Need real API key mode. |
| RUN3.11 | P3 | Prompt caching efficiency unmeasured | Need `cache_read_input_tokens / total_input_tokens` metrics per run. |

---

## Run 5.1: Review Follow-up (2026-04-13)

Detailed implementation plan:
`docs/superflow/plans/2026-04-13-review-fixes.md`

### P1 — Should fix next

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.01 | P1 | Write-stage correctness must not depend on Redis | `packages/core/alayaos_core/extraction/pipeline.py`, `packages/core/alayaos_core/repositories/workspace.py` | Replace correctness-critical write serialization with a DB-backed workspace lock. Keep Redis as an optional optimization only. |
| RUN5.02 | P1 | Manual integrator trigger returns an orphan run | `packages/api/alayaos_api/routers/integrator_runs.py`, `packages/core/alayaos_core/worker/tasks.py` | Reuse the API-created `IntegratorRun` row instead of creating a second worker-owned row. |
| RUN5.03 | P1 | Worker creates a new SQLAlchemy engine per task | `packages/core/alayaos_core/worker/tasks.py` | Reuse one async engine/session factory per worker process and add a cleanup hook for tests/shutdown. |

---

## Run 5.2: Security Hardening (2026-04-13)

Security report:
`docs/audits/2026-04-13-security-best-practices.md`

Detailed implementation plan:
`docs/superflow/plans/2026-04-13-security-hardening.md`

### P1 — Should fix next

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.04 | P1 | Memory-read endpoints must require read scope | `packages/api/alayaos_api/routers/search.py`, `packages/api/alayaos_api/routers/ask.py` | Fix `SBP-001`: enforce `require_scope("read")` and co-deliver the `key_prefix` runtime fix safely. |
| RUN5.05 | P1 | Rate limiting must not fail open on Redis outages | `packages/core/alayaos_core/services/rate_limiter.py`, `packages/api/alayaos_api/routers/search.py`, `packages/api/alayaos_api/routers/ask.py` | Fix `SBP-002`: return explicit degraded/fail-closed behavior instead of silently allowing unthrottled expensive requests. |

### P2 — Should fix soon

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.06 | P2 | Disable or protect OpenAPI/docs in production | `packages/api/alayaos_api/main.py`, `packages/core/alayaos_core/config.py` | Fix `SBP-003`: make docs exposure an explicit config choice rather than a production default. |
| RUN5.07 | P2 | Add trusted host validation or document equivalent edge enforcement | `packages/api/alayaos_api/main.py`, `packages/core/alayaos_core/config.py` | Fix `SBP-004`: add `TrustedHostMiddleware` support and make the deployment expectation explicit. |

### P3 — Nice to have after boundary hardening

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.08 | P3 | Reduce anonymous readiness detail leakage | `packages/api/alayaos_api/routers/health.py` | Fix `SBP-005`: keep health useful for operators while avoiding bootstrap and dependency-state disclosure by default. |
| RUN5.09 | P3 | Redact CLI secret output by default | `packages/cli-go/internal/cmd/setup.go` | Fix `SBP-006`: avoid printing API keys to stdout unless the operator explicitly opts in. |

---

## Run 4+: Future (from Master Plan)

| Run | Scope | Status |
|-----|-------|--------|
| Run 4 | CLI (Typer + Rich) | Not started |
| Run 5a-d | Connectors (Slack, GitHub, Linear, Webhook) | Not started |
| Run 6 | MCP Server | Not started |
| Run 7 | Web UI | Not started |
| Run 8a-q | Workflows, Agents, Analytics | Not started |
