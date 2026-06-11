"""Tests for GeoFeaturesV1."""

import pytest


class TestGeoFeaturesV1:
    def test_schema_version(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1

        features = GeoFeaturesV1()
        assert features.schema_version == "geo.features.v1"

    def test_default_values(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1

        features = GeoFeaturesV1()

        # Retrieval signals default to False/None
        assert features.exact_code_hit is False
        assert features.exact_name_hit is False
        assert features.fts_bm25_norm is None

    def test_to_dict(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1

        features = GeoFeaturesV1(
            exact_code_hit=True,
            fts_bm25_norm=0.85,
            query_len=5,
        )

        d = features.to_dict()
        assert d["exact_code_hit"] is True
        assert d["fts_bm25_norm"] == 0.85
        assert d["query_len"] == 5

    def test_candidate_prominence_default_none(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1

        features = GeoFeaturesV1()
        assert features.candidate_prominence is None

    def test_immutable(self):
        from pydantic import ValidationError

        from resolvekit.packs.geo.features import GeoFeaturesV1

        features = GeoFeaturesV1(exact_code_hit=True)
        with pytest.raises(ValidationError):
            features.exact_code_hit = False
