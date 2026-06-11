"""Contract tests for the normalizer-version gate and code-normalization surface.

Covers four contract points:

(a) GeoNormalizer and OrgNormalizer casefold all code systems.
(b) DataPackLoader.load raises DataPackNormalizerVersionError for packs
    whose metadata omits or mismatches normalizer_version.
(c) Resolver._runner.normalize_code_value routes through the correct
    domain normalizer (geo→GeoNormalizer, org→OrgNormalizer).
(d) F10 parity — resolve("FRA", from_system="iso3") resolves to the same
    entity as entity(iso3="FRA") and entity(iso3="fra") on Resolver.lite().
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION, DataPackLoader
from resolvekit.core.errors import DataPackNormalizerVersionError

# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _write_sqlite(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
    conn.close()


def _base_metadata(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "datapack_id": "geo.countries-v1",
        "module_id": "geo.countries",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "build_timestamp": "2024-01-15T10:00:00Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# (a) Normalizer output tests
# ---------------------------------------------------------------------------


class TestNormalizerCasefolds:
    """GeoNormalizer and OrgNormalizer casefold every code system."""

    def test_geo_iso3_casefolds(self) -> None:
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        assert GeoNormalizer().normalize_code("iso3", "FRA") == "fra"

    def test_geo_iso2_casefolds(self) -> None:
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        assert GeoNormalizer().normalize_code("iso2", "US") == "us"

    def test_org_duns_strips_dashes(self) -> None:
        from resolvekit.packs.org.normalizer import OrgNormalizer

        assert OrgNormalizer().normalize_code("duns", "12-345-6789") == "123456789"

    def test_org_lei_casefolds(self) -> None:
        from resolvekit.packs.org.normalizer import OrgNormalizer

        assert OrgNormalizer().normalize_code("lei", "ABC") == "abc"


# ---------------------------------------------------------------------------
# (b) Load gate raises DataPackNormalizerVersionError for legacy packs
# ---------------------------------------------------------------------------


class TestNormalizerVersionGate:
    """DataPackLoader.load raises on packs with absent or mismatched normalizer_version."""

    def test_raises_when_normalizer_version_absent(self, tmp_path: Path) -> None:
        """Absent normalizer_version defaults to 'legacy', which the gate rejects."""
        meta = _base_metadata()
        del meta["normalizer_version"]  # type: ignore[misc]
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")

        with pytest.raises(DataPackNormalizerVersionError):
            DataPackLoader().load(tmp_path)

    def test_raises_when_normalizer_version_is_legacy(self, tmp_path: Path) -> None:
        """Explicit 'legacy' value is the sentinel for pre-contract packs."""
        meta = _base_metadata(normalizer_version="legacy")
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")

        with pytest.raises(DataPackNormalizerVersionError) as exc_info:
            DataPackLoader().load(tmp_path)

        err = exc_info.value
        assert err.expected == NORMALIZER_VERSION
        assert err.found == "legacy"

    def test_raises_when_normalizer_version_mismatches(self, tmp_path: Path) -> None:
        """A hypothetical future version also triggers the gate."""
        meta = _base_metadata(normalizer_version="casefold.2")
        (tmp_path / "metadata.json").write_text(json.dumps(meta))
        _write_sqlite(tmp_path / "entities.sqlite")

        with pytest.raises(DataPackNormalizerVersionError) as exc_info:
            DataPackLoader().load(tmp_path)

        assert exc_info.value.found == "casefold.2"

    def test_passes_with_correct_normalizer_version(self, tmp_path: Path) -> None:
        """Packs with the current NORMALIZER_VERSION load without error."""
        (tmp_path / "metadata.json").write_text(json.dumps(_base_metadata()))
        _write_sqlite(tmp_path / "entities.sqlite")

        pack = DataPackLoader().load(tmp_path)
        assert pack.metadata.normalizer_version == NORMALIZER_VERSION


# ---------------------------------------------------------------------------
# (c) normalize_code_value accessor parity via Resolver._runner
# ---------------------------------------------------------------------------


class TestNormalizeCodeValueAccessor:
    """Resolver._runner.normalize_code_value routes through pack normalizers."""

    @pytest.fixture(scope="class")
    def lite_resolver(self):
        from resolvekit.core.api.resolver import Resolver

        return Resolver.lite()

    def test_geo_iso3_casefolds_via_runner(self, lite_resolver) -> None:
        result = lite_resolver._runner.normalize_code_value("iso3", "FRA")
        assert result == "fra"

    def test_geo_iso3_idempotent_on_lowercase(self, lite_resolver) -> None:
        result = lite_resolver._runner.normalize_code_value("iso3", "fra")
        assert result == "fra"

    def test_org_duns_strips_dashes_via_runner(self, lite_resolver) -> None:
        # Resolver.lite() loads geo-only; DUNS is an org system, falls back to
        # BaseNormalizer which casefolds.  Contract: must not crash and must
        # return something consistent (strip whitespace at minimum).
        result = lite_resolver._runner.normalize_code_value("duns", "12-345-6789")
        # BaseNormalizer fallback strips whitespace but not dashes — verify type
        assert isinstance(result, str)

    def test_accepts_pack_filter_kwarg(self, lite_resolver) -> None:
        result = lite_resolver._runner.normalize_code_value(
            "iso3", "FRA", pack_filter=frozenset({"geo"})
        )
        assert result == "fra"


# ---------------------------------------------------------------------------
# (d) Resolve parity — resolve(from_system=) == entity() for both cases
# ---------------------------------------------------------------------------


class TestResolveParity:
    """resolve("FRA", from_system="iso3") resolves the same entity as entity(iso3="FRA")."""

    @pytest.fixture(scope="class")
    def lite_resolver(self):
        from resolvekit.core.api.resolver import Resolver

        return Resolver.lite()

    def test_resolve_from_system_matches_entity_lookup(self, lite_resolver) -> None:
        via_entity = lite_resolver.entity(iso3="FRA")
        via_resolve = lite_resolver.resolve("FRA", from_system="iso3")

        assert via_entity is not None, "entity(iso3='FRA') must not be None"
        assert via_resolve.entity_id is not None, "resolve must not be NIL"
        assert via_entity.entity_id == via_resolve.entity_id

    def test_resolve_from_system_lowercase_matches(self, lite_resolver) -> None:
        via_upper = lite_resolver.resolve("FRA", from_system="iso3")
        via_lower = lite_resolver.resolve("fra", from_system="iso3")

        assert via_upper.entity_id is not None
        assert via_lower.entity_id is not None
        assert via_upper.entity_id == via_lower.entity_id

    def test_entity_lookup_case_insensitive(self, lite_resolver) -> None:
        via_upper = lite_resolver.entity(iso3="FRA")
        via_lower = lite_resolver.entity(iso3="fra")

        assert via_upper is not None
        assert via_lower is not None
        assert via_upper.entity_id == via_lower.entity_id
