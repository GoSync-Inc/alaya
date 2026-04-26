# Sanitize Corpus — Operator Procedure

This document describes how to safely pull production Slack events, sanitize PII,
and produce a bench fixture ready for `just bench`.

## Purpose and Threat Model

**What we protect against:**

- PII leaking into git: real names, emails, phone numbers, Slack user IDs, channel IDs
- Company-internal URL paths that reveal internal tooling
- Real company name appearing in fixtures
- Accidentally committed secrets (API keys, tokens, JWTs)

**What we do NOT protect against:**

- Semantic content of messages (topics, project names if not the company name)
- Linguistic style patterns that might be recognizable
- Statistical frequency analysis of anonymized IDs

The sanitized corpus is safe to commit to the repository; the raw export must never be
committed and must be deleted after sanitization (see Storage Policy below).

## Prerequisites

### Python dependencies

```bash
uv sync --all-packages --dev
```

This installs `faker` and `spacy` (required by `scripts/sanitize_corpus.py`).

### spaCy language models (optional but recommended for PERSON NER)

The script uses spaCy NER to detect and replace person names in free text.
Without the models, names embedded in message text are **not** replaced
(Slack user IDs, actor fields, emails, phones are still sanitized regardless).

Download the models once per development environment:

```bash
uv run python -m spacy download en_core_web_sm   # English model (~12 MB)
uv run python -m spacy download ru_core_news_sm  # Russian model (~45 MB)
```

If models are absent, the script prints a warning to stderr and continues.

### SSH access

You need SSH access to the production PostgreSQL host (or an SSH tunnel to it).
Ask your infrastructure team for access details. Use a read-only database role.

## Pull Procedure

**Step 1: Open an SSH tunnel to the production database**

```bash
ssh -L 5433:<PROD_DB_HOST>:5432 <BASTION_HOST> -N &
# Replace <PROD_DB_HOST> and <BASTION_HOST> with actual values (not stored in git)
```

**Step 2: Export events via psql**

> **Why not `COPY … TO STDOUT`?**
> PostgreSQL's TEXT-format COPY escapes backslashes, turning JSON's `\"` into `\\"` and
> breaking downstream JSON parsing. Using `psql -A -t` (unaligned, tuples-only) outputs
> each row's text directly with no extra escaping.
> The `::text` cast on `json_build_object(…)::text` is required so psql renders the value
> without additional quoting.
> `BEGIN READ ONLY; … ROLLBACK;` provides defence-in-depth: even with a writable role,
> the transaction cannot mutate data.

**Pattern A — SSH tunnel + local psql**

Open the tunnel first (Step 1), then run locally:

```bash
psql "postgresql://<DB_USER>:<DB_PASS>@localhost:5433/<DB_NAME>" -A -t -q <<'SQL' > /tmp/raw_events.jsonl
BEGIN READ ONLY;

SELECT json_build_object(
  'id', id::text,
  'raw_text', raw_text,
  'ts', extract(epoch from source_timestamp)::bigint::text,
  'channel_id', channel_id,
  'actor', actor_user_id,
  'thread_ts', thread_ts,
  'source_type', source_type,
  'source_id', source_id
)::text
FROM l0_events
WHERE workspace_id = '<WORKSPACE_UUID>'
  AND source_timestamp >= NOW() - INTERVAL '<N> days'
  AND raw_text IS NOT NULL
  AND is_deleted = false
ORDER BY source_timestamp;

ROLLBACK;
SQL
```

**Pattern B — SSH + docker exec to remote container (no local psql needed)**

```bash
ssh user@<BASTION_OR_DB_HOST> \
  'docker exec -i <POSTGRES_CONTAINER> psql -U <DB_USER> -d <DB_NAME> -A -t -q' \
  <<'SQL' > /tmp/raw_events.jsonl
BEGIN READ ONLY;

SELECT json_build_object(
  'id', id::text,
  'raw_text', raw_text,
  'ts', extract(epoch from source_timestamp)::bigint::text,
  'channel_id', channel_id,
  'actor', actor_user_id,
  'thread_ts', thread_ts,
  'source_type', source_type,
  'source_id', source_id
)::text
FROM l0_events
WHERE workspace_id = '<WORKSPACE_UUID>'
  AND source_timestamp >= NOW() - INTERVAL '<N> days'
  AND raw_text IS NOT NULL
  AND is_deleted = false
ORDER BY source_timestamp;

ROLLBACK;
SQL
```

Replace placeholders:
- `<DB_USER>`, `<DB_NAME>`: database credentials (from 1Password / secrets manager; no password flag needed when the container trusts the role)
- `<DB_PASS>`: only used in Pattern A's connection string
- `<BASTION_OR_DB_HOST>`: SSH target
- `<POSTGRES_CONTAINER>`: Docker container name (e.g. `postgres`)
- `<WORKSPACE_UUID>`: target workspace UUID — find it with:
  ```bash
  # Find the right workspace UUID (look at the workspace_name column):
  #   psql -c "SELECT id, workspace_name FROM slack_workspaces ORDER BY installed_at;"
  # If the schema uses the generic workspaces table instead:
  #   psql -c "SELECT id, name FROM workspaces ORDER BY created_at;"
  ```
- `<N>`: number of days to pull (e.g. `14` for 2 weeks)

**Step 3: Verify the pull**

```bash
wc -l /tmp/raw_events.jsonl
head -1 /tmp/raw_events.jsonl | python3 -m json.tool
```

Expected output: a valid JSON object with `id`, `raw_text`, `ts`, `channel_id`, `actor` fields.

## Sanitize Procedure

```bash
uv run python scripts/sanitize_corpus.py \
  --input /tmp/raw_events.jsonl \
  --output tests/fixtures/bench/realistic_14d.jsonl \
  --company-name Globex \
  --seed 42 \
  --time-shift-days 365 \
  --mapping-out /tmp/realistic_14d.mapping.json
```

**Parameters:**

| Flag | Default | Description |
|------|---------|-------------|
| `--input` | (required) | Path to raw JSONL from the export step |
| `--output` | (required) | Destination path (must be gitignored — see Storage Policy) |
| `--company-name` | (required) | Replacement name for company references (e.g. `Globex`) |
| `--seed` | `42` | Deterministic random seed for faker. Use the same seed each time for byte-identical output |
| `--time-shift-days` | `365` | Shift all timestamps back by N days. Relative intervals are preserved exactly |
| `--mapping-out` | (optional) | Write `{real -> fake}` mapping to a JSON file for reversibility audit |

**Exit codes:**

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Secret pattern detected — **no output written**. Inspect the error, fix the source, re-run |
| 2 | Malformed input (JSON parse error or missing required field) |
| 3 | I/O error (file not found, permission denied) |

If the script exits 1, it reports which line numbers and pattern names matched.
Do NOT commit the raw file — investigate with your security team.

## Verification Checklist

After sanitization, run these checks before using the fixture:

```bash
# 1. Company name absent (ticketscloud / tickets cloud / tcloud)
grep -i "ticketscloud\|tickets cloud\|tcloud" tests/fixtures/bench/realistic_14d.jsonl \
  && echo "FAIL: company name still present" || echo "OK: company name absent"

# 2. No real Slack user mentions (non-FAKE)
grep -E '<@U[A-Z0-9]+>' tests/fixtures/bench/realistic_14d.jsonl \
  | grep -v '_FAKE_' \
  && echo "FAIL: real user mentions present" || echo "OK: no real user mentions"

# 3. No raw email addresses at company domain (adjust domain)
grep -E '[a-zA-Z0-9._%+-]+@company\.internal' tests/fixtures/bench/realistic_14d.jsonl \
  && echo "FAIL: company emails present" || echo "OK: no company emails"

# 3b. Broad email scan across all lines (requires a dot in the domain to avoid
#     false positives from Slack @here / @nickname mention patterns).
#     Review any hits — @example.com addresses are synthetic and safe to ignore.
grep -E '[a-zA-Z0-9._%+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}' \
  tests/fixtures/bench/realistic_14d.jsonl \
  | grep -v '@example\.com' \
  && echo "REVIEW: possible real emails found above" || echo "OK: no suspicious emails"

# 4. No secret patterns
grep -E 'sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|aws_secret_access_key' \
  tests/fixtures/bench/realistic_14d.jsonl \
  && echo "FAIL: secrets still present" || echo "OK: no secrets"

# 5. Verify JSON validity of all lines
python3 -c "
import json, sys
with open('tests/fixtures/bench/realistic_14d.jsonl') as f:
    for i, line in enumerate(f, 1):
        if line.strip():
            json.loads(line)
print(f'OK: all lines valid JSON')
"

# 6. Spot-check a few records manually
head -5 tests/fixtures/bench/realistic_14d.jsonl | python3 -m json.tool
```

## Next: run the bench

Once the fixture is in place and verified, run the bench harness against it:

```bash
set -a; source <repo-root>/.env; set +a
export ANTHROPIC_API_KEY="$ALAYA_ANTHROPIC_API_KEY"

just bench --fixture realistic_14d --timeout-seconds 1800
# or for fast iteration:
just bench --fixture realistic_3d --timeout-seconds 1800
```

Output lands in `bench_results/<DATE>-<SHA>/`. Read `summary.md` for the headline numbers.

## Storage Policy

| File | Location | Policy |
|------|----------|--------|
| Raw export (`/tmp/raw_events.jsonl`) | Local disk only | **Delete immediately** after sanitization succeeds |
| Mapping file (`*.mapping.json`) | Local disk only | Never commit; delete after audit |
| Sanitized fixture (`realistic*.jsonl`, `*.local.jsonl`) | `tests/fixtures/bench/` | Gitignored (see `.gitignore` in that directory) |

The `.gitignore` at `tests/fixtures/bench/` ignores:

```
realistic*.jsonl
*.local.jsonl
*.mapping.json
```

This means the sanitized output is safe to place in the fixtures directory for local bench
runs without risk of accidentally committing it.

## Notes on thread_ts

Production Slack data shows 0 thread reply events currently (connector imports flat).
The `thread_ts` field is supported by `sanitize_corpus.py` — if present, it is time-shifted
identically to `ts`. The field is passed through to the output record as-is.

If real thread data appears in the future, `scripts/bench_ingest.py` may need a 1-line update
to forward `thread_ts` to the `/ingest/text` API endpoint. No changes to the bench harness
are needed for this sanitizer.

## Troubleshooting

**Script hangs on large input:**
spaCy NER runs per-record on the full message text. For very large corpora (>10k events),
this can take several minutes. The script prints a summary line to stderr on completion.

**Secret detected (exit 1):**
The raw export contains a leaked credential. Do NOT proceed — contact your security team.
The script deliberately halts and writes no output when this happens.

**spaCy model warning:**
If you see `warn: spaCy model 'en_core_web_sm' not installed`, run:
```bash
uv run python -m spacy download en_core_web_sm
uv run python -m spacy download ru_core_news_sm
```
Without these models, person names in message text are not replaced, but all other
patterns (IDs, emails, phones, URLs, company name) are still sanitized.
