"""Tests for EntityRecord attribute access and dispatch_pivot.

Covers attribute access, scoped CSS, and _repr_html_.
"""

from __future__ import annotations

import pytest

from resolvekit.core.errors import UnknownCodeSystemError
from resolvekit.core.model.entity import CodeRecord, EntityRecord, NameRecord
from resolvekit.core.model.entity_attributes import (
    KNOWN_PIVOTS,
    _flag_from_iso2,
    dispatch_pivot,
)

# ---------------------------------------------------------------------------
# Fixtures — five canonical countries
# ---------------------------------------------------------------------------


def _make_entity(
    *,
    entity_id: str,
    canonical_name: str,
    iso2: str | None = None,
    iso3: str | None = None,
    numeric: str | None = None,
    continent: str | None = None,
    extra_codes: dict[str, str] | None = None,
    aliases: list[str] | None = None,
) -> EntityRecord:
    """Build a minimal ``EntityRecord`` for testing."""
    codes: list[CodeRecord] = []
    for system, value in (("iso2", iso2), ("iso3", iso3), ("numeric", numeric)):
        if value is not None:
            codes.append(
                CodeRecord(system=system, value=value, value_norm=value.lower())
            )
    for system, value in (extra_codes or {}).items():
        codes.append(CodeRecord(system=system, value=value, value_norm=value.lower()))

    names: list[NameRecord] = []
    for alias in aliases or []:
        names.append(
            NameRecord(
                value=alias,
                value_norm=alias.lower(),
                kind="alias",
                is_preferred=False,
            )
        )

    attrs: dict[str, str | int | float | bool] = {}
    if continent is not None:
        attrs["continent"] = continent

    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        codes=codes,
        names=names,
        attributes=attrs,
    )


US = _make_entity(
    entity_id="country/USA",
    canonical_name="United States",
    iso2="US",
    iso3="USA",
    numeric="840",
    continent="Americas",
    aliases=["United States of America", "USA"],
)

DE = _make_entity(
    entity_id="country/DEU",
    canonical_name="Germany",
    iso2="DE",
    iso3="DEU",
    numeric="276",
    continent="Europe",
    aliases=["Deutschland"],
)

FR = _make_entity(
    entity_id="country/FRA",
    canonical_name="France",
    iso2="FR",
    iso3="FRA",
    numeric="250",
    continent="Europe",
    aliases=["République française"],
)

JP = _make_entity(
    entity_id="country/JPN",
    canonical_name="Japan",
    iso2="JP",
    iso3="JPN",
    numeric="392",
    continent="Asia",
    aliases=["Nippon"],
)

ZA = _make_entity(
    entity_id="country/ZAF",
    canonical_name="South Africa",
    iso2="ZA",
    iso3="ZAF",
    numeric="710",
    continent="Africa",
    aliases=["Republic of South Africa"],
)

_ALL_FIVE = [US, DE, FR, JP, ZA]

# ---------------------------------------------------------------------------
# ISO / attribute round-trips for 5 canonical countries
# ---------------------------------------------------------------------------


def test_entity_iso2_iso3_for_us_de_fr_jp_za() -> None:
    """All five entities expose correct iso2, iso3, numeric, name, continent."""
    expected = [
        ("US", "USA", "840", "United States", "Americas"),
        ("DE", "DEU", "276", "Germany", "Europe"),
        ("FR", "FRA", "250", "France", "Europe"),
        ("JP", "JPN", "392", "Japan", "Asia"),
        ("ZA", "ZAF", "710", "South Africa", "Africa"),
    ]
    for entity, (iso2, iso3, num, name, cont) in zip(_ALL_FIVE, expected, strict=True):
        assert entity.iso2 == iso2
        assert entity.iso3 == iso3
        assert entity.numeric == num
        assert entity.name == name
        assert entity.continent == cont


# ---------------------------------------------------------------------------
# Flag emoji via Unicode regional indicator symbols
# ---------------------------------------------------------------------------


def test_entity_flag_unicode_regional_indicator() -> None:
    """US flag is 🇺🇸 (two regional indicator letters U+1F1FA, U+1F1F8)."""
    assert US.flag == "\U0001f1fa\U0001f1f8"  # 🇺🇸


def test_flag_from_iso2_all_five() -> None:
    """_flag_from_iso2 produces the correct emoji for each country."""
    pairs = [
        ("US", "\U0001f1fa\U0001f1f8"),
        ("DE", "\U0001f1e9\U0001f1ea"),
        ("FR", "\U0001f1eb\U0001f1f7"),
        ("JP", "\U0001f1ef\U0001f1f5"),
        ("ZA", "\U0001f1ff\U0001f1e6"),
    ]
    for code, expected in pairs:
        assert _flag_from_iso2(code) == expected


def test_flag_from_iso2_invalid_raises() -> None:
    """_flag_from_iso2 raises ValueError for non-two-letter inputs."""
    with pytest.raises(ValueError, match="two-letter"):
        _flag_from_iso2("USA")


# ---------------------------------------------------------------------------
# continent read from attributes
# ---------------------------------------------------------------------------


def test_entity_continent_from_attributes() -> None:
    """continent property reads from entity.attributes['continent']."""
    assert US.continent == "Americas"
    assert DE.continent == "Europe"


def test_entity_continent_none_when_absent() -> None:
    """continent is None when the attribute is not set."""
    entity = _make_entity(
        entity_id="test/X",
        canonical_name="No Continent",
        iso2="XX",
    )
    assert entity.continent is None


# ---------------------------------------------------------------------------
# codes_dict and code() helper
# ---------------------------------------------------------------------------


def test_entity_codes_dict_round_trips_via_code_system() -> None:
    """codes_dict and code() return the same values for all systems."""
    for entity in _ALL_FIVE:
        cd = entity.codes_dict
        for system, value in cd.items():
            assert entity.code(system) == value


def test_entity_code_returns_none_for_missing_system() -> None:
    """code() returns None for an unknown code system."""
    assert US.code("wikidata") is None


# ---------------------------------------------------------------------------
# aliases
# ---------------------------------------------------------------------------


def test_entity_aliases_list() -> None:
    """aliases returns non-preferred name values."""
    assert "United States of America" in US.aliases
    assert "Deutschland" in DE.aliases


# ---------------------------------------------------------------------------
# to() pivot method
# ---------------------------------------------------------------------------


def test_entity_to_system_pivot() -> None:
    """entity.to() delegates to dispatch_pivot for known pivots."""
    assert US.to("iso2") == "US"
    assert US.to("iso3") == "USA"
    assert US.to("name") == "United States"
    assert US.to("flag") == US.flag
    assert US.to("continent") == "Americas"


def test_entity_to_unknown_system_raises_with_hint() -> None:
    """entity.to() with an unknown system raises UnknownCodeSystemError."""
    with pytest.raises(UnknownCodeSystemError):
        US.to("nonexistent_system_xyz")


# ---------------------------------------------------------------------------
# _repr_html_ scoped CSS
# ---------------------------------------------------------------------------


def test_entity_repr_html_contains_entity_id() -> None:
    """Rendered HTML contains the entity_id and canonical_name."""
    html = US._repr_html_()
    assert "country/USA" in html
    assert "United States" in html


def test_entity_repr_html_scoped_no_style_leak() -> None:
    """Two entities get different container IDs so styles don't collide."""
    html1 = US._repr_html_()
    html2 = DE._repr_html_()

    # Extract container IDs — both must be present and different
    import re

    ids1 = re.findall(r'id="(rk-[a-z]+-\d+)"', html1)
    ids2 = re.findall(r'id="(rk-[a-z]+-\d+)"', html2)

    assert ids1, "US HTML has no rk-* container id"
    assert ids2, "DE HTML has no rk-* container id"
    assert ids1[0] != ids2[0], "Two renders must get distinct container IDs"

    # Scoping: every CSS selector must start with the container scope
    container_id = ids1[0]
    style_block = re.search(r"<style>(.*?)</style>", html1, re.DOTALL)
    assert style_block is not None
    for line in style_block.group(1).strip().splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("}") and "{" in stripped:
            assert stripped.startswith(f"#{container_id}"), (
                f"CSS selector not scoped: {stripped!r}"
            )


# ---------------------------------------------------------------------------
# dispatch_pivot — isolated unit tests
# ---------------------------------------------------------------------------


def test_dispatch_pivot_entity_record_type() -> None:
    """dispatch_pivot(entity, EntityRecord) returns the entity itself."""
    result = dispatch_pivot(US, EntityRecord)
    assert result is US


def test_dispatch_pivot_isolated_known_pivots() -> None:
    """dispatch_pivot returns correct values for every KNOWN_PIVOT."""
    for pivot in KNOWN_PIVOTS:
        result = dispatch_pivot(US, pivot)
        assert result == getattr(US, pivot)


def test_dispatch_pivot_code_system_branch() -> None:
    """dispatch_pivot routes to codes_dict when target is a code system name."""
    entity = _make_entity(
        entity_id="test/T",
        canonical_name="Test",
        iso2="TS",
        extra_codes={"wikidata": "Q12345"},
    )
    assert dispatch_pivot(entity, "wikidata") == "Q12345"


def test_dispatch_pivot_attribute_branch() -> None:
    """dispatch_pivot routes to entity.attributes for attribute keys."""
    # continent is a KNOWN_PIVOT — test a non-KNOWN_PIVOT attribute instead
    entity2 = EntityRecord(
        entity_id="test/T2",
        entity_type="geo.country",
        canonical_name="Test2",
        canonical_name_norm="test2",
        attributes={"custom_attr": "custom_value"},
    )
    assert dispatch_pivot(entity2, "custom_attr") == "custom_value"


def test_dispatch_pivot_unknown_raises() -> None:
    """dispatch_pivot raises UnknownCodeSystemError for unknown targets."""
    with pytest.raises(UnknownCodeSystemError):
        dispatch_pivot(US, "completely_unknown_pivot_xyz")


def test_dispatch_pivot_wrong_type_raises() -> None:
    """dispatch_pivot raises TypeError for non-str, non-EntityRecord targets."""
    with pytest.raises(TypeError, match="to= must be str"):
        dispatch_pivot(US, 42)  # type: ignore[arg-type]
