"""Tests for OrgLinker."""

from resolvekit.core.linking import Linker
from resolvekit.core.model import EntityRecord
from resolvekit.core.store.interface import EntityStore


class MockOrgStore(EntityStore):
    """Minimal EntityStore stub for testing OrgLinker."""

    def __init__(self):
        self._entities_by_code: dict[str, list[str]] = {}
        self._entities: dict[str, dict] = {}

    def add_entity(
        self,
        entity_id: str,
        codes: dict[str, str] | None = None,
        entity_type: str = "Company",
    ) -> None:
        """Add an entity to the mock store."""
        self._entities[entity_id] = {"entity_type": entity_type}
        if codes:
            for system, value in codes.items():
                key = f"{system}:{value}"
                if key not in self._entities_by_code:
                    self._entities_by_code[key] = []
                self._entities_by_code[key].append(entity_id)

    def lookup_code(self, system: str, value_norm: str) -> list[str]:
        key = f"{system}:{value_norm}"
        return self._entities_by_code.get(key, [])

    def lookup_name_exact(
        self, value_norm: str, name_kinds: set[str] | None = None
    ) -> list[str]:
        return []

    def code_systems(self) -> frozenset[str]:
        return frozenset(key.split(":", 1)[0] for key in self._entities_by_code)

    def get_entity(self, entity_id: str) -> EntityRecord | None:
        return None

    def search_fulltext(
        self, query_norm: str, fields: set[str] | None = None, limit: int = 10
    ) -> list[tuple[str, float, int]]:
        return []

    def bulk_get_entities(self, entity_ids: list[str]) -> dict[str, EntityRecord]:
        return {}


class TestOrgLinker:
    """Tests for OrgLinker protocol compliance and behavior."""

    def test_satisfies_linker_protocol(self):
        """OrgLinker satisfies the Linker protocol."""
        from resolvekit.packs.org.linker import OrgLinker

        linker = OrgLinker()
        assert isinstance(linker, Linker)

    def test_resolve_by_dcid_single_match(self):
        """Resolves link when dcid matches exactly one entity."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity(
            "org/AAPL", codes={"dcid": "org/AAPL", "lei": "HWUPKR0MPOU8FGXBT394"}
        )

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"dcid": "org/AAPL", "revenue": 394000000000},
            link_keys=["dcid"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/AAPL"

    def test_resolve_by_lei_single_match(self):
        """Resolves link when LEI matches exactly one entity."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity(
            "org/MSFT", codes={"dcid": "org/MSFT", "lei": "INR2EJN1ERAN0W5ZP974"}
        )

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"lei": "INR2EJN1ERAN0W5ZP974", "employees": 220000},
            link_keys=["lei"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/MSFT"

    def test_resolve_by_duns_single_match(self):
        """Resolves link when DUNS matches exactly one entity."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity("org/GOOGL", codes={"duns": "061007705"})

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"duns": "061007705"},
            link_keys=["duns"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/GOOGL"

    def test_resolve_by_permid_single_match(self):
        """Resolves link when PermID matches exactly one entity."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity("org/META", codes={"permid": "5037066765"})

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"permid": "5037066765"},
            link_keys=["permid"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/META"

    def test_resolve_tries_keys_in_order(self):
        """Tries link keys in order until one succeeds."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity(
            "org/AMZN", codes={"dcid": "org/AMZN", "lei": "ZBER123456789012XXXX"}
        )

        linker = OrgLinker()
        # dcid not in row, should fall back to lei
        result = linker.resolve_link(
            overlay_row={"lei": "ZBER123456789012XXXX", "market_cap": 1500000000000},
            link_keys=["dcid", "lei"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/AMZN"

    def test_not_found_when_no_keys_match(self):
        """Returns not_found when no link keys produce a match.

        ``lei`` must be a known system in the store (so the open-gate accepts
        it) but the supplied value must not match any entity.  Without a real
        ``lei`` entry in the store ``code_systems()`` would not return "lei",
        turning a mere miss into an ``invalid_key`` error.
        """
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        # Give TSLA a dcid and a lei so both systems are in code_systems().
        store.add_entity(
            "org/TSLA", codes={"dcid": "org/TSLA", "lei": "00EHHQ2ZHDCFXJCPCL46"}
        )

        linker = OrgLinker()
        result = linker.resolve_link(
            # dcid absent from row (skipped); lei value present but no entity matches.
            overlay_row={"lei": "NONEXISTENT12345678XX"},
            link_keys=["dcid", "lei"],
            base_store=store,
        )

        assert result.status == "not_found"

    def test_ambiguous_when_multiple_matches(self):
        """Returns ambiguous when multiple entities match."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        # Two entities with same LEI (shouldn't happen but handle it)
        store.add_entity("org/ACME", codes={"lei": "SAME123456789012XXXX"})
        store.add_entity("org/ACME-subsidiary", codes={"lei": "SAME123456789012XXXX"})

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"lei": "SAME123456789012XXXX"},
            link_keys=["lei"],
            base_store=store,
        )

        assert result.status == "ambiguous"
        assert set(result.candidates) == {"org/ACME", "org/ACME-subsidiary"}

    def test_invalid_key_for_unknown_system(self):
        """Returns invalid_key for unknown code systems."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"unknown_code": "ABC123"},
            link_keys=["unknown_code"],
            base_store=store,
        )

        assert result.status == "invalid_key"
        assert result.message is not None
        assert "unknown_code" in result.message

    def test_resolve_by_ticker(self):
        """Resolves link by ticker."""
        from resolvekit.packs.org.linker import OrgLinker

        store = MockOrgStore()
        store.add_entity("org/NVDA", codes={"ticker": "NVDA"})

        linker = OrgLinker()
        result = linker.resolve_link(
            overlay_row={"ticker": "NVDA"},
            link_keys=["ticker"],
            base_store=store,
        )

        assert result.status == "linked"
        assert result.entity_id == "org/NVDA"
