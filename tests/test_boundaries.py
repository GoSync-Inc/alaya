"""Import boundary check — core must not depend on api/cli/connectors."""

import tomllib
from pathlib import Path


def test_core_does_not_import_api():
    """core package must not depend on api/cli/connectors."""
    pyproject = Path("packages/core/pyproject.toml")
    with open(pyproject, "rb") as f:
        config = tomllib.load(f)
    deps = config.get("project", {}).get("dependencies", [])
    for dep in deps:
        dep_lower = dep.lower()
        assert "alayaos-api" not in dep_lower, f"core depends on api: {dep}"
        assert "alayaos-cli" not in dep_lower, f"core depends on cli: {dep}"
        assert "alayaos-connectors" not in dep_lower, f"core depends on connectors: {dep}"


def test_api_does_not_import_cli():
    """api package must not depend on cli/connectors."""
    pyproject = Path("packages/api/pyproject.toml")
    with open(pyproject, "rb") as f:
        config = tomllib.load(f)
    deps = config.get("project", {}).get("dependencies", [])
    for dep in deps:
        dep_lower = dep.lower()
        assert "alayaos-cli" not in dep_lower, f"api depends on cli: {dep}"
        assert "alayaos-connectors" not in dep_lower, f"api depends on connectors: {dep}"
