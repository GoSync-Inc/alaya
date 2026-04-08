# Run 3: Intelligence Pipeline — Known Limitations & Tech Debt

**Created:** 2026-04-08 (post Run 3 merge)
**Status:** Open — items for Run 4+ backlog

---

## P1 — Should fix in next Run

### 1. Entity dedup is soft-delete only, no full merge
- **Where:** `extraction/integrator/engine.py` `_merge_duplicates()`
- **What:** Dedup soft-deletes entity_b and merges aliases into entity_a, but does NOT reassign claims/relations from B to A. Consumers querying by entity_id will miss claims attached to the deleted duplicate.
- **Fix:** Add claim/relation reassignment: `UPDATE l2_claims SET entity_id = A WHERE entity_id = B`, same for l1_relations (both source and target).
- **Blocked by:** Needs careful handling of composite FKs + RLS.

### 2. Integration tests are all skipped
- **Where:** `tests/test_rls.py`, `tests/test_composite_fk.py`, `tests/test_rls_leak.py`
- **What:** 18 integration tests require live Postgres with seed data. No conftest creates the test DB/seeds automatically.
- **Fix:** Add `conftest.py` with `@pytest.fixture` that creates a temp DB, runs migrations, seeds core data, and tears down.

### 3. Redis health check shows "unavailable"
- **Where:** `api/routers/health.py`
- **What:** Health check connects to Redis via hardcoded URL or config, but may not match `ALAYA_REDIS_URL` env var prefix.
- **Fix:** Verify `Settings.REDIS_URL` is used consistently in health check.

---

## P2 — Should fix eventually

### 4. `update_type` enrichment stores in properties, not entity_type_id
- **Where:** `extraction/integrator/engine.py` `_apply_action()`
- **What:** Resolves type slug via `EntityTypeRepository.get_by_slug()` and sets `entity.entity_type_id`, but only if the slug matches an existing EntityTypeDefinition. Non-standard slugs from LLM are silently dropped.
- **Fix:** Add fallback: if slug not found, store in properties as `corrected_type` for manual review.

### 5. `INTEGRATOR_MAX_WAIT_SECONDS` = 1800 (30 min) vs spec's 300 (5 min)
- **Where:** `config.py` line 57
- **What:** Spec designed 300s for responsiveness. 1800s barely meets "30 min freshness" success criterion.
- **Decision:** Intentional — 300s causes excessive Integrator runs on low-volume workspaces. Revisit when usage patterns are clearer.

### 6. Entity cache not warmed with proper timestamps
- **Where:** `extraction/integrator/engine.py` `_run_locked()` line ~185
- **What:** Cache warm passes `last_seen_at: 0` for all entities → sorted set scores are all 0 → no meaningful ordering for Crystallizer snapshots.
- **Fix:** Use `entity.last_seen_at` or `entity.updated_at` as score.

### 7. DateNormalizer used only in `normalize_date` enrichment action
- **Where:** `extraction/integrator/date_normalizer.py`
- **What:** Module is wired into engine but not into Crystallizer extraction. Date claims from extraction still store raw text ("в пятницу") instead of ISO 8601.
- **Fix:** Wire DateNormalizer into `atomic_write` or `write_claim` for date-type claims.

### 8. No cross-workspace entity matching safeguard in Integrator
- **Where:** `extraction/integrator/engine.py`
- **What:** The engine loads entities via `entity_repo.list_recent(workspace_id)` + RLS. Safe in practice, but no explicit assert/check that all scope_ids belong to the same workspace.
- **Fix:** Add assertion: `assert all(eid in workspace_entity_ids for eid in dirty_entity_ids)`.

---

## P3 — Nice to have

### 9. README not updated for Run 3
- **What:** README still describes the system aspirationally. Now that API, extraction pipeline, and entities actually work, README should reflect reality.
- **When:** After CLI (Run 4) — that's when external users can actually try the system.

### 10. `eval_extraction.py` shows 0 crystal chunks in comparison table
- **Where:** `scripts/eval_extraction.py`
- **What:** FakeLLMAdapter returns realistic but low DomainScores. Crystal threshold comparison is technically correct but the eval table is not useful without real LLM calls.
- **Fix:** Add a `--real` flag that uses ANTHROPIC_API_KEY for actual comparison.

### 11. Prompt caching efficiency unmeasured
- **What:** Double-pass verification (Cortex + Crystallizer) relies on Anthropic prompt caching. Actual cache hit rate is unknown until production.
- **Fix:** Add metrics: `cache_read_input_tokens / total_input_tokens` ratio per extraction run.

---

## Cross-reference

- Master plan: `docs/superflow/plans/2026-04-07-alayaos-pivot.md`
- Run 3 spec: `docs/superflow/specs/2026-04-07-run3-intelligence-design.md`
- Run 3 eval: `docs/superflow/specs/2026-04-07-run3-intelligence-eval.md`
- Holistic review findings: addressed in PR #34 (all CRITICAL/HIGH fixed)
