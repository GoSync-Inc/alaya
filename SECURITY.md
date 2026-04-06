# Security Policy

## Reporting a vulnerability

**Do NOT open a public GitHub issue for security vulnerabilities.**

Please email **security@alayaos.com** with:
- Description of the vulnerability
- Steps to reproduce
- Potential impact

We will acknowledge your report within 48 hours and work on a fix.

## Supported versions

We recommend always using the latest version.

## Security features (planned)

These security measures are being implemented as part of the initial release:

- All secrets managed via environment variables (never in code)
- Encryption at rest for OAuth tokens and API keys (Fernet/AES)
- Row-Level Security (RLS) for workspace isolation
- Rate limiting on all API endpoints
- Audit logging for all data access
