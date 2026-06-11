"""Tests for OrgFeaturesV1."""


class TestOrgFeaturesV1:
    """Tests for typed org feature schema."""

    def test_schema_version(self):
        from resolvekit.packs.org.features import OrgFeaturesV1

        features = OrgFeaturesV1()
        assert features.schema_version == "org.features.v1"

    def test_acronym_features(self):
        from resolvekit.packs.org.features import OrgFeaturesV1

        features = OrgFeaturesV1(
            acronym_hit=True,
            acronym_exact=True,
            query_is_acronym_like=True,
        )

        assert features.acronym_hit is True
        assert features.acronym_exact is True

    def test_context_alignment_features(self):
        from resolvekit.packs.org.features import OrgFeaturesV1

        features = OrgFeaturesV1(
            parent_org_match=True,
            country_match=True,
            type_match=False,
        )

        d = features.to_dict()
        assert d["parent_org_match"] is True
        assert d["type_match"] is False
