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

## Run 5.3: Extraction Pipeline Reliability (2026-04-14)

Source: benchmark on 40 real Slack events (`docs/superflow/audits/2026-04-14-pre-benchmark-handoff.md` Step B).
Brief: `docs/superflow/specs/2026-04-14-run5.3-pipeline-reliability-brief.md`
Plan: `docs/superflow/plans/2026-04-14-run5.3-pipeline-reliability.md`

### In scope for this run

| ID | P | Title | Where | Details |
|----|---|-------|-------|---------|
| RUN5.3.01 | P1 | `EntityMatchResult.reasoning` max_length too short | `packages/core/alayaos_core/extraction/schemas.py`, `packages/core/alayaos_core/extraction/integrator/schemas.py` | LLM reasoning exceeds 200 chars — `ValidationError` aborts `job_write`, run stuck at `cortex_complete`. Raise limit to 1000 and add regression. |
| RUN5.3.02 | P1 | Anthropic adapter: tolerate JSON-string for list fields | `packages/core/alayaos_core/llm/anthropic.py` | LLM sometimes returns list fields as a JSON-encoded string. Auto-parse when field annotation is `list[...]` and value is a parseable JSON array. |
| RUN5.3.03 | P1 | Run status never transitions to `failed` on writer/crystallize crash | `packages/core/alayaos_core/worker/tasks.py` | Wrap task bodies in try/except. On any `Exception`, call `mark_failed` and re-raise. |
| RUN5.3.04 | P1 | Integrator O(n²) dedup times out | `packages/core/alayaos_core/extraction/integrator/engine.py`, `dedup.py` | Replace all-pairs LLM loop with vector-similarity shortlist + LLM-verify top-k. New settings `INTEGRATOR_DEDUP_SHORTLIST_K`, `INTEGRATOR_DEDUP_SIMILARITY_THRESHOLD`. |
| RUN5.3.05 | P2 | Cortex `is_crystal`: smalltalk-aware rule | `packages/core/alayaos_core/extraction/cortex/classifier.py` | `is_crystal = not (smalltalk ≥ 0.8 AND max_non_smalltalk < 0.4)` AND `max_non_smalltalk ≥ threshold`. Filters chit-chat while keeping mixed-signal events. |
| RUN5.3.06 | P2 | `extraction_runs.cost_usd` / `tokens_in` aggregation from traces | `packages/core/alayaos_core/worker/tasks.py`, `repositories/extraction_run.py` | Add `recalc_usage` and call on terminal transitions. Run-level observability matches trace-level reality. |

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
