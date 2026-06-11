"""Crosswalk value-object for bulk() short-circuit resolution.

A ``Crosswalk`` is an immutable value→entity_id mapping that, when passed as
``crosswalk=`` to ``bulk()``, causes matched values to skip name resolution
entirely (bypassing code-detection, ``on_ambiguous``, ``not_found``, and
``from_system``).

``IGNORE`` sentinel entries map a value to null output (``None``) regardless of
the ``to=`` target.

Public surface
--------------
``IGNORE``        — module-level singleton re-exported as ``rk.IGNORE``
``Crosswalk``     — frozen dataclass; construct via ``from_dict`` / ``from_csv``

Internal sentinels (used by the bulk engine in ``bulk.py``)
-----------------------------------------------------------
``_MISSING``      — returned by ``_get`` when the value is absent from the
                    crosswalk, distinguishing absence from IGNORE (``None``).
"""

from __future__ import annotations

import copy
import csv
import re
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Internal sentinel — absence marker returned by _get
# ---------------------------------------------------------------------------

# Returned by Crosswalk._get when the value is not in the crosswalk; distinguishes
# "not found" from "IGNORE" (None). The bulk engine imports this rather than
# re-defining it, so the `is _MISSING` identity check holds across modules.
_MISSING: object = object()


# ---------------------------------------------------------------------------
# IGNORE sentinel
# ---------------------------------------------------------------------------


class _Ignore:
    """Singleton sentinel: a crosswalk entry that maps a value to null output.

    Pass ``IGNORE`` (the module-level instance) as a dict value to
    ``Crosswalk.from_dict`` to mark a value as intentionally unmappable.
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "rk.IGNORE"


# Crosswalk sentinel that maps a value to None output. Re-exported as rk.IGNORE
# from the top-level package.
IGNORE: _Ignore = _Ignore()

# ---------------------------------------------------------------------------
# Reserved CSV token (IGNORE serialisation in the entity_id column)
# ---------------------------------------------------------------------------

_IGNORE_TOKEN = "IGNORE"

# ---------------------------------------------------------------------------
# Structural validation
# ---------------------------------------------------------------------------

_ENTITY_ID_RE = re.compile(r"^[^/]+/[^/]+$")


def _validate_entity_id(value: str, eid: str) -> None:
    """Raise ValueError when *eid* is not a well-formed ``pack/code`` entity-id."""
    if not _ENTITY_ID_RE.fullmatch(eid):
        raise ValueError(
            f"crosswalk entry {value!r} -> {eid!r} is not a well-formed entity-id"
            " (expected 'pack/code')"
        )


# ---------------------------------------------------------------------------
# Crosswalk frozen dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Crosswalk:
    """A complete value→entity_id mapping that short-circuits ``bulk()`` resolution.

    Construction
    ------------
    Use ``from_dict`` or ``from_csv``; do not instantiate directly.

    The ``_mapping`` field is the internal dict (value → entity_id or None).
    ``None`` encodes an IGNORE entry; the external IGNORE sentinel is normalised
    to ``None`` at construction.

    Note: ``Crosswalk`` is not hashable (the internal dict field prevents it).
    Do not use as a dict key or set member.

    Attributes
    ----------
    _mapping:
        Internal ``{value: entity_id | None}`` dict.  ``None`` == IGNORE.
    strict:
        When ``True`` (default), ``bulk()`` raises ``CrosswalkError`` if any
        mapped entity-id does not exist in the loaded data.  When ``False``,
        unknown ids produce per-value misses that follow the ``not_found``
        policy.
    """

    _mapping: dict[str, str | None]
    strict: bool = True

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(
        cls,
        mapping: dict[str, str | _Ignore | None],  # type: ignore[type-arg]
        *,
        strict: bool = True,
    ) -> Crosswalk:
        """Build a ``Crosswalk`` from a plain dict.

        Parameters
        ----------
        mapping:
            ``{value: entity_id | IGNORE | None}``.  ``IGNORE`` and ``None``
            are both treated as "ignore this value" (normalised to internal
            ``None``).  Entity-id strings are structurally validated (must
            match ``pack/code``).
        strict:
            Carried onto the ``Crosswalk`` instance; controls apply-time
            existence validation in ``bulk()``.

        Raises
        ------
        ValueError
            When any entity-id string is malformed.
        """
        internal: dict[str, str | None] = {}
        for value, eid in mapping.items():
            if eid is None or isinstance(eid, _Ignore):
                internal[value] = None
            else:
                _validate_entity_id(value, eid)
                internal[value] = eid
        # Deep-copy so external mutation cannot leak in.
        return cls(_mapping=copy.deepcopy(internal), strict=strict)

    @classmethod
    def from_csv(cls, path: str | Path, *, strict: bool = True) -> Crosswalk:
        """Load a ``Crosswalk`` from a CSV file previously written by ``to_csv``.

        The CSV must have exactly the columns ``value`` and ``entity_id``
        (additional columns are ignored).  In the ``entity_id`` column:

        - ``IGNORE`` (case-sensitive) or an empty cell → IGNORE entry.
        - Anything else → treated as an entity-id and structurally validated.

        Parameters
        ----------
        path:
            File path; opened as UTF-8 text.
        strict:
            Carried onto the resulting ``Crosswalk`` instance.

        Raises
        ------
        ValueError
            When required columns are missing, a ``value`` appears more than
            once, or an entity-id string is malformed.
        """
        path = Path(path)
        internal: dict[str, str | None] = {}
        with path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames is None or not {
                "value",
                "entity_id",
            }.issubset(set(reader.fieldnames)):
                got = list(reader.fieldnames) if reader.fieldnames else []
                raise ValueError(
                    f"crosswalk CSV must have columns 'value','entity_id'; got {got}"
                )
            for row in reader:
                value = row["value"]
                raw_eid = row["entity_id"].strip()
                if value in internal:
                    raise ValueError(f"crosswalk CSV has duplicate value {value!r}")
                if raw_eid in ("", _IGNORE_TOKEN):
                    internal[value] = None
                else:
                    _validate_entity_id(value, raw_eid)
                    internal[value] = raw_eid
        return cls(_mapping=internal, strict=strict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_csv(self, path: str | Path) -> None:
        """Write the crosswalk to a CSV file.

        The file has columns ``value``, ``entity_id``.  IGNORE entries are
        written as the literal token ``IGNORE`` in the ``entity_id`` column.
        Readable by ``from_csv``.

        Parameters
        ----------
        path:
            Destination file path; created / overwritten as UTF-8 text.
        """
        path = Path(path)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=["value", "entity_id"])
            writer.writeheader()
            for value, eid in self._mapping.items():
                writer.writerow(
                    {
                        "value": value,
                        "entity_id": _IGNORE_TOKEN if eid is None else eid,
                    }
                )

    # ------------------------------------------------------------------
    # Membership protocol
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of entries in the crosswalk."""
        return len(self._mapping)

    def __contains__(self, value: object) -> bool:
        """Return ``True`` when *value* is a key in the crosswalk."""
        return value in self._mapping

    # ------------------------------------------------------------------
    # Internal lookup (used by the bulk engine)
    # ------------------------------------------------------------------

    def _get(self, value: str) -> str | None | object:
        """Look up *value* in the crosswalk.

        Returns
        -------
        str
            The entity-id for a mapped entry.
        None
            The entry is an IGNORE mapping.
        ``_MISSING``
            The value is not in the crosswalk at all.
        """
        if value not in self._mapping:
            return _MISSING
        return self._mapping[value]  # str or None
