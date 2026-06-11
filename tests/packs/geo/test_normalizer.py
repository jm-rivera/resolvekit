"""Tests for GeoNormalizer."""

from resolvekit.core.linking import Normalizer


class TestGeoNormalizer:
    """Tests for GeoNormalizer protocol compliance and behavior."""

    def test_satisfies_normalizer_protocol(self):
        """GeoNormalizer satisfies the Normalizer protocol."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert isinstance(normalizer, Normalizer)

    def test_normalize_name_lowercases(self):
        """normalize_name converts to lowercase."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_name("FRANCE") == "france"
        assert normalizer.normalize_name("Germany") == "germany"

    def test_normalize_name_preserves_diacritics(self):
        """normalize_name preserves diacritics (important for geo)."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        # Diacritics preserved
        assert normalizer.normalize_name("São Paulo") == "são paulo"
        assert normalizer.normalize_name("Côte d'Ivoire") == "côte d'ivoire"
        assert normalizer.normalize_name("München") == "münchen"

    def test_normalize_name_collapses_whitespace(self):
        """normalize_name collapses multiple spaces."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_name("United   States") == "united states"
        assert normalizer.normalize_name("  France  ") == "france"

    def test_normalize_name_applies_nfkc(self):
        """normalize_name applies NFKC normalization."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        # NFKC normalizes compatibility characters
        # U+210C (BLACK-LETTER CAPITAL H) stays as-is in NFKC (not a compat char)
        # But ﬁ (U+FB01) becomes "fi"
        assert normalizer.normalize_name("ﬁnland") == "finland"

    def test_normalize_code_iso3_casefolds(self):
        """normalize_code casefolds ISO-3 codes (builder stores lowercase)."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_code("iso3", "FRA") == "fra"
        assert normalizer.normalize_code("iso3", "Deu") == "deu"

    def test_normalize_code_iso2_casefolds(self):
        """normalize_code casefolds ISO-2 codes (builder stores lowercase)."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_code("iso2", "FR") == "fr"
        assert normalizer.normalize_code("iso2", "De") == "de"

    def test_normalize_code_dcid_casefolds(self):
        """normalize_code casefolds dcid values (builder stores lowercase)."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_code("dcid", "geo/FRA") == "geo/fra"
        assert normalizer.normalize_code("dcid", "geo/Country") == "geo/country"

    def test_normalize_code_geonameid_strips_whitespace(self):
        """normalize_code strips whitespace from geonameid."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_code("geonameid", " 3017382 ") == "3017382"

    def test_normalize_code_unknown_system_strips_whitespace(self):
        """normalize_code strips whitespace for unknown systems."""
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        normalizer = GeoNormalizer()
        assert normalizer.normalize_code("other", " value ") == "value"
