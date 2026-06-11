"""Tests for feature vectorization."""

from __future__ import annotations

import pytest

from resolvekit.calibration.vectorize import (
    GEO_FEATURE_NAMES,
    ORG_FEATURE_NAMES,
    QUERY_LEN_SCALE,
    features_dict_to_vector,
    vectorize_geo_features,
)
from resolvekit.packs.geo.features import GeoFeaturesV1

pytestmark = pytest.mark.calibration


class TestGeoFeatureNames:
    def test_feature_names_match_model_dump_keys(self):
        """GEO_FEATURE_NAMES must exactly match GeoFeaturesV1.model_dump() key order."""
        features = GeoFeaturesV1()
        model_keys = list(features.model_dump().keys())
        assert model_keys == GEO_FEATURE_NAMES

    def test_feature_names_length(self):
        assert len(GEO_FEATURE_NAMES) == 18

    def test_query_len_scale(self):
        assert QUERY_LEN_SCALE == 20.0


class TestVectorizeGeoFeatures:
    def test_all_defaults_gives_mostly_zeros(self):
        features = GeoFeaturesV1()
        vec = vectorize_geo_features(features)
        # All bool fields default to False -> 0.0
        # All float|None fields default to None -> 0.0
        # query_len defaults to 0 -> 0.0
        assert all(v == 0.0 for v in vec)
        assert len(vec) == len(GEO_FEATURE_NAMES)

    def test_bool_encoding_true(self):
        features = GeoFeaturesV1(exact_code_hit=True)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("exact_code_hit")
        assert vec[idx] == 1.0

    def test_bool_encoding_false(self):
        features = GeoFeaturesV1(exact_name_hit=False)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("exact_name_hit")
        assert vec[idx] == 0.0

    def test_float_none_encoding(self):
        features = GeoFeaturesV1(fts_bm25_norm=None)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("fts_bm25_norm")
        assert vec[idx] == 0.0

    def test_float_value_encoding(self):
        features = GeoFeaturesV1(fts_bm25_norm=0.75)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("fts_bm25_norm")
        assert abs(vec[idx] - 0.75) < 1e-9

    def test_bool_none_encoding_none(self):
        """bool | None field: None encodes as 0.0."""
        features = GeoFeaturesV1(containment_pass=None)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("containment_pass")
        assert vec[idx] == 0.0

    def test_bool_none_encoding_true(self):
        features = GeoFeaturesV1(containment_pass=True)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("containment_pass")
        assert vec[idx] == 1.0

    def test_bool_none_encoding_false(self):
        features = GeoFeaturesV1(containment_pass=False)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("containment_pass")
        assert vec[idx] == 0.0

    def test_query_len_scaling_below_cap(self):
        features = GeoFeaturesV1(query_len=10)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("query_len")
        assert abs(vec[idx] - 10.0 / 20.0) < 1e-9

    def test_query_len_scaling_at_cap(self):
        features = GeoFeaturesV1(query_len=20)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("query_len")
        assert abs(vec[idx] - 1.0) < 1e-9

    def test_query_len_scaling_above_cap(self):
        features = GeoFeaturesV1(query_len=50)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("query_len")
        assert abs(vec[idx] - 1.0) < 1e-9

    def test_query_len_zero(self):
        features = GeoFeaturesV1(query_len=0)
        vec = vectorize_geo_features(features)
        idx = GEO_FEATURE_NAMES.index("query_len")
        assert vec[idx] == 0.0

    def test_full_features_vector_length(self):
        features = GeoFeaturesV1(
            exact_code_hit=True,
            fts_bm25_norm=0.8,
            query_len=15,
            containment_pass=True,
        )
        vec = vectorize_geo_features(features)
        assert len(vec) == len(GEO_FEATURE_NAMES)


class TestFeaturesDictToVector:
    def test_basic_dict(self):
        feature_names = ["a", "b", "c"]
        d = {"a": 1.0, "b": 0.5, "c": 0.0}
        vec = features_dict_to_vector(feature_names, d)
        assert vec == [1.0, 0.5, 0.0]

    def test_missing_key_defaults_to_zero(self):
        feature_names = ["a", "b", "c"]
        d = {"a": 1.0}
        vec = features_dict_to_vector(feature_names, d)
        assert vec[0] == 1.0
        assert vec[1] == 0.0
        assert vec[2] == 0.0

    def test_none_value_defaults_to_zero(self):
        feature_names = ["x"]
        d = {"x": None}
        vec = features_dict_to_vector(feature_names, d)
        assert vec[0] == 0.0

    def test_bool_true_encodes_as_one(self):
        feature_names = ["flag"]
        d = {"flag": True}
        vec = features_dict_to_vector(feature_names, d)
        assert vec[0] == 1.0

    def test_bool_false_encodes_as_zero(self):
        feature_names = ["flag"]
        d = {"flag": False}
        vec = features_dict_to_vector(feature_names, d)
        assert vec[0] == 0.0

    def test_query_len_normalised(self):
        feature_names = ["query_len"]
        d = {"query_len": 10}
        vec = features_dict_to_vector(feature_names, d)
        assert abs(vec[0] - 0.5) < 1e-9

    def test_query_len_capped(self):
        feature_names = ["query_len"]
        d = {"query_len": 100}
        vec = features_dict_to_vector(feature_names, d)
        assert vec[0] == 1.0

    def test_consistent_with_vectorize_geo_features(self):
        """features_dict_to_vector with GEO_FEATURE_NAMES must match vectorize_geo_features."""
        features = GeoFeaturesV1(
            exact_code_hit=True,
            fts_bm25_norm=0.6,
            query_len=8,
            containment_pass=False,
        )
        via_function = vectorize_geo_features(features)
        via_dict = features_dict_to_vector(GEO_FEATURE_NAMES, features.model_dump())
        assert via_function == pytest.approx(via_dict)


class TestOrgFeatureNames:
    def test_feature_names_match_model_dump_keys(self):
        from resolvekit.packs.org.features import OrgFeaturesV1

        features = OrgFeaturesV1()
        model_keys = list(features.model_dump().keys())
        assert model_keys == ORG_FEATURE_NAMES

    def test_feature_names_length(self):
        assert len(ORG_FEATURE_NAMES) == 15
