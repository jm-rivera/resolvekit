"""Tests for LogisticScoringModel."""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest

from resolvekit.calibration.scoring_model import (
    LogisticScoringModel,
    load_scoring_model,
    save_scoring_model,
)
from resolvekit.calibration.vectorize import GEO_FEATURE_NAMES
from resolvekit.packs.geo.features import GeoFeaturesV1

pytestmark = pytest.mark.calibration


def _make_zero_model(domain: str = "geo", n: int = 100) -> LogisticScoringModel:
    """Model with all-zero weights and zero bias -> always predicts 0.5."""
    return LogisticScoringModel(
        feature_names=GEO_FEATURE_NAMES,
        weights=[0.0] * len(GEO_FEATURE_NAMES),
        bias=0.0,
        domain=domain,
        fit_n_samples=n,
    )


class TestLogisticScoringModelPredict:
    def test_zero_weights_predicts_half(self):
        model = _make_zero_model()
        features = GeoFeaturesV1()
        result = model.predict(features)
        assert abs(result - 0.5) < 1e-9

    def test_positive_bias_above_half(self):
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.0] * len(GEO_FEATURE_NAMES),
            bias=1.0,
            domain="geo",
            fit_n_samples=10,
        )
        features = GeoFeaturesV1()
        result = model.predict(features)
        # sigmoid(1) = e/(1+e) ≈ 0.731
        expected = 1.0 / (1.0 + math.exp(-1.0))
        assert abs(result - expected) < 1e-9

    def test_negative_bias_below_half(self):
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.0] * len(GEO_FEATURE_NAMES),
            bias=-1.0,
            domain="geo",
            fit_n_samples=10,
        )
        features = GeoFeaturesV1()
        result = model.predict(features)
        expected = 1.0 / (1.0 + math.exp(1.0))
        assert abs(result - expected) < 1e-9

    def test_known_weights_exact_code_hit(self):
        """Weight only on exact_code_hit: predict(exact_code_hit=True) > predict(False)."""
        idx = GEO_FEATURE_NAMES.index("exact_code_hit")
        weights = [0.0] * len(GEO_FEATURE_NAMES)
        weights[idx] = 5.0

        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=weights,
            bias=0.0,
            domain="geo",
            fit_n_samples=10,
        )

        feat_hit = GeoFeaturesV1(exact_code_hit=True)
        feat_miss = GeoFeaturesV1(exact_code_hit=False)

        assert model.predict(feat_hit) > model.predict(feat_miss)
        # With weight=5, logit=5 -> sigmoid(5) ≈ 0.9933
        assert model.predict(feat_hit) > 0.99

    def test_output_bounded_0_1(self):
        model = _make_zero_model()
        for features in [
            GeoFeaturesV1(exact_code_hit=True),
            GeoFeaturesV1(fts_bm25_norm=1.0),
            GeoFeaturesV1(),
        ]:
            result = model.predict(features)
            assert 0.0 <= result <= 1.0

    def test_overflow_safety_large_positive(self):
        """Very large logit: no NaN or inf."""
        weights = [100.0] * len(GEO_FEATURE_NAMES)
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=weights,
            bias=100.0,
            domain="geo",
            fit_n_samples=5,
        )
        features = GeoFeaturesV1(exact_code_hit=True, exact_name_hit=True)
        result = model.predict(features)
        assert not math.isnan(result)
        assert not math.isinf(result)
        assert result < 1.0  # sigmoid(30) not 1.0

    def test_overflow_safety_large_negative(self):
        """Very negative logit: no NaN or inf."""
        weights = [-100.0] * len(GEO_FEATURE_NAMES)
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=weights,
            bias=-100.0,
            domain="geo",
            fit_n_samples=5,
        )
        features = GeoFeaturesV1(exact_code_hit=True)
        result = model.predict(features)
        assert not math.isnan(result)
        assert not math.isinf(result)
        assert result > 0.0  # sigmoid(-30) not 0.0


class TestLogisticScoringModelVersion:
    def test_model_version_string(self):
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.0] * len(GEO_FEATURE_NAMES),
            bias=0.0,
            domain="geo",
            fit_n_samples=42,
        )
        version = model.model_version
        assert "logistic" in version
        assert "geo.features.v1" in version
        assert "42" in version

    def test_model_version_is_string(self):
        model = _make_zero_model()
        assert isinstance(model.model_version, str)


class TestLogisticScoringModelFrozen:
    def test_frozen_model_rejects_mutation(self):
        model = _make_zero_model()
        with pytest.raises(Exception):
            model.bias = 1.0  # type: ignore[misc]

    def test_frozen_model_rejects_weight_change(self):
        model = _make_zero_model()
        with pytest.raises(Exception):
            model.weights = [1.0]  # type: ignore[misc]


class TestLogisticScoringModelJsonRoundtrip:
    def test_save_and_load(self):
        original = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[float(i) * 0.1 for i in range(len(GEO_FEATURE_NAMES))],
            bias=-0.5,
            domain="geo",
            fit_n_samples=200,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(original, path)
            loaded = load_scoring_model(path)

        assert loaded.domain == original.domain
        assert loaded.bias == original.bias
        assert loaded.weights == original.weights
        assert loaded.feature_names == original.feature_names
        assert loaded.fit_n_samples == original.fit_n_samples
        assert loaded.schema_version == original.schema_version

    def test_predict_consistent_after_roundtrip(self):
        original = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.5 * i for i in range(len(GEO_FEATURE_NAMES))],
            bias=1.0,
            domain="geo",
            fit_n_samples=50,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(original, path)
            loaded = load_scoring_model(path)

        features = GeoFeaturesV1(
            exact_code_hit=True,
            fts_bm25_norm=0.5,
            query_len=10,
        )
        assert abs(original.predict(features) - loaded.predict(features)) < 1e-9

    def test_json_has_method_field(self):
        model = _make_zero_model()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(model, path)
            data = json.loads(path.read_text())

        assert data["method"] == "logistic"

    def test_load_validates_method_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text(
                json.dumps(
                    {
                        "method": "platt",
                        "feature_names": [],
                        "weights": [],
                        "bias": 0.0,
                        "domain": "geo",
                        "fit_n_samples": 1,
                    }
                )
            )
            with pytest.raises(Exception):
                load_scoring_model(path)

    def test_threshold_fields_roundtrip(self):
        original = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.0] * len(GEO_FEATURE_NAMES),
            bias=0.0,
            domain="geo",
            fit_n_samples=100,
            confidence_threshold=0.55,
            min_gap=0.06,
            exact_code_min_score=0.78,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(original, path)
            loaded = load_scoring_model(path)

        assert loaded.confidence_threshold == 0.55
        assert loaded.min_gap == 0.06
        assert loaded.exact_code_min_score == 0.78

    def test_threshold_fields_absent_in_old_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "old_model.json"
            path.write_text(
                json.dumps(
                    {
                        "method": "logistic",
                        "feature_names": GEO_FEATURE_NAMES,
                        "weights": [0.0] * len(GEO_FEATURE_NAMES),
                        "bias": 0.0,
                        "domain": "geo",
                        "fit_n_samples": 50,
                    }
                )
            )
            loaded = load_scoring_model(path)

        assert loaded.confidence_threshold is None
        assert loaded.min_gap is None
        assert loaded.exact_code_min_score is None
