# Run 6.2 Changelog: Access & Normalization

## Breaking Behavior Changes

- restricted and private events now extract instead of being skipped by the extraction pipeline. For pre-6.2 deployments, run `packages/core/alayaos_core/scripts/backfill_restricted_extraction.py` for existing restricted/private events that legacy workers skipped.
- claim.value.iso can be null when date normalization fails. Date claims also carry `normalized`, `anchor`, and `reason` so clients can distinguish parsed dates from failed parses.
- List responses add stable ACL metadata: `meta.filtered_count` is always present, and `meta.filter_reason` is populated when ACL filtering hides rows.
- `vector_chunks.access_level` is fall-closed: missing source provenance, source-less claims, and entity vectors without sourced claims default to `restricted` rather than inheriting a broader access level.

## New Operator Surface

- `ALAYA_PART_OF_STRICT=strict` remains the required operator posture/default for `part_of` hierarchy enforcement; Run 6.2 adds `GET /admin/flags` via S3 for runtime flag inspection.
- non-admin /tree bypasses cache by design. Admin tree responses keep using cached briefings, while non-admin responses render live filtered content to avoid leaking cached restricted summaries.

## Operator Actions Required

- pgvector >=0.8 required. Migration 008 and API startup fail fast when the installed extension is older.
- Initialize new databases with `CREATE EXTENSION IF NOT EXISTS vector;`; the migration and API startup guards enforce the >=0.8 requirement.
- Follow the deploy runbook in the Run 6.2 spec: drain workers before migration, or run the restricted/private-event backfill after a rolling deploy.
- Run `uv run python -m alayaos_core.scripts.backfill_restricted_extraction --workspace-id <workspace> --dry-run` first, then rerun with `--apply` after reviewing the count.
- The backfill selection uses `FOR UPDATE SKIP LOCKED` and skips events with pending/running extraction runs to reduce duplicate enqueue during concurrent operator invocations. Duplicate enqueue can still occur if two operators select the same skipped event before either process creates the new extraction run; rerun the dry-run and check worker/idempotency logs if multiple backfills run at once.
- HNSW recall is covered by an ACL-filtered integration test that compares pgvector indexed results with exact-scan results for the same allowed access set.

<!-- updated-by-superflow:2026-04-25 -->
