# Contributing to Alaya

Thanks for your interest in contributing!

## Ways to contribute

- **Report bugs** — open an issue with reproduction steps
- **Suggest features** — open a feature request issue
- **Fix bugs** — look for issues labeled `good first issue` or `help wanted`
- **Improve docs** — README, code comments, examples

## Before you code

For anything beyond a small bugfix, **please open an issue first** to discuss the approach. This saves everyone time.

## Development setup

```bash
# Clone
git clone https://github.com/GoSync-Inc/alaya.git
cd alaya

# Install dependencies
uv sync

# Start services
docker compose up -d

# Verify
uv run ruff check .
uv run pyright
uv run pytest
```

## Making changes

1. Create a branch: `git checkout -b feat/your-feature`
2. Make your changes
3. Run checks: `uv run ruff check . && uv run pyright && uv run pytest`
4. Commit with conventional message: `feat: add X` / `fix: resolve Y`
5. Push and open a PR

## Code style

- Formatter: `ruff format`
- Linter: `ruff check`
- Types: `pyright` strict mode
- See `CLAUDE.md` for naming conventions and architecture rules

## License

By contributing, you agree that your contributions will be licensed under the [BSL 1.1](./LICENSE).
