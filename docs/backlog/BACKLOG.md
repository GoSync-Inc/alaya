# AlayaOS — Unified Backlog

Single source of truth for all tech debt, known limitations, and research items across all runs.

**Format:** `[RUN-N.NN]` prefix for traceability. Priority: P1 (next run), P2 (eventually), P3 (nice to have).

_Last audited: 2026-04-25. Closed items moved to `## Closed` section with commit hashes._

---

## CC-Research Items (from Master Plan brainstorm)

Plan file `docs/superflow/plans/2026-04-07-alayaos-pivot.md` no longer exists (pre-Run-2 planning artifact). Specs were planned but never written.

| ID | Title | Target Run | Status |
|----|-------|-----------|--------|
| BACKLOG-252 | Per-Query Context Cache | Run 3 (Search) | Deferred — Run 3 became Intelligence Pipeline |
| BACKLOG-254 | Cost Tracking & Analytics | Run 8q | Open |
| BACKLOG-255 | Per-User Memory System | Run 8a | Open |
| BACKLOG-256 | Autonomous Task Queue | Run 8d | Open |
| BACKLOG-257 | Context Compaction (long Slack threads) | Run 2 | Partially done — CortexChunker handles chunking |
| BACKLOG-258 | Resilient LLM Retry | Run 2 | DONE — cross-provider fallback shipped (`16b0be6`) |
| BACKLOG-259 | Org-Level Policy & Limits | Run 8m | Open |
| BACKLOG-260 | Team Memory Sync (delta sync, ETag) | Run 5 | Open |
| BACKLOG-261 | Deferred Tool Loading | Run 8p | Open |
| BACKLOG-263 | Multi-Agent Architecture | Run 8n | Open |
| BACKLOG-264 | Prompt Engineering (cache-aware sectioning) | Run 2 | Done — ephemeral cache_control in AnthropicAdapter |

---

## Run 1 + 1.1: Foundation + Hardening

No open items — all addressed during Run 2.

---

## Run 3: Intelligence Pipeline

### P1 — Should fix in next run

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN3.03 | P1 | Redis health check "unavailable" | `api/routers/health.py:55` | TODO comment present: `checks["redis"] = "unavailable"`. `Settings.REDIS_URL` not wired into health check. |

### P2 — Should fix eventually

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN3.04 | P2 | `update_type` fallback for unknown slugs | `integrator/engine.py:924` | LLM may return slugs not in EntityTypeDefinition. If `et_repo.get_by_slug` returns None, update is silently dropped. |
| RUN3.05 | P2 | INTEGRATOR_MAX_WAIT_SECONDS 1800 vs spec 300 | `config.py:63` | Intentional — 300s too aggressive for low-volume. Revisit with usage data. |
| RUN3.06 | P2 | Entity cache warmed with score=0 | `integrator/engine.py:304` | `last_seen_at: 0` → no meaningful sorted set ordering for Crystallizer. Use `entity.updated_at`. |
| RUN3.07 | P2 | DateNormalizer not wired into Writer | `date_normalizer.py` | Only used in Integrator enrichment, not in `write_claim` for date-type claims. |
| RUN3.08 | P2 | No explicit workspace assertion in Integrator scope | `integrator/engine.py` | RLS protects in practice, but no assert that dirty-set IDs match workspace. |

### P3 — Nice to have

| ID | P | Title | Details |
|----|---|-------|---------|
| RUN3.09 | P3 | README not updated | Waiting for CLI (Run 4) before updating README for external users. |
| RUN3.10 | P3 | Eval script needs `--real` flag | `scripts/eval_extraction.py` — FakeLLM comparison not useful. Need real API key mode. |
| RUN3.11 | P3 | Prompt caching efficiency unmeasured | Need `cache_read_input_tokens / total_input_tokens` metrics per run. |

---

## Run 5.3: Extraction Pipeline Reliability (2026-04-14)

Source: benchmark on 40 real Slack events. Plan files (`2026-04-14-pre-benchmark-handoff.md`, `2026-04-14-run5.3-pipeline-reliability-brief.md`, `2026-04-14-run5.3-pipeline-reliability.md`) are not present in the repository — pre-commit planning artifacts.

### Deferred (out of scope for Run 5.3, track here)

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.3.07 | P2 | Drop Cortex `verify` pass by default | `packages/core/alayaos_core/extraction/cortex/classifier.py` | Benchmark showed verify changes scores in 38/40 chunks but doesn't demonstrably improve quality on sample. Dropping it halves Cortex cost. Could be a config flag `CORTEX_VERIFY_ENABLED=false`. |
| RUN5.3.08 | P3 | Cortex prompt caching: pad system prompt > 1024 tokens | `packages/core/alayaos_core/extraction/cortex/classifier.py` | Haiku requires ≥ 1024 tokens for cache hits. Current classifier prompt is ~ 200 tokens, so 0 cache hits. Either pad with example domain descriptions or switch to Sonnet. |
| RUN5.3.09 | P2 | Extractor: current date in system prompt | `packages/core/alayaos_core/extraction/extractor.py` | "1 марта" gets resolved to wrong year (e.g. 2024 instead of 2026). Inject today's date into the system prompt so LLM anchors relative dates correctly. |
| RUN5.3.10 | P3 | Extractor: prefer specific predicates over `description` | `packages/core/alayaos_core/extraction/extractor.py` | `description` is ~ 26-36% of all claims in benchmark — LLM uses it as a catch-all bailout. Tighten system prompt: "Use `description` only if no more specific predicate fits." |
| RUN5.3.11 | P3 | Resolver: Slack handle `<@UXXXXXX>` → user name | `packages/core/alayaos_core/extraction/resolver.py` | Handles persist as `person` entity name. Requires Slack connector (Run 5a) to populate a user table with handle→name mapping. |
| RUN5.3.12 | P3 | `l2_claims` temporal: multiple values per (entity, predicate) | `packages/core/alayaos_core/models/claim.py`, `integrator/` | Many `status` claims for the same entity cause graph fragmentation. Needs schema design: supersede-on-write vs. temporal interval vs. latest-wins policy. |
| RUN5.3.13 | P2 | Orphan-run reaper: retry stuck `cortex_complete` from earlier crashes | `packages/core/alayaos_core/worker/tasks.py` | RUN5.3.03 prevents NEW stuck runs forward. This item is about cleaning up runs stuck from before that fix (reaper task, periodic). |

---

## Run 4+: Future (from Master Plan)

| Run | Scope | Status |
|-----|-------|--------|
| Run 4 | CLI (Typer + Rich) | Not started |
| Run 5a-d | Connectors (Slack, GitHub, Linear, Webhook) | Not started |
| Run 6 | MCP Server | Not started |
| Run 7 | Web UI | Not started |
| Run 8a-q | Workflows, Agents, Analytics | Not started |

---

## Vision Alignment Gaps (2026-04-14)

Расхождения между `docs/vision/` артефактами и текущей реализацией. Vision позиционирует Alaya как **operational memory + workflow engine** («из разговоров в состояние, из состояния в действия»). Построено: memory + extraction + retrieval. Не построено: workflow/action layer и несколько принципов уровня схемы.

Source: `docs/vision/alaya-master-vision-session-summary-ru.md`, `alaya-operational-memory-whitepaper-ru.md`, `alaya-implementation-note-ru.md`.

### P1 — критичные для vision-позиционирования

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| VGAP.01 | P1 | Action Loop MVP — reminders, stale surfacing, state-triggered workflows | новый `core/workflow/`, TaskIQ jobs, `api/routers/workflows.py` | Execution сейчас — внутренний слой pipeline. Vision: execution — **часть identity системы**. MVP: `job_remind`, `job_stale_scan`, `job_followup_check` + 3 endpoint'а. Без этого Alaya = просто память, а не operational engine. |
| VGAP.02 | P1 | Declared vs Inferred на claim | `models/claim.py`, `crystallizer/schemas.py`, extraction prompt | Vision: «один из важнейших принципов». Сейчас есть только `confidence` — это не то же самое. Добавить `kind: Literal["declared","inferred"]`. Crystallizer должен различать на выходе. Inferred не маскируется под declared. |
| VGAP.03 | P1 | Commitment как отдельный entity/claim kind | `entity_types` seed + crystallizer prompt + eval | Обязательства («Иван сделает X к Y») — это топливо для Action Loop (VGAP.01). Без отдельного извлечения reminders не из чего строить. Пересекается с VGAP.02 (commitment = declared по определению). |

### P2 — важные гигиенические

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| VGAP.04 | P2 | Stale-state detection + surfacing | `integrator/` + новый endpoint `/state/stale` | Формула: `max(valid_from, last_touched) + decay > threshold` → сущность/claim в review. Питает VGAP.01. |
| VGAP.05 | P2 | ACL propagation: event → chunks → claims → retrieval | `writer.py`, все workspace-scoped repos | Сейчас `access_level` проверяется только в `should_extract()`. Claim неявно наследует от event — но это не фильтруется при retrieval по API-key/person scope. Явно пропагировать и фильтровать. |
| VGAP.06 | P2 | Correction loop | `PATCH /claims/{id}` + integrator hook | Ручная коррекция claim → старый в `superseded`, downstream tree dirty, conflicts-recheck. Сейчас PATCH не триггерит ничего. |

### P3 — практики и дисциплина

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| VGAP.07 | P3 | Core Extraction Journal как практика | `docs/core-journal/` + CLAUDE.md addendum | Vision: для каждой крупной фичи запись — core/domain/reusable, зависимости, цена выделения. Это discipline, не feature. Нужна, чтобы избежать premature carve-out. |
| VGAP.08 | P3 | Evals-first как политика | CLAUDE.md architecture rules | Vision: «любой сложный слой требует evals или justified skip». Расширить `eval_extraction.py` → `--real` flag + LongMemEval-style harness. Связано с RUN3.10. |

---

## Product Strategy (2026-04-14)

Стратегические направления за пределами core engineering. **Не для ближайшего run'а** — здесь чтобы учитывать при дизайне контрактов (в частности MCP-surface в Run 6).

| ID | Scope | Title | Details |
|----|-------|-------|---------|
| PROD.01 | strategic | Alaya Sync — local daemon as paid tier | Отдельный продукт и репо, не часть core. Локальный демон (macOS/Win/Linux), который: (1) наблюдает AI-инструменты (Claude Code hooks, Cursor logs, Zed AI, Raycast AI), (2) инжектирует briefing на SessionStart, (3) захватывает PreCompact/SessionEnd → events в Alaya. Зачем: скиллы и хуки в агентах нестабильны — нужен managed sync-слой между AI-tools и корпоративной памятью. Depends on: стабильный MCP-контракт в Run 6 (MCP должен быть достаточно богат, чтобы sync-daemon мог им пользоваться). MVP: Claude Code + Cursor, macOS. Ценовая модель: seat-based subscription поверх OSS core. |
| PROD.02 | strategic | AlayaOS (B2B chief of staff) vs Between (personal) — product split | Vision фиксирует две продуктовые оси над общим ядром. Сейчас фокус — только AlayaOS / corporate memory. Between делается отдельно, carve-out ядра не делаем. Это напоминание, чтобы не плодить абстракции «на будущее». |
| PROD.03 | strategic | Alaya Workflow — stateless SaaS для бизнес-процессов | Отдельный paid SaaS поверх open-core Alaya. **Не хранит клиентских данных** — работает через API-ключ к Core клиента (self-host или managed cloud). Содержит: (1) библиотеку recipe'ов для типовых бизнес-процессов, (2) domain packs (sales / ops / HR / compliance), (3) visual orchestration, (4) webhooks-мост к внешним системам, (5) trigger-слой поверх state-changes в Core. Граница с Core: в open-core остаются **workflow primitives** (TaskIQ triggers, reminders, stale-detection), в Workflow — **готовые бизнес-процессы и domain recipes**. Depends on: VGAP.01 Action Loop MVP в core + стабильный MCP-контракт. Ценовая модель: per-workspace subscription, возможно metered по числу триггеров/recipe-runs. Strategic angle: трёхслойная продуктовая линия Core (OSS) + Workflow (SaaS) + Sync (desktop) — все работают через один API-контракт, ни один не дублирует storage друг друга. |

---

## Run 5.4: Knowledge Graph Consolidation (2026-04-16)

Merged 2026-04-16 via PRs #87–#94. Plan files not in repo (planning artifacts).

### P1 — must fix next

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.4.FU.03 | P1 | Complete RUN5.4.09 integrator cost observability | `packages/core/alayaos_core/extraction/integrator/engine.py`, `packages/core/alayaos_core/extraction/integrator/schemas.py:87-88`, `packages/core/alayaos_core/worker/tasks.py:761` | `IntegratorRunResult.cost_usd` / `tokens_used` default 0.0 / 0 and are never populated. `update_counters` accepts the field but the worker forwards values that were never set. No `pipeline_traces → integrator_runs` aggregation mirror of the Run 5.3 `recalc_usage` pattern was added. Two paths to close: (a) mirror `recalc_usage` for integrator by summing `pipeline_traces` joined on `run_id`; (b) plumb LLM usage returns from `PanoramicPass` + `DeduplicatorV2` back through `_run_locked`. Cross-link: prior RUN5.3 follow-up #1. |
| RUN5.4.FU.04 | P1 | Run post-merge Step D benchmark on 40-event fixture | `scripts/bench_ingest.py`, `data/slack_export/slack_sample_40.jsonl` (local) | Run 5.4 audit records every quality-facing brief target as ⚠️ "unverified — benchmark deferred" because no re-benchmark was executed after PR #94 merged. Items that resolve only after Step D: dedup merge count, garbage remaining, description-fill rate, task/goal/north_star usage, synthetic project count, multi-pass wallclock, `extraction_runs.cost_usd` under multi-pass. |

### P2 — important hygiene

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.4.FU.06 | P2 | Wire `CONSOLIDATOR_PANORAMIC_MAX_ENTITIES` through `Settings` | `packages/core/alayaos_core/config.py`, `packages/core/alayaos_core/extraction/integrator/passes/panoramic.py:150` | `CLAUDE.md:85` advertises it as an env var; implementation reads only the constructor param. The env var is inert today — panoramic cap is fixed at whatever the caller passes. |
| RUN5.4.FU.07 | P2 | Synthetic dedup-gold fixture | `tests/fixtures/`, `test_integrator_dedup.py` | Dedup tests use FakeLLM with hand-crafted batches. No regression fixture for abbreviation/transliteration pairs (Орг/Орги, КС/Ticketscloud). Run 5.3 follow-up #5, still open post-Run 5.4. |

### P3 — nice to have

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.4.FU.08 | P3 | Document v1 fallback path retention | `CLAUDE.md`, in-code docstrings on `EntityDeduplicator` and `DeduplicatorV2` | `DeduplicatorV2` is the intended path; `EntityDeduplicator` (v1) remains for the no-embeddings case. No doc explains when each fires or the deprecation plan for v1. Cross-link: prior RUN3.01 (claimed closed in code by dedup v2, not marked closed in backlog until now). |
| RUN5.4.FU.09 | P3 | Tidy unreachable `IntegratorAction.status='failed'` enum value | `alembic/versions/006_consolidator_schema.py:32`, `packages/core/alayaos_core/repositories/integrator_action.py` | Migration declares `failed` in the allowed values; no code path writes it. Either wire the failed state into the apply_action error path or drop from the enum. |

### Run 5.4 brief-deferred items

Ported verbatim from the brief's "Items deferred" table (RUN5.4.10–15).

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.4.10 | P2 | Slack handle → user name resolution | `packages/core/alayaos_core/extraction/resolver.py` | `<@UXXXXXX>` persists as a `person` entity name. Needs the Slack connector (Run 5a, not started) to populate a user table with handle→name mapping. Cross-link: prior RUN5.3.11. |
| RUN5.4.11 | P2 | LLM decision cache for panoramic pass | new | Panoramic LLM call is the dominant per-pass cost. Repeated runs over overlapping entity sets could cache the decision. Out of scope in Run 5.4 because benchmark-driven evidence does not yet exist. |
| RUN5.4.12 | P3 | Action review UI | new | `integrator_actions` is a full audit table, but there is no UI/CLI surface to review pending actions before apply or to batch-rollback. Deferred until Web UI (Run 7). |
| RUN5.4.13 | P3 | Per-workspace dedup / panoramic thresholds | `packages/core/alayaos_core/config.py` | Thresholds (`INTEGRATOR_DEDUP_*`, `CONSOLIDATOR_PANORAMIC_MAX_ENTITIES`) are global-per-deployment today. Per-workspace tuning needs a workspace-level settings table. Not needed until multi-tenant deployments appear. |
| RUN5.4.14 | P2 | Cortex verify-vs-classify ordering fix | `packages/core/alayaos_core/extraction/cortex/classifier.py` | Duplicate of prior RUN5.3 follow-up #4. Benchmark in Run 5.3 showed `verify` changes scores in 38/40 chunks without demonstrable quality improvement. Either drop `verify` by default (`CORTEX_VERIFY_ENABLED=false`) or fix the ordering so `verify` runs on top of `classify` rather than standalone. |
| RUN5.4.15 | P2 | `tokens_in` split into `input`/`output`/`cache_*` | `packages/core/alayaos_core/models/extraction_run.py`, `models/pipeline_trace.py` | Duplicate of prior RUN5.3 follow-up #2. Current single `tokens_in` column conflates all Anthropic token classes, so cache efficiency cannot be measured against total spend. Needs schema change + `recalc_usage` update. |

### Closed in Run 5.4 (audit verification)

| Backlog ID | Title | Evidence |
|-----------|-------|----------|
| RUN3.01 | Entity dedup: soft-delete only, no claim/relation reassignment | Closed in code by DeduplicatorV2 (`packages/core/alayaos_core/extraction/integrator/dedup.py:589-640`) and the v1 fallback fix (`packages/core/alayaos_core/extraction/integrator/engine.py:807-860`). Raw-SQL reassignment of claims, relations, chunks now runs on every merge path. |

---

## Run 6.1: Data Integrity (2026-04-25)

Merged 2026-04-25 via PRs #108 (S1), #109 (S2), #110 (S3). Charter + spec + plan in `docs/superflow/{specs,plans}/2026-04-24-run6.1-data-integrity-*`. Preflight audit artifact: `docs/superflow/audits/2026-04-25-run6.1-audit.md`.

### P1 — must fix next

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN6.1.FU.01 | P1 | Implement `ALAYA_PART_OF_STRICT` feature flag | `packages/core/alayaos_core/repositories/relation.py`, `packages/core/alayaos_core/config.py` | Charter documented `ALAYA_PART_OF_STRICT=false` as warn-only fallback when preflight audit finds inverted rows in production. Not implemented in Run 6.1 (scope). Needed IF a future deployed environment surfaces inverted rows that cannot be fixed in-place before merging new code. Today strict enforcement always raises. |

### P2 — important hygiene

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN6.1.FU.02 | P2 | Bulk-SELECT tier validation in `create_batch` | `packages/core/alayaos_core/repositories/relation.py` `_validate_part_of_tier` | Holistic code review H2: per-row SELECT during `create_batch` pre-validation is N round-trips. Replace with single `SELECT source_id, sd.slug, target_id, td.slug ... WHERE (source_id, target_id) = ANY(ARRAY[...])` per batch, map slug→rank in Python. Low real-world impact today (small batches); promote if extraction pipeline ingests batches with many part_of edges. |
| RUN6.1.FU.03 | P2 | Bulk conflict check in `_check_merge_rollback_conflicts` | `packages/core/alayaos_core/repositories/integrator_action.py` | Holistic code review M3: per-ID SELECT across 4 FK kinds is O(N) round-trips. Rare admin rollback today — promote only when rollback timeout becomes a concern. Replace with 4 bulk SELECTs (`WHERE id = ANY(:ids)`) classified in Python. |

### P3 — nice to have

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN6.1.FU.04 | P3 | Split panoramic log event for self-ref vs tier inversion | `packages/core/alayaos_core/extraction/integrator/engine.py:474,514` | Holistic product review M1: `panoramic_part_of_rejected` is emitted for both tier violations AND self-ref rejections (via the universal `_reject_self_reference` guard). The `action` field disambiguates, but the event name misleads ops filtering. Either split into `panoramic_self_ref_rejected` + `panoramic_tier_violation_rejected`, or add a `violation_type` structured field. |
| RUN6.1.FU.05 | P3 | Add `rollback_merge_skipped_deleted_relations` log-capture assertion | `packages/core/tests/integration/test_integrator_merge_rollback.py` | Holistic product review M2: `test_rollback_merge_does_not_resurrect_self_ref` verifies the data invariant but does not assert the structured log. Future regression that silently drops the log emission would pass today. Wrap `apply_rollback` in `structlog.testing.capture_logs()` + assert. |
| RUN6.1.FU.06 | P3 | Factor duplicated "SELECT IDs before mutation" between dedup and engine | `packages/core/alayaos_core/extraction/integrator/dedup.py`, `.../engine.py` | Holistic code review backlog: both merge producers have near-identical scaffolding for the v2 audit ID capture. If `_merge_duplicates` (legacy engine path) is later retired once dedup v2 fully covers the merge scenarios, extract into shared helper. Not dead code today (both producers active). |

### Closed in Run 6.1 (audit verification)

| Backlog ID | Title | Evidence |
|-----------|-------|----------|
| RUN5.4.FU.01 | Enforce `ENTITY_TYPE_TIER_RANK` on `part_of` writes | Closed by Sprint 2 — `RelationRepository._validate_part_of_tier` (`packages/core/alayaos_core/repositories/relation.py`) fires on every `create()` and `create_batch()` call. Writer (`writer.py`), panoramic (`engine.py:462,485`), enrichment (`engine.py:911`) each catch `HierarchyViolationError` and log a named structured event. Preflight audit script `scripts/audit_part_of_hierarchy.py`. Commits `e89512b`, `de4f2a2`, `1ebdd24`, `f083bf7`. |
| RUN5.4.FU.02 | `_rollback_merge` FK reassignment | Closed by Sprint 3 — `_rollback_merge` branches on `snapshot_schema_version`. v2 path walks `moved_claim_ids` + `moved_relation_source_ids` + `moved_relation_target_ids` + `moved_chunk_ids` and bulk-UPDATEs FK back to loser; restores winner metadata from `inverse["winner_before"]`. v1 actions degrade gracefully. Commits `a31be88`, `f0789af`, `c875f57`, `20af24f`. |

RUN3.02 (integration tests all skipped) was marked DONE in prior run; Sprint 1 hardened further by replacing the harness with testcontainers + alembic + non-superuser `alaya_app` role (commits `ec5d44d`, `7038194`, `40be788`). RLS negatives are now proven against a real role.

---

## Run 6.2: Access & Normalization (2026-04-25)

### Follow-ups

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN6.2.FU.01 | P2 | Instrument `part_of` tier violation counter | `packages/api/alayaos_api/routers/admin.py`, future log-store integration | `/admin/flags` intentionally reports `violations_last_24h=null` with `violations_last_24h_reason="counter_not_yet_instrumented"` until structured log counters are queryable. |

---

## Closed

Items verified DONE as of 2026-04-17 audit. Commit hashes reference the fix landing in this repo.

### Run 2

| ID | Title | Status | Commit |
|----|-------|--------|--------|
| RUN2.01 | LLM cross-provider fallback | DONE | `16b0be6` feat: LLM cross-provider fallback with factory |
| RUN2.02 | Consolidation agent stub (`job_enrich` no-op) | OBSOLETE | Replaced by Integrator (Run 3); no fix needed |

### Run 3

| ID | Title | Status | Commit |
|----|-------|--------|--------|
| RUN3.01 | Entity dedup: claim/relation reassignment on merge | DONE | `b3451b6` fix: reassign claims/relations/chunks on entity merge (also verified in Run 5.4 code review) |
| RUN3.02 | Integration tests all skipped (18) | DONE | `02b3a53` fix: integration test infrastructure and markers |

### Run 5.1

| ID | Title | Status | Commit |
|----|-------|--------|--------|
| RUN5.01 | Write-stage correctness must not depend on Redis | DONE | `9fe627d` fix: move write serialization to db lock |
| RUN5.02 | Manual integrator trigger returns an orphan run | DONE | `6ef8ba2` fix: reuse api-created integrator runs |
| RUN5.03 | Worker creates a new SQLAlchemy engine per task | DONE | `d32eda2` refactor: reuse worker db engine per process |

### Run 5.2 (Security Hardening — SBP-001..006)

Security audit source: `docs/audits/2026-04-13-security-best-practices.md`

| ID | SBP | Title | Status | Commit |
|----|-----|-------|--------|--------|
| RUN5.04 | SBP-001 | Memory-read scope enforcement | DONE | `a9d1fd4` fix: harden read auth and rate limit boundaries |
| RUN5.05 | SBP-002 | Rate limiting fail-closed on Redis outage | DONE | `a9d1fd4` fix: harden read auth and rate limit boundaries |
| RUN5.06 | SBP-003 | Disable OpenAPI/docs in production | DONE | `6909204` fix: add production Caddyfile, migration error handling, docs |
| RUN5.07 | SBP-004 | TrustedHost validation | DONE | `6909204` fix: add production Caddyfile, migration error handling, docs |
| RUN5.08 | SBP-005 | Reduce anonymous readiness detail leakage | DONE | `34c9e3a` fix: reduce health and cli secret leakage (`HEALTH_READY_VERBOSE` flag) |
| RUN5.09 | SBP-006 | Redact CLI secret output by default | DONE | `34c9e3a` fix: reduce health and cli secret leakage (`--show-secret` flag) |

### Run 5.3 (in-scope items)

| ID | Title | Status | Commit |
|----|-------|--------|--------|
| RUN5.3.01 | `EntityMatchResult.reasoning` max_length too short | DONE | `c806593` fix: raise EntityMatchResult.reasoning max_length |
| RUN5.3.02 | Anthropic adapter: tolerate JSON-string for list fields | DONE | `5ee7d21` fix: handle PEP 604 list unions in adapter coercion |
| RUN5.3.03 | Run status never transitions to `failed` on crash | DONE | `73cc753` fix: log mark_failed errors, cover job_cortex + persistence tests |
| RUN5.3.04 | Integrator O(n²) dedup times out | DONE | `b7cf224` perf: batch integrator dedup via vector shortlist |
| RUN5.3.05 | Cortex `is_crystal`: smalltalk-aware rule | DONE | `2c64e4e` feat: smalltalk-aware is_crystal rule |
| RUN5.3.06 | `extraction_runs.cost_usd` / `tokens_in` aggregation | DONE | `032f2dd` feat: aggregate cost and tokens onto extraction_runs; `3e4f027` fix: recalc_usage for zero-crystal path |
