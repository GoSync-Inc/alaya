# Alaya CLI

Corporate memory CLI — query knowledge, manage entities, configure AI agents.

## Install

```bash
go install github.com/GoSync-Inc/alaya/packages/cli-go/cmd/alaya@latest
```

## Auth

```bash
export ALAYA_API_KEY=ak_your_key_here
# or
alaya auth login --key ak_... --url http://localhost:8000
```

## Commands

| Command | Description |
|---------|-------------|
| `alaya search "query"` | Hybrid search (FTS + vector + entity name) |
| `alaya ask "question"` | Natural language Q&A with citations |
| `alaya entity list` | List entities |
| `alaya entity get <id>` | Get entity details |
| `alaya claim list` | List claims |
| `alaya tree show [path]` | Knowledge tree node |
| `alaya tree export [path]` | Export subtree as markdown |
| `alaya ingest file <path>` | Ingest file content |
| `alaya ingest text "content"` | Ingest text |
| `alaya key create/list/revoke` | API key management |
| `alaya setup agent --profile` | Agent integration setup |

All commands support `--json` for machine-readable output.
