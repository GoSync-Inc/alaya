# Alaya Roadmap

Current status: **core stabilization phase**. Alaya's ingestion, extraction, and knowledge-graph layers are functionally complete. Before layering on connectors, MCP surface, and action/workflow features, we are closing quality, observability, and integrity gaps.

## Strategy

Alaya's product split:

- **Core (OSS, this repo)** — corporate memory engine + workflow primitives. Everything required to take raw events → structured graph → action queue.
- **Alaya Sync (planned)** — personal desktop daemon. Bridges local AI tools and core.
- **Alaya Workflow (planned SaaS)** — domain recipe packs, managed connectors, visual builder, team governance. Built on top of core primitives.

See `docs/vision/` for the full picture.

## Core Stabilization (Q2 2026)

Four sequential runs. Each closes with a merged PR set and a post-merge audit. Planning discipline: `docs/superflow/plans/*` (internal) per run; progress is tracked in this file and in `docs/backlog/BACKLOG.md`.

### Run 6.1 — Data Integrity ✅ MERGED 2026-04-25

**Goal:** close structural invariants that slipped through prior reviews; unblock the integration test suite so subsequent runs can move safely.

**Sprints (3, all merged):**
- S1 (PR #108, merged `40be788`) — Integration harness replaced with testcontainers + `alembic upgrade head` + non-superuser `alaya_app` role. Four new RLS negatives + `test_rls_policy_coverage` + pgvector smoke. CI `integration-test` job no longer needs `services: postgres`.
- S2 (PR #109, merged `f083bf7`) — `ENTITY_TYPE_TIER_RANK` enforced at every `part_of` write; universal self-reference rejection for ALL relation types. Writer / panoramic / enrichment each catch `HierarchyViolationError` with their own structured log. `scripts/audit_part_of_hierarchy.py` preflight audit script. Closed `RUN5.4.FU.01`.
- S3 (PR #110, merged `20af24f`) — `_rollback_merge` branches on `snapshot_schema_version`: v1 graceful partial, v2 full FK + winner-metadata reversal via additive `inverse` payload. `params`/`targets` shapes preserved per-producer; API round-trip tests verify. Closed `RUN5.4.FU.02`.

**Outcome:** `just test-integration` runs green in CI; `pytest` proves tier_rank + self-ref enforcement; merge rollback integration test proves FK + winner metadata reversal; legacy v1 audits degrade gracefully. Preflight audit artifact: `docs/superflow/audits/2026-04-25-run6.1-audit.md`.

### Run 6.2 — Access & Normalization ✅ FINAL 2026-04-25

**Goal:** close remaining correctness gaps around permissions and temporal data before benchmark work.

**Sprints (4, PRs #111-#114 queued for Phase 3 merge):**
- S1 — ACL propagation from events into `vector_chunks` and `claim_effective_access`; search, ask, tree, singleton repositories, and list metadata enforce caller visibility (`VGAP.05`).
- S2 — `DateNormalizer` moved to the shared extraction package and wired into `Writer`; date claims normalize at write time with anchor/reason metadata (`RUN3.07`).
- S3 — `ALAYA_PART_OF_STRICT` supports `strict`/`warn`/`off`, with admin visibility and startup flag logging for `part_of` hierarchy enforcement.
- S4 — Redis readiness reports bounded `ok`/`down`/`degraded` states; `channel` access is explicit retrieval tier 1; obsolete restricted-skip monitoring was removed.

**Outcome:** retrieval ACL is enforced beyond `should_extract()`; `channel`/`private`/`restricted` events still extract and gate at retrieval; write-time date normalization is covered by focused `pytest`; Redis and channel hygiene are ready for Run 6.3 benchmarks.

### Run 6.3 — Observability & Benchmark Automation

**Goal:** make quality improvements evidence-driven. Today quality targets from Run 5.4 are all unverified — we do not know what works.

**Sprints (3–4):**
- S1 — `just bench` one-command reproducible benchmark. Spins docker stack, creates API key, ingests the fixture, waits on the worker, dumps `extraction_runs` + `integrator_runs` summary to `bench_results/`.
- S2 — Integrator cost/token tracking (`RUN5.4.FU.03` + `RUN5.3` follow-up #1). Populate `integrator_runs.cost_usd` by mirroring the Run 5.3 `recalc_usage` pattern.
- S3 — Prompt-cache hit ratio metrics on every LLM adapter (`RUN3.11`). Emit `cache_read / total_input` per pipeline stage.
- S4 (optional) — Pad Cortex prompt over 1024 tokens for Haiku cache eligibility (`RUN5.3.08`).

**Exit criteria:** `just bench` prints a reproducible report; `integrator_runs.cost_usd > 0` on a fresh bench run; cache metrics appear in structlog output.

### Run 6.4 — Extraction Quality (evidence-driven)

**Goal:** improve graph shape using the metrics from 6.3. Order of work is determined by bench output, not pre-planned.

**Candidate sprints:**
- Crystallizer prompt v3: reduce `description` catch-all rate (`RUN5.3.10`), inject current date (`RUN5.3.09`).
- Claim supersession policy for multi-value (entity, predicate) pairs (`RUN5.3.12`).
- Synthetic dedup-gold fixture (`RUN5.4.FU.07`).

**Exit criteria:** a measurable improvement on at least two benchmark metrics from 6.3 output, with before/after numbers in the post-merge audit.

## After core stabilization

Once 6.1–6.4 are merged, the core is considered production-ready. Roadmap continues with:

- **Run 7 — Action Loop MVP** (`VGAP.01`–`VGAP.04`): workflow primitives (`workflow_actions` table, `job_remind`, `job_stale_scan`, `job_followup_check`, commitment kind, declared/inferred claim). This is what turns Alaya from memory into an operational engine.
- **Run 8 — Slack input connector** (`RUN 5a`): first real-world ingestion connector.
- **Run 9 — MCP Server** (`RUN 6`): agent-facing interface for Claude Code / Cursor / any MCP host.
- **Run 10 — Go CLI polish** (`RUN 4+`): documentation, keyring, user-facing flows.
- Further runs: additional connectors (GitHub, Linear, webhook), Web UI, Alaya Sync (desktop), Alaya Workflow (SaaS).

Sequencing rationale: input connectors before MCP (so agents have real data to retrieve); Action Loop before connectors is intentional — action primitives shape the MCP contract, so MCP sees the full shape of the API on first release rather than evolving under existing clients.

## Runs already completed

See the merged PR history on GitHub and `docs/backlog/BACKLOG.md` for item-level closure. High-level:

- Run 1 + 1.1 — Foundation + Hardening
- Run 2 — Extraction Pipeline
- Run 3 — Intelligence Pipeline (Cortex, Crystallizer, Integrator v1)
- Run 4 — Search + Ask + Go CLI
- Run 5.1 — Review follow-ups
- Run 5.2 — Security Hardening
- Run 5.3 — Pipeline Reliability
- Run 5.4 — Knowledge Graph Consolidation

## How to use this document

- **Contributors:** pick an open sprint in the current run. Coordinate via issues before starting.
- **Agent sessions (Superflow and direct):** read `CLAUDE.md` first, then this file, then `docs/backlog/BACKLOG.md`. Pick the current run (first non-completed row in the Core Stabilization table). Start Phase 1 (Discovery) from there.
- **Status updates:** when a run completes, move the row to "Runs already completed" and advance the current pointer.

This file is the source of truth for sequencing. Item-level detail lives in `docs/backlog/BACKLOG.md`; per-run plans live in `docs/superflow/plans/*` (internal, not tracked in git).

<!-- updated-by-superflow:2026-04-25 -->
