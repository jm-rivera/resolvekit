"""Source-agnostic record intake, column-role schema, and namespace guard.

This module owns the first step of the BYOD pipeline:
- ``read_records`` normalises any supported source into a plain ``list[dict]``.
- ``RecordSchema`` resolves the column-to-role mapping from explicit args + inference.
- ``validate_namespace`` guards against path-traversal before any filesystem ops.
"""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

#: Accepted ``data`` shapes for ``read_records``.
#: duck-typed DataFrames (pandas/polars) are passed as ``Any``; they are
#: dispatched via ``hasattr`` checks, never via type imports.
ByodData = Any  # str | Path | list[dict] | dict | DataFrame (duck-typed)


@dataclass
class ByodRecord:
    """Normalised per-row representation the builder consumes."""

    entity_id_seed: str | None
    canonical_name: str | None
    aliases: list[str]
    codes: dict[str, str]
    attrs: dict[str, Any]
    entity_type: str | None


# ---------------------------------------------------------------------------
# Namespace guard
# ---------------------------------------------------------------------------

_DOMAIN_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")


def validate_namespace(namespace: str) -> str:
    """Return *namespace* if it matches the allowed pattern; else raise ValueError.

    The pattern ``^[a-zA-Z0-9][a-zA-Z0-9_-]*$`` prevents path-traversal
    sequences (``../``, ``/``, etc.) from leaking into entity IDs or cache
    directory paths.

    Args:
        namespace: Candidate namespace string.

    Returns:
        The unchanged *namespace* on match.

    Raises:
        ValueError: When *namespace* does not match the pattern.
    """
    if not _DOMAIN_NAME_RE.match(namespace):
        raise ValueError(
            f"Invalid namespace {namespace!r}: must match "
            r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$ (no slashes, dots, or leading dashes)"
        )
    return namespace


# ---------------------------------------------------------------------------
# Empty-cell detection
# ---------------------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    """Return True for None, NaN, and empty/whitespace strings."""
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return isinstance(value, str) and value.strip() == ""


# ---------------------------------------------------------------------------
# read_records
# ---------------------------------------------------------------------------


def _dict_to_rows(mapping: dict) -> list[dict[str, Any]]:
    """Expand a ``{key: record}`` dict into a row list, injecting ``__id__``."""
    rows: list[dict[str, Any]] = []
    for key, record in mapping.items():
        row = dict(record)
        row["__id__"] = key
        rows.append(row)
    return rows


def read_records(data: ByodData) -> list[dict[str, Any]]:
    """Read records from any supported source into a list of row dicts.

    Supported sources:

    - ``list[dict]`` — used as-is.
    - ``dict`` (id → record mapping) — each value becomes a row; the key is
      injected as ``"__id__"`` so callers can promote it to the id column.
    - CSV / JSON / JSONL file path (``str`` or ``pathlib.Path``):
        - ``.csv`` — parsed with ``csv.DictReader``.
        - ``.json`` — loaded as a JSON array or object (same dict-of-dicts rule).
        - ``.jsonl`` — one JSON object per line.
    - Pandas DataFrame: detected via ``hasattr(data, "to_dict")``;
      converted with ``data.to_dict("records")``.
    - Polars DataFrame: detected via ``hasattr(data, "iter_rows")``;
      converted with ``list(data.iter_rows(named=True))``.

    Pandas/polars are never imported; duck-typing keeps them optional.

    Args:
        data: Any of the supported source shapes.

    Returns:
        A ``list`` of plain ``dict[str, Any]`` row objects.

    Raises:
        ValueError: For an unsupported file extension or a malformed file path.
    """
    # Duck-typed DataFrames — check iter_rows first because polars DataFrames
    # expose BOTH iter_rows and to_dict (the latter taking no arguments in polars).
    if hasattr(data, "iter_rows"):
        return list(data.iter_rows(named=True))  # type: ignore[union-attr]

    if hasattr(data, "to_dict") and not isinstance(data, dict):
        return data.to_dict("records")  # type: ignore[union-attr]

    if isinstance(data, list):
        return cast("list[dict[str, Any]]", list(data))

    if isinstance(data, dict):
        return _dict_to_rows(data)

    return _read_file(Path(data))


def _read_file(path: Path) -> list[dict[str, Any]]:
    """Read a CSV, JSON, or JSONL file into a list of row dicts."""
    suffix = path.suffix.lower()

    if suffix == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))

    if suffix == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        if isinstance(raw, dict):
            return _dict_to_rows(raw)
        raise ValueError(
            f"JSON file must contain a list or object of records, got {type(raw).__name__}"
        )

    if suffix == ".jsonl":
        return [
            json.loads(stripped)
            for line in path.read_text(encoding="utf-8").splitlines()
            if (stripped := line.strip())
        ]

    raise ValueError(
        f"Unsupported file extension {suffix!r}. Supported: .csv, .json, .jsonl"
    )


# ---------------------------------------------------------------------------
# RecordSchema
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordSchema:
    """Resolved column-to-role mapping for a record set.

    Attributes:
        id: Column name whose values become entity_id seeds, or None (auto-seq).
        names: Canonical name column(s).
        aliases: Alias column names.
        codes: ``{system: column}`` mapping.
        attrs: List of attribute columns, ``"rest"`` (all unlisted), or None.
        entity_type: Column name (``entity_type_is_literal=False``) or a literal
            string to stamp on every entity (``entity_type_is_literal=True``).
        entity_type_is_literal: True when ``entity_type`` is a fixed string.
    """

    id: str | None
    names: list[str]
    aliases: list[str]
    codes: dict[str, str]  # system -> column
    attrs: list[str] | Literal["rest"] | None
    entity_type: str | None
    entity_type_is_literal: bool

    @classmethod
    def resolve(
        cls,
        rows: list[dict[str, Any]],
        *,
        name: str | list[str],
        id: str | None = None,
        aliases: str | list[str] | None = None,
        codes: list[str] | dict[str, str] | None = None,
        attrs: list[str] | Literal["rest"] | None = None,
        entity_type: str | None = None,
        columns: dict[str, str] | None = None,
        known_systems: frozenset[str] = frozenset(),
    ) -> RecordSchema:
        """Resolve a ``RecordSchema`` from user-supplied role arguments.

        The column universe is derived from the first row of *rows* (or *columns*
        if supplied).  Inference: any column whose name is in *known_systems* is
        treated as a code when *codes* is omitted.  All other columns are dropped
        unless ``attrs="rest"``.

        The ``name`` column(s) are NEVER inferred as attrs, even with
        ``attrs="rest"``.

        Args:
            rows: The already-read row list; used to detect available columns.
            name: Required canonical name column or list of columns.
            id: Column whose values become entity_id seeds.  Auto-sequence when
                ``None``.
            aliases: Alias column name(s).
            codes: Explicit code columns.  List form ``["iso3"]`` → system name
                equals column name.  Dict form ``{"iso3": "country_code"}`` →
                system → column.
            attrs: Explicit attribute columns, ``"rest"`` (keep all unlisted), or
                ``None`` (drop unlisted).
            entity_type: Column name or a fixed literal to stamp on all entities.
            columns: ``{role_or_system: column}`` rename override applied before
                role resolution.
            known_systems: System names used as inference hints for code columns
                when *codes* is omitted.

        Returns:
            A frozen ``RecordSchema`` instance.

        Raises:
            ValueError: When *name* is missing, or a dict-form *codes* column is
                absent from the records.
        """
        if not name:
            raise ValueError("'name' is required and must name at least one column")

        # Determine available columns
        avail: set[str] = set()
        if rows:
            avail = set(rows[0].keys())
        elif columns:
            avail = set(columns.values())

        # Normalise name to a list
        name_cols: list[str] = [name] if isinstance(name, str) else list(name)

        # Normalise aliases
        alias_cols: list[str] = []
        if aliases is not None:
            alias_cols = [aliases] if isinstance(aliases, str) else list(aliases)

        # Apply column rename overrides.
        # columns maps {role-or-system token → actual column name in the data}.
        # avail already holds actual column names (the rename targets), so no
        # recompute of avail is needed — just remap role references to their
        # actual columns before any validation.
        if columns:
            name_cols = [columns.get(c, c) for c in name_cols]
            if id is not None:
                id = columns.get(id, id)
            alias_cols = [columns.get(c, c) for c in alias_cols]
            if entity_type is not None:
                entity_type = columns.get(entity_type, entity_type)

        # Validate the name column(s) exist. A typo here otherwise surfaces far
        # downstream as an opaque "canonical_name is required for minting".
        if avail:
            missing_name = next((c for c in name_cols if c not in avail), None)
            if missing_name is not None:
                raise ValueError(
                    f"name column {missing_name!r} not found in records. "
                    f"Available columns: {sorted(avail)}"
                )

        # Resolve codes dict
        codes_dict: dict[str, str] = {}
        if codes is not None:
            if isinstance(codes, dict):
                # dict form: {system: column} — column already explicit; columns=
                # does not further remap it (user named the column directly).
                # Validate every column is present.
                for system, col in codes.items():
                    if avail and col not in avail:
                        raise ValueError(
                            f"codes column {col!r} (for system {system!r}) not found in "
                            f"records. Available columns: {sorted(avail)}"
                        )
                    codes_dict[system] = col
            else:
                # list form: system key = the token; column = columns.get(token, token)
                # so the system key stays logical (e.g. "iso3") while the data
                # column can be renamed via columns=.
                for col in codes:
                    actual_col = columns.get(col, col) if columns else col
                    if avail and actual_col not in avail:
                        raise ValueError(
                            f"codes column {actual_col!r} not found in records. "
                            f"Available columns: {sorted(avail)}"
                        )
                    codes_dict[col] = actual_col
        else:
            # Inference: columns in known_systems become codes
            for col in avail:
                if col in known_systems:
                    codes_dict[col] = col

        # Resolve entity_type
        et_is_literal = False
        et_value = entity_type
        if entity_type is not None and avail and entity_type not in avail:
            # Treat as a literal stamp — not a column reference
            et_is_literal = True

        # Resolve attrs
        resolved_attrs: list[str] | Literal["rest"] | None
        if attrs == "rest":
            resolved_attrs = "rest"
        elif attrs is not None:
            resolved_attrs = list(attrs)
        else:
            resolved_attrs = None

        return cls(
            id=id,
            names=name_cols,
            aliases=alias_cols,
            codes=codes_dict,
            attrs=resolved_attrs,
            entity_type=et_value,
            entity_type_is_literal=et_is_literal,
        )

    def row_to_record(self, row: dict[str, Any], *, normalizer: Any) -> ByodRecord:
        """Convert one raw row dict into a ``ByodRecord``.

        Empty cells (None, NaN, empty/whitespace strings) are treated as absent
        and excluded from codes, aliases, and attrs.

        Args:
            row: A single row dict from ``read_records``.
            normalizer: A normalizer instance providing ``normalize_name`` and
                ``normalize_code`` methods.

        Returns:
            A ``ByodRecord`` ready for the builder.
        """
        # entity_id seed
        seed: str | None = None
        if self.id is not None:
            raw_id = row.get(self.id)
            if not _is_empty(raw_id):
                seed = str(raw_id)
        elif "__id__" in row:
            # dict-input key injected by read_records
            raw_id = row["__id__"]
            if not _is_empty(raw_id):
                seed = str(raw_id)

        # canonical name — first non-empty name column wins
        canonical_name: str | None = None
        for col in self.names:
            val = row.get(col)
            if not _is_empty(val):
                canonical_name = str(val)
                break

        # aliases
        aliases: list[str] = []
        for col in self.aliases:
            val = row.get(col)
            if not _is_empty(val):
                aliases.append(str(val))

        # codes
        codes: dict[str, str] = {}
        for system, col in self.codes.items():
            val = row.get(col)
            if not _is_empty(val):
                codes[system] = str(val)

        # attrs
        spoken_for: set[str] = (
            set(self.names) | set(self.aliases) | set(self.codes.values()) | {"__id__"}
        )
        if self.id is not None:
            spoken_for.add(self.id)
        if self.entity_type is not None and not self.entity_type_is_literal:
            spoken_for.add(self.entity_type)

        raw_attrs: dict[str, Any] = {}
        if self.attrs == "rest":
            for col, val in row.items():
                if col not in spoken_for and not _is_empty(val):
                    raw_attrs[col] = val
        elif self.attrs is not None:
            for col in self.attrs:
                val = row.get(col)
                if not _is_empty(val):
                    raw_attrs[col] = val

        # entity_type
        entity_type: str | None = None
        if self.entity_type is not None:
            if self.entity_type_is_literal:
                entity_type = self.entity_type
            else:
                val = row.get(self.entity_type)
                if not _is_empty(val):
                    entity_type = str(val)

        return ByodRecord(
            entity_id_seed=seed,
            canonical_name=canonical_name,
            aliases=aliases,
            codes=codes,
            attrs=raw_attrs,
            entity_type=entity_type,
        )


# ---------------------------------------------------------------------------
# normalize_records — canonical per-row dict the builder consumes
# ---------------------------------------------------------------------------


def normalize_records(
    rows: list[dict[str, Any]],
    schema: RecordSchema,
    *,
    normalizer: Any,
) -> list[ByodRecord]:
    """Convert all rows in *rows* to ``ByodRecord`` instances.

    Applies ``RecordSchema.row_to_record`` to each row.  Rows where the
    canonical name resolves to empty are still returned (the builder decides
    what to do with them).

    Args:
        rows: Raw row dicts from ``read_records``.
        schema: Resolved ``RecordSchema``.
        normalizer: Normalizer instance with ``normalize_name``/``normalize_code``.

    Returns:
        List of ``ByodRecord`` objects in the same order as *rows*.
    """
    return [schema.row_to_record(row, normalizer=normalizer) for row in rows]
