# Run 3 Intelligence Pipeline — Evaluation Against Success Criteria

**Date:** 2026-04-07  
**Sprint:** 6 (final sprint of Run 3)  
**Status:** Documentation only — no production data yet. Explains how each criterion would be measured in production.

---

## Success Criteria and Measurement Approach

### 1. Cost Reduction: ≥40% cheaper than Run 2

**Criterion:** The Run 3 pipeline must cost at least 40% less per event than the Run 2 single-pass Sonnet extraction.

**Mechanism:**
- **Cortex classifier** uses `claude-3-haiku-20240307` (≈$0.25/MTok input) for chunk classification.
- Only **crystal chunks** (classification score ≥ threshold) are forwarded to `claude-3-5-sonnet-20241022` (≈$3/MTok input).
- For a typical Slack channel with 60–70% smalltalk/low-signal messages, only 30–40% of chunks reach Sonnet.
- Cost formula: `cost_run3 = N_chunks * cost_haiku + N_crystal * cost_sonnet`; `cost_run2 = N_chunks * cost_sonnet`.

**Measurement in production:**
- Compare `extraction_runs.cortex_cost_usd + crystallizer_cost_usd` (Run 3) vs hypothetical `tokens_in * sonnet_rate` (Run 2) per event.
- Crystal selection rate of 35% → ~40% cost savings (Haiku overhead ≈ 8%, Sonnet savings ≈ 65% * 60% = 39%).

---

### 2. Precision: ≤5 false entities per 20 events

**Criterion:** No more than 5 spurious entity extractions per batch of 20 events.

**Mechanism:**
- **Double-pass verification** in CortexClassifier: each chunk is classified, then re-classified with a different prompt to confirm. Disagreements are flagged via `verification_changed = True`.
- **CrystallizerVerifier** verifies the extracted `ExtractionResult` from each crystal chunk: re-runs extraction on the same text and compares entities. Discrepancies are tracked in `extraction_runs.verification_changes`.
- **Entity validation** in Pydantic schemas: script tags rejected, control chars stripped, confidence bounds `[0, 1]` enforced, length limits applied.
- **Resolver disambiguation** (LLM-based) prevents phantom duplicates.

**Measurement in production:**
- Manual review of 20 events from a staging workspace.
- Count entities with confidence < 0.5 and no corroborating claims → false positives.
- Track `verification_changes` counter from `extraction_runs` table as a proxy signal.

---

### 3. Entity Dedup: ≤2% duplicate entities after integration

**Criterion:** After Integrator runs, fewer than 2% of entities in the graph are duplicates of each other.

**Mechanism:**
- **Integrator 3-tier matching:** (1) exact name match, (2) fuzzy similarity (Levenshtein + token overlap), (3) LLM disambiguation for ambiguous pairs above configurable threshold (`INTEGRATOR_DEDUP_THRESHOLD`).
- **EntityDeduplicator** finds pairs and soft-merges: the weaker entity is marked `is_deleted = True` and its claims/relations are migrated to the canonical entity.
- **EntityCacheService** (Redis-backed) provides O(1) lookup by normalized name to prevent re-insertion of known entities.
- **integrator_runs.entities_deduplicated** counter tracks each run's dedup activity.

**Measurement in production:**
- After 1 week of ingestion: query `SELECT COUNT(*) FROM entities WHERE is_deleted = FALSE` and manually inspect random sample for name-collision duplicates.
- Track `entities_deduplicated / entities_scanned` ratio in `integrator_runs` — target < 2%.

---

### 4. Hierarchy: ≥80% of Tasks linked to a parent Project

**Criterion:** At least 80% of entities classified as `task` have a `member_of` or `part_of` relation to a `project` entity.

**Mechanism:**
- **EntityEnricher** in the Integrator pipeline: after dedup, enriches each entity with inferred relations. For `task` entities, attempts to identify parent project from co-occurring claims (deadline, owner) and existing workspace relations.
- **`INTEGRATOR_BATCH_SIZE`** entities per LLM enrichment batch — Sonnet infers hierarchy from context window.
- **Relation creation** via `relation_repo.create` with `source_entity_id`, `target_entity_id`, and `relation_type = "member_of"`.

**Measurement in production:**
- Query: `SELECT COUNT(*) FROM relations WHERE relation_type = 'member_of'` filtered to task→project pairs.
- Divide by total task count: `SELECT COUNT(*) FROM entities e JOIN entity_types et ON e.entity_type_id = et.id WHERE et.slug = 'task'`.
- Target ≥ 80% coverage ratio.

---

### 5. Latency: ≤10s per event (p95)

**Criterion:** 95th percentile end-to-end latency from ingest to entities written is ≤ 10 seconds.

**Mechanism:**
- **Cortex stage** (~2s): Haiku classification of all chunks (parallel via async), single DB write per chunk.
- **Crystallizer stage** (~4s per crystal chunk, parallel): Sonnet extraction + verification for each crystal chunk. Multiple crystal chunks run concurrently as separate `job_crystallize` tasks.
- **Writer stage** (~1s): resolver + atomic write — runs after all crystallizer tasks complete.
- **Total budget:** 2 + max(crystal_chunks * 4 / parallelism) + 1. For 1 crystal chunk: ~7s. For 2 parallel crystal chunks: ~9s.

**Measurement in production:**
- Track `extraction_runs.started_at` → `extraction_runs.completed_at` for all events.
- Compute p95 using: `SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (completed_at - started_at))) FROM extraction_runs WHERE status = 'completed'`.
- Target ≤ 10s.

---

### 6. Freshness: ≤30 min enrichment delay after entity creation

**Criterion:** New entities created by the Writer are enriched by the Integrator within 30 minutes.

**Mechanism:**
- **Dirty-set trigger:** Writer pushes each new/updated entity ID to `dirty_set:{workspace_id}` Redis key immediately after write.
- **`job_check_integrator`** (periodic task): scans all `dirty_set:*` keys, triggers `job_integrate` if count ≥ `INTEGRATOR_DIRTY_SET_THRESHOLD` (default 10) OR age ≥ `INTEGRATOR_MAX_WAIT_SECONDS` (default 1800s = 30 min).
- **Age marker:** `dirty_set:{workspace_id}:created_at` is set on first dirty-set write, reset after drain. Guarantees max 30-min delay even for sparse activity.

**Measurement in production:**
- Track `entities.updated_at` vs `integrator_runs.completed_at` for workspace.
- Maximum gap across all entities in a workspace after `job_integrate` completes should be ≤ 1800s.
- Monitor `INTEGRATOR_MAX_WAIT_SECONDS` config vs actual age at trigger time.

---

### 7. Verification: ≥95% agreement rate between first and second pass

**Criterion:** Double-pass verification agrees ≥95% of the time (i.e., second pass confirms first pass without changes).

**Mechanism:**
- **CortexClassifier double-pass:** `classify_and_verify(chunk)` runs classification twice. Returns `changed = True` if domains differ by > epsilon. Tracked in `extraction_runs.verification_changes`.
- **CrystallizerVerifier double-pass:** `verify(chunk_text, system_prompt, initial_result)` re-runs extraction and compares entity/claim lists. Returns `verification_changed = True` if results differ.
- Both changes are counted in `extraction_runs.verification_changes`.

**Measurement in production:**
- `agreement_rate = 1 - (SUM(verification_changes) / COUNT(*))` from `extraction_runs` where status = 'completed'.
- Equivalently: `SELECT AVG(CASE WHEN verification_changes = 0 THEN 1.0 ELSE 0.0 END) FROM extraction_runs WHERE status = 'completed'`.
- Target ≥ 95% (i.e., ≤ 5% of runs have any verification disagreement).

---

## Summary

| # | Criterion | Mechanism | Key Counter |
|---|-----------|-----------|-------------|
| 1 | ≥40% cost reduction | Haiku for classify, Sonnet only for crystal | `cortex_cost_usd + crystallizer_cost_usd` |
| 2 | ≤5 false entities / 20 events | Double-pass verification + Pydantic validation | `verification_changes`, manual review |
| 3 | ≤2% duplicate entities | Integrator 3-tier dedup (exact→fuzzy→LLM) | `entities_deduplicated / entities_scanned` |
| 4 | ≥80% tasks linked to project | EntityEnricher hierarchy inference | `relations WHERE relation_type='member_of'` |
| 5 | ≤10s per event (p95) | Async pipeline: Cortex 2s + Crystallizer 4s | `completed_at - started_at` p95 |
| 6 | ≤30 min enrichment freshness | Dirty-set + max_wait=1800s trigger | `INTEGRATOR_MAX_WAIT_SECONDS` |
| 7 | ≥95% verification agreement | Double-pass on Cortex + Crystallizer | `1 - verification_changes / total_runs` |

*All measurements are designed to be evaluated once production data is available (≥1 week of real ingestion).*
