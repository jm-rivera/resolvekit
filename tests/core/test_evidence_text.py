"""Tests for M4 evidence_text: describe_features and renderer integration."""

from resolvekit.core.explain import Scorecard
from resolvekit.core.explain.feature_text import describe_features
from resolvekit.core.explain.renderers import MarkdownRenderer, TextRenderer
from resolvekit.core.explain.scorecard import CandidateScorecard, SourceContribution
from resolvekit.core.model import ResolutionStatus

# ---------------------------------------------------------------------------
# describe_features unit tests
# ---------------------------------------------------------------------------


class TestDescribeFeatures:
    def test_describe_features_exact_code(self):
        result = describe_features({"exact_code_hit": True})
        assert "matched code exactly" in result

    def test_describe_features_exact_name(self):
        result = describe_features({"exact_name_hit": True})
        assert "matched canonical name exactly" in result

    def test_describe_features_very_close_edit(self):
        result = describe_features({"fuzzy_edit_sim": 0.9})
        assert "very close edit-distance match" in result
        assert "close edit-distance match" not in result

    def test_describe_features_close_edit(self):
        result = describe_features({"fuzzy_edit_sim": 0.7})
        assert "close edit-distance match" in result
        assert "very close edit-distance match" not in result

    def test_describe_features_disjoint_edit_buckets(self):
        """fuzzy_edit_sim=0.9 produces only the 'very close' string."""
        result = describe_features({"fuzzy_edit_sim": 0.9})
        assert sum("edit-distance match" in s for s in result) == 1
        assert "very close edit-distance match" in result

    def test_describe_features_edit_below_threshold(self):
        result = describe_features({"fuzzy_edit_sim": 0.5})
        assert not any("edit-distance" in s for s in result)

    def test_describe_features_strong_fts(self):
        result = describe_features({"fts_bm25_norm": 0.8})
        assert "strong full-text match" in result

    def test_describe_features_fts_below_threshold(self):
        result = describe_features({"fts_bm25_norm": 0.6})
        assert "strong full-text match" not in result

    def test_describe_features_acronym(self):
        result = describe_features({"acronym_hit": True})
        assert "acronym match" in result

    def test_describe_features_empty(self):
        assert describe_features({}) == []

    def test_describe_features_false_bools_ignored(self):
        result = describe_features({"exact_name_hit": False, "acronym_hit": False})
        assert result == []

    def test_describe_features_caps_at_six(self):
        """All six feature types simultaneously must still cap at 6."""
        features = {
            "exact_code_hit": True,
            "exact_name_hit": True,
            "fuzzy_edit_sim": 0.9,
            "fts_bm25_norm": 0.8,
            "acronym_hit": True,
            # Extra unrelated keys should not inflate beyond 6
            "schema_version": "1.0",
            "some_float": 123.4,
        }
        result = describe_features(features)
        assert len(result) <= 6

    def test_describe_features_orders_by_informativeness(self):
        """exact_name_hit should appear before close-edit when both present."""
        result = describe_features({"exact_name_hit": True, "fuzzy_edit_sim": 0.7})
        assert result.index("matched canonical name exactly") < result.index(
            "close edit-distance match"
        )

    def test_describe_features_exact_code_before_exact_name(self):
        result = describe_features({"exact_code_hit": True, "exact_name_hit": True})
        assert result.index("matched code exactly") < result.index(
            "matched canonical name exactly"
        )


# ---------------------------------------------------------------------------
# Renderer integration tests
# ---------------------------------------------------------------------------


def _make_scorecard(
    evidence_text: list[str] | None = None,
    matched_value: str | None = None,
) -> Scorecard:
    sources = [
        SourceContribution(
            name="geo_exact_name",
            matched_field="name.canonical",
            score=1.0,
            matched_value=matched_value,
        )
    ]
    winner = CandidateScorecard(
        entity_id="country/ITA",
        confidence=0.99,
        rank=1,
        sources=sources,
        evidence_text=evidence_text or [],
    )
    return Scorecard(
        query_text="Italy",
        normalized_text="italy",
        status=ResolutionStatus.RESOLVED,
        entity_id="country/ITA",
        confidence=0.99,
        winner=winner,
    )


class TestTextRendererEvidence:
    def test_text_renderer_includes_why_this_match(self):
        scorecard = _make_scorecard(evidence_text=["matched canonical name exactly"])
        output = TextRenderer().render(scorecard)
        assert "Why this match:" in output
        assert "- matched canonical name exactly" in output

    def test_text_renderer_no_why_section_when_empty(self):
        scorecard = _make_scorecard(evidence_text=[])
        output = TextRenderer().render(scorecard)
        assert "Why this match" not in output

    def test_text_renderer_shows_matched_value(self):
        scorecard = _make_scorecard(matched_value="italy")
        output = TextRenderer().render(scorecard)
        assert 'matched "italy"' in output

    def test_text_renderer_no_matched_value_line_when_none(self):
        scorecard = _make_scorecard(matched_value=None)
        output = TextRenderer().render(scorecard)
        lines = output.splitlines()
        assert not any(line.strip().startswith('matched "') for line in lines)

    def test_text_renderer_multiple_evidence_items(self):
        evidence = ["matched code exactly", "strong full-text match"]
        scorecard = _make_scorecard(evidence_text=evidence)
        output = TextRenderer().render(scorecard)
        assert "matched code exactly" in output
        assert "strong full-text match" in output


class TestMarkdownRendererEvidence:
    def test_markdown_renderer_includes_why_this_match(self):
        scorecard = _make_scorecard(evidence_text=["matched canonical name exactly"])
        output = MarkdownRenderer().render(scorecard)
        assert "### Why this match" in output
        assert "- matched canonical name exactly" in output

    def test_markdown_renderer_no_why_section_when_empty(self):
        scorecard = _make_scorecard(evidence_text=[])
        output = MarkdownRenderer().render(scorecard)
        assert "Why this match" not in output

    def test_markdown_renderer_shows_matched_value(self):
        scorecard = _make_scorecard(matched_value="italy")
        output = MarkdownRenderer().render(scorecard)
        assert 'matched "italy"' in output

    def test_markdown_renderer_no_matched_value_when_none(self):
        scorecard = _make_scorecard(matched_value=None)
        output = MarkdownRenderer().render(scorecard)
        lines = output.splitlines()
        assert not any('matched "' in line for line in lines)

    def test_markdown_renderer_multiple_evidence_items(self):
        evidence = ["matched canonical name exactly", "strong full-text match"]
        scorecard = _make_scorecard(evidence_text=evidence)
        output = MarkdownRenderer().render(scorecard)
        assert "matched canonical name exactly" in output
        assert "strong full-text match" in output
