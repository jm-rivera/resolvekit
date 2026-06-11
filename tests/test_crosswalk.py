"""Tests for Crosswalk value-object and CrosswalkError.

Covers:
- Construction via from_dict (basic, IGNORE sentinel, None-as-IGNORE, malformed id)
- to_csv / from_csv round-trip (including IGNORE survival and empty-cell handling)
- Duplicate value detection in from_csv
- Missing required columns in from_csv
- strict= carried on instance
- CrosswalkError offender list
"""

from __future__ import annotations

import pathlib

import pytest

from resolvekit.core.errors import CrosswalkError
from resolvekit.core.model.crosswalk import _MISSING, IGNORE, Crosswalk

# ---------------------------------------------------------------------------
# from_dict
# ---------------------------------------------------------------------------


def test_from_dict_basic(tmp_path: pathlib.Path) -> None:
    """Basic construction: __len__ and __contains__ reflect the mapping."""
    cw = Crosswalk.from_dict({"Congo": "country/COD", "France": "country/FRA"})
    assert len(cw) == 2
    assert "Congo" in cw
    assert "France" in cw
    assert "Germany" not in cw


def test_from_dict_ignore_sentinel() -> None:
    """IGNORE sentinel normalises to internal None; value is still in the crosswalk."""
    cw = Crosswalk.from_dict({"X": IGNORE})
    assert "X" in cw
    assert cw._get("X") is None  # internal IGNORE representation


def test_from_dict_none_is_ignore() -> None:
    """Passing None as a value is equivalent to passing IGNORE."""
    cw = Crosswalk.from_dict({"X": None})
    assert "X" in cw
    assert cw._get("X") is None


def test_from_dict_malformed_entity_id_raises() -> None:
    """An entity-id without a '/' (e.g. a bare ISO3) must be rejected at construction."""
    with pytest.raises(ValueError, match="not a well-formed entity-id"):
        Crosswalk.from_dict({"Congo": "COD"})


def test_from_dict_entity_id_no_left_side_raises() -> None:
    """Entity-id with nothing before the slash is malformed."""
    with pytest.raises(ValueError, match="not a well-formed entity-id"):
        Crosswalk.from_dict({"X": "/COD"})


def test_from_dict_entity_id_no_right_side_raises() -> None:
    """Entity-id with nothing after the slash is malformed."""
    with pytest.raises(ValueError, match="not a well-formed entity-id"):
        Crosswalk.from_dict({"X": "country/"})


def test_from_dict_deep_copy_prevents_mutation() -> None:
    """External mutation of the input dict does not affect the Crosswalk."""
    mapping: dict[str, str | None] = {"Congo": "country/COD"}
    cw = Crosswalk.from_dict(mapping)
    mapping["Congo"] = "country/FRA"
    assert cw._get("Congo") == "country/COD"


# ---------------------------------------------------------------------------
# _get return values
# ---------------------------------------------------------------------------


def test_get_hit_returns_entity_id() -> None:
    """_get returns the entity-id string for a mapped entry."""
    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    assert cw._get("Congo") == "country/COD"


def test_get_absent_returns_missing_sentinel() -> None:
    """_get returns _MISSING (not None) for a value not in the crosswalk."""
    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    result = cw._get("Germany")
    assert result is _MISSING


def test_get_ignore_returns_none() -> None:
    """_get returns None (not _MISSING) for an IGNORE entry."""
    cw = Crosswalk.from_dict({"X": IGNORE})
    assert cw._get("X") is None


# ---------------------------------------------------------------------------
# to_csv / from_csv round-trip
# ---------------------------------------------------------------------------


def test_to_csv_from_csv_roundtrip_identity(tmp_path: pathlib.Path) -> None:
    """to_csv + from_csv round-trip preserves _mapping and strict.

    IGNORE entries must survive: emitted as the 'IGNORE' token, re-read as None.
    """
    original = Crosswalk.from_dict(
        {"Congo": "country/COD", "Ruritania": IGNORE, "France": "country/FRA"},
        strict=False,
    )
    csv_path = tmp_path / "cw.csv"
    original.to_csv(csv_path)

    loaded = Crosswalk.from_csv(csv_path, strict=False)

    assert loaded._mapping == original._mapping
    assert loaded.strict is False
    # Explicitly confirm IGNORE survived
    assert loaded._get("Ruritania") is None
    assert loaded._get("Congo") == "country/COD"


def test_from_csv_empty_cell_is_ignore(tmp_path: pathlib.Path) -> None:
    """An empty entity_id cell in the CSV is treated as IGNORE on read."""
    csv_path = tmp_path / "cw.csv"
    csv_path.write_text("value,entity_id\nX,\n", encoding="utf-8")

    cw = Crosswalk.from_csv(csv_path)
    assert cw._get("X") is None


def test_from_csv_dup_value_raises(tmp_path: pathlib.Path) -> None:
    """Duplicate value rows in a CSV must be rejected with a clear message."""
    csv_path = tmp_path / "dup.csv"
    csv_path.write_text(
        "value,entity_id\nCongo,country/COD\nCongo,country/COG\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate value"):
        Crosswalk.from_csv(csv_path)


def test_from_csv_missing_columns_raises(tmp_path: pathlib.Path) -> None:
    """A CSV that lacks required columns raises ValueError with a helpful message."""
    csv_path = tmp_path / "bad.csv"
    csv_path.write_text("name,id\nCongo,country/COD\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must have columns"):
        Crosswalk.from_csv(csv_path)


def test_from_csv_missing_value_column_raises(tmp_path: pathlib.Path) -> None:
    """A CSV with entity_id but no value column raises ValueError."""
    csv_path = tmp_path / "bad2.csv"
    csv_path.write_text("entity_id\ncountry/COD\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must have columns"):
        Crosswalk.from_csv(csv_path)


def test_from_csv_extra_columns_accepted(tmp_path: pathlib.Path) -> None:
    """Extra columns beyond value and entity_id are silently ignored."""
    csv_path = tmp_path / "extra.csv"
    csv_path.write_text(
        "value,entity_id,note\nCongo,country/COD,approved\n",
        encoding="utf-8",
    )
    cw = Crosswalk.from_csv(csv_path)
    assert cw._get("Congo") == "country/COD"


# ---------------------------------------------------------------------------
# strict carried on instance
# ---------------------------------------------------------------------------


def test_strict_carried_on_instance_via_from_dict() -> None:
    """strict=False is stored on the Crosswalk instance."""
    cw = Crosswalk.from_dict({"Congo": "country/COD"}, strict=False)
    assert cw.strict is False


def test_strict_carried_on_instance_via_from_csv(tmp_path: pathlib.Path) -> None:
    """from_csv(..., strict=False).strict is False."""
    csv_path = tmp_path / "cw.csv"
    csv_path.write_text("value,entity_id\nCongo,country/COD\n", encoding="utf-8")
    cw = Crosswalk.from_csv(csv_path, strict=False)
    assert cw.strict is False


def test_strict_default_is_true() -> None:
    """strict defaults to True."""
    cw = Crosswalk.from_dict({"Congo": "country/COD"})
    assert cw.strict is True


# ---------------------------------------------------------------------------
# CrosswalkError
# ---------------------------------------------------------------------------


def test_crosswalk_error_lists_offenders() -> None:
    """CrosswalkError stores and exposes the full offender list."""
    err = CrosswalkError(["country/AAA", "country/BBB"])
    assert err.offenders == ["country/AAA", "country/BBB"]


def test_crosswalk_error_message_includes_count() -> None:
    """The error message states how many unknown ids were found."""
    err = CrosswalkError(["a/b", "c/d"])
    assert "2 unknown entity-id(s)" in str(err)


def test_crosswalk_error_message_includes_preview() -> None:
    """The error message includes a preview of the offending ids."""
    err = CrosswalkError(["a/b"])
    assert "'a/b'" in str(err)


def test_crosswalk_error_hint_mentions_strict_false() -> None:
    """The hint text names strict=False as the escape route."""
    err = CrosswalkError(["a/b"])
    assert err.hint is not None
    assert "strict=False" in err.hint


def test_crosswalk_error_truncates_long_preview() -> None:
    """Preview is capped at 10 offenders regardless of list length."""
    offenders = [f"country/{i:03d}" for i in range(20)]
    err = CrosswalkError(offenders)
    # All 20 stored on .offenders
    assert len(err.offenders) == 20
    # But preview in the message shows at most 10
    preview_part = str(err).split("[")[1].split("]")[0]
    # count commas in the repr list — 9 commas = 10 items
    assert preview_part.count(",") <= 9


def test_crosswalk_error_is_resolver_error() -> None:
    """CrosswalkError is a ResolverError subclass."""
    from resolvekit.core.errors_base import ResolverError

    err = CrosswalkError(["a/b"])
    assert isinstance(err, ResolverError)
