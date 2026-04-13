# Security Best Practices Report

Date: 2026-04-13
Scope: `packages/api`, `packages/core`, `packages/cli-go`
References:
- `/Users/egoregerev/.codex/skills/security-best-practices/references/python-fastapi-web-server-security.md`
- `/Users/egoregerev/.codex/skills/security-best-practices/references/golang-general-backend-security.md`

Follow-up implementation plan:
- `docs/superflow/plans/2026-04-13-security-hardening.md`

## Executive Summary

The repository already has several strong security foundations: tenant isolation is enforced through PostgreSQL RLS, API keys are hashed, request validation is pervasive, and the Go CLI prefers OS keyring storage over plaintext files. The main gaps are in API surface hardening rather than the core data model.

The highest-priority issue is authorization design around `/search` and `/ask`: both routes bypass the explicit scope-enforcement pattern used elsewhere in the API. The next most important issue is abuse resistance: the rate limiter fails open whenever Redis is unavailable, which weakens protection on the most expensive endpoints. The rest of the findings are baseline production hardening issues: docs/OpenAPI are enabled by default, Host validation is not visible in app code, the readiness endpoint leaks internal deployment state, and the CLI prints API keys directly to stdout during agent setup.

---

## High Severity

### SBP-001: `/search` and `/ask` bypass explicit scope enforcement

- Rule ID: `FASTAPI-AUTH-001`
- Severity: High
- Location:
  - `packages/api/alayaos_api/routers/search.py:20-24`
  - `packages/api/alayaos_api/routers/ask.py:25-29`
  - `packages/api/alayaos_api/deps.py:98-112`
- Evidence:

```python
# packages/api/alayaos_api/routers/search.py
@router.post("/search", response_model=SearchResponse)
async def search(
    body: SearchRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
):
```

```python
# packages/api/alayaos_api/routers/ask.py
@router.post("/ask", response_model=AskResult)
async def ask_endpoint(
    body: AskRequest,
    session: Annotated[AsyncSession, Depends(get_workspace_session)],
    api_key: Annotated[APIKey, Depends(get_api_key)],
):
```

```python
# packages/api/alayaos_api/deps.py
def require_scope(scope: str):
    async def _check_scope(api_key: Annotated[APIKey, Depends(get_api_key)]) -> APIKey:
        if scope not in api_key.scopes:
            raise HTTPException(...)
```

- Impact: The intended authorization boundary is “valid key + required scope”, but these two routes currently accept any valid API key. If the separate runtime bug on `api_key.prefix` is fixed without also fixing authz, write-only or narrowly-scoped keys will be able to read workspace memory.
- Fix: Replace `Depends(get_api_key)` with `Depends(require_scope("read"))` on both routes, or attach the dependency at router level for all read endpoints.
- Mitigation: Until fixed, avoid issuing non-read keys to untrusted clients and keep these endpoints disabled behind the existing runtime failure.
- False positive notes: Current exploitability is partially masked by a separate AttributeError bug (`api_key.prefix` vs `key_prefix`). The authorization defect still exists in the code path design and should be corrected before the route is repaired.

---

## Medium Severity

### SBP-002: Rate limiting fails open when Redis is unavailable

- Rule ID: `FASTAPI-BASELINE-RATE-LIMIT`
- Severity: Medium
- Location:
  - `packages/api/alayaos_api/routers/search.py:28-35`
  - `packages/api/alayaos_api/routers/ask.py:33-42`
  - `packages/core/alayaos_core/services/rate_limiter.py:60-83`
- Evidence:

```python
# packages/api/alayaos_api/routers/search.py
redis_client = None
with contextlib.suppress(Exception):
    redis_client = aioredis.from_url(settings.REDIS_URL)
limiter = RateLimiterService(redis=redis_client)
allowed, retry_after = await limiter.check(f"{api_key.prefix}:search", 60, 60)
```

```python
# packages/core/alayaos_core/services/rate_limiter.py
if self._redis is None:
    return True, None

...
except Exception:
    log.warning("rate_limiter_redis_error", key=key)
    return True, None
```

- Impact: A Redis outage or connection failure removes throttling on `/ask` and `/search`, which are the two endpoints most likely to amplify cost and abuse. A valid API key can then generate unbounded expensive work.
- Fix: Fail closed or degraded for these endpoints when Redis is unavailable, or add a safe local fallback limiter. At minimum, distinguish “Redis unavailable” from “allowed”.
- Mitigation: Add gateway or proxy-level rate limits in front of `/ask` and `/search`.
- False positive notes: If an external API gateway already enforces strict per-key limits, the operational risk is reduced, but that control is not visible in repository code.

### SBP-003: OpenAPI and interactive docs are enabled by default in production

- Rule ID: `FASTAPI-OPENAPI-001`
- Severity: Medium
- Location: `packages/api/alayaos_api/main.py:34-35`
- Evidence:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="AlayaOS API", version="0.1.0", lifespan=lifespan)
```

FastAPI defaults expose `/docs`, `/redoc`, and `/openapi.json` unless explicitly disabled or protected.

- Impact: Public docs materially increase endpoint discovery and lower the cost of probing internal/admin routes.
- Fix: In production, set `docs_url=None`, `redoc_url=None`, and `openapi_url=None`, or gate them behind auth / an internal-only route.
- Mitigation: Restrict these paths at the reverse proxy if they must stay enabled in the app.
- False positive notes: If infrastructure already blocks `/docs`, `/redoc`, and `/openapi.json`, verify that restriction is enforced consistently across environments.

### SBP-004: Host header validation is not visible in app code

- Rule ID: `FASTAPI-HOST-001`
- Severity: Medium
- Location:
  - `packages/api/alayaos_api/main.py:34-59`
  - `packages/api/alayaos_api/middleware.py:31-33`
- Evidence:

```python
def create_app() -> FastAPI:
    app = FastAPI(title="AlayaOS API", version="0.1.0", lifespan=lifespan)
    ...
    register_error_handlers(app)
```

```python
def register_error_handlers(app: FastAPI) -> None:
    app.add_middleware(RequestIDMiddleware)
```

There is no visible `TrustedHostMiddleware` or equivalent host allowlisting in the FastAPI app.

- Impact: If the service is deployed behind a permissive proxy, spoofed `Host` headers can affect absolute URL generation, callbacks, redirects, and any future security decisions that trust request host/origin data.
- Fix: Add `TrustedHostMiddleware` with an allowlist sourced from configuration, or document and enforce equivalent validation at the edge.
- Mitigation: Ensure ingress / reverse proxy rejects unexpected Host values before traffic reaches the app.
- False positive notes: This may already be handled by infrastructure. That control is not visible in repository code and should be verified at runtime/config level.

---

## Low Severity

### SBP-005: `/health/ready` exposes internal deployment state anonymously

- Rule ID: `FASTAPI-INFO-001`
- Severity: Low
- Location: `packages/api/alayaos_api/routers/health.py:19-60`
- Evidence:

```python
@router.get("/health/ready")
async def health_ready(session: Annotated[AsyncSession, Depends(get_session)]):
    ...
    return {"status": overall, "checks": checks, "first_run": first_run}
```

The route reveals:
- database availability
- migration state
- seed state
- whether any user API keys exist yet (`first_run`)

- Impact: This is useful reconnaissance for an attacker and also exposes bootstrap state for fresh deployments.
- Fix: Keep `/health/live` public and reduce `/health/ready` to a coarse status, or protect the detailed readiness endpoint behind internal networking / auth.
- Mitigation: Restrict `/health/ready` to cluster-local or load-balancer health checks only.
- False positive notes: If `/health/ready` is already internal-only at the edge, the exposure is operationally reduced.

### SBP-006: `alaya setup agent` prints API keys directly to stdout

- Rule ID: `GO-CONFIG-001`
- Severity: Low
- Location: `packages/cli-go/internal/cmd/setup.go:52-64`
- Evidence:

```go
case "claude-code":
    fmt.Printf(`{"mcpServers":{"alaya":{"command":"alaya","args":["mcp"],"env":{"ALAYA_SERVER_URL":"%s","ALAYA_API_KEY":"%s"}}}}`, baseURL, apiKey)
...
case "codex":
    fmt.Printf("export ALAYA_SERVER_URL=%s\nexport ALAYA_API_KEY=%s\n", baseURL, apiKey)
...
default:
    fmt.Printf("ALAYA_SERVER_URL=%s\nALAYA_API_KEY=%s\nALAYA_API_BASE=%s/api/v1\n", baseURL, apiKey, baseURL)
```

- Impact: Secrets are pushed into terminal scrollback, shell captures, shared session logs, and copy/paste history.
- Fix: Default to redacted output and add an explicit `--show-secret` or `--copy-env` flag. Another safe option is to write config snippets with placeholders while keeping the real key in keyring storage.
- Mitigation: At minimum, print a warning before outputting secrets and document the risk in CLI help.
- False positive notes: This is a developer-tooling exposure rather than a server-side vulnerability, but it still violates the “do not output secrets unless necessary” baseline.

---

## Positive Observations

- `packages/api/alayaos_api/deps.py` validates API key structure and hashes before lookup.
- `packages/core/alayaos_core/config.py` uses `SecretStr` for sensitive Python settings.
- `packages/cli-go/internal/auth/keyring.go` stores API keys in OS keyring rather than plaintext files.
- No obvious use of `InsecureSkipVerify`, shell execution, unsafe templating, or committed secrets was found in the reviewed source files.

## Recommended Remediation Order

1. Fix `SBP-001` together with the existing `/search` and `/ask` runtime bug so the routes are repaired safely.
2. Fix `SBP-002` before wider rollout of `/ask`, because that endpoint directly drives LLM cost.
3. Fix `SBP-003` and `SBP-004` as production-baseline hardening before public deployment.
4. Fix `SBP-005` and `SBP-006` as low-risk cleanup items.
