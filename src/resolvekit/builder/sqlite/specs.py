"""Data-driven INSERT spec for the four public SQLite tables.

Mirrors the ``TABLE_DIFF_SPECS`` pattern from ``diff.py``.  Each entry carries
the per-table default conflict policy and the frozen column list so every INSERT
site can be driven by the same spec rather than hand-rolling column lists.
"""

from __future__ import annotations

from typing import TypedDict

from resolvekit.builder.sqlite.constants import SQLITE_IDENTIFIER_RE


class _InsertSpec(TypedDict):
    conflict: str
    columns: list[str]


TABLE_INSERT_SPECS: dict[str, _InsertSpec] = {
    "entities": {
        "conflict": "REPLACE",
        "columns": [
            "entity_id",
            "entity_type",
            "canonical_name",
            "canonical_name_norm",
            "valid_from",
            "valid_until",
            "attrs_json",
        ],
    },
    "names": {
        "conflict": "IGNORE",
        "columns": [
            "entity_id",
            "name_kind",
            "value",
            "value_norm",
            "lang",
            "script",
            "is_preferred",
        ],
    },
    "codes": {
        "conflict": "REPLACE",
        "columns": [
            "entity_id",
            "system",
            "value",
            "value_norm",
        ],
    },
    "relations": {
        "conflict": "IGNORE",
        "columns": [
            "entity_id",
            "relation_type",
            "target_id",
            "valid_from",
            "valid_until",
        ],
    },
}

_VALID_CONFLICTS = {"REPLACE", "IGNORE"}


def insert_prefix(table: str, *, conflict: str | None = None) -> str:
    """Return ``INSERT OR <conflict> INTO <table>(<cols>)`` with validated identifiers.

    ``table`` must be a key in ``TABLE_INSERT_SPECS``.  ``conflict`` overrides
    the table's default when supplied; it must be one of ``"REPLACE"`` or
    ``"IGNORE"``.  All identifier names are validated against
    ``SQLITE_IDENTIFIER_RE`` — only the hardcoded spec values reach the SQL
    string; no caller-supplied data is interpolated.
    """
    spec = TABLE_INSERT_SPECS.get(table)
    if spec is None:
        raise ValueError(f"Unknown table: {table!r}")

    resolved_conflict = conflict if conflict is not None else spec["conflict"]
    if resolved_conflict not in _VALID_CONFLICTS:
        raise ValueError(
            f"conflict must be one of {_VALID_CONFLICTS!r}, got {resolved_conflict!r}"
        )

    # Validate the table identifier (hardcoded via spec key, but gated for safety).
    if SQLITE_IDENTIFIER_RE.fullmatch(table) is None:
        raise ValueError(f"Invalid SQL identifier: {table!r}")

    validated_cols: list[str] = []
    for col in spec["columns"]:
        if SQLITE_IDENTIFIER_RE.fullmatch(col) is None:
            raise ValueError(f"Invalid SQL identifier: {col!r}")
        validated_cols.append(f'"{col}"')

    cols_sql = ", ".join(validated_cols)
    return f'INSERT OR {resolved_conflict} INTO "{table}"({cols_sql})'
