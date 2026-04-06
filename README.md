# Alaya

Open-source corporate memory platform. Extracts structured knowledge from your work tools, serves it to any AI agent.

## Why

AI agents start every session from scratch. Decisions get lost in chat history. Knowledge is scattered across a dozen tools.

Alaya runs in the background — absorbs, structures, connects. When an agent needs context, it's already there.

## How it works

```
Sources (Slack, GitHub, Linear, docs, ...)
          |
     Extraction --> Entities, Claims, Relations
          |
     Knowledge Tree --> browsable like a book
          |
     CLI - MCP - API --> any AI agent
```

**Entities** — people, projects, tasks, decisions. Dynamic ontology that grows with your company.

**Claims** — atomic facts with provenance. "Project Alpha deadline is March 15" links back to the message where it was said. When the deadline changes, both facts are preserved with full history.

**Knowledge Tree** — hierarchical memory, like a table of contents. An agent reads the overview, drills into the section it needs.

## Status

Under active development. First release coming soon.

## Stack

Python 3.13 / FastAPI / SQLAlchemy 2.0 + Pydantic / PostgreSQL + pgvector / Redis / TaskIQ / Anthropic SDK / Typer

## License

[BSL 1.1](./LICENSE) — source available, self-host without restrictions. Converts to Apache 2.0 after 3 years.
