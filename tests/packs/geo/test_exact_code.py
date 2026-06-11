from resolvekit.packs.geo.sources import GeoExactCodeSource


class TestGeoExactCodeSourceName:
    def test_source_name_endswith_exact_code(self):
        """decision.py and extractor.py rely on endswith('exact_code')."""
        source = GeoExactCodeSource()
        assert source.name.endswith("exact_code")

    def test_source_name_contains_exact_code(self):
        """runner.py uses 'exact_code' in source_name."""
        source = GeoExactCodeSource()
        assert "exact_code" in source.name
