"""Tests for fit_scoring_model."""

from __future__ import annotations

import pytest

from resolvekit.calibration.dataset import LabeledExample
from resolvekit.calibration.scoring_model import LogisticScoringModel
from resolvekit.calibration.vectorize import GEO_FEATURE_NAMES

pytestmark = pytest.mark.calibration

try:
    import sklearn  # noqa: F401

    _has_sklearn = True
except ImportError:
    _has_sklearn = False


def _make_example(
    label: int,
    features_dict: dict[str, float] | None,
    query_text: str = "test",
) -> LabeledExample:
    return LabeledExample(
        query_text=query_text,
        expected_entity_id="geo/TEST",
        source_adapter="synthetic",
        domain="geo",
        top_entity_id="geo/TEST" if label == 1 else "geo/OTHER",
        raw_score=0.9 if label == 1 else 0.2,
        label=label,
        features_dict=features_dict,
    )


def _separable_examples() -> list[LabeledExample]:
    """Synthetic examples clearly separable on exact_code_hit."""
    examples = []
    for _ in range(20):
        d_pos = dict.fromkeys(GEO_FEATURE_NAMES, 0.0)
        d_pos["exact_code_hit"] = 1.0
        examples.append(_make_example(1, d_pos, "positive"))

        d_neg = dict.fromkeys(GEO_FEATURE_NAMES, 0.0)
        d_neg["exact_code_hit"] = 0.0
        examples.append(_make_example(0, d_neg, "negative"))
    return examples


@pytest.mark.skipif(
    not _has_sklearn, reason="scikit-learn required for fit_scoring_model"
)
class TestFitScoringModel:
    def test_fit_returns_logistic_model(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        assert isinstance(model, LogisticScoringModel)
        assert model.domain == "geo"

    def test_fit_feature_names_match_geo(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        assert model.feature_names == GEO_FEATURE_NAMES

    def test_fit_weights_correct_length(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        assert len(model.weights) == len(GEO_FEATURE_NAMES)

    def test_fit_n_samples_correct(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        assert model.fit_n_samples == len(examples)

    def test_fit_separable_data_good_brier(self):
        """On clearly separable data, Brier score should be low."""
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        predicted = []
        for ex in examples:

            class FakeFeatureVector:
                def __init__(self, features_dict: dict) -> None:
                    self._features_dict = features_dict

                def to_dict(self) -> dict:
                    return self._features_dict

            predicted.append(
                model.predict(FakeFeatureVector(ex.features_dict))  # type: ignore[arg-type]
            )

        labels = [ex.label for ex in examples]
        brier = sum(
            (p - lbl) ** 2 for p, lbl in zip(predicted, labels, strict=False)
        ) / len(labels)
        assert brier < 0.25

    def test_fit_requires_both_classes(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        d = dict.fromkeys(GEO_FEATURE_NAMES, 0.0)
        examples = [_make_example(1, d) for _ in range(5)]

        with pytest.raises(ValueError, match="positive and negative"):
            fit_scoring_model(examples, domain="geo")

    def test_fit_requires_features_dict(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        # Examples without features_dict should be filtered out
        examples = [
            _make_example(1, None),
            _make_example(0, None),
        ]
        with pytest.raises(ValueError, match="at least 2"):
            fit_scoring_model(examples, domain="geo")

    def test_fit_skips_examples_without_features(self):
        """Only examples with features_dict are used; others are ignored."""
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        # Add some examples without features_dict — they should be silently skipped
        examples.append(_make_example(1, None))
        examples.append(_make_example(0, None))

        model = fit_scoring_model(examples, domain="geo")

        # fit_n_samples should exclude the examples without features
        assert model.fit_n_samples == len(examples) - 2

    def test_fit_separable_positive_predicts_higher(self):
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model = fit_scoring_model(examples, domain="geo")

        d_pos = dict.fromkeys(GEO_FEATURE_NAMES, 0.0)
        d_pos["exact_code_hit"] = 1.0
        d_neg = dict.fromkeys(GEO_FEATURE_NAMES, 0.0)
        d_neg["exact_code_hit"] = 0.0

        class _FV:
            def __init__(self, d: dict) -> None:
                self._d = d

            def to_dict(self) -> dict:
                return self._d

        pos_score = model.predict(_FV(d_pos))  # type: ignore[arg-type]
        neg_score = model.predict(_FV(d_neg))  # type: ignore[arg-type]
        assert pos_score > neg_score

    def test_fit_regularization_parameter(self):
        """Different regularization values should produce different models."""
        from resolvekit.calibration.fitting import fit_scoring_model

        examples = _separable_examples()
        model_high_reg = fit_scoring_model(examples, domain="geo", regularization=0.01)
        model_low_reg = fit_scoring_model(examples, domain="geo", regularization=100.0)

        # Lower regularization -> larger weights in magnitude
        max_high = max(abs(w) for w in model_high_reg.weights)
        max_low = max(abs(w) for w in model_low_reg.weights)
        assert max_low > max_high
