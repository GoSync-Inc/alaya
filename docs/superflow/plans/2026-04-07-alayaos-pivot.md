# AlayaOS Pivot — Master Plan

**Date:** 2026-04-07
**Status:** Phase 1 Complete — ready for sequential Superflow execution
**Artifacts:**
- Product Brief: `docs/superflow/specs/2026-04-07-alayaos-pivot-brief.md`
- Technical Spec: `docs/superflow/specs/2026-04-07-alayaos-pivot-design.md`
- Competitor Research: session notes (summarized below)
- Security Audit: session notes (summarized below)

---

## Context

AlayaOS is pivoting from a Slack AI bot to an **open-source (BSL) corporate intelligence platform**. The platform ingests data from work tools, extracts structured entities and temporal claims, organizes knowledge into a browsable tree, and serves it to any AI agent via CLI/MCP/API.

This document slices the full scope into **independent Superflow runs**, each buildable and mergeable on its own. Each run produces a working increment of the product.

---

## Architecture Summary

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4: WORKFLOWS (paid SaaS) — Run 8+                │
│  Decision Drift, Project Pulse, Morning Brief,          │
│  Smart Agents, Proactive Push                           │
├─────────────────────────────────────────────────────────┤
│  Layer 3: WEB UI — Run 7                                │
│  Free: dashboard, tree, search, settings                │
│  Paid: workflow builder, graph viz, analytics            │
├─────────────────────────────────────────────────────────┤
│  Layer 2: CONNECTORS & INTERFACES                       │
│  CLI (Run 4), MCP (Run 6), API (Runs 1+3+6)            │
│  Slack (Run 5a), GitHub (Run 5b), Linear (Run 5c)       │
├─────────────────────────────────────────────────────────┤
│  Layer 1: BRAIN (core)                                  │
│  Data Model (Run 1), Extraction (Run 2),                │
│  Search + Knowledge Tree (Run 3)                        │
└─────────────────────────────────────────────────────────┘
```

---

## Superflow Runs

### Run 1: Foundation — Data Model + Docker + Basic API
**Governance:** standard
**Estimated sprints:** 5-7
**Depends on:** nothing (first run, new repo)
**New repo:** `alayaos` (GitHub, BSL license)

**Scope:**
- Create new repo with monorepo structure (`packages/core`, `packages/api`, etc.)
- Python project setup: `pyproject.toml` (uv workspaces), ruff, pyright, CI (GitHub Actions)
- All core database tables: `workspaces`, `l0_events`, `entity_type_definitions`, `l1_entities`, `entity_external_ids`, `l1_relations`, `relation_sources`, `l2_claims`, `claim_sources`, `l3_tree_nodes`, `vector_chunks`, `audit_log`, `api_keys`
- ACL tables: `workspace_members`, `access_groups`, `access_group_members`, `resource_grants`
- PostgreSQL RLS policies for workspace isolation
- Alembic migrations setup
- Core entity types seeding (8 types: person, team, project, task, decision, document, event, organization)
- SQLModel/SQLAlchemy models for all tables
- Basic CRUD repository layer (create/get/update/list for entities, claims, types)
- API key auth (create, verify, revoke)
- Docker Compose: app + postgres + redis + caddy + migrate init container
- Healthcheck endpoints (`/health/live`, `/health/ready`)
- Basic REST API: entities CRUD, types CRUD, claims CRUD, api keys
- `CLAUDE.md` + `llms.txt` for new repo
- BSL license file
- README with quickstart

**Input spec:** `docs/superflow/specs/2026-04-07-alayaos-pivot-design.md` sections 2, 3, 8.1, 9, 10
**Review focus:** data model integrity, Docker production-readiness, RLS correctness

---

### Run 2: Extraction Pipeline — L0 → L1 → L2
**Governance:** standard
**Estimated sprints:** 5-7
**Depends on:** Run 1 (data model, CRUD repos)

**Scope:**
- L0 event ingestion service (create events, dedup by source_type+source_id)
- Staged extraction pipeline (5 stages from spec section 4.1):
  - Stage 1: Preprocessing (source-specific parsing, chunking)
  - Stage 2: LLM extraction (Anthropic SDK primary, LiteLLM fallback)
  - Stage 3: Entity resolution (fuzzy name + external_id matching)
  - Stage 4: Atomic write (L1 entities + relations + L2 claims + provenance links)
  - Stage 5: Async enrichment (vector embedding with pgvector)
- TaskIQ broker + worker setup (jobs, retry, DLQ)
- Extraction prompt design (entities + relations + claims output)
- Claim supersession logic (temporal chain, conflict resolution per section 4.4)
- Model registry + LLM provider config (Anthropic/OpenAI/Ollama)
- Token encryption (MultiFernet with rotation)
- Consolidation agent (periodic: entity dedup, disputed claims, staleness scoring)
- Manual ingestion API endpoints: `POST /ingest/text`, `POST /ingest/webhook`
- Unit + integration tests for extraction pipeline

**Input spec:** sections 4, 9.2
**CC-Research inputs:**
- **BACKLOG-258** (Resilient LLM Retry) — exponential backoff, jitter, Retry-After, cross-provider fallback. Critical for production extraction.
- **BACKLOG-257** (Context Compaction) — chunking/compaction for long Slack threads before extraction
- **BACKLOG-260** (Team Memory Sync) — workspace-level shared knowledge patterns (delta sync, ETag, upsert semantics)
- **BACKLOG-264** (Prompt Engineering) — cache-aware prompt sectioning for extraction prompts
**Key risk:** extraction quality — need gold standard test data
**Cherry-pick reference:** Crystallizer prompts, entity_matcher, consolidation logic from existing Alaya

---

### Run 3: Search + Knowledge Tree
**Governance:** standard
**Estimated sprints:** 4-6
**Depends on:** Run 2 (entities, claims, vectors exist in DB)

**Scope:**
- Hybrid search service: vector (pgvector HNSW) + FTS (tsvector) + entity name matching
- ACL-aware search (JOIN through resource_grants)
- Search API endpoint: `POST /api/v1/search`
- Natural language Q&A endpoint: `POST /api/v1/ask` (LLM over search results)
- L3 Knowledge Tree:
  - Default tree template (sections from spec 5.1)
  - Markdown rendering engine (per-entity-type templates)
  - On-demand rebuild with dirty flag (spec 5.2)
  - Tree API: `GET /api/v1/tree`, `GET /api/v1/tree/{path}`
  - Export: `POST /api/v1/tree/export`
- Entity timeline API: `GET /api/v1/entities/{id}/claims` (claim history)

**Input spec:** sections 5, 8.1 (search/tree endpoints)
**CC-Research inputs:**
- **BACKLOG-252** (Per-Query Context Cache) — cache entity/claim lookups during search to avoid redundant DB hits
**Cherry-pick reference:** vector_service, FTS from existing Alaya

---

### Run 4: CLI
**Governance:** light
**Estimated sprints:** 3-4
**Depends on:** Run 3 (search + tree API must exist)

**Scope:**
- `alayaos-cli` package (Typer + Rich)
- All v1.0 commands from spec section 7.2:
  - `alaya init`, `alaya login`, `alaya status`
  - `alaya ingest text/file`
  - `alaya memory tree/show/search/export/pull/push`
  - `alaya ask`
  - `alaya entity list/get/timeline`
  - `alaya type list/create`
  - `alaya key create/list/revoke`
  - `alaya config show/set`
- Agent integration hooks: `alaya memory pull --format claude-md`
- `pip install alayaos-cli` / `uv tool install alayaos-cli`
- Shell completion

**Input spec:** section 7
**Note:** CLI is thin client over REST API — most logic is server-side

---

### Run 5: Connectors (one per sub-run)
**Governance:** light per connector
**Estimated sprints:** 2-3 per connector
**Depends on:** Run 2 (ingestion API)

#### Run 5a: Slack Connector
- OAuth2 flow for Slack workspace
- Message ingestion (channels, threads, DMs with access_level)
- Channel membership sync → access_groups
- Real-time events via Slack Events API (or polling)
- User mapping → entity_external_ids
- Tests

#### Run 5b: GitHub Connector
- OAuth2 PKCE flow
- Webhook receiver for events (issues, PRs, commits, reviews)
- Entity mapping (repos → projects, issues → tasks, users → persons)
- Tests

#### Run 5c: Linear Connector
- OAuth2 flow
- Webhook receiver for issue/project updates
- Entity mapping (issues → tasks, projects → projects, users → persons)
- Tests

#### Run 5d: Generic Webhook + Document Ingestion
- `POST /api/v1/ingest/webhook` with HMAC verification
- `POST /api/v1/ingest/document` with file upload (PDF, DOCX, MD parsing)
- Document chunking for large files
- Docling (IBM) or similar for PDF/DOCX parsing
- Tests

**Input spec:** section 6
**Cherry-pick reference:** OAuth providers from existing Alaya (reference, not direct port)

---

### Run 6: MCP Server + API Hardening
**Governance:** standard
**Estimated sprints:** 4-5
**Depends on:** Runs 3+4 (search, tree, CLI exist)

**Scope:**
- FastMCP server package with all v1.0 tools (spec section 8.2)
- Outbound webhooks (subscribe, dispatch, HMAC signing, auto-disable)
- GDPR endpoints (export, forget)
- Cursor pagination on all list endpoints
- Rate limiting (per-key, per-workspace)
- Audit log for all API requests
- API docs (OpenAPI/Swagger)
- Integration tests for MCP tools

**Input spec:** sections 8.1, 8.2, 9.3

---

### Run 7: Web UI (v1.1)
**Governance:** standard
**Estimated sprints:** 6-8
**Depends on:** Runs 1-6 (full API surface)

**Scope:**
- React/Next.js app in `packages/web/`
- Free tier: dashboard, knowledge tree browser, entity explorer, search, settings, connector management
- Authentication (workspace login, API key session)
- Responsive design
- Docker integration (served via Caddy)

**Open design questions (need spec before run):**
- Framework: Next.js App Router or plain React + Vite?
- Component library: shadcn/ui? Radix?
- SSR vs SPA?

---

### Run 8+: Paid Features, Advanced Memory & Platform (v1.1+)
**Governance:** varies
**Depends on:** Runs 1-6 stable

These are separate Superflow runs, each self-contained. Grouped by product layer.

#### 🧠 Memory & Personalization

| Run | Feature | Gov | Sprints | CC-Research | Notes |
|-----|---------|-----|---------|-------------|-------|
| 8a | **Per-User Memory System** | standard | 3-4 | **BACKLOG-255** | Personal notes, preferences, source tracking, visibility ("what do you know about me?"), deletion |
| 8b | LLM-Suggested Ontology | standard | 3-4 | — | LLM proposes new entity types during extraction → draft → admin confirms → promoted to full type. Self-evolving schema |
| 8c | Bidirectional Auto-Sync | standard | 3-4 | — | File watcher daemon on dev machines, git post-commit hooks → auto-push local knowledge back to Brain. Conflict resolution with Brain as source of truth |

#### 🤖 Paid SaaS: Autonomous Agents & Workflows

The core paid value proposition — things local agents (Claude Code, Perplexity) **cannot do** because they're reactive and session-bound. These require server-side infrastructure.

| Run | Feature | Gov | Sprints | CC-Research | Notes |
|-----|---------|-----|---------|-------------|-------|
| 8d | **Autonomous Task Queue** | standard | 5-7 | **BACKLOG-256** | Agent self-scheduling ("check this in 2 days"), DreamTask (background memory consolidation 4 stages: orient→gather→consolidate→prune), cron-triggered agent tasks. Foundation for all workflow products |
| 8e | Proactive Push Engine | standard | 4-5 | — | Notification service with delivery channels (Telegram, Slack, email). Shared infra for all proactive features. Budget/quiet hours/preferences |
| 8f | **Decision Drift Detector** | light | 2-3 | — | Scans L2 claims for decisions discussed but never formalized. Alert: "Team discussed migrating to Postgres 3 times this month but no decision entity exists" |
| 8g | **Project Pulse** (Weekly Digest) | light | 2-3 | — | Per-project: status changes, new blockers, deadline drift, ownership changes. Delivered weekly via push engine |
| 8h | **Morning Brief** | light | 2-3 | — | Personalized daily: overnight activity, mentions, decisions affecting your projects, today's tasks. Delivered via push engine |
| 8i | **Ownerless Work Detector** | light | 2-3 | — | Tasks/decisions without owner claims → alert to team lead. "3 tasks from last week's meeting have no assignee" |
| 8n | **Multi-Agent Architecture** | standard | 5-7 | **BACKLOG-263** | Subagent spawning, coordinator mode. Complex workflows: "analyze all Q1 decisions and produce strategic summary" with specialist sub-agents |

#### 🖥️ Web UI

| Run | Feature | Gov | Sprints | Notes |
|-----|---------|-----|---------|-------|
| 7 | **Web UI Free Tier** | standard | 6-8 | Dashboard, knowledge tree browser (interactive mind-map), entity explorer, search, settings, connector management. React/Next.js |
| 8j | **Web UI Paid Tier** | standard | 5-7 | Workflow builder (visual, drag-and-drop cron/trigger configuration), agent configuration, advanced graph visualization (entity relationship map), timeline view (claim history as interactive timeline), team analytics (extraction quality, coverage, activity) |

#### 🔌 Platform & Infrastructure

| Run | Feature | Gov | Sprints | CC-Research | Notes |
|-----|---------|-----|---------|-------------|-------|
| 8k | Additional Connectors | light each | 2-3 each | — | Telegram, Notion, Google Workspace, email (IMAP), Jira, ClickUp, HubSpot. Each is independent Superflow run |
| 8l | Python SDK | light | 2-3 | — | `pip install alayaos`, typed client with async support |
| 8m | **Org-Level Policy & Limits** | standard | 3-4 | **BACKLOG-259** | Per-workspace usage limits, extraction quotas, ETag-cached policy. Required for paid tier enforcement |
| 8o | **Billing (Stripe)** | standard | 4-5 | — | Subscription management, tier gating (free/pro/enterprise), usage metering, self-serve checkout |
| 8p | **Deferred Tool Loading** | standard | 3-4 | **BACKLOG-261** | When 100+ connectors/tools exist, lazy-load tool schemas. Context window optimization for MCP with many tools |
| 8q | **Cost Tracking & Analytics** | light | 2-3 | **BACKLOG-254** | Per-workspace LLM cost tracking, extraction cost per entity type, usage dashboards |

#### 🔐 Enterprise

| Run | Feature | Gov | Sprints | Notes |
|-----|---------|-----|---------|-------|
| 8r | SOC 2 Readiness | standard | 4-5 | Audit log completeness, encryption verification, RBAC documentation, incident runbook |
| 8s | GDPR Compliance | standard | 3-4 | Right to forget, data export, consent management, DPA templates |
| 8t | SSO / OIDC | standard | 3-4 | Enterprise auth: Okta, Azure AD, Google Workspace SSO |
| 8u | On-Prem Deploy Guide | light | 2-3 | Kubernetes manifests, Helm chart, air-gapped deployment docs |

---

## CC-Research Cross-Reference (BACKLOG-250..264)

Patterns and specs from Claude Code codebase analysis, mapped to AlayaOS runs:

| BACKLOG | Title | Mapped to Run | How it applies |
|---------|-------|--------------|----------------|
| **255** | Per-User Memory System | **Run 8a** | Personal notes/preferences with source tracking, visibility, deletion. Core personalization feature |
| **256** | Autonomous Task Queue | **Run 8d** | Agent self-scheduling, DreamTask (background memory consolidation), cron-triggered agent tasks |
| **258** | Resilient LLM Retry | **Run 2** | Exponential backoff + jitter + cross-provider fallback for extraction pipeline |
| **260** | Team Memory Sync | **Run 1-2** | Workspace-level shared knowledge, delta sync patterns, ETag caching |
| **257** | Context Compaction | **Run 2** | Chunking/compaction for long threads before extraction |
| **264** | Prompt Engineering | **Run 2** | Cache-aware prompt sectioning for extraction prompts |
| **252** | Per-Query Context Cache | **Run 3** | Cache entity/claim lookups during search |
| **250** | Tool Pipeline | **Run 6** | Parallel tool execution with rate control for MCP |
| **261** | Deferred Tool Loading | **Run 6** | Context window optimization — lazy tool schema loading |
| **254** | Cost Tracking | **Run 6** | Per-conversation LLM cost monitoring |
| **259** | Org-Level Policy | **Run 8m** | Per-workspace usage limits and quotas |
| **263** | Multi-Agent Architecture | **Run 8n** | Subagent coordination for complex workflows |
| **251** | Declarative Hook System | Backlog | Tool lifecycle hooks (before/after execution) |
| **253** | Speculative Prefetch | Not applicable | No typing events in CLI-first architecture |
| **262** | Core Platform Architecture | Reference | Vision document, not actionable spec |

Full specs: `docs/backlog/BACKLOG-250.md` through `BACKLOG-264.md` (on main branch)

---

## What NOT to Lose (v1.1 Feature Backlog)

These ideas came from brainstorming/research but were scoped out of v1.0. Each is preserved here for future runs:

### Dynamic Ontology — Self-Evolving Schema
- LLM proposes new entity types during extraction → `suggested_types` in draft mode
- Admin confirms/rejects via CLI/API/Web UI
- Ontology Agent (periodic cron) reviews all types, merges duplicates, builds hierarchy
- Source: brainstorming session, Cognee/Graphiti research

### Hierarchical Knowledge Tree as Mind-Map
- Beyond markdown export: interactive browsable tree in Web UI
- Expand/collapse sections, click to drill down
- Bidirectional links between entities
- Staleness heat map (which parts of knowledge are outdated)
- Source: user request, ByteRover/SHIMI research

### Bidirectional Agent Sync (Auto)
- File watcher daemon on local machine
- Monitors `.claude/`, `CLAUDE.md`, project docs for changes
- Auto-pushes relevant changes back to Brain
- Git hook integration (post-commit → push docs changes)
- Source: user request, Hermes agent research

### Pattern Analytics (Smart Agents)
- Deadline Drift: detect repeated deadline claims on same entity
- Ownerless Work: tasks/decisions without `owner` predicate
- Stale Projects: no new claims in 30+ days
- Burnout Signals: person entity with excessive task claims
- Goal Drift: goal entity claims changing frequently
- Source: Codex product review, user ideas

### Temporal Validity Windows (Graphiti-inspired)
- Each claim has `estimated_start` (when fact became true) vs `observed_at` (when we learned it)
- Timeline view shows "Alice was tech lead since Jan 2025, observed in Slack on April 2026"
- Source: Graphiti research, security research

### Local LLM Support
- `docker-compose.local-llm.yml` overlay with Ollama/vLLM
- For privacy-sensitive deployments (data never leaves server)
- Recommended models: Qwen3-14B for extraction, Gemma-3-4B for scoring
- Source: security research

### PII Redaction
- Microsoft Presidio integration before LLM extraction
- Reversible anonymization (mapping table for de-anonymization)
- Configurable per workspace
- Source: security research

### Open-Source Community Features
- Contributor License Agreement (CLA)
- Plugin architecture for custom connectors
- Community connector marketplace
- SBOM generation, cosign for Docker images
- Source: security research, BSL best practices

### Easy Setup / Onboarding Flow (from brainstorm)
- One Docker command → running Brain
- One CLI command in Claude Code → connected to Brain
- Simple web interface for OAuth setup (connect Slack, GitHub, etc.)
- Auto-generate CLAUDE.md sections from Brain for each team member
- Guided "first 10 minutes" flow: deploy → connect → ingest → browse
- Source: brainstorm session

### Alaya as Agent Layer (from brainstorm)
- Keep Alaya Slack/Telegram bot as optional agent that sits on top of AlayaOS Brain
- Alaya handles: standups, interviews, onboarding, meeting summaries
- Alaya uses Brain via same API/MCP that Claude Code uses
- Monetization option: Alaya agent as separate paid product
- Source: brainstorm session — "Alaya stays as agent, Brain is the platform"

### Web UI as Paid Feature (from brainstorm)
- Basic free dashboard (tree browser, search, settings)
- Advanced paid features: workflow builder, graph visualization, team analytics, agent configuration
- Potential third monetization lever alongside SaaS workflows and enterprise
- Source: brainstorm session

### Cron as Core Infrastructure for Paid Tier (from brainstorm)
- TaskIQ cron jobs already proven in Alaya (7 job modules, reliable)
- Crons power: morning brief, weekly digest, decision drift detection, stale project alerts
- Users can't run crons from Claude Code — this is our value add
- Delegatable repeating tasks: "every Monday check X and notify Y"
- Source: brainstorm session + Hermes agent research (built-in cron scheduler)

### Knowledge Tree as Interactive Mind-Map (from brainstorm)
- Beyond markdown export: visual tree in Web UI
- Expand/collapse nodes, drill into entities
- Staleness heat map (which parts are outdated)
- Bidirectional links between entities
- Source: brainstorm session — "как mind-map"

### Claims-Based Analytics (from brainstorm)
- Deadline Drift: detect repeated deadline changes via claim supersession chain
- Pattern detection: "this team changes deadlines 3x more than average"
- Risk scoring: entities with many disputed claims = uncertain state
- Highlight insights proactively: "3 projects have blockers older than 2 weeks"
- Source: brainstorm session — "через claims можно анализировать паттерны"

### Dynamic Ontology — Self-Learning Agent (from brainstorm)
- Not just LLM-suggested types, but a dedicated Ontology Agent that:
  - Runs periodically (like consolidator)
  - Reviews all entity types created across workspace
  - Merges duplicates ("Client" and "Customer" → one type)
  - Builds type hierarchy ("legal_contract" → child of "document")
  - Adapts extraction prompts based on learned ontology
- Each company evolves its own knowledge schema over time
- Agent recursively improves as more data flows in
- Source: brainstorm session — "чтобы модель решала, что важно сохранить"

### Honcho-Style Memory Patterns (from research — github.com/plastic-labs/honcho)

**Multi-level claims (adapt for v1.0 L2 Claims):**
- Add `level` field to claims: `explicit` (direct fact), `deductive` (inferred from other claims), `inductive` (pattern from 2+ sources), `contradiction` (conflicting facts)
- Add `premise_claim_ids` to claims — enables reasoning chain navigation (claim A + B → C)
- This gives the Knowledge Tree richer content: not just facts but inferences and contradictions

**Dreamer-style consolidation (adapt for consolidation agent):**
- Deduction Specialist: find logical consequences, detect updates/contradictions in claims
- Induction Specialist: find patterns across claims (need 2+ sources to qualify as pattern)
- Surprisal-based attention: use embedding geometry (cover tree / random projection tree) to find anomalous claims cheaply (no LLM). Prioritize reviewing the "surprising" facts first
- Trigger: 50+ new claims AND 8+ hours since last run (Honcho's heuristic)

**Entity Cards (compact cached summaries):**
- Company Card, Team Card, Person Card, Project Card — max 40 key facts each
- Auto-updated by consolidation agent
- Injected into agent context instantly (no search needed)
- Like Honcho's "Peer Card" but for any entity type

**Observer/Observed perspective (v1.1 — role-based views):**
- Different roles see different slices of the same entity
- CEO's view of Engineering vs HR's view of Engineering
- Enables role-based Knowledge Tree rendering — same tree, filtered by role/ACL
- Important feature for corporate context, not just nice-to-have
- Implementation: claims tagged with visibility level, tree renderer filters by current user's role

**What NOT to take from Honcho:**
- Peer-centric data model (our entity model is more flexible for corporate use)
- Their Postgres-based queue (we use TaskIQ/Redis)
- Full Dreamer autonomy (corporate memory needs scoped consolidation per project/timeframe)

### Hermes-Style Memory Architecture (from research)
- Three-level memory: simple facts (MEMORY.md) → searchable history (FTS) → deep model (Honcho/dialectic)
- Self-patching skills: agent learns from mistakes, updates own playbook
- Built-in cron scheduler (not system cron): tick every 60s, JSON-backed job queue
- Deliver results to Telegram/Discord/Slack/email
- Source: Hermes agent analysis shared by user

### Connector Architecture — Native > MCP Wrappers (from brainstorm)
- Build reliable native connectors, not MCP wrappers around flaky APIs
- Each connector: OAuth flow + webhook receiver + incremental sync + entity mapping
- Generic webhook endpoint for any custom source
- Document ingestion (PDF, DOCX, MD) with chunking
- Future: plugin architecture for community-contributed connectors
- Source: brainstorm session — "делал бы какие-то более надёжные интег коннекторы"

### Monetization Strategy (from brainstorm)
- **Free (BSL, self-hosted):** Brain (storage, extraction, search, knowledge tree), CLI, MCP, API, basic Web UI
- **Paid SaaS — Workflows tier:** proactive push, autonomous agents, decision drift, project pulse, morning brief, cron workflows
- **Paid SaaS — Web UI tier:** advanced visualization, workflow builder, agent config, team analytics
- **Enterprise:** SSO, SOC 2 compliance, dedicated support, SLA, on-prem deploy guide
- **Potential 4th lever:** Alaya agent (bot for Slack/Telegram) as separate subscription
- BSL license: open source but can't resell as hosted service. Converts to Apache 2.0 after 3 years
- Source: brainstorm session — "память бесплатная, workflow по подписке"

### Multi-Agent Connectors (from brainstorm)
- Not just Claude Code — support ALL local agents:
  - Claude Code (CLI + MCP)
  - Codex (CLI)
  - Perplexity Computer (MCP)
  - OpenClaw (API)
  - Cursor (MCP)
  - Custom agents (REST API + Python SDK)
- Easy setup for each: `alaya init` → one command → connected
- Source: brainstorm session — "ко всем коннекторы прям изишные"

### Go CLI Binary (from stack review)
- Lightweight Go binary (~20MB) as alternative to Python CLI
- `brew install alaya` or `curl | install` — no Python needed
- Same REST API client, just compiled
- When: if non-developer users (marketing, sales) struggle with Python CLI installation
- Not needed for v1.0 — Python CLI is fine for developer ICP
- Source: Opus language analysis — "единственный кейс для Go"

### Stack Additions (from Codex review)
- **Authlib** — OAuth/OIDC library for connectors (replaces custom OAuth code)
- **MCP Python SDK** (official) — replaces FastMCP fork
- **httpx** — unified async HTTP client (already used in Alaya)
- **structlog** — structured JSON logging (better than loguru for open-source)
- **pydantic-settings** — configuration management
- **Reranker** — search quality improvement layer (vector + FTS → reranker → top results). Libraries: `rerankers`, FlashRank, or FastEmbed reranking. Add in Run 3 (Search)
- **Sentry** — opt-in error tracking for SaaS tier
- **OpenTelemetry + Prometheus + Grafana** — observability (cherry-pick from Alaya, 36 metrics)
- **EmbeddingProvider interface** — abstract FastEmbed behind interface so users can swap to Voyage/OpenAI/TEI
- Source: Codex stack review (GPT-5.4, high reasoning)

### Tailscale / Zero-Trust Network (from brainstorm)
- Self-hosted Brain behind Tailscale for secure corporate access
- No public ports needed — all access via Tailscale mesh
- Documentation for Tailscale + Docker setup
- Source: brainstorm session — "по Tailscale и так далее, что безопасно"

---

## Competitor Intelligence (preserved from research)

### Key Findings

| Competitor | What they do | Our advantage |
|-----------|-------------|---------------|
| **Glean** | Full entity extraction, enterprise graph. Closed, $50k+/yr | Open-source, self-hostable, 100x cheaper |
| **Graphiti/Zep** | Temporal KG engine (Apache 2.0). No connectors, no product | Ready product with connectors + CLI |
| **Cognee** | Extraction pipeline with ontology grounding (Apache 2.0). No connectors | Ready product, dynamic ontology |
| **SuperMemory** | Memory API for agents. No entity extraction | Structured entities + claims with provenance |
| **Dust/Onyx** | RAG-based search. No entity extraction | Structured extraction, not dumb RAG |
| **Khoj** | Personal AI assistant (AGPL). No corporate features | Corporate-grade: ACL, multi-user, extraction |
| **Letta/MemGPT** | Agent-controlled memory. No extraction | Automatic extraction from work tools |

### Unique positioning
"Open-source Glean for AI-native teams" — structured corporate memory with entity extraction, temporal claims, and agent-native connectors.

### Nobody does this (our niche)
Open-source "Slack/GitHub/Linear → structured knowledge graph (People, Projects, Decisions, Claims with provenance)" as a self-hostable product with CLI/MCP/API.

---

## Security Highlights (preserved from audit)

### P0 (must have at launch)
- MultiFernet key rotation for encryption
- Docker internal network (no port exposure for DB/Redis)
- Non-root container user, `no-new-privileges`
- `gitleaks` scan before open-source
- Secure-by-default entrypoint (reject default passwords)
- Inbound webhook HMAC verification

### P1 (before paid tier)
- LUKS documentation for Docker volumes
- SOPS + age for encrypted env files
- Presidio PII redaction option
- GDPR endpoints (export, forget)
- PostgreSQL RLS enforcement

### P2 (before enterprise)
- Local LLM overlay (Ollama/vLLM)
- SOC 2 readiness (audit log, encryption, RBAC, backup)
- Anomaly detection for bulk data extraction
- Docker socket proxy for Caddy
- SBOM + cosign

---

## Codex Product Recommendations (preserved)

From Codex product expert review (GPT-5.4, high reasoning):

1. **Narrow ICP to AI-native product/engineering teams** — don't try "corporate memory for everyone" on day 1. Start with Slack + GitHub + Linear, expand later.

2. **Trust-first UX: browsable knowledge tree with evidence** — not just chat answers, but a wiki you can verify. Each fact links to source. This is the real differentiator.

3. **Hybrid ontology with governance** — core types + user-defined + LLM-suggested (draft mode). Never let LLM create types automatically without confirmation.

4. **Agent-native DX must be best in class** — `alaya init` in 10 minutes. Opinionated examples: "memory for repo", "memory for incident channel".

5. **Paid layer = opinionated coordination products, not generic cron** — "Decision Drift", "Ownerless Work", "Project Pulse". Specific outcomes, not abstract automation.

---

## Execution Order

```
Run 1: Foundation (new repo, data model, Docker, basic API)
  ↓ merge
Run 2: Extraction Pipeline (L0→L1→L2, LLM, TaskIQ)
  ↓ merge
Run 3: Search + Knowledge Tree (vector, FTS, L3, markdown)
  ↓ merge
Run 4: CLI (Typer, all commands, agent hooks)
  ↓ merge
Run 5a-d: Connectors (Slack, GitHub, Linear, webhook — can parallel)
  ↓ merge
Run 6: MCP + API Hardening (full tool set, webhooks, GDPR, rate limiting)
  ↓ merge
────── v1.0 MVP complete ──────
Run 7: Web UI
Run 8a-k: Paid features, advanced connectors, SDK, billing
```

Each run is a fresh `superflow` invocation. The spec + brief + this master plan are the shared context. Each run starts by reading this document + the spec.

---

## How to Start Next Run

```bash
# 1. Create new repo
gh repo create alaya-os/alayaos --public
cd alayaos

# 2. Initialize project structure (or let Run 1 Superflow do it)

# 3. Start Superflow Run 1
# Feed it: this master plan + spec + brief
# Scope: "Run 1: Foundation" from this document
# Governance: standard
```
