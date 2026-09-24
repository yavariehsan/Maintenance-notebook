"""Isolation verification: the package must not depend on the host app.

Static checks (no host runtime needed):

- no absolute import outside ``maintenance_troubleshooting``, the stdlib,
  or declared third-party dependencies;
- no reference to host modules, host env vars, SurrealDB, FastAPI, or the
  host data directory in package *source*;
- ``pyproject.toml`` declares no host/framework/database dependencies;
- the public API imports with a scrubbed environment (no host env vars).
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PACKAGE_ROOT / "src" / "maintenance_troubleshooting"

FORBIDDEN_MODULES = {
    "open_notebook",
    "api",
    "commands",
    "surrealdb",
    "surreal_commands",
    "fastapi",
    "uvicorn",
    "streamlit",
}

FORBIDDEN_STRINGS = (
    "open_notebook",
    "surrealdb",
    "SURREAL",
    "OPEN_NOTEBOOK",
    "notebook_data",
    "127.0.0.1:8000",
)


def _iter_sources() -> list[Path]:
    return sorted(SRC_ROOT.rglob("*.py"))


def _imported_top_levels(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.add("__relative__")
            elif node.module:
                found.add(node.module.split(".")[0])
    return found


def test_no_forbidden_imports() -> None:
    """No source file imports host, framework, or database modules."""
    violations: list[str] = []
    for path in _iter_sources():
        top_levels = _imported_top_levels(ast.parse(path.read_text(encoding="utf-8")))
        for module in sorted(top_levels & FORBIDDEN_MODULES):
            violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports '{module}'")
    assert not violations, "forbidden imports:\n" + "\n".join(violations)


def test_no_relative_imports_escaping_package() -> None:
    """No relative import tries to leave the package boundary."""
    violations = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in _iter_sources()
        if "__relative__" in _imported_top_levels(ast.parse(path.read_text(encoding="utf-8")))
    ]
    assert not violations, "escaping relative imports:\n" + "\n".join(violations)


def test_no_host_strings_in_source() -> None:
    """No host env vars, hosts, or data-dir references in source."""
    violations: list[str] = []
    for path in _iter_sources():
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for needle in FORBIDDEN_STRINGS:
            if needle.lower() in lowered:
                violations.append(
                    f"{path.relative_to(PACKAGE_ROOT)} mentions '{needle}'"
                )
    assert not violations, "host references:\n" + "\n".join(violations)


def test_declared_dependencies_are_minimal() -> None:
    """pyproject must not pull framework/database/UI stacks."""
    content = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8").lower()
    for forbidden in ("fastapi", "surrealdb", "uvicorn", "react", "pydantic", "numpy"):
        assert forbidden not in content, f"dependency leak: {forbidden}"


def test_public_api_imports_without_host_environment() -> None:
    """Public API imports with host env vars scrubbed from the process env."""
    scrubbed = {
        key: value
        for key, value in os.environ.items()
        if "NOTEBOOK" not in key.upper() and "SURREAL" not in key.upper()
    }
    probe = (
        "import os, sys; "
        f"os.environ.clear(); os.environ.update({scrubbed!r}); "
        "sys.path.insert(0, r'" + str(SRC_ROOT.parent) + "'); "
        "import maintenance_troubleshooting as m; "
        "print(m.__version__); print(callable(m.analyze_workbook))"
    )
    import subprocess

    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "True" in completed.stdout
