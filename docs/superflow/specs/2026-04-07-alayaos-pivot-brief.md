# AlayaOS — Open-Source Corporate Intelligence Platform

## Product Brief

**Date:** 2026-04-07
**Status:** Approved (Phase 1 Step 7)

---

## Problem Statement

AI-агенты (Claude Code, Codex, Perplexity) стали основным рабочим инструментом для команд всех профилей, но они начинают каждую сессию без контекста о компании. Корпоративные знания разбросаны по 5-10 инструментам, и ни одно open-source решение не извлекает из них структурированные сущности с provenance и temporal history.

## Product Summary

**AlayaOS** — open-source (BSL) self-hostable platform, которая автоматически строит и поддерживает структурированную память компании из всех рабочих источников, и отдаёт её любому AI-агенту через CLI, MCP и API.

### Feature List

**Layer 1: Brain (free, BSL)**
- L0 Event Storage — immutable log из всех источников
- L1 Entities & Relations — dynamic ontology (core types + user-defined + LLM-suggested with confirmation)
- L2 Claims — атомарные факты с provenance, temporal validity, supersession chain
- L3 Knowledge Tree — иерархическая browsable память (PostgreSQL → markdown export)
- Extraction Pipeline — LLM-based entity/relation/claim extraction
- Consolidation — periodic merge, dedup, staleness marking, pattern detection
- Hybrid Search — vector (pgvector) + FTS + entity graph
- ACL — per-entity access control with provenance

**Layer 2: Connectors (free, BSL)**
- Native connectors: Slack, GitHub, Linear, Telegram, Notion, Google Workspace, email
- CLI: `alaya init/connect/ingest/memory/ask/entity/type`
- MCP Server: для Claude Code, Cursor, Codex
- REST API: OpenAPI spec, cursor pagination, webhooks
- Python SDK
- Bidirectional sync: agents read from Brain AND write back (push hooks, auto-sync)

**Layer 3: Web UI**
- Free tier: dashboard, knowledge tree browser, entity explorer, search, settings, connector management
- Paid tier: workflow builder, agent configuration, advanced graph visualization, timeline view, team analytics

**Layer 4: Workflows (paid SaaS)**
- Decision Drift — решения, которые обсуждаются, но не фиксируются
- Ownerless Work — задачи без owner или follow-up
- Project Pulse — weekly digest с рисками и blockers
- Deadline Drift — паттерны переносов дедлайнов, risk alerts
- Morning Brief — personalized daily summary
- Custom cron workflows
- Proactive push: Telegram, Slack, email
- Smart agents: аналитика поверх Claims (паттерны, anomalies, risk signals)

### NOT in Scope (v1.0)

- Mobile app
- Video/audio processing (только текст и транскрипты)
- Real-time collaboration UI (не Google Docs)
- Собственная LLM (используем cloud/local через LiteLLM)
- ERP/CRM глубокие интеграции (Salesforce, SAP)

### Key Decisions

| Decision | Rationale |
|----------|-----------|
| New repo, not fork | Clean architecture, easy open-source, no legacy |
| BSL license (3yr → Apache 2.0) | Open enough for adoption, protects SaaS revenue |
| PostgreSQL + pgvector | JSONB = flexible, pgvector = vectors, RLS = multi-tenant |
| Hybrid ontology | Core types + user-defined + LLM-suggested with confirmation |
| L2 Claims layer | Temporal facts with provenance, enables pattern analytics |
| Knowledge Tree in DB → markdown export | ACL-safe source of truth + agent-friendly export |
| CLI-first DX | 10-32x cheaper per token than MCP, ~100% reliability |
| Monorepo with packages | Simpler CI, versioning, coordination |
| Bidirectional agent sync | Agents read AND write to Brain (hooks, push, auto-sync) |

## Jobs to be Done

1. When **starting a Claude Code / Perplexity session**, I want to **instantly have company context**, so I can **skip 10 minutes of context-setting**
2. When **a team makes a decision in Slack**, I want it to be **automatically captured as a structured claim with source**, so I can **find it in 6 months**
3. When **onboarding to a new project**, I want to **browse a knowledge tree**, so I can **get productive in hours, not weeks**
4. When **managing a team**, I want **proactive alerts about stalled decisions, deadline drift, and ownerless work**, so I can **intervene early**
5. When **working locally with Claude Code**, I want my **learnings and decisions to flow back into the team brain**, so **knowledge doesn't stay siloed on my machine**

## User Stories

1. As a **developer**, I want to run `alaya ask "who decided to migrate to Postgres and why?"` and get an answer with source links
2. As a **team lead**, I want a Monday morning brief: what changed, new decisions, blocked tasks, deadline drifts
3. As a **marketer**, I want to ask "what did we decide about positioning?" and get the decision with context
4. As a **sales person**, I want to ask "what's the status of the Acme deal?" and get info assembled from Linear + Slack
5. As a **CEO**, I want a weekly company pulse with risks, blockers, and changed assumptions
6. As a **new team member**, I want to `alaya memory show projects/billing` and see a complete project summary
7. As a **platform admin**, I want to `docker compose up` and have secure corporate memory in 10 minutes

## ICP

AI-native teams любого профиля (dev, product, marketing, sales, leadership) в стартапах и компаниях 10-150 человек, которые уже используют Claude Code / Codex / Perplexity Computer в повседневной работе.

## Success Criteria

1. **Time to value**: `docker compose up` → first `alaya memory tree` in < 15 minutes
2. **Extraction quality**: >80% precision on entity/claim extraction
3. **GitHub stars**: 1000+ in first 3 months
4. **Active self-hosted installs**: 50+ in first 6 months
5. **Paid conversions**: 5+ teams on Workflow tier in first 6 months

## Edge Cases

- **Empty workspace**: first run → clear onboarding guide, not empty screens
- **LLM API key missing**: extraction disabled gracefully, storage and search still work
- **Huge history (100k+ messages)**: incremental ingestion with progress, don't OOM
- **Conflicting facts**: temporal validity chain, show latest with history of changes
- **Private data**: DM content = CONFIDENTIAL, never sent to LLM without explicit opt-in
- **Local LLM**: Ollama/vLLM as alternative to cloud APIs for privacy-sensitive deployments

## Architecture Layers

```
┌─────────────────────────────────────────────────────────┐
│  Layer 4: WORKFLOWS (paid SaaS)                         │
│  Decision Drift, Project Pulse, Morning Brief,          │
│  Smart Agents, Proactive Push                           │
├─────────────────────────────────────────────────────────┤
│  Layer 3: WEB UI                                        │
│  Free: dashboard, tree, search, settings                │
│  Paid: workflow builder, graph viz, analytics            │
├─────────────────────────────────────────────────────────┤
│  Layer 2: CONNECTORS                                    │
│  CLI, MCP, REST API, SDK, Bidirectional Sync            │
│  Native: Slack, GitHub, Linear, Telegram, Notion, email │
├─────────────────────────────────────────────────────────┤
│  Layer 1: BRAIN (core, BSL)                             │
│  L0 Events → L1 Entities → L2 Claims → L3 Knowledge    │
│  Extraction, Consolidation, Search, ACL                 │
└─────────────────────────────────────────────────────────┘
```

## Competitive Positioning

"Open-source Glean for AI-native teams" — structured corporate memory with entity extraction, temporal claims, and agent-native connectors. Self-hostable, BSL licensed.

| vs | Our advantage |
|----|---------------|
| Glean | Open-source, self-hostable, 100x cheaper |
| Graphiti/Cognee | Ready product with connectors, not just engine |
| SuperMemory | Structured entities + claims, not just flat facts |
| Dust/Onyx | Entity extraction with provenance, not dumb RAG |
| Notion/Confluence | Auto-populated from work tools, not manual wiki |
