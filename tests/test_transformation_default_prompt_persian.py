"""Migration 31 regression: default Transformation prompt requires Persian output.

The default Transformation instructions (``open_notebook:default_prompts``,
seeded by migration 5, prepended to every Transformation's own prompt in
``open_notebook/graphs/transformation.py``) must establish a Persian
language/style policy WITHOUT changing any Transformation's task, WITHOUT
introducing input placeholders, and WITHOUT touching the execution flow.

These tests pin the migration files so the policy can never be silently
dropped or morphed into a translation task.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "open_notebook" / "database" / "migrations"


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8-sig")


def _body(name: str) -> str:
    """Migration statements without `--` comment lines."""
    return "\n".join(
        line for line in _read(name).splitlines()
        if not line.strip().startswith("--")
    )


def test_migration_31_updates_default_transformation_prompt():
    text = _read("31.surrealql")
    assert "open_notebook:default_prompts" in text
    assert "transformation_instructions" in text
    # Non-destructive content update: never drop tables or delete rows.
    assert "REMOVE TABLE" not in text
    assert "DELETE" not in text


def test_migration_31_requires_persian_output():
    text = _body("31.surrealql")
    assert "Persian (Farsi)" in text
    assert "Execute the requested transformation normally" in text


def test_migration_31_preserves_facts_and_uncertainty():
    text = _body("31.surrealql")
    assert "Do not invent facts" in text
    assert "Preserve numbers" in text
    assert "Preserve uncertainty" in text
    assert "technical terms" in text


def test_migration_31_has_no_input_placeholders():
    text = _body("31.surrealql")
    for placeholder in ("{{INPUT}}", "{{INSIGHT}}", "{{input}}", "{{insight}}"):
        assert placeholder not in text
    lowered = text.lower()
    assert "translate the following insight" not in lowered
    assert "wait for input" not in lowered
    assert "ask me for input" not in lowered


def test_migration_31_keeps_original_instructions_intact():
    text = _body("31.surrealql")
    # Original seed clauses from migration 5 must survive verbatim.
    assert "You are my learning assistant" in text
    assert "Do not give me any warnings about copyright or plagiarism" in text
    assert "Execute my request completely" in text


def test_migration_31_down_restores_previous_prompt():
    text = _read("31_down.surrealql")
    assert "open_notebook:default_prompts" in text
    assert "You are my learning assistant" in text
    assert "Persian (Farsi)" not in text
    assert "REMOVE TABLE" not in text
    assert "DELETE" not in text


def test_migration_31_registered_in_manager():
    manager = (
        REPO_ROOT / "open_notebook" / "database" / "async_migrate.py"
    ).read_text(encoding="utf-8-sig")
    assert "migrations/31.surrealql" in manager
    assert "migrations/31_down.surrealql" in manager


def test_builtin_transformation_prompts_unchanged():
    text = _read("5.surrealql")
    # Summary must remain a Summary: its task text is untouched.
    assert "create a summary that:" in text
    assert "Captures the core concepts and key information" in text
    assert "Dense Summary" in text
    assert "Key Insights" in text


def test_execution_template_still_injects_instructions_and_input():
    template = (
        REPO_ROOT / "prompts" / "transformation" / "execute.jinja"
    ).read_text(encoding="utf-8-sig")
    assert "{{ instructions }}" in template
    assert "# INPUT" in template
    graph = (
        REPO_ROOT / "open_notebook" / "graphs" / "transformation.py"
    ).read_text(encoding="utf-8-sig")
    # Default instructions are prepended; the real source text rides the
    # HumanMessage — no new input variable in the contract.
    assert "default_prompts.transformation_instructions" in graph
    assert "HumanMessage(content=content_str)" in graph
