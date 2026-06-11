"""Tests for build_byod_pack: code/name linking, on_miss, ordered link_on fallback.

Fixture base: a minimal geo pack with one entity (geo/FRA) accessible via
iso3="FRA" and by name "france".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.shared.build.schema import SCHEMA_SQL

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_metadata(
    path: Path,
    *,
    domain_pack_id: str,
    module_id: str,
    pack_type: str = "base",
    base_module_ids: list[str] | None = None,
    link_keys: list[str] | None = None,
) -> None:
    payload: dict = {
        "datapack_id": f"{module_id}-v1",
        "module_id": module_id,
        "domain_pack_id": domain_pack_id,
        "pack_type": pack_type,
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "entity_schema_version": "1.0",
        "feature_schema_version": f"{domain_pack_id}.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "index_versions": {"fts": "fts5", "symspell": None},
        "build_timestamp": "2026-01-01T00:00:00+00:00",
        "source_datasets": ["test"],
        "module_dependencies": [],
    }
    if base_module_ids is not None:
        payload["base_module_ids"] = base_module_ids
        payload["link_keys"] = link_keys or []
    (path / "metadata.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _make_geo_base(base_dir: Path) -> None:
    """Build a minimal geo base pack: geo/FRA (France, iso3=FRA, wikidata=Q142)."""
    base_dir.mkdir(parents=True, exist_ok=True)

    db_path = base_dir / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)

    conn.execute(
        "INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm)"
        " VALUES (?, ?, ?, ?)",
        ("geo/FRA", "geo.country", "France", "france"),
    )
    conn.execute(
        "INSERT INTO names (entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
        " VALUES (?, 'canonical', ?, ?, '', '', 1)",
        ("geo/FRA", "France", "france"),
    )
    conn.execute(
        "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
        ("geo/FRA", "iso3", "FRA", "fra"),
    )
    conn.execute(
        "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
        ("geo/FRA", "wikidata", "Q142", "q142"),
    )
    conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    _write_metadata(base_dir, domain_pack_id="geo", module_id="geo.base.test")


def _make_geo_base_two_entities(base_dir: Path) -> None:
    """Base with two entities sharing the same name (ambiguity test)."""
    base_dir.mkdir(parents=True, exist_ok=True)

    db_path = base_dir / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)

    for eid, iso, name, name_norm in [
        ("geo/SPF1", "SP1", "Springfield", "springfield"),
        ("geo/SPF2", "SP2", "Springfield", "springfield"),
    ]:
        conn.execute(
            "INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm)"
            " VALUES (?, ?, ?, ?)",
            (eid, "geo.admin1", name, name_norm),
        )
        conn.execute(
            "INSERT INTO names (entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
            " VALUES (?, 'canonical', ?, ?, '', '', 1)",
            (eid, name, name_norm),
        )
        conn.execute(
            "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
            (eid, "iso3", iso, iso),
        )

    conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()

    _write_metadata(base_dir, domain_pack_id="geo", module_id="geo.base.ambig.test")


# ---------------------------------------------------------------------------
# Helper: read entity count from a built pack
# ---------------------------------------------------------------------------


def _entity_count(pack_dir: Path) -> int:
    conn = sqlite3.connect(pack_dir / "entities.sqlite")
    count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    conn.close()
    return count


def _entity_ids(pack_dir: Path) -> set[str]:
    conn = sqlite3.connect(pack_dir / "entities.sqlite")
    rows = conn.execute("SELECT entity_id FROM entities").fetchall()
    conn.close()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Tests: code linking (open key — wikidata)
# ---------------------------------------------------------------------------


class TestCodeLinking:
    def test_open_key_wikidata_links(self, tmp_path: Path) -> None:
        """An open key (wikidata) not in a subclass frozenset links correctly."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"wikidata": "Q142", "local_name": "France locale"}]
        schema = RecordSchema.resolve(
            rows,
            name="local_name",
            codes=["wikidata"],
        )

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["wikidata"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1
        assert outcome.minted == 0
        assert outcome.skipped == 0
        assert "geo/FRA" in _entity_ids(outcome.pack_dir)

    def test_code_link_is_case_insensitive(self, tmp_path: Path) -> None:
        """An overlay code value links even when its case differs from the
        base's stored (casefolded) code value.

        The builder casefolds code values at build time; bundled geo packs
        store iso3 codes lowercased ("ken"). An overlay row with "KEN" must
        still link because GeoNormalizer casefolds the overlay value to "ken"
        before the lookup.
        """
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        # Base where iso3 is stored with a casefolded value_norm ("ken"),
        # matching what the builder writes for real bundled geo packs.
        base_dir = tmp_path / "base"
        base_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(base_dir / "entities.sqlite")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm)"
            " VALUES (?, ?, ?, ?)",
            ("geo/KEN", "geo.country", "Kenya", "kenya"),
        )
        conn.execute(
            "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
            ("geo/KEN", "iso3", "KEN", "ken"),
        )
        conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()
        _write_metadata(base_dir, domain_pack_id="geo", module_id="geo.base.test")

        # uppercase iso3 input vs lowercase index
        rows = [{"iso3": "KEN", "label": "Kenya extra", "pop_m": "55"}]
        schema = RecordSchema.resolve(
            rows, name="label", codes=["iso3"], attrs=["pop_m"]
        )

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1, (
            "uppercase iso3 should link to lowercase-indexed code"
        )
        assert outcome.skipped == 0

    def test_iso3_lowercase_links_via_geo_normalizer(self, tmp_path: Path) -> None:
        """Lowercase iso3='fra' links because the builder casefolds at build time."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"iso3": "fra", "label": "France"}]
        schema = RecordSchema.resolve(
            rows,
            name="label",
            codes=["iso3"],
        )

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1
        assert outcome.minted == 0
        assert "geo/FRA" in _entity_ids(outcome.pack_dir)

    def test_colon_system_links(self, tmp_path: Path) -> None:
        """Colon-namespaced code system (oecd:provider) can be a link key."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        # Build a base with a colon-system code.
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        db_path = base_dir / "entities.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT INTO entities (entity_id, entity_type, canonical_name, canonical_name_norm)"
            " VALUES (?, ?, ?, ?)",
            ("custom/acme", "custom", "Acme Corp", "acme corp"),
        )
        conn.execute(
            "INSERT INTO names (entity_id, name_kind, value, value_norm, lang, script, is_preferred)"
            " VALUES (?, 'canonical', 'Acme Corp', 'acme corp', '', '', 1)",
            ("custom/acme",),
        )
        conn.execute(
            "INSERT INTO codes (entity_id, system, value, value_norm) VALUES (?, ?, ?, ?)",
            ("custom/acme", "oecd:provider", "P001", "p001"),
        )
        conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
        conn.commit()
        conn.close()
        _write_metadata(base_dir, domain_pack_id="custom", module_id="custom.base.test")

        rows = [{"oecd:provider": "P001", "label": "Acme"}]
        schema = RecordSchema.resolve(
            rows,
            name="label",
            codes={"oecd:provider": "oecd:provider"},
        )

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="custom",
            namespace="my_custom",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["custom.base.test"],
            link_on=["oecd:provider"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1
        assert "custom/acme" in _entity_ids(outcome.pack_dir)


# ---------------------------------------------------------------------------
# Tests: "name" linking strategy
# ---------------------------------------------------------------------------


class TestNameLinking:
    def test_name_key_links_by_exact_normalised_name(self, tmp_path: Path) -> None:
        """link_on=['name'] matches geo/FRA via normalised name 'france'."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"label": "France", "extra": "data"}]
        schema = RecordSchema.resolve(rows, name="label")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["name"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1
        assert "geo/FRA" in _entity_ids(outcome.pack_dir)


# ---------------------------------------------------------------------------
# Tests: ordered link_on fallback
# ---------------------------------------------------------------------------


class TestLinkOnOrder:
    def test_link_on_order_preserved_name_first(self, tmp_path: Path) -> None:
        """link_on=['name','iso3'] tries name first; iso3 is fallback.

        When name matches, the result is linked — iso3 is never tried.
        We verify by supplying a non-matching iso3 value; if order were reversed
        the result would be not_found.
        """
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        # name="France" matches, iso3="BOGUS" does not — if name tried first, linked.
        rows = [{"label": "France", "iso3": "BOGUS"}]
        schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["name", "iso3"],  # name first
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1, "name tried first should have linked"

    def test_link_on_order_code_before_name(self, tmp_path: Path) -> None:
        """link_on=['iso3','name'] — iso3 matches first; name not reached."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"label": "France", "iso3": "FRA"}]
        schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3", "name"],  # code first
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 1

    def test_link_on_key_missing_from_record_is_skipped(self, tmp_path: Path) -> None:
        """A key in link_on that is absent from the record row is skipped silently."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        # Row has no iso3 column, but link_on specifies iso3 then name.
        rows = [{"label": "France"}]
        schema = RecordSchema.resolve(rows, name="label")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3", "name"],
            on_miss="skip",
            cache=False,
        )

        # "iso3" absent from record → skipped; "name" tried and links "france".
        assert outcome.linked == 1


# ---------------------------------------------------------------------------
# Tests: on_miss modes
# ---------------------------------------------------------------------------


class TestOnMiss:
    def test_on_miss_skip_drops_unlinked_row(self, tmp_path: Path) -> None:
        """Unlinked row with on_miss='skip' is counted and not written."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"iso3": "ZZZ", "label": "Nowhere"}]
        schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.skipped == 1
        assert outcome.linked == 0
        assert _entity_count(outcome.pack_dir) == 0

    def test_on_miss_error_raises(self, tmp_path: Path) -> None:
        """Unlinked row with on_miss='error' raises ValueError."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"iso3": "ZZZ", "label": "Nowhere"}]
        schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

        with pytest.raises(ValueError):
            build_byod_pack(
                records=rows,
                schema=schema,
                domain="geo",
                namespace="my_geo",
                pack_type="overlay",
                base_paths=[base_dir],
                base_module_ids=["geo.base.test"],
                link_on=["iso3"],
                on_miss="error",
                cache=False,
            )

    def test_on_miss_mint_creates_new_entity(self, tmp_path: Path) -> None:
        """Unlinked row with on_miss='mint' becomes a new entity."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        rows = [{"iso3": "ZZZ", "label": "Ruritania"}]
        schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_extra",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3"],
            on_miss="mint",
            cache=False,
        )

        assert outcome.minted == 1
        assert outcome.linked == 0
        ids = _entity_ids(outcome.pack_dir)
        assert any(eid.startswith("my_extra/") for eid in ids)

    def test_pure_mint_from_records_all_rows_minted(self, tmp_path: Path) -> None:
        """No base, link_on=[], every row mints."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        rows = [
            {"id": "w1", "label": "Widget"},
            {"id": "w2", "label": "Gadget"},
        ]
        schema = RecordSchema.resolve(rows, name="label", id="id")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="custom",
            namespace="my_items",
            pack_type="base",
            base_paths=None,
            link_on=[],
            on_miss="mint",
            cache=False,
        )

        assert outcome.minted == 2
        assert outcome.linked == 0
        ids = _entity_ids(outcome.pack_dir)
        assert "my_items/w1" in ids
        assert "my_items/w2" in ids


# ---------------------------------------------------------------------------
# Tests: ambiguous rows
# ---------------------------------------------------------------------------


class TestAmbiguous:
    def test_ambiguous_link_is_counted_and_skipped(self, tmp_path: Path) -> None:
        """Two base entities with the same name → ambiguous, counted, not written."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base_two_entities(base_dir)

        rows = [{"label": "Springfield"}]
        schema = RecordSchema.resolve(rows, name="label")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.ambig.test"],
            link_on=["name"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.ambiguous == 1
        assert outcome.linked == 0
        assert _entity_count(outcome.pack_dir) == 0


# ---------------------------------------------------------------------------
# Tests: minted entities in namespace + name collision
# ---------------------------------------------------------------------------


class TestMintedEntities:
    def test_minted_entities_use_namespace_prefix(self, tmp_path: Path) -> None:
        """Minted entities have entity_id = f'{namespace}/{seed}'."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        rows = [
            {"id": "r1", "name": "Alpha"},
            {"id": "r2", "name": "Beta"},
        ]
        schema = RecordSchema.resolve(rows, name="name", id="id")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="custom",
            namespace="ns",
            pack_type="base",
            link_on=[],
            on_miss="mint",
            cache=False,
        )

        ids = _entity_ids(outcome.pack_dir)
        assert "ns/r1" in ids
        assert "ns/r2" in ids

    def test_two_minted_rows_same_name_are_distinct_entities(
        self, tmp_path: Path
    ) -> None:
        """Two rows with the same canonical name mint as separate entities."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        rows = [
            {"id": "a", "name": "Duplicate"},
            {"id": "b", "name": "Duplicate"},
        ]
        schema = RecordSchema.resolve(rows, name="name", id="id")

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="custom",
            namespace="ns",
            pack_type="base",
            link_on=[],
            on_miss="mint",
            cache=False,
        )

        assert outcome.minted == 2
        ids = _entity_ids(outcome.pack_dir)
        assert "ns/a" in ids
        assert "ns/b" in ids


# ---------------------------------------------------------------------------
# Tests: overlay metadata flags
# ---------------------------------------------------------------------------


class TestOverlayMetadata:
    def test_overlay_metadata_allow_new_entities_true_for_mint(
        self, tmp_path: Path
    ) -> None:
        """Overlay metadata has allow_new_entities=True regardless of on_miss."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        for on_miss in ("mint", "skip"):
            rows = [{"iso3": "FRA", "label": "France"}]
            schema = RecordSchema.resolve(rows, name="label", codes=["iso3"])

            outcome = build_byod_pack(
                records=rows,
                schema=schema,
                domain="geo",
                namespace="my_geo",
                pack_type="overlay",
                base_paths=[base_dir],
                base_module_ids=["geo.base.test"],
                link_on=["iso3"],
                on_miss=on_miss,
                cache=False,
            )

            metadata = json.loads(
                (outcome.pack_dir / "metadata.json").read_text(encoding="utf-8")
            )
            assert metadata["allow_new_entities"] is True, (
                f"allow_new_entities should be True for on_miss={on_miss!r}"
            )


# ---------------------------------------------------------------------------
# Tests: multi-row-per-entity
# ---------------------------------------------------------------------------


class TestMultiRowPerEntity:
    def test_two_rows_same_base_entity_no_crash(self, tmp_path: Path) -> None:
        """Two overlay rows linking to the same base entity must not IntegrityError.

        Both rows should be counted as linked and both aliases should be present
        in the overlay pack (codes/names accumulate onto the entity).
        """
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        base_dir = tmp_path / "base"
        _make_geo_base(base_dir)

        # Two rows keyed to the same entity (iso3=FRA → geo/FRA), each adding
        # a different alias.
        rows = [
            {"iso3": "FRA", "local": "République française"},
            {"iso3": "FRA", "local": "Frankreich"},
        ]
        schema = RecordSchema.resolve(
            rows,
            name="local",
            codes=["iso3"],
            aliases=["local"],
        )

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="my_geo",
            pack_type="overlay",
            base_paths=[base_dir],
            base_module_ids=["geo.base.test"],
            link_on=["iso3"],
            on_miss="skip",
            cache=False,
        )

        assert outcome.linked == 2, f"expected 2 linked rows, got {outcome.linked}"
        assert outcome.skipped == 0

        # Both aliases should be stored in the pack's names table.
        conn = sqlite3.connect(outcome.pack_dir / "entities.sqlite")
        alias_rows = conn.execute(
            "SELECT value FROM names WHERE entity_id = ? AND name_kind = 'alias'",
            ("geo/FRA",),
        ).fetchall()
        conn.close()
        stored_aliases = {r[0] for r in alias_rows}
        assert "République française" in stored_aliases, (
            f"first alias missing from names; stored: {stored_aliases}"
        )
        assert "Frankreich" in stored_aliases, (
            f"second alias missing from names; stored: {stored_aliases}"
        )

    def test_pure_mint_two_rows_same_id_no_crash(self, tmp_path: Path) -> None:
        """Two rows with the same id mint without crashing.

        First occurrence's canonical_name wins; both rows are tallied as minted.
        For same-system codes, INSERT OR REPLACE means the last value wins
        (schema constraint: one value per (entity_id, system)).
        """
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.intake import RecordSchema

        rows = [
            {"id": "x", "label": "Alpha", "sku": "A001"},
            {"id": "x", "label": "AlphaV2", "sku": "A002"},
        ]
        schema = RecordSchema.resolve(rows, name="label", id="id", codes=["sku"])

        outcome = build_byod_pack(
            records=rows,
            schema=schema,
            domain="custom",
            namespace="ns",
            pack_type="base",
            link_on=[],
            on_miss="mint",
            cache=False,
        )

        assert outcome.minted == 2, (
            f"expected 2 minted tallies (one per input row), got {outcome.minted}"
        )

        # Only one entity row in the DB (same id).
        conn = sqlite3.connect(outcome.pack_dir / "entities.sqlite")
        entity_rows = conn.execute(
            "SELECT canonical_name FROM entities WHERE entity_id = ?", ("ns/x",)
        ).fetchall()
        conn.close()

        assert len(entity_rows) == 1, "duplicate entity_id must be written once"
        # First row's name wins (add_entity skipped for repeat id).
        assert entity_rows[0][0] == "Alpha", (
            f"expected first name 'Alpha', got {entity_rows[0][0]!r}"
        )
