"""Tests for OrgScorer."""

import pytest


class TestOrgScorer:
    """Tests for OrgScorer strictness and heuristics."""

    def test_wrong_feature_type_raises(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.org.scoring import OrgScorer

        scorer = OrgScorer()

        with pytest.raises(TypeError, match="OrgScorer requires OrgFeaturesV1"):
            scorer.score(GeoFeaturesV1(), None)
