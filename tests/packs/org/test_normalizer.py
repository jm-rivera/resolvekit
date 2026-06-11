"""Tests for OrgNormalizer."""

from resolvekit.core.linking import Normalizer


class TestOrgNormalizer:
    """Tests for OrgNormalizer protocol compliance and behavior."""

    def test_satisfies_normalizer_protocol(self):
        """OrgNormalizer satisfies the Normalizer protocol."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert isinstance(normalizer, Normalizer)

    def test_normalize_name_lowercases(self):
        """normalize_name converts to lowercase."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_name("APPLE") == "apple"
        assert normalizer.normalize_name("Microsoft") == "microsoft"

    def test_normalize_name_strips_legal_suffixes(self):
        """normalize_name strips common legal suffixes."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_name("Apple Inc.") == "apple"
        assert normalizer.normalize_name("Microsoft Corporation") == "microsoft"
        assert normalizer.normalize_name("Amazon.com, Inc.") == "amazon.com"
        assert normalizer.normalize_name("Siemens AG") == "siemens"
        assert normalizer.normalize_name("BMW GmbH") == "bmw"
        assert normalizer.normalize_name("LVMH SA") == "lvmh"
        assert normalizer.normalize_name("Toyota Ltd") == "toyota"
        assert normalizer.normalize_name("Samsung LLC") == "samsung"

    def test_normalize_name_collapses_whitespace(self):
        """normalize_name collapses multiple spaces."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_name("General   Electric") == "general electric"
        assert normalizer.normalize_name("  Tesla  ") == "tesla"

    def test_normalize_name_applies_nfkc(self):
        """normalize_name applies NFKC normalization."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        # NFKC normalizes compatibility characters
        assert normalizer.normalize_name("ﬁdelity") == "fidelity"

    def test_normalize_code_lei_casefolds(self):
        """normalize_code casefolds LEI codes (builder stores lowercase)."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert (
            normalizer.normalize_code("lei", "HWUPKR0MPOU8FGXBT394")
            == "hwupkr0mpou8fgxbt394"
        )

    def test_normalize_code_duns_strips_dashes(self):
        """normalize_code strips dashes from DUNS codes."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_code("duns", "06-100-7705") == "061007705"
        assert normalizer.normalize_code("duns", "061007705") == "061007705"

    def test_normalize_code_ticker_casefolds(self):
        """normalize_code casefolds ticker symbols (builder stores lowercase)."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_code("ticker", "AAPL") == "aapl"
        assert normalizer.normalize_code("ticker", "Msft") == "msft"

    def test_normalize_code_dcid_casefolds(self):
        """normalize_code casefolds dcid values (builder stores lowercase)."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_code("dcid", "org/Apple") == "org/apple"

    def test_normalize_code_permid_strips_whitespace(self):
        """normalize_code strips whitespace from permid."""
        from resolvekit.packs.org.normalizer import OrgNormalizer

        normalizer = OrgNormalizer()
        assert normalizer.normalize_code("permid", " 5037066765 ") == "5037066765"
