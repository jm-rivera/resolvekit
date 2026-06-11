"""Tests for per-call ``to=`` name-grammar support and list-chain error.

Coverage:
- resolve(to="name:fr") → localized name string
- resolve(to="name:es") → localized name string
- bulk(to="name:fr") → series of localized names
- EntityRecord.to("name:fr") → localized name string
- Per-entity miss: valid grammar, entity lacks that lang → None (not raise)
- Malformed grammar via resolve: resolve(to="name:") → UnknownOutputError
- Malformed grammar via entity.to(): entity.to("name:") → UnknownOutputError
- Per-call list: resolve(to=["iso3","name"]) → TypeError with directive hint
- Regression: existing view/default_to grammar + chain still works
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.errors import UnknownOutputError
from resolvekit.core.model.entity import CodeRecord, EntityRecord, NameRecord

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_geo() -> Resolver:
    """Resolver over geo.countries — no default output."""
    return Resolver.from_modules(module_ids=["geo.countries"])


# ---------------------------------------------------------------------------
# Helper: build a minimal EntityRecord
# ---------------------------------------------------------------------------


def _make_entity(
    *,
    entity_id: str = "country/TEST",
    canonical_name: str = "Test",
    codes: list[tuple[str, str]] | None = None,
    names: list[NameRecord] | None = None,
) -> EntityRecord:
    code_records = [
        CodeRecord(system=sys, value=val, value_norm=val.lower())
        for sys, val in (codes or [])
    ]
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        names=names or [],
        codes=code_records,
    )


def _name(
    value: str,
    *,
    kind: str = "alias",
    lang: str | None = None,
    script: str | None = None,
    is_preferred: bool = False,
) -> NameRecord:
    return NameRecord(
        value=value,
        value_norm=value.lower(),
        kind=kind,
        lang=lang,
        script=script,
        is_preferred=is_preferred,
    )


# ---------------------------------------------------------------------------
# resolve(to="name:<lang>") — per-call grammar
# ---------------------------------------------------------------------------


class TestResolveNameGrammarPerCall:
    def test_germany_french_name(self, r_geo: Resolver) -> None:
        """resolve(to='name:fr') returns the French name 'Allemagne'."""
        result = r_geo.resolve("Germany", to="name:fr")
        assert result == "Allemagne"

    def test_spain_spanish_name(self, r_geo: Resolver) -> None:
        """resolve(to='name:es') returns the Spanish name 'España'."""
        result = r_geo.resolve("Spain", to="name:es")
        assert result == "España"

    def test_no_match_returns_none(self, r_geo: Resolver) -> None:
        """Unresolved input with name grammar → None (not raise)."""
        result = r_geo.resolve("zzz_not_a_place_xyzzy", to="name:fr")
        assert result is None

    def test_entity_lacks_lang_returns_none(self, r_geo: Resolver) -> None:
        """Per-entity miss: entity lacks the requested lang → None, not raise."""
        # Use an unlikely lang code that the data won't have.
        result = r_geo.resolve("Germany", to="name:tlh")
        assert result is None


# ---------------------------------------------------------------------------
# bulk(to="name:fr") — per-call grammar for batch
# ---------------------------------------------------------------------------


class TestBulkNameGrammarPerCall:
    def test_bulk_french_names_series(self, r_geo: Resolver) -> None:
        """bulk(to='name:fr') returns French names for Germany and France."""
        result = r_geo.bulk(values=["Germany", "France"], to="name:fr")
        values = list(result)
        assert "Allemagne" in values
        assert "France" in values  # French name of France is also "France"


# ---------------------------------------------------------------------------
# EntityRecord.to("name:fr") — model-layer per-entity grammar
# ---------------------------------------------------------------------------


class TestEntityRecordToNameGrammar:
    def test_entity_to_french_name(self, r_geo: Resolver) -> None:
        """entity.to('name:fr') returns the French name."""
        result = r_geo.resolve("Germany", to=None, include_entity=True)
        assert result.is_resolved
        entity = result.entity
        assert entity is not None
        fr_name = entity.to("name:fr")
        assert fr_name == "Allemagne"

    def test_entity_to_name_lang_miss_returns_none(self) -> None:
        """entity.to('name:tlh') → None when the entity has no Klingon names."""
        entity = _make_entity(
            canonical_name="Germany",
            names=[_name("Allemagne", lang="fr")],
        )
        assert entity.to("name:tlh") is None

    def test_entity_to_name_miss_does_not_raise(self) -> None:
        """A valid grammar token for a missing lang → None (quiet miss)."""
        entity = _make_entity(
            canonical_name="Germany",
            names=[_name("Allemagne", lang="fr")],
        )
        # Valid grammar, entity simply lacks 'zh' → None
        assert entity.to("name:zh") is None

    def test_entity_to_name_fr_hit(self) -> None:
        """Hand-built entity with French name → entity.to('name:fr') returns it."""
        entity = _make_entity(
            canonical_name="Germany",
            names=[_name("Allemagne", lang="fr", is_preferred=True)],
        )
        assert entity.to("name:fr") == "Allemagne"


# ---------------------------------------------------------------------------
# Malformed grammar raises UnknownOutputError (loud — programming error)
# ---------------------------------------------------------------------------


class TestMalformedGrammarRaises:
    def test_resolve_malformed_name_empty_middle(self, r_geo: Resolver) -> None:
        """resolve(to='name:') → UnknownOutputError (not None, not UnknownCodeSystemError)."""
        with pytest.raises(UnknownOutputError):
            r_geo.resolve("Germany", to="name:")

    def test_entity_to_malformed_name_empty_middle(self) -> None:
        """entity.to('name:') → UnknownOutputError (not None)."""
        entity = _make_entity(
            canonical_name="Germany",
            names=[_name("Allemagne", lang="fr")],
        )
        with pytest.raises(UnknownOutputError):
            entity.to("name:")

    def test_resolve_malformed_name_too_many_parts(self, r_geo: Resolver) -> None:
        """resolve(to='name:fr:Latn:extra') → UnknownOutputError."""
        with pytest.raises(UnknownOutputError):
            r_geo.resolve("Germany", to="name:fr:Latn:extra")


# ---------------------------------------------------------------------------
# Per-call list to= raises TypeError with directive hint (chains are view-only)
# ---------------------------------------------------------------------------


class TestPerCallListRaisesTypeError:
    def test_resolve_list_to_raises_type_error(self, r_geo: Resolver) -> None:
        """resolve(to=['iso3','name']) → TypeError (chains stay view/default_to-only)."""
        with pytest.raises(TypeError):
            r_geo.resolve("Germany", to=["iso3", "name"])  # type: ignore[arg-type]

    def test_resolve_list_to_error_has_hint(self, r_geo: Resolver) -> None:
        """TypeError.hint mentions rk.to or default_to."""
        try:
            r_geo.resolve("Germany", to=["iso3", "name"])  # type: ignore[arg-type]
        except TypeError as exc:
            hint = getattr(exc, "hint", None)
            assert hint is not None, "TypeError should carry a .hint attribute"
            assert "rk.to" in hint or "default_to" in hint, (
                f"Hint should mention 'rk.to' or 'default_to', got: {hint!r}"
            )
        else:
            pytest.fail("Expected TypeError was not raised")

    def test_resolve_list_to_message_is_directive(self, r_geo: Resolver) -> None:
        """TypeError message directs caller to rk.to([...]) or default_to=[...]."""
        try:
            r_geo.resolve("Germany", to=["iso3", "name"])  # type: ignore[arg-type]
        except TypeError as exc:
            msg = str(exc)
            assert "rk.to" in msg or "default_to" in msg, (
                f"Message should direct caller, got: {msg!r}"
            )
        else:
            pytest.fail("Expected TypeError was not raised")


# ---------------------------------------------------------------------------
# Regression: existing view/default_to grammar + chain path still works
# ---------------------------------------------------------------------------


class TestRegressionViewPathUnchanged:
    def test_view_name_fr_resolve(self, r_geo: Resolver) -> None:
        """rk.to('name:fr').resolve('Germany') == 'Allemagne' (unchanged)."""
        view = r_geo.to("name:fr")
        assert view.resolve("Germany") == "Allemagne"

    def test_view_chain_falls_through(self, r_geo: Resolver) -> None:
        """rk.to(['iso3','name']).resolve() still works (chain via view)."""
        view = r_geo.to(["iso3", "name"])
        result = view.resolve("Germany")
        assert result == "DEU"

    def test_default_to_name_fr_works(self) -> None:
        """Resolver.from_modules(default_to='name:fr') still works."""
        r = Resolver.from_modules(module_ids=["geo.countries"], default_to="name:fr")
        assert r.resolve("Germany") == "Allemagne"

    def test_default_to_chain_iso3_name_works(self) -> None:
        """Resolver.from_modules(default_to=['iso3','name']) still works."""
        r = Resolver.from_modules(
            module_ids=["geo.countries"], default_to=["iso3", "name"]
        )
        assert r.resolve("Germany") == "DEU"
        # European Union has no iso3, falls through to name.
        result = r.resolve("European Union")
        assert isinstance(result, str) and len(result) > 0
