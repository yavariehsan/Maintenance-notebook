"""Migration 29 regression (campact): LLM tables must stay schemaless.

Production root cause: the prod ``llm_knowledge_build`` table was
SCHEMAFULL with ``TYPE array`` fields, so SurrealDB 2.6.5 silently
dropped ``source_report_ids``/``manifest`` on every write and each
manual build was born manifest-less (worker then failed it at the
manifest gate in <1s). Migration 29 repairs both LLM tables to
schemaless and removes the lossy field definitions. These tests pin
the repair files so the drift can never be reintroduced unnoticed.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = REPO_ROOT / "open_notebook" / "database" / "migrations"

#: Every array/object field whose values SurrealDB 2.6.5 silently drops
#: on schemafull tables (verified against prod INFO FOR TABLE output).
LOSSY_FIELDS = (
    "source_report_ids",
    "manifest",
    "warnings",
    "findings",
    "candidate_causes",
    "diagnostic_steps",
    "corrective_actions",
    "verification_steps",
    "post_repair_events",
)


def _read(name: str) -> str:
    return (MIGRATIONS / name).read_text(encoding="utf-8-sig")


def _body(name: str) -> str:
    """Migration statements without `--` comment lines."""
    return "\n".join(
        line for line in _read(name).splitlines()
        if not line.strip().startswith("--")
    )


def test_migration_29_repairs_llm_tables_to_schemaless():
    text = _read("29.surrealql")
    # OVERWRITE is required: plain DEFINE fails with "already exists" on 2.6.5.
    assert "DEFINE TABLE OVERWRITE llm_knowledge_build SCHEMALESS" in text
    assert "DEFINE TABLE OVERWRITE llm_knowledge_record SCHEMALESS" in text
    assert "REMOVE FIELD" in text
    for field in LOSSY_FIELDS:
        assert field in text, f"migration 29 must address lossy field {field}"
    # No schemafull table definition may remain anywhere in the
    # statements (comments excluded) — including the OVERWRITE form.
    assert "SCHEMAFULL" not in _body("29.surrealql")
    # Row-preserving repair: never drop tables or delete rows.
    assert "REMOVE TABLE" not in text
    assert "DELETE llm_knowledge" not in text


def test_migration_29_down_is_non_destructive_rollback():
    text = _read("29_down.surrealql")
    assert "DELETE llm_knowledge" not in text
    assert "REMOVE TABLE" not in text


def test_migration_29_registered_in_manager():
    manager = (
        REPO_ROOT / "open_notebook" / "database" / "async_migrate.py"
    ).read_text(encoding="utf-8-sig")
    assert "migrations/29.surrealql" in manager
    assert "migrations/29_down.surrealql" in manager
