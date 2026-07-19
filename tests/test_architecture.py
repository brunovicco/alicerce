"""Regression tests for the approved Phase 2A package boundaries."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "alicerce"
EXPECTED_LAYERS = {"domain", "application", "ports", "adapters"}
ALLOWED_IMPORTS = {
    "domain": {"domain"},
    "ports": {"domain", "ports"},
    "application": {"domain", "ports", "application"},
    "adapters": {"domain", "ports", "application", "adapters"},
}
BANNED_DOMAIN_TOKENS = {
    "a2a",
    "anthropic",
    "claude",
    "codex",
    "github",
    "mcp",
    "openai",
    "opentelemetry",
}


def _python_files() -> Iterator[Path]:
    yield from sorted(SOURCE_ROOT.rglob("*.py"))


def _layer_for(path: Path) -> str | None:
    relative = path.relative_to(SOURCE_ROOT)
    return relative.parts[0] if len(relative.parts) > 1 else None


def _internal_imports(path: Path) -> Iterator[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("alicerce."):
                    yield alias.name
        elif (
            isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("alicerce.")
        ):
            yield node.module


def test_required_package_layers_exist() -> None:
    """The approved dependency layers exist as importable packages."""
    actual = {
        path.name
        for path in SOURCE_ROOT.iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    assert actual >= EXPECTED_LAYERS
    assert (SOURCE_ROOT / "adapters" / "local" / "__init__.py").is_file()


def test_layer_import_direction_is_inward_only() -> None:
    """Source imports cannot point from an inner layer to an outer layer."""
    violations: list[str] = []
    for path in _python_files():
        source_layer = _layer_for(path)
        if source_layer not in ALLOWED_IMPORTS:
            continue
        for imported in _internal_imports(path):
            parts = imported.split(".")
            target_layer = parts[1] if len(parts) > 1 else None
            if target_layer and target_layer not in ALLOWED_IMPORTS[source_layer]:
                violations.append(f"{path.relative_to(ROOT)} -> {imported}")
    assert violations == []


def test_domain_and_ports_are_provider_neutral() -> None:
    """Trusted inner boundaries contain no provider or protocol identifiers."""
    violations: list[str] = []
    for layer in ("domain", "ports"):
        for path in sorted((SOURCE_ROOT / layer).rglob("*.py")):
            content = path.read_text(encoding="utf-8").casefold()
            matches = sorted(token for token in BANNED_DOMAIN_TOKENS if token in content)
            if matches:
                violations.append(f"{path.relative_to(ROOT)}: {', '.join(matches)}")
    assert violations == []


def test_runtime_dependency_is_only_pinned_canonical_schemas() -> None:
    """The mandatory runtime has only the immutable canonical schemas dependency."""
    with (ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)

    dependencies = pyproject["project"]["dependencies"]
    assert len(dependencies) == 1
    dependency = dependencies[0]
    assert dependency.startswith("loop-schemas @ git+")
    assert "0459d61b7b1d4e7b46709e6d3895770553e6fab0" in dependency


def test_forbidden_external_dependencies_are_absent() -> None:
    """Phase 2B and external telemetry packages remain outside the runtime."""
    with (ROOT / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)

    serialized = "\n".join(pyproject["project"]["dependencies"]).casefold()
    forbidden = ("a2a-otel-kit", "anthropic", "mcp", "openai", "opentelemetry")
    assert [name for name in forbidden if name in serialized] == []
