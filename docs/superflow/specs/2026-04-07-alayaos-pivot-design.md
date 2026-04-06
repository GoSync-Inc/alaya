# AlayaOS — Technical Design Specification

**Date:** 2026-04-07
**References:** [Product Brief](./2026-04-07-alayaos-pivot-brief.md)
**Status:** Draft (rev 2 — post dual-model review)

---

## 1. Overview

AlayaOS is an open-source (BSL) self-hostable corporate intelligence platform. It ingests data from work tools (Slack, GitHub, Linear, etc.), extracts structured entities and temporal claims via LLM, organizes them into a browsable knowledge tree, and exposes everything through CLI, MCP, and REST API for AI agents.

This spec covers the architecture of a **new repository** (`alayaos`), designed from scratch as a platform — not a Slack bot. Valuable code from the existing Alaya codebase is cherry-picked where noted.

---

## 2. Repository Structure

```
alayaos/
├── packages/
│   ├── core/                    # Layer 1: Brain
│   │   ├── alayaos/
│   │   │   ├── models/          # SQLModel/SQLAlchemy table definitions
│   │   │   ├── extraction/      # LLM extraction pipeline
│   │   │   ├── consolidation/   # Merge, dedup, staleness
│   │   │   ├── search/          # Vector + FTS + entity graph
│   │   │   ├── ontology/        # Dynamic type registry
│   │   │   ├── knowledge_tree/  # L3 Book layer + markdown renderer
│   │   │   ├── acl/             # Access control
│   │   │   └── config/          # Settings, model registry
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   ├── connectors/              # Layer 2: Source connectors
│   │   ├── alayaos_connectors/
│   │   │   ├── slack/
│   │   │   ├── github/
│   │   │   ├── linear/
│   │   │   ├── telegram/
│   │   │   ├── notion/
│   │   │   ├── google/
│   │   │   ├── email/
│   │   │   └── base.py          # Connector interface
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   ├── cli/                     # CLI tool
│   │   ├── alayaos_cli/
│   │   │   ├── commands/        # init, connect, ingest, memory, ask, entity, type
│   │   │   └── main.py          # Typer app
│   │   └── pyproject.toml
│   │
│   ├── api/                     # REST API + MCP Server
│   │   ├── alayaos_api/
│   │   │   ├── routes/          # FastAPI route modules
│   │   │   ├── mcp/             # MCP server (FastMCP)
│   │   │   ├── auth/            # API key auth, RBAC
│   │   │   └── webhooks/        # Outbound webhook dispatch
│   │   ├── tests/
│   │   └── pyproject.toml
│   │
│   └── web/                     # Web UI (future, separate sprint)
│       ├── src/
│       └── package.json
│
├── docker-compose.yml           # One-liner deploy
├── docker-compose.dev.yml       # Dev overlay (hot reload, debug)
├── docker-compose.local-llm.yml # Ollama/vLLM overlay
├── Dockerfile                   # Multi-stage, non-root, slim
├── pyproject.toml               # Workspace root (uv workspaces)
├── uv.lock
├── LICENSE                      # BSL 1.1
├── CLAUDE.md                    # AI agent instructions
└── README.md
```

**Build system:** uv workspaces (monorepo). Each package is independently installable but shares the lock file.

---

## 3. Data Model

### 3.1 Core Tables

Cherry-picked and evolved from existing Alaya `l0_events`, `l1_entities`, `l1_relations`.

#### Workspaces

```sql
CREATE TABLE workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    settings JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### L0 Events (immutable event log)

```sql
CREATE TABLE l0_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    source_type TEXT NOT NULL,         -- 'slack', 'github', 'linear', 'email', 'manual', 'api'
    source_id TEXT,                     -- external ID (message ts, commit sha, issue id)
    content_hash TEXT NOT NULL,         -- SHA-256 for dedup
    raw_text TEXT NOT NULL,
    actor_external_id TEXT,            -- who generated this event
    mentioned_external_ids TEXT[],
    event_kind TEXT,                    -- 'message', 'commit', 'issue_update', 'document', 'meeting_transcript'
    metadata JSONB DEFAULT '{}',       -- source-specific metadata
    access_level TEXT DEFAULT 'public', -- public, channel, private, restricted
    access_context TEXT,               -- channel_id, dm_pair, etc.
    occurred_at TIMESTAMPTZ,           -- when event actually happened (may differ from created_at)
    is_extracted BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, source_type, source_id)  -- idempotency: same source event = same row
);

CREATE INDEX idx_l0_workspace_created ON l0_events(workspace_id, created_at DESC);
CREATE INDEX idx_l0_source ON l0_events(workspace_id, source_type, source_id);
CREATE INDEX idx_l0_not_extracted ON l0_events(workspace_id) WHERE NOT is_extracted;
-- content_hash used for content-level dedup within same source_type (not unique constraint)
```

#### Entity Type Definitions (dynamic ontology)

```sql
CREATE TABLE entity_type_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,                -- 'person', 'project', 'legal_contract'
    display_name TEXT,                 -- 'Legal Contract'
    description TEXT,                  -- LLM uses this for classification
    parent_type_id UUID REFERENCES entity_type_definitions(id),  -- inheritance FK
    field_schema JSONB DEFAULT '{}',   -- JSON Schema for entity data field
    is_core BOOLEAN DEFAULT FALSE,     -- shipped with product
    is_confirmed BOOLEAN DEFAULT TRUE, -- false for LLM-suggested (draft)
    suggested_by TEXT,                 -- 'system', 'user', 'llm'
    usage_count INTEGER DEFAULT 0,     -- how many entities of this type exist
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, name)
);
```

**Core types** (seeded on workspace creation):
- `person` — people (employees, contacts)
- `team` — organizational units
- `project` — projects, initiatives
- `task` — action items, todos, tickets
- `decision` — agreed-upon choices
- `document` — docs, pages, specs
- `event` — meetings, milestones, incidents
- `organization` — companies, clients, partners

#### L1 Entities

```sql
CREATE TABLE l1_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    entity_type_id UUID NOT NULL REFERENCES entity_type_definitions(id),  -- FK to type registry
    name TEXT NOT NULL,
    description TEXT,
    data JSONB DEFAULT '{}',           -- type-specific structured data
    aliases TEXT[] DEFAULT '{}',       -- alternative names for matching
    access_level TEXT DEFAULT 'public',
    access_context TEXT,
    is_deleted BOOLEAN DEFAULT FALSE,  -- soft delete
    version INTEGER DEFAULT 1,         -- optimistic concurrency
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_l1_workspace_type ON l1_entities(workspace_id, entity_type_id) WHERE NOT is_deleted;
CREATE INDEX idx_l1_name_trgm ON l1_entities USING gin(name gin_trgm_ops);

-- Normalized external IDs (replaces JSONB external_ids)
CREATE TABLE entity_external_ids (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES l1_entities(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,            -- 'slack', 'github', 'linear'
    external_id TEXT NOT NULL,
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    UNIQUE(workspace_id, provider, external_id)
);

CREATE INDEX idx_ext_ids_entity ON entity_external_ids(entity_id);
CREATE INDEX idx_ext_ids_lookup ON entity_external_ids(workspace_id, provider, external_id);
```

#### L1 Relations

```sql
CREATE TABLE l1_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    source_entity_id UUID NOT NULL REFERENCES l1_entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES l1_entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,       -- dynamic: 'member_of', 'owns', 'blocks', etc.
    data JSONB DEFAULT '{}',
    confidence FLOAT DEFAULT 1.0,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,              -- NULL = still active
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Normalized provenance for relations (replaces UUID[] source_event_ids)
CREATE TABLE relation_sources (
    relation_id UUID NOT NULL REFERENCES l1_relations(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES l0_events(id),
    PRIMARY KEY (relation_id, event_id)
);
```

#### L2 Claims (NEW — temporal facts with provenance)

```sql
CREATE TABLE l2_claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    entity_id UUID NOT NULL REFERENCES l1_entities(id) ON DELETE CASCADE,
    predicate TEXT NOT NULL,            -- 'deadline', 'status', 'budget', 'owner', 'decision'
    value TEXT NOT NULL,                -- the fact value
    value_type TEXT DEFAULT 'text',     -- 'text', 'date', 'number', 'boolean', 'entity_ref'
    value_ref UUID,                     -- if value_type='entity_ref', points to another entity
    level TEXT DEFAULT 'explicit',     -- 'explicit' (from text), 'deductive' (inferred), 'inductive' (pattern), 'contradiction'
    premise_claim_ids UUID[],           -- for deductive/inductive: which claims led to this inference
    confidence FLOAT DEFAULT 0.8,
    source_summary TEXT,                -- human-readable source context
    observed_at TIMESTAMPTZ NOT NULL,   -- when we first observed this fact (message timestamp)
    estimated_start TIMESTAMPTZ,        -- optional: when fact actually became true (may predate observation)
    valid_to TIMESTAMPTZ,              -- NULL = still active
    supersedes UUID REFERENCES l2_claims(id), -- which previous claim this replaces
    status TEXT DEFAULT 'active',      -- 'active', 'superseded', 'retracted', 'disputed'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Normalized provenance for claims (replaces UUID[] source_event_ids)
CREATE TABLE claim_sources (
    claim_id UUID NOT NULL REFERENCES l2_claims(id) ON DELETE CASCADE,
    event_id UUID NOT NULL REFERENCES l0_events(id),
    PRIMARY KEY (claim_id, event_id)
);

CREATE INDEX idx_l2_entity ON l2_claims(entity_id, predicate) WHERE status = 'active';
CREATE INDEX idx_l2_workspace ON l2_claims(workspace_id, created_at DESC);
```

#### L3 Knowledge Tree Nodes

```sql
CREATE TABLE l3_tree_nodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    parent_id UUID REFERENCES l3_tree_nodes(id),
    path TEXT NOT NULL,                 -- 'projects/alpha/decisions'
    title TEXT NOT NULL,
    node_type TEXT NOT NULL,            -- 'section', 'entity_page', 'summary', 'index'
    content_markdown TEXT,              -- pre-rendered markdown
    source_entity_id UUID REFERENCES l1_entities(id),  -- for entity_page nodes
    staleness_score FLOAT DEFAULT 0.0, -- 0=fresh, 1=stale
    last_rebuilt TIMESTAMPTZ,
    sort_order INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, path)
);

CREATE INDEX idx_l3_parent ON l3_tree_nodes(workspace_id, parent_id);
CREATE INDEX idx_l3_path ON l3_tree_nodes(workspace_id, path);
```

#### Vector Chunks (for semantic search)

```sql
CREATE TABLE vector_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    source_type TEXT NOT NULL,         -- 'l0_event', 'l1_entity', 'l2_claim', 'l3_node'
    source_id UUID NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1024),            -- dimension depends on model
    metadata JSONB DEFAULT '{}',
    access_level TEXT DEFAULT 'public',
    access_context TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_vector_hnsw ON vector_chunks
    USING hnsw(embedding vector_cosine_ops) WITH (m=16, ef_construction=64);
```

#### Audit Log

```sql
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL,
    actor_type TEXT NOT NULL,          -- 'user', 'api_key', 'system', 'agent'
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,              -- 'entity.create', 'claim.create', 'search.execute', 'export'
    resource_type TEXT,
    resource_id UUID,
    details JSONB,
    ip_address INET,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- Immutable: no UPDATE/DELETE allowed via RLS policy
```

#### API Keys

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,
    key_hash TEXT NOT NULL,            -- SHA-256 of the key
    key_prefix TEXT NOT NULL,          -- 'ala_live_abc' (first 12 chars for identification)
    scopes TEXT[] NOT NULL,            -- ['read', 'write', 'admin']
    person_id UUID REFERENCES l1_entities(id), -- optional: person-bound key
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 3.2 Access Control Model

#### Principals & Memberships

```sql
CREATE TABLE workspace_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    person_entity_id UUID REFERENCES l1_entities(id),  -- linked L1 Person
    email TEXT,                         -- for matching before entity linking
    role TEXT DEFAULT 'member',        -- 'admin', 'member', 'viewer'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(workspace_id, email)
);

CREATE TABLE access_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL,                -- 'engineering-team', 'slack-channel-general'
    source TEXT,                       -- 'slack_channel', 'manual', 'team_entity'
    source_id TEXT,                    -- channel_id, team_entity_id
    UNIQUE(workspace_id, name)
);

CREATE TABLE access_group_members (
    group_id UUID NOT NULL REFERENCES access_groups(id) ON DELETE CASCADE,
    member_id UUID NOT NULL REFERENCES workspace_members(id) ON DELETE CASCADE,
    PRIMARY KEY (group_id, member_id)
);
```

#### Resource Grants (normalized per-resource visibility)

```sql
CREATE TABLE resource_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id),
    resource_type TEXT NOT NULL,        -- 'l0_event', 'l1_entity', 'l2_claim'
    resource_id UUID NOT NULL,
    grantee_type TEXT NOT NULL,         -- 'group', 'member', 'everyone'
    grantee_id UUID,                    -- access_groups.id or workspace_members.id (NULL for 'everyone')
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_grants_resource ON resource_grants(resource_type, resource_id);
CREATE INDEX idx_grants_grantee ON resource_grants(grantee_type, grantee_id);
```

#### ACL Policy Evaluation

Access to entities, claims, events, and search results:

1. `access_level = 'public'` → grant with `grantee_type='everyone'` (auto-created on ingestion)
2. `access_level = 'channel'` → grant to the corresponding `access_group` (Slack channel → group)
3. `access_level = 'private'` → grants to specific `workspace_members` (DM participants)
4. `access_level = 'restricted'` → grant only to workspace admins group

All search, export, and API responses JOIN through `resource_grants` for filtering. Knowledge tree markdown rendering respects ACL — restricted content is redacted or omitted. Vector search includes grant check in WHERE clause.

#### Inbound Webhook Security

Inbound webhooks (`POST /api/v1/ingest/webhook`) require:
1. Bearer API key (existing)
2. Optional HMAC-SHA256 signature verification (`X-Alaya-Signature` header)
3. Timestamp-based replay protection (reject requests older than 5 minutes)

### 3.3 PostgreSQL RLS (Row-Level Security)

Enabled for all workspace-scoped tables. Application sets `app.workspace_id` session variable:

```sql
ALTER TABLE l0_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE l0_events FORCE ROW LEVEL SECURITY;
CREATE POLICY workspace_isolation ON l0_events
    USING (workspace_id = current_setting('app.workspace_id')::uuid);

-- Repeat for: l1_entities, l1_relations, l2_claims, l3_tree_nodes,
-- vector_chunks, api_keys, entity_type_definitions
```

---

## 4. Extraction Pipeline

### 4.1 Flow (staged pipeline with durable jobs)

```
L0 Events (new batch)
    ↓
Stage 1: Preprocessing (no LLM)
    - Source-specific parsing (Slack markdown → plain text, etc.)
    - Chunking for long documents/transcripts (sliding window)
    - Dedup check (content_hash within source_type)
    ↓
Stage 2: Extraction (LLM, durable TaskIQ job with retry + DLQ)
    - Reads: current ontology + existing entity names/aliases
    - Processes chunks in batches (prompt caching for shared context)
    - Outputs: entities, relations, claims
    - Note: LLM-suggested ontology types are v1.1 (deferred from v1 hot path)
    ↓
Stage 3: Resolution (no LLM)
    - Entity matching (fuzzy name + external_id + alias)
    - Claim conflict resolution (see 4.4)
    - Dedup against existing entities
    ↓
Stage 4: Write (atomic transaction)
    - L1 entities + relations (create/update)
    - L2 claims (create, handle supersession)
    - Provenance links (claim_sources, relation_sources)
    ↓
Stage 5: Enrichment (async, periodic)
    - Vector embedding (batch, async)
    - Knowledge tree rebuild (on-demand, not cron — see 5.2)
    - Dirty-entity incremental enrichment
```

Each stage is a separate TaskIQ job with:
- Retry policy (3 retries, exponential backoff)
- Dead Letter Queue for persistent failures
- Idempotency (same input = same output, safe to re-run)
- Progress tracking via Redis (`extraction:{workspace}:{batch_id}:status`)

### 4.2 Extraction Prompt Design

The extraction prompt receives:
1. Raw text from L0 event
2. Current ontology (entity_type_definitions for this workspace)
3. Existing entity names + aliases (for matching, not creation of duplicates)
4. Instructions to output structured JSON

Output schema:
```json
{
  "entities": [
    {
      "name": "Project Alpha",
      "type": "project",
      "aliases": ["Alpha", "proj-alpha"],
      "external_ids": {},
      "data": {"status": "active"}
    }
  ],
  "relations": [
    {
      "source": "Alice Smith",
      "target": "Project Alpha",
      "type": "owns",
      "confidence": 0.9
    }
  ],
  "claims": [
    {
      "entity": "Project Alpha",
      "predicate": "deadline",
      "value": "2026-04-15",
      "value_type": "date",
      "confidence": 0.85,
      "source_summary": "Alice mentioned in #engineering: 'Alpha deadline is April 15'"
    }
  ],
  // v1.1: "suggested_types" array (LLM proposes new entity types)
}
```

### 4.4 Claim Conflict Resolution

When multiple claims for the same `(entity_id, predicate)` arrive:

1. **Different timestamps** → later `observed_at` supersedes earlier (standard temporal chain)
2. **Same timestamp, different sources** → higher-confidence claim is `status='active'`, lower-confidence claim is `status='disputed'`. If confidences are equal (within 0.05), both are `disputed`. User can resolve via API/CLI (`PATCH /api/v1/claims/{id}` with `status=active|retracted`).
3. **Same source, updated** → supersession chain (`supersedes` FK)

Consolidation agent (periodic, configurable — default daily):
- Merges duplicate entities (fuzzy name + alias matching across types)
- Resolves disputed claims older than N days (configurable) by picking highest-confidence
- Marks stale entities (no new claims in 30+ days) with `staleness_score`
- Detects patterns: deadline drift (claim supersession on `deadline` predicate), ownerless work (tasks without `owner` claims)
- Pattern results stored as special claims with `predicate='_pattern_detected'`

### 4.5 LLM Provider Strategy — Model-Agnostic Architecture

**Principle:** One interface, rich implementations. No lowest common denominator.

#### Interface (~20 LOC)

```python
class LLMServiceInterface(ABC):
    @abstractmethod
    async def complete(self, prompt: str, system: str | None, ...) -> LLMResponse: ...

    @abstractmethod
    async def complete_json(self, prompt: str, response_model: type[T], ...) -> tuple[T, LLMUsage]: ...
```

#### Adapters (~100-200 LOC each)

| Adapter | Provider-specific features | Structured output |
|---------|--------------------------|-------------------|
| `AnthropicAdapter` | Prompt caching (`cache_control`), extended thinking, system_blocks | Native constrained decoding + JSON fallback |
| `OpenAIAdapter` | Reasoning effort, response_format | Native `response_format: type[BaseModel]` |
| `OllamaAdapter` | OpenAI-compatible API (`base_url` swap) | JSON instruction in system prompt + Pydantic validation + retry |

`OllamaAdapter` also works for **vLLM** — same OpenAI-compatible API with different `base_url`.

#### Factory + Config

```python
# Config (settings.py):
EXTRACTION_LLM_PROVIDER: str = "anthropic"  # anthropic | openai | ollama | vllm
EXTRACTION_LLM_MODEL: str = "claude-haiku-4-5"
EXTRACTION_LLM_BASE_URL: str = ""           # only for ollama/vllm

# Factory:
def create_llm_service(provider, model, **kwargs) -> LLMServiceInterface:
    match provider:
        case "anthropic": return AnthropicAdapter(model=model, ...)
        case "openai":    return OpenAIAdapter(model=model, ...)
        case "ollama" | "vllm": return OllamaAdapter(model=model, base_url=..., ...)
```

#### Prompt format handling

Prompts are Python functions with `provider` parameter:
- Anthropic: XML tags (`<instructions>`, `<context>`, `<entities>`)
- Others: Markdown headers (`## Instructions`, `## Context`)

#### Local LLM recommendations

| Task | Minimum model | RAM | Quality vs Claude |
|------|--------------|-----|------------------|
| Extraction | Qwen 3 14B | 10GB | ~80% |
| Scoring | Qwen 3 7B | 5GB | ~85% |
| Q&A | Mistral Small 3.2 24B | 16GB | ~75% |

#### What NOT to do
- No LiteLLM for extraction hot path (supply chain risk, performance overhead)
- No LangChain-style over-abstraction (6 layers for 1 LLM call)
- No stripping Anthropic features (cache saves 90% cost)

Cherry-pick from existing Alaya: `LLMServiceInterface`, `AnthropicLLMService`, `OpenAILLMService`, `model_registry.py` (all reference, adapt for new architecture).

---

## 5. Knowledge Tree (L3)

### 5.1 Tree Structure

Default tree template (auto-created on workspace init):

```
{workspace}/
├── _index.md              # Company overview + table of contents
├── people/
│   ├── _index.md          # Org chart, team structure
│   └── {person-slug}.md   # Per-person page
├── teams/
│   ├── _index.md
│   └── {team-slug}.md
├── projects/
│   ├── _index.md          # Active projects dashboard
│   └── {project-slug}/
│       ├── summary.md
│       ├── decisions.md   # Decisions related to this project
│       ├── risks.md       # Active risks and blockers
│       └── timeline.md    # Claim history as timeline
├── decisions/
│   ├── _index.md          # Recent decisions log
│   └── {decision-slug}.md
├── this-week.md           # Auto-generated weekly summary
└── patterns.md            # Detected patterns (deadline drift, etc.)
```

### 5.2 Tree Rebuilding (on-demand + dirty-flag, not periodic cron)

Tree nodes are rebuilt **lazily** when requested, not on a fixed cron:

1. When extraction writes/updates an entity or claim → mark affected `l3_tree_nodes` as dirty (`staleness_score = 1.0`)
2. When `alaya memory show <path>` or `GET /api/v1/tree/<path>` is called:
   - If node is clean (staleness < 0.5) → return cached `content_markdown`
   - If node is dirty → re-render from L1 entities + L2 claims, update cache, return
3. `alaya memory export` triggers full rebuild of all dirty nodes before export
4. Optional background job (`rebuild_dirty_nodes`) can be enabled for high-traffic deployments

This avoids wasting LLM/compute on rebuilding nodes nobody reads, while ensuring freshness when actually accessed.

### 5.3 Markdown Rendering

Each entity type has a rendering template. Example for `project`:

```markdown
# {name}

**Status:** {claim:status} | **Owner:** {claim:owner} | **Deadline:** {claim:deadline}

## Summary
{description}

## Key Facts
{for claim in active_claims}
- **{claim.predicate}**: {claim.value}
  _Source: {claim.source_summary} ({claim.observed_at})_
{endfor}

## Decisions
{for decision in related_decisions}
- [{decision.name}](../decisions/{decision.slug}.md) — {decision.description}
{endfor}

## Risks & Blockers
{for claim in claims where predicate in ('blocker', 'risk', 'blocked_by')}
- {claim.value} (since {claim.observed_at})
{endfor}

## Timeline
{for claim in all_claims order by valid_from desc}
- {claim.observed_at}: {claim.predicate} = {claim.value}
{endfor}
```

### 5.4 Export

`alaya memory export ./output/` generates the full tree as markdown files on disk. AI agents can then read them as regular files.

`alaya memory show projects/alpha` returns the rendered markdown for a single node via API.

---

## 6. Connectors Architecture

### 6.1 Connector Interface

```python
# packages/connectors/alayaos_connectors/base.py

class ConnectorConfig(BaseModel):
    """Per-workspace connector configuration."""
    connector_type: str
    credentials: dict          # encrypted at rest
    settings: dict = {}        # connector-specific settings
    last_sync_cursor: str | None = None

class BaseConnector(ABC):
    @abstractmethod
    async def authenticate(self, config: ConnectorConfig) -> bool: ...

    @abstractmethod
    async def ingest(
        self, config: ConnectorConfig, since: datetime | None = None
    ) -> AsyncIterator[L0EventCreate]: ...

    @abstractmethod
    async def test_connection(self, config: ConnectorConfig) -> bool: ...

    @property
    @abstractmethod
    def connector_type(self) -> str: ...

    @property
    @abstractmethod
    def required_credentials(self) -> list[str]: ...
```

### 6.2 Initial Connectors

Cherry-pick from existing Alaya:

**v1.0 connectors:**

| Connector | Source | Notes |
|-----------|--------|-------|
| Slack | `adapters/slack/` (reference) | OAuth flow, message ingestion, channel sync. Redesign needed (decouple from Bolt) |
| GitHub | `adapters/oauth/providers/github.py` (reference) | OAuth PKCE exists, need webhook receiver for events |
| Linear | `adapters/oauth/providers/linear.py` (reference) | OAuth, issue sync via webhooks |
| Generic webhook | NEW | Any source that can POST JSON |
| Manual (text/file) | NEW | CLI `alaya ingest text/file` |

**v1.1 connectors (deferred):**

| Connector | Notes |
|-----------|-------|
| Telegram | Ingestion path from existing bot code |
| Notion | Page content extraction |
| Google Workspace | Calendar, Docs, Drive |
| Email | IMAP/SMTP connector |

### 6.3 Webhook Ingestion (generic)

For any source that can send webhooks:

```
POST /api/v1/ingest/webhook
Authorization: Bearer ala_live_...
Content-Type: application/json

{
  "source_type": "custom",
  "source_id": "jira-PROJ-123",
  "text": "Issue PROJ-123 moved to Done by Alice",
  "actor": "alice@company.com",
  "metadata": {"jira_key": "PROJ-123", "status": "Done"},
  "timestamp": "2026-04-07T10:00:00Z"
}
```

---

## 7. CLI Design

### 7.1 Framework

**Typer** (by FastAPI creator) + **Rich** for formatting.

```bash
pip install alayaos-cli
# or
uv tool install alayaos-cli
```

### 7.2 Command Reference

```
alaya init                              # Configure server URL + API key
alaya login                             # Interactive auth
alaya status                            # Server health + workspace info

# Connectors
alaya connect slack                     # OAuth flow (opens browser)
alaya connect github
alaya connect list                      # Show connected sources
alaya connect test slack                # Test connection health

# Ingestion
alaya ingest --all --days 30            # Ingest from all connectors
alaya ingest slack --channel general    # Specific source
alaya ingest file report.pdf            # Upload document
alaya ingest text "Key decision: ..."   # Manual fact entry

# Memory (knowledge tree)
alaya memory tree                       # Show tree table of contents
alaya memory show projects/alpha        # Render specific node
alaya memory search "API migration"     # Hybrid search
alaya memory export ./output/           # Export full tree as markdown files
alaya memory pull                       # Update local context files (CLAUDE.md, etc.)
alaya memory push "learned X about Y"  # Push fact from local agent back to Brain

# Ask (natural language)
alaya ask "who decided to use Redis?"
alaya ask "what are current blockers?"

# Entities
alaya entity list                       # All entities
alaya entity list --type project        # Filter by type
alaya entity get <id>                   # Details + claims
alaya entity timeline <id>             # Claim history

# Types (dynamic ontology)
alaya type list                         # Current ontology
alaya type create <name> --desc "..."  # Create manually
# v1.1: alaya type suggest / alaya type confirm (LLM-suggested types)

# Admin
alaya config show                       # Current configuration
alaya config set extraction.model claude-sonnet-4-6
alaya key create --name "ci-bot" --scopes read
alaya key list
alaya key revoke <prefix>
```

### 7.3 Bidirectional Agent Sync

**Pull (read from Brain):**
- `alaya memory pull --format claude-md` → generates context file for Claude Code
- Hook integration: `.claude/hooks/session-start.sh` calls `alaya memory pull`
- Returns: company overview, relevant project context, recent decisions

**Push (write to Brain) — v1: manual only:**
- `alaya memory push "We decided to use Redis for caching"` → creates L0 event + triggers extraction
- `alaya memory push --file ./meeting-notes.md` → ingests document
- MCP tool: `memory_push(fact)` → same as CLI push

**Auto-sync (v1.1 — deferred from v1):**
- File watcher daemon that monitors local `.claude/` and project docs for changes
- Git hook integration (post-commit → push changed docs to Brain)
- Deferred because: requires careful design to avoid noise, privacy controls, and conflict resolution

### 7.4 Agent Integration

For Claude Code / Codex / Perplexity — one-liner setup:

```bash
# Add to CLAUDE.md or .cursorrules:
# "Run `alaya memory pull` at session start for company context"

# Or as a hook (.claude/hooks/session-start.sh):
alaya memory pull --format claude-md > .claude/context/company.md
```

---

## 8. API & MCP

### 8.1 REST API Endpoints

```
# Auth
POST   /api/v1/auth/keys              # Create API key
GET    /api/v1/auth/keys              # List keys
DELETE /api/v1/auth/keys/{prefix}     # Revoke

# Entities
GET    /api/v1/entities               # List (cursor pagination, type filter)
GET    /api/v1/entities/{id}          # Get with active claims
POST   /api/v1/entities               # Create
PATCH  /api/v1/entities/{id}          # Update (optimistic concurrency)
DELETE /api/v1/entities/{id}          # Soft delete

# Claims
GET    /api/v1/entities/{id}/claims   # Claims for entity
POST   /api/v1/claims                 # Create claim
GET    /api/v1/claims/{id}/history    # Supersession chain

# Search
POST   /api/v1/search                 # Hybrid search (vector + FTS + entity)
POST   /api/v1/ask                    # Natural language Q&A (LLM)

# Knowledge Tree
GET    /api/v1/tree                   # Tree structure (TOC)
GET    /api/v1/tree/{path}            # Node content (markdown)
POST   /api/v1/tree/export            # Export full tree

# Ingestion
POST   /api/v1/ingest/webhook         # Generic webhook ingestion
POST   /api/v1/ingest/document        # Document upload
POST   /api/v1/ingest/text            # Manual text ingestion

# Types
GET    /api/v1/types                   # List type definitions
POST   /api/v1/types                   # Create type
PATCH  /api/v1/types/{name}           # Update (confirm, modify schema)
# v1.1: GET /api/v1/types/suggested   # LLM-suggested types

# Connectors
GET    /api/v1/connectors              # List connected sources
POST   /api/v1/connectors/{type}/auth  # Start OAuth flow
DELETE /api/v1/connectors/{type}       # Disconnect

# Webhooks (outbound)
POST   /api/v1/webhooks                # Subscribe
GET    /api/v1/webhooks                # List subscriptions
DELETE /api/v1/webhooks/{id}           # Unsubscribe

# GDPR
POST   /api/v1/gdpr/export            # Export all user data
POST   /api/v1/gdpr/forget            # Delete all user data

# Health
GET    /health/live                    # Liveness
GET    /health/ready                   # Readiness (DB + Redis)
```

### 8.2 MCP Server Tools

```
memory_tree()             — browse hierarchical knowledge (TOC)
memory_show(path)         — get specific node as markdown
memory_search(query)      — hybrid search
memory_ask(question)      — natural language Q&A
memory_push(fact)         — write fact back to Brain

entity_list(type?, query?) — list entities
entity_get(id)            — entity details with claims
entity_create(type, name, data) — create entity
entity_timeline(id)       — claim history

type_list()               — current ontology
# v1.1: type_suggest(), get_digest()

ingest_text(text, source?) — manual ingestion
ingest_document(path)     — document ingestion
```

---

## 9. Security

### 9.1 Encryption

- **At rest**: LUKS for Docker volumes (documented for self-hosted). Application-level Fernet encryption for OAuth tokens and API key secrets.
- **In transit**: TLS 1.3 via Caddy reverse proxy (auto-cert).
- **Key rotation**: MultiFernet with primary + previous key support.

### 9.2 LLM Data Privacy

- **Data classification**: `access_level` on L0 events determines what can be sent to LLM.
- **RESTRICTED data**: never sent to external LLM API.
- **CONFIDENTIAL data** (DMs): sent only with explicit workspace opt-in.
- **Local LLM option**: `docker-compose.local-llm.yml` overlay with Ollama/vLLM.
- **PII redaction**: optional Presidio integration before extraction (configurable).

### 9.3 Auth & RBAC

- API keys with scope bundles: `read`, `write`, `admin`.
- Person-bound keys (optional): inherit ACL of the person.
- Rate limiting: per-key and per-workspace.
- Audit logging: all API requests logged to `audit_log` table.

### 9.4 Docker Hardening

- `python:3.13-slim` base, non-root user.
- `no-new-privileges: true`, `cap_drop: ALL`.
- Internal Docker network for DB/Redis (no port exposure).
- Secure-by-default entrypoint: reject default/empty passwords.
- Read-only root filesystem where possible.

---

## 10. Deployment

### 10.1 Docker Compose (self-hosted)

```yaml
services:
  migrate:
    build: .
    command: alembic upgrade head
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
    depends_on:
      postgres:
        condition: service_healthy
    networks: [internal]

  app:
    build: .
    ports: ["127.0.0.1:8000:8000"]
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER:-anthropic}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
    depends_on:
      migrate:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks: [internal, external]
    security_opt: ["no-new-privileges:true"]
    deploy:
      resources:
        limits: { memory: 1G }

  worker:
    build: .
    command: taskiq worker alayaos.tasks:broker
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379
      ENCRYPTION_KEY: ${ENCRYPTION_KEY}
      LLM_PROVIDER: ${LLM_PROVIDER:-anthropic}
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}
    depends_on:
      migrate:
        condition: service_completed_successfully
      redis:
        condition: service_healthy
    networks: [internal]
    security_opt: ["no-new-privileges:true"]

  scheduler:
    build: .
    command: taskiq scheduler alayaos.tasks:broker
    restart: unless-stopped
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      REDIS_URL: redis://:${REDIS_PASSWORD}@redis:6379
    depends_on:
      worker:
        condition: service_started
      redis:
        condition: service_healthy
    networks: [internal]
    security_opt: ["no-new-privileges:true"]

  postgres:
    image: pgvector/pgvector:0.8.0-pg17
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes: [postgres-data:/var/lib/postgresql/data]
    networks: [internal]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    security_opt: ["no-new-privileges:true"]

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes: [redis-data:/data]
    networks: [internal]
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    security_opt: ["no-new-privileges:true"]

  caddy:
    image: caddy:2-alpine
    ports: ["80:80", "443:443"]
    volumes: [caddy-data:/data, caddy-config:/config]
    networks: [internal, external]

networks:
  internal:
    internal: true
  external:

volumes:
  postgres-data:
  redis-data:
  caddy-data:
  caddy-config:
```

### 10.2 Quick Start

**Fast path (< 15 min, no OAuth required):**

```bash
git clone https://github.com/alaya-os/alayaos.git
cd alayaos
cp .env.example .env
# Edit .env: set ANTHROPIC_API_KEY (or skip for storage-only mode)
# ENCRYPTION_KEY auto-generated on first run if empty
docker compose up -d
pip install alayaos-cli
alaya init --server http://localhost:8000
alaya login                                    # creates admin key
alaya ingest text "Our team uses PostgreSQL, React, and Python"
alaya ingest file ./meeting-notes.md           # upload any document
alaya memory tree                              # see extracted knowledge!
```

**Full path (with Slack connector, ~20-30 min first time):**

```bash
# After fast path...
alaya connect slack                            # OAuth flow opens in browser
alaya ingest slack --channel general --days 30 # ingest Slack history
alaya memory tree                              # see enriched knowledge tree
```

**First-run UX:** When workspace has no data, `alaya memory tree` shows a guided onboarding message:
```
Your knowledge tree is empty. Get started:
  1. alaya ingest text "..."        — add a fact manually
  2. alaya ingest file report.pdf   — upload a document
  3. alaya connect slack            — connect Slack for automatic ingestion
  4. alaya connect github           — connect GitHub
```

**Graceful LLM degradation:** If `ANTHROPIC_API_KEY` is empty:
- Storage, search, and manual entity creation work normally
- Extraction pipeline is disabled (warning at startup)
- `alaya ask` returns error: "LLM not configured. Set ANTHROPIC_API_KEY to enable AI features."

---

## 11. Testing Strategy

| Type | Location | Uses LLM | When |
|------|----------|----------|------|
| Unit tests | `packages/*/tests/` | No | Every PR (CI) |
| Integration tests | `tests/integration/` | No | Every PR (CI) |
| Extraction quality tests | `tests/extraction/` | Yes | Before release |
| E2E tests | `tests/e2e/` | Yes | Before release |

CI: GitHub Actions — ruff + pyright + pytest on every PR.

---

## 12. Code Reuse from Existing Alaya

Classified as **direct port** (copy with minor changes) vs **reference** (rewrite inspired by existing logic).

### Direct Ports (copy + adapt)

| Module | Source path | Changes |
|--------|------------|---------|
| Token encryption | `adapters/security/encryption.py` | Add MultiFernet rotation |
| Distributed locks | `adapters/tasks/locks.py` | Keep as-is |
| Model registry | `config/model_registry.py` | Adapt model names |
| LLM config | `config/llm_config.py` | Keep |
| Prometheus metrics | `adapters/metrics/registry.py` | Rename metrics |
| L0 event model | `domain/entities/l0_event.py` | Add `occurred_at`, change dedup key |
| L1 entity model | `domain/entities/l1_entity.py` | Remove StrEnum, add `is_deleted` |
| API key auth | `adapters/api/auth.py` | Add UNIQUE constraints |

### Reference Modules (redesign, use as inspiration)

| Module | Source path | Why redesign needed |
|--------|------------|---------------------|
| Extraction pipeline | `business/extraction/crystallizer.py` | Current is one-shot per-event; need staged chunking pipeline |
| Entity matcher | `business/extraction/entity_matcher.py` | Tightly coupled to Slack user IDs; needs generic external_id resolution |
| Consolidation | `business/consolidation/` | Needs claims-aware merge + conflict resolution |
| Vector search | `adapters/database/vector_service.py` | Coupled to Slack message model; needs generic source_type |
| FTS search | `adapters/agents/tools/search.py` | Embedded in agent tool wrapper with Slack ACL; extract core logic |
| OAuth providers | `adapters/oauth/providers/*.py` | Each ~150 LOC of shared boilerplate; redesign with BaseConnector |
| TaskIQ broker/worker | `adapters/tasks/broker.py`, `worker.py` | Import side effects, Slack-specific startup; redesign clean |
| REST endpoints | `adapters/api/v1/` | Expand significantly for tree, claims, types, GDPR |
| MCP server | `adapters/mcp_server/` | Double the tool count, different auth model |
| Telegram connector | `adapters/telegram/` | Coupled to Alaya agent pipeline; extract ingestion-only path |

---

## 13. Scope Boundaries (v1.0 vs v1.1)

### v1.0 (MVP — ship this first)

- **Connectors**: Slack + GitHub + Linear + generic webhook + manual text/file ingest
- **Ontology**: Core types only (person, team, project, task, decision, document, event, organization). User-defined types via API/CLI.
- **Extraction**: Staged pipeline with chunking, retry, DLQ. Claims output.
- **Knowledge Tree**: On-demand rebuild, markdown export, CLI browse
- **CLI**: Full command set (init, connect, ingest, memory, ask, entity, type)
- **API**: REST + MCP with ACL-aware search/export
- **Agent sync**: Manual push (`alaya memory push`), pull hooks
- **Deployment**: Docker Compose with secure defaults, migrations, healthchecks

### v1.1 (deferred)

- LLM-suggested ontology types (draft → confirm flow)
- Auto-sync daemon (file watcher, git hooks for bidirectional agent sync)
- Additional connectors: Telegram, Notion, Google, email
- Web UI (React/Next.js)
- Paid workflow products (Decision Drift, Project Pulse, Morning Brief push)
- Proactive push delivery (Telegram, Slack, email)
- Python SDK package
- Graph database integration (if PostgreSQL relations prove insufficient)

### Out of scope (not planned)

- Mobile app
- Video/audio processing
- Real-time collaboration UI
- Custom LLM fine-tuning
- ERP/CRM deep integrations (Salesforce, SAP)

---

## 14. Open Questions

1. **Embedding model**: FastEmbed (local, free) vs Voyage/OpenAI (cloud, better quality)? → Recommend FastEmbed for v1 (zero external deps), configurable for cloud.
2. **Web UI framework**: Next.js App Router? Or simpler (plain React + Vite)? → Deferred to v1.1.
3. **Billing infrastructure**: Stripe? → Deferred to v1.1.

### Resolved (from review)

- **Graph DB**: No. Start with PostgreSQL relations. Add graph later if needed.
- **Dynamic ontology in v1**: Core types + user-defined only. LLM-suggested deferred to v1.1.
- **L3 tree rebuild**: On-demand (dirty flag), not cron.
- **Auto-sync**: Deferred to v1.1. Manual push only in v1.
- **Proactive push**: Deferred to v1.1. v1 is pull-only (CLI, API, MCP).
- **Cherry-pick vs rewrite**: Classified honestly. 8 direct ports, 10 reference-only modules.
