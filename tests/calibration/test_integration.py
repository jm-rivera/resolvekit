"""Integration tests for calibration + scorer/pack wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from resolvekit.calibration.models import (
    IsotonicCalibrator,
    PlattCalibrator,
    StratifiedCalibrator,
    save_calibrator,
)
from resolvekit.calibration.scoring_model import (
    LogisticScoringModel,
    save_scoring_model,
)
from resolvekit.calibration.vectorize import GEO_FEATURE_NAMES
from resolvekit.packs.geo.scoring import GeoScorer
from resolvekit.packs.org.scoring import OrgScorer

pytestmark = pytest.mark.integration


def _make_test_model() -> LogisticScoringModel:
    """Simple scoring model that always predicts ~0.5."""
    return LogisticScoringModel(
        feature_names=GEO_FEATURE_NAMES,
        weights=[0.0] * len(GEO_FEATURE_NAMES),
        bias=0.0,
        domain="geo",
        fit_n_samples=100,
    )


class TestGeoScorerCalibration:
    def test_geo_scorer_with_platt(self):
        # A=-2, B=0.5: sigmoid(-2*0.7 + 0.5) = sigmoid(-0.9) != 0.7
        cal = PlattCalibrator(a=-2.0, b=0.5, domain="geo", fit_n_samples=100)
        scorer = GeoScorer(calibrator=cal)

        raw_score = 0.7
        # calibrate() ignores query/candidate args, pass None as existing tests do
        calibrated = scorer.calibrate(raw_score, None, None)  # type: ignore[arg-type]

        assert abs(calibrated - raw_score) > 0.01

    def test_geo_scorer_without_calibrator(self):
        scorer = GeoScorer()
        raw_score = 0.75
        result = scorer.calibrate(raw_score, None, None)  # type: ignore[arg-type]
        assert result == raw_score

    def test_org_scorer_with_isotonic(self):
        cal = IsotonicCalibrator(
            xs=[0.0, 0.5, 1.0],
            ys=[0.1, 0.55, 0.95],
            domain="org",
            fit_n_samples=50,
        )
        scorer = OrgScorer(calibrator=cal)

        raw_score = 0.5
        calibrated = scorer.calibrate(raw_score, None, None)  # type: ignore[arg-type]
        assert abs(calibrated - 0.55) < 1e-9


class TestPackCalibration:
    def test_geo_pack_with_calibrator_path(self):
        from resolvekit.packs.geo.pack import GeoPack

        cal = PlattCalibrator(a=-1.0, b=0.0, domain="geo", fit_n_samples=100)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cal.json"
            save_calibrator(cal, path)

            pack = GeoPack(calibrator_path=str(path))
            scorer = pack.scorer

        assert scorer._calibrator is not None
        assert isinstance(scorer._calibrator, PlattCalibrator)

    def test_org_pack_with_calibrator_path(self):
        from resolvekit.packs.org.pack import OrgPack

        cal = IsotonicCalibrator(
            xs=[0.0, 1.0],
            ys=[0.0, 1.0],
            domain="org",
            fit_n_samples=50,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "cal.json"
            save_calibrator(cal, path)

            pack = OrgPack(calibrator_path=str(path))
            scorer = pack.scorer

        assert scorer._calibrator is not None
        assert isinstance(scorer._calibrator, IsotonicCalibrator)

    def test_geo_pack_no_calibrator(self):
        from resolvekit.packs.geo.pack import GeoPack

        pack = GeoPack()
        scorer = pack.scorer
        assert scorer._calibrator is None

    def test_org_pack_no_calibrator(self):
        from resolvekit.packs.org.pack import OrgPack

        pack = OrgPack()
        scorer = pack.scorer
        assert scorer._calibrator is None


class TestStratifiedCalibrationIntegration:
    def test_geo_scorer_with_stratified(self):
        from resolvekit.core.model import NormalizedText, Query

        short_cal = PlattCalibrator(a=-2.0, b=0.5, domain="geo", fit_n_samples=50)
        long_cal = PlattCalibrator(a=-5.0, b=2.0, domain="geo", fit_n_samples=50)
        strat = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=short_cal,
            long_calibrator=long_cal,
            domain="geo",
            fit_n_samples=100,
        )
        scorer = GeoScorer(calibrator=strat)

        short_query = Query(
            raw_text="USA",
            normalized=NormalizedText(original="USA", normalized="usa"),
        )
        long_query = Query(
            raw_text="United States of America",
            normalized=NormalizedText(
                original="United States of America",
                normalized="united states of america",
            ),
        )

        raw_score = 0.7
        short_result = scorer.calibrate(raw_score, short_query, None)  # type: ignore[arg-type]
        long_result = scorer.calibrate(raw_score, long_query, None)  # type: ignore[arg-type]

        # Different lengths should produce different calibrated scores
        assert short_result != long_result
        # Short should use short_cal, long should use long_cal
        assert abs(short_result - short_cal.predict(0.7)) < 1e-9
        assert abs(long_result - long_cal.predict(0.7)) < 1e-9

    def test_geo_pack_with_stratified_calibrator_path(self):
        from resolvekit.packs.geo.pack import GeoPack

        strat = StratifiedCalibrator(
            short_query_threshold=6,
            short_calibrator=PlattCalibrator(
                a=-2.0, b=1.0, domain="geo", fit_n_samples=50
            ),
            long_calibrator=PlattCalibrator(
                a=-3.0, b=1.5, domain="geo", fit_n_samples=50
            ),
            domain="geo",
            fit_n_samples=100,
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "strat_cal.json"
            save_calibrator(strat, path)

            pack = GeoPack(calibrator_path=str(path))
            scorer = pack.scorer

        assert scorer._calibrator is not None
        assert isinstance(scorer._calibrator, StratifiedCalibrator)


class TestGeoPackWithScoringModel:
    def test_geo_pack_with_model_path(self):
        from resolvekit.packs.geo.pack import GeoPack

        model = _make_test_model()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(model, path)

            pack = GeoPack(model_path=str(path))
            scorer = pack.scorer

        assert scorer._model is not None
        assert isinstance(scorer._model, LogisticScoringModel)

    def test_geo_pack_model_predict_returns_probability(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.pack import GeoPack

        model = _make_test_model()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(model, path)

            pack = GeoPack(model_path=str(path))
            scorer = pack.scorer

        features = GeoFeaturesV1(exact_code_hit=True)
        score = scorer.score(features, None)  # type: ignore[arg-type]
        assert 0.0 <= score <= 1.0

    def test_geo_pack_model_confidence_band_is_none(self):
        from resolvekit.packs.geo.pack import GeoPack

        model = _make_test_model()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(model, path)

            pack = GeoPack(model_path=str(path))
            scorer = pack.scorer

        assert scorer.confidence_band is None

    def test_geo_pack_model_scorer_type_is_model(self):
        from resolvekit.packs.geo.pack import GeoPack

        model = _make_test_model()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "model.json"
            save_scoring_model(model, path)

            pack = GeoPack(model_path=str(path))
            scorer = pack.scorer

        assert scorer.scorer_type == "model"

    def test_geo_pack_no_model_has_confidence_band(self):
        from resolvekit.packs.geo.pack import GeoPack

        pack = GeoPack()
        scorer = pack.scorer
        assert scorer.confidence_band is not None

    def test_geo_scorer_model_takes_precedence_in_score(self):
        """When model is set, score() uses model, not heuristic."""
        from resolvekit.packs.geo.features import GeoFeaturesV1

        # Model with strong positive bias toward 1.0
        model = LogisticScoringModel(
            feature_names=GEO_FEATURE_NAMES,
            weights=[0.0] * len(GEO_FEATURE_NAMES),
            bias=10.0,  # very high -> predict ~1.0
            domain="geo",
            fit_n_samples=10,
        )
        scorer = GeoScorer(model=model)

        features = GeoFeaturesV1(fts_bm25_norm=0.1)  # would score low heuristically
        score = scorer.score(features, None)  # type: ignore[arg-type]

        # Model says ~1.0, heuristic would say ~0.44
        assert score > 0.99
