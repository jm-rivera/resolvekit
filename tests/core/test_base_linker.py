"""Tests for BaseLinker: open gate, "name" strategy, ordered fallback."""

from __future__ import annotations

from collections.abc import Iterator

from resolvekit.core.linking.base_linker import BaseLinker
from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore

# ---------------------------------------------------------------------------
# Minimal mock store
# ---------------------------------------------------------------------------


class _MockStore(EntityStore):
    """In-memory store for linker unit tests."""

    def __init__(
        self,
        codes: dict[tuple[str, str], list[str]],
        names: dict[str, list[str]],
        systems: frozenset[str],
    ) -> None:
        # codes: (system, value_norm) -> [entity_id, ...]
        self._codes = codes
        # names: value_norm -> [entity_id, ...]
        self._names = names
        self._systems = systems

    def code_systems(self) -> frozenset[str]:
        return self._systems

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        return self._codes.get((system, value_norm), [])

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return self._names.get(value_norm, [])

    def get_entity(self, entity_id: str) -> EntityRecord | None:  # pragma: no cover
        return None

    def search_fulltext(
        self, query_norm: str, fields: set[str] | None = None, limit: int = 10
    ) -> list[tuple[str, float, int]]:  # pragma: no cover
        return []

    def bulk_get_entities(
        self, entity_ids: list[str]
    ) -> dict[str, EntityRecord]:  # pragma: no cover
        return {}

    def iter_names(
        self,
        *,
        entity_type_prefixes: frozenset[str] | None = None,
        with_name_meta: bool = False,
    ) -> (
        Iterator[tuple[str, str]] | Iterator[tuple[str, str, str, str]]
    ):  # pragma: no cover
        return iter([])


def _store_with(
    *,
    iso3: dict[str, str] | None = None,
    wikidata: dict[str, str] | None = None,
    names: dict[str, str] | None = None,
    extra_systems: frozenset[str] = frozenset(),
) -> _MockStore:
    """Build a mock store with the given fixtures."""
    codes: dict[tuple[str, str], list[str]] = {}
    systems: set[str] = set(extra_systems)

    if iso3:
        systems.add("iso3")
        for val, eid in iso3.items():
            codes[("iso3", val)] = [eid]

    if wikidata:
        systems.add("wikidata")
        for val, eid in wikidata.items():
            codes[("wikidata", val)] = [eid]

    name_map: dict[str, list[str]] = {}
    if names:
        for val_norm, eid in names.items():
            name_map[val_norm] = [eid]

    return _MockStore(codes=codes, names=name_map, systems=frozenset(systems))


# ---------------------------------------------------------------------------
# Tests: open gate (code systems)
# ---------------------------------------------------------------------------


class TestOpenGate:
    def test_system_in_store_accepts_via_live_lookup(self):
        """A system present in the store (but not in any subclass frozenset) links."""
        store = _store_with(wikidata={"Q142": "geo/FRA"})
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"wikidata": "Q142"},
            link_keys=["wikidata"],
            base_store=store,
        )

        assert result.is_success
        assert result.entity_id == "geo/FRA"

    def test_system_in_store_accepts_via_precomputed_valid_systems(self):
        """Passing valid_systems avoids the live code_systems() call."""
        store = _store_with(wikidata={"Q142": "geo/FRA"})
        linker = BaseLinker()

        # Pass pre-computed set (no live SELECT DISTINCT needed)
        result = linker.resolve_link(
            overlay_row={"wikidata": "Q142"},
            link_keys=["wikidata"],
            base_store=store,
            valid_systems=frozenset({"wikidata"}),
        )

        assert result.is_success
        assert result.entity_id == "geo/FRA"

    def test_unknown_key_returns_invalid_key(self):
        """A key absent from the store and absent from valid_systems → invalid_key."""
        store = _store_with(iso3={"FRA": "geo/FRA"})
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"bogus_system": "X"},
            link_keys=["bogus_system"],
            base_store=store,
        )

        assert result.status == "invalid_key"
        assert "bogus_system" in (result.message or "")

    def test_unknown_key_not_in_valid_systems_returns_invalid_key(self):
        """A key absent from an explicitly supplied valid_systems → invalid_key."""
        store = _store_with(iso3={"FRA": "geo/FRA"})
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"bogus": "X"},
            link_keys=["bogus"],
            base_store=store,
            valid_systems=frozenset({"iso3"}),
        )

        assert result.status == "invalid_key"

    def test_empty_link_keys_returns_not_found(self):
        """No keys to try → not_found."""
        store = _store_with(iso3={"FRA": "geo/FRA"})
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"iso3": "FRA"},
            link_keys=[],
            base_store=store,
        )

        assert result.status == "not_found"


# ---------------------------------------------------------------------------
# Tests: "name" strategy
# ---------------------------------------------------------------------------


class TestNameStrategy:
    def test_name_key_links_via_lookup_name_exact(self):
        """``"name"`` key triggers an exact normalised-name lookup."""
        store = _store_with(names={"france": "geo/FRA"})
        linker = BaseLinker()

        # Inject normalised name under __name__ (as link_and_add would)
        result = linker.resolve_link(
            overlay_row={"__name__": "france"},
            link_keys=["name"],
            base_store=store,
        )

        assert result.is_success
        assert result.entity_id == "geo/FRA"

    def test_name_key_ambiguous_when_multiple_matches(self):
        """Two entities sharing the same normalised name → ambiguous."""
        store = _MockStore(
            codes={},
            names={"springfield": ["geo/SPF-IL", "geo/SPF-MO"]},
            systems=frozenset(),
        )
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"__name__": "springfield"},
            link_keys=["name"],
            base_store=store,
        )

        assert result.status == "ambiguous"
        assert set(result.candidates) == {"geo/SPF-IL", "geo/SPF-MO"}

    def test_name_key_missing_name_falls_through(self):
        """If ``__name__`` is absent, the "name" key is skipped (continues loop)."""
        store = _store_with(
            iso3={"DEU": "geo/DEU"},
            names={"germany": "geo/DEU"},
        )
        linker = BaseLinker()

        # __name__ absent → skip "name" key, fall through to "iso3"
        result = linker.resolve_link(
            overlay_row={"iso3": "DEU"},
            link_keys=["name", "iso3"],
            base_store=store,
            valid_systems=frozenset({"iso3"}),
        )

        assert result.is_success
        assert result.entity_id == "geo/DEU"

    def test_name_key_not_found_returns_not_found(self):
        """No name match and no other keys → not_found."""
        store = _store_with(names={})
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"__name__": "atlantis"},
            link_keys=["name"],
            base_store=store,
        )

        assert result.status == "not_found"


# ---------------------------------------------------------------------------
# Tests: ordered fallback
# ---------------------------------------------------------------------------


class TestOrderedFallback:
    def test_first_matching_key_wins(self):
        """When both keys would succeed, the first one in order wins."""
        store = _MockStore(
            codes={
                ("iso3", "FRA"): ["geo/FRA"],
                ("iso2", "FR"): ["geo/FRA"],
            },
            names={},
            systems=frozenset({"iso3", "iso2"}),
        )
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"iso3": "FRA", "iso2": "FR"},
            link_keys=["iso3", "iso2"],
            base_store=store,
        )

        assert result.is_success
        assert result.entity_id == "geo/FRA"

    def test_first_key_miss_falls_to_second(self):
        """When the first key finds no match, the second is tried."""
        store = _MockStore(
            codes={("iso2", "DE"): ["geo/DEU"]},
            names={},
            systems=frozenset({"iso3", "iso2"}),
        )
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"iso3": "DEU_MISSING", "iso2": "DE"},
            link_keys=["iso3", "iso2"],
            base_store=store,
        )

        assert result.is_success
        assert result.entity_id == "geo/DEU"

    def test_name_first_then_code_fallback(self):
        """link_keys=["name", "iso3"] tries name first; code wins when name misses."""
        store = _MockStore(
            codes={("iso3", "ESP"): ["geo/ESP"]},
            names={},  # no name match
            systems=frozenset({"iso3"}),
        )
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"__name__": "españa", "iso3": "ESP"},
            link_keys=["name", "iso3"],
            base_store=store,
        )

        assert result.is_success
        assert result.entity_id == "geo/ESP"

    def test_ambiguous_stops_loop_immediately(self):
        """An ambiguous first key stops the loop — the second key is not tried."""
        store = _MockStore(
            codes={
                ("iso3", "GBR"): ["geo/GBR-1", "geo/GBR-2"],
                ("iso2", "GB"): ["geo/GBR-1"],
            },
            names={},
            systems=frozenset({"iso3", "iso2"}),
        )
        linker = BaseLinker()

        result = linker.resolve_link(
            overlay_row={"iso3": "GBR", "iso2": "GB"},
            link_keys=["iso3", "iso2"],
            base_store=store,
        )

        assert result.status == "ambiguous"
        assert set(result.candidates) == {"geo/GBR-1", "geo/GBR-2"}
