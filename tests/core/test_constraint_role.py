"""Tests for ConstraintRole enum and default-None fields.

Verifies that:
- ConstraintRole has all expected members and inherits StrEnum semantics.
- ConstraintOutcome.role defaults to None and the model stays frozen.
- CandidateEvidence.match_tier defaults to None and the model stays frozen.
- Both fields accept explicit values without changing existing required args.
"""

import pytest


class TestConstraintRole:
    """ConstraintRole enum members and StrEnum semantics."""

    def test_all_members_present(self):
        from resolvekit.core.model.candidate import ConstraintRole

        expected = {
            "PARENT_SCOPE",
            "COUNTRY_SCOPE",
            "TYPE_SCOPE",
            "TEMPORAL_SCOPE",
            "MEMBERSHIP_SCOPE",
            "CONTAINMENT_SCOPE",
        }
        assert {m.name for m in ConstraintRole} == expected

    def test_str_enum_values(self):
        from resolvekit.core.model.candidate import ConstraintRole

        assert ConstraintRole.PARENT_SCOPE == "parent_scope"
        assert ConstraintRole.COUNTRY_SCOPE == "country_scope"

    def test_exported_from_model_init(self):
        from resolvekit.core.model import ConstraintRole  # noqa: F401 — import check


class TestConstraintOutcomeRole:
    """ConstraintOutcome.role field — additive, default None, frozen."""

    def _make_outcome(self, **kwargs):
        from resolvekit.core.model.candidate import ConstraintOutcome

        return ConstraintOutcome(constraint_name="test_constraint", **kwargs)

    def test_role_defaults_none(self):
        outcome = self._make_outcome()
        assert outcome.role is None

    def test_role_accepts_constraint_role(self):
        from resolvekit.core.model.candidate import ConstraintOutcome, ConstraintRole

        outcome = ConstraintOutcome(
            constraint_name="org_parent_constraint",
            role=ConstraintRole.PARENT_SCOPE,
        )
        assert outcome.role is ConstraintRole.PARENT_SCOPE

    def test_role_accepts_country_scope(self):
        from resolvekit.core.model.candidate import ConstraintOutcome, ConstraintRole

        outcome = ConstraintOutcome(
            constraint_name="org_country_relevance",
            role=ConstraintRole.COUNTRY_SCOPE,
        )
        assert outcome.role == "country_scope"

    def test_model_is_frozen(self):
        outcome = self._make_outcome()
        with pytest.raises(Exception):
            outcome.role = "mutated"  # type: ignore[assignment]

    def test_existing_fields_unchanged(self):
        from resolvekit.core.model.candidate import ConstraintOutcome, Severity

        outcome = ConstraintOutcome(
            constraint_name="some_constraint",
            passed=False,
            severity=Severity.HARD,
            reason="failed hard check",
        )
        assert outcome.constraint_name == "some_constraint"
        assert outcome.passed is False
        assert outcome.severity is Severity.HARD
        assert outcome.reason == "failed hard check"
        assert outcome.role is None


class TestCandidateEvidenceMatchTier:
    """CandidateEvidence.match_tier field — additive, default None, frozen."""

    def _make_evidence(self, **kwargs):
        from resolvekit.core.model.candidate import CandidateEvidence

        return CandidateEvidence(entity_id="country/USA", source_name="fts", **kwargs)

    def test_match_tier_defaults_none(self):
        ev = self._make_evidence()
        assert ev.match_tier is None

    def test_match_tier_accepts_match_tier(self):
        from resolvekit.core.model.result import MatchTier

        ev = self._make_evidence(match_tier=MatchTier.EXACT_NAME)
        assert ev.match_tier is MatchTier.EXACT_NAME

    def test_match_tier_accepts_fuzzy(self):
        from resolvekit.core.model.result import MatchTier

        ev = self._make_evidence(match_tier=MatchTier.FUZZY)
        assert ev.match_tier == "fuzzy"

    def test_model_is_frozen(self):
        ev = self._make_evidence()
        with pytest.raises(Exception):
            ev.match_tier = "mutated"  # type: ignore[assignment]

    def test_existing_fields_unchanged(self):
        ev = self._make_evidence(
            raw_score=0.95,
            rank=1,
            matched_field="code.iso3",
            matched_value="USA",
        )
        assert ev.entity_id == "country/USA"
        assert ev.source_name == "fts"
        assert ev.raw_score == 0.95
        assert ev.rank == 1
        assert ev.matched_field == "code.iso3"
        assert ev.matched_value == "USA"
        assert ev.match_tier is None
