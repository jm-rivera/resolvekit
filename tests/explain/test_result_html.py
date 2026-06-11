"""Verify result HTML rendering and delegators for RESOLVED/AMBIGUOUS/NO_MATCH
status, including HTML escaping and hint generation.
"""

from __future__ import annotations

from resolvekit.core.explain import result_html as rh
from resolvekit.core.model.result import (
    CandidateSummary,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionResultList,
    ResolutionStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolved(
    entity_id: str = "country/US",
    confidence: float = 0.95,
    pack_id: str = "geo",
) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity_id,
        confidence=confidence,
        pack_id=pack_id,
        reasons=[ReasonCode.FTS_MATCH],
        query_text="US",
    )


def _ambiguous(candidates: list[CandidateSummary] | None = None) -> ResolutionResult:
    if candidates is None:
        candidates = [
            CandidateSummary(
                entity_id="country/US",
                confidence=0.85,
                canonical_name="United States",
                entity_type="geo.country",
                pack_id="geo",
            ),
            CandidateSummary(
                entity_id="country/UM",
                confidence=0.80,
                canonical_name="U.S. Minor Outlying Islands",
                entity_type="geo.country",
                pack_id="geo",
            ),
        ]
    return ResolutionResult(
        status=ResolutionStatus.AMBIGUOUS,
        reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
        candidates=candidates,
        query_text="US",
    )


def _no_match(hints: list[RefinementHint] | None = None) -> ResolutionResult:
    return ResolutionResult(
        status=ResolutionStatus.NO_MATCH,
        reasons=[ReasonCode.NO_CANDIDATES],
        refinement_hints=hints or [],
        query_text="xyzzy",
    )


# ---------------------------------------------------------------------------
# status_badge_html
# ---------------------------------------------------------------------------


class TestStatusBadgeHtml:
    def test_resolved_color(self) -> None:
        badge = rh.status_badge_html(ResolutionStatus.RESOLVED)
        assert "#22c55e" in badge
        assert "resolved" in badge

    def test_ambiguous_color(self) -> None:
        badge = rh.status_badge_html(ResolutionStatus.AMBIGUOUS)
        assert "#f59e0b" in badge
        assert "ambiguous" in badge

    def test_no_match_color(self) -> None:
        badge = rh.status_badge_html(ResolutionStatus.NO_MATCH)
        assert "#ef4444" in badge
        assert "no_match" in badge

    def test_error_color(self) -> None:
        badge = rh.status_badge_html(ResolutionStatus.ERROR)
        assert "#ef4444" in badge


# ---------------------------------------------------------------------------
# did_you_mean_lines
# ---------------------------------------------------------------------------


class TestDidYouMeanLines:
    def test_returns_none_when_no_candidates(self) -> None:
        result = _no_match()
        assert rh.did_you_mean_lines(result) is None

    def test_returns_none_when_all_names_match_query(self) -> None:
        cand = CandidateSummary(
            entity_id="country/US",
            confidence=0.9,
            canonical_name="US",  # same as query_text
        )
        result = _ambiguous([cand])
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=[cand],
            query_text="US",
        )
        assert rh.did_you_mean_lines(result) is None

    def test_returns_lines_for_unique_names(self) -> None:
        result = _ambiguous()
        lines = rh.did_you_mean_lines(result)
        assert lines is not None
        assert "United States" in lines
        assert "U.S. Minor Outlying Islands" in lines
        assert "resolvekit.resolve(text=" in lines

    def test_deduplicates_names(self) -> None:
        cand_a = CandidateSummary(entity_id="a", confidence=0.9, canonical_name="Foo")
        cand_b = CandidateSummary(entity_id="b", confidence=0.8, canonical_name="Foo")
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=[cand_a, cand_b],
            query_text="f",
        )
        lines = rh.did_you_mean_lines(result)
        assert lines is not None
        assert lines.count("Foo") == 1


# ---------------------------------------------------------------------------
# disambiguate_hint
# ---------------------------------------------------------------------------


class TestDisambiguateHint:
    def test_returns_none_when_no_query_text(self) -> None:
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=[],
        )
        assert rh.disambiguate_hint(result) is None

    def test_returns_did_you_mean_lines_first(self) -> None:
        result = _ambiguous()
        hint = rh.disambiguate_hint(result)
        assert hint is not None
        assert "United States" in hint

    def test_falls_back_to_type_narrowing(self) -> None:
        # Candidate without canonical_name → did_you_mean_lines returns None
        # Only one candidate has entity_type geo.country → type narrowing fires
        cand = CandidateSummary(
            entity_id="country/US",
            confidence=0.85,
            entity_type="geo.country",
            pack_id="geo",
        )
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=[cand],
            query_text="US",
        )
        hint = rh.disambiguate_hint(result)
        assert hint is not None
        assert "geo.country" in hint


# ---------------------------------------------------------------------------
# refinement_hint
# ---------------------------------------------------------------------------


class TestRefinementHint:
    def test_returns_none_with_no_hints(self) -> None:
        result = _no_match()
        assert rh.refinement_hint(result) is None

    def test_entity_types_hint(self) -> None:
        cand = CandidateSummary(
            entity_id="country/US",
            confidence=0.8,
            entity_type="geo.country",
        )
        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
            candidates=[cand],
            refinement_hints=[RefinementHint.ENTITY_TYPES],
            query_text="US",
        )
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "entity_types" in hint
        assert "geo.country" in hint

    def test_did_you_mean_hint(self) -> None:
        cand = CandidateSummary(
            entity_id="country/US",
            confidence=0.8,
            canonical_name="United States",
        )
        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
            candidates=[cand],
            refinement_hints=[RefinementHint.DID_YOU_MEAN],
            query_text="Unitd States",
        )
        hint = rh.refinement_hint(result)
        assert hint is not None
        assert "United States" in hint


# ---------------------------------------------------------------------------
# result_repr_html — RESOLVED
# ---------------------------------------------------------------------------


class TestResultReprHtmlResolved:
    def test_contains_status_badge(self) -> None:
        html = rh.result_repr_html(_resolved())
        assert "resolved" in html
        assert "#22c55e" in html

    def test_contains_entity_id(self) -> None:
        html = rh.result_repr_html(_resolved(entity_id="country/US"))
        assert "country/US" in html

    def test_contains_confidence(self) -> None:
        html = rh.result_repr_html(_resolved(confidence=0.95))
        assert "0.950" in html

    def test_contains_pack_id(self) -> None:
        html = rh.result_repr_html(_resolved(pack_id="geo"))
        assert "geo" in html

    def test_scoped_container_id(self) -> None:
        html = rh.result_repr_html(_resolved())
        assert 'id="rk-result-' in html
        assert "table.rk-result" in html

    def test_html_escaping_in_entity_id(self) -> None:
        """entity_id with < > must be HTML-escaped: raw < never appears verbatim."""
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="bad<script>id",
            confidence=0.9,
            reasons=[ReasonCode.FTS_MATCH],
        )
        html = rh.result_repr_html(result)
        # The literal <script> tag must not appear — it should be &lt;script&gt;
        assert "<script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# result_repr_html — AMBIGUOUS
# ---------------------------------------------------------------------------


class TestResultReprHtmlAmbiguous:
    def test_contains_disambiguate_row(self) -> None:
        html = rh.result_repr_html(_ambiguous())
        assert "disambiguate" in html

    def test_contains_candidates(self) -> None:
        html = rh.result_repr_html(_ambiguous())
        assert "candidates" in html

    def test_hint_escaped(self) -> None:
        """Hints rendered inside <code> must be escaped."""
        cand = CandidateSummary(
            entity_id="country/US",
            confidence=0.85,
            canonical_name='<script>alert("xss")</script>',
            entity_type="geo.country",
        )
        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[ReasonCode.AMBIGUOUS_LOW_GAP],
            candidates=[cand],
            query_text="US",
        )
        html = rh.result_repr_html(result)
        assert "<script>" not in html


# ---------------------------------------------------------------------------
# result_repr_html — NO_MATCH
# ---------------------------------------------------------------------------


class TestResultReprHtmlNoMatch:
    def test_no_disambiguate_row(self) -> None:
        html = rh.result_repr_html(_no_match())
        assert "disambiguate" not in html

    def test_contains_status_badge(self) -> None:
        html = rh.result_repr_html(_no_match())
        assert "no_match" in html
        assert "#ef4444" in html


# ---------------------------------------------------------------------------
# result_list_repr_html
# ---------------------------------------------------------------------------


class TestResultListReprHtml:
    def test_contains_header_row(self) -> None:
        result_list = ResolutionResultList([_resolved(), _no_match()])
        html = rh.result_list_repr_html(result_list)
        assert "<th>status</th>" in html
        assert "<th>entity_id</th>" in html
        assert "<th>confidence</th>" in html

    def test_contains_resolved_row(self) -> None:
        result_list = ResolutionResultList([_resolved(entity_id="country/US")])
        html = rh.result_list_repr_html(result_list)
        assert "country/US" in html
        assert "resolved" in html

    def test_scoped_container_id(self) -> None:
        result_list = ResolutionResultList([_resolved()])
        html = rh.result_list_repr_html(result_list)
        assert 'id="rk-resultlist-' in html
        assert "table.rk-results" in html

    def test_empty_list(self) -> None:
        result_list = ResolutionResultList([])
        html = rh.result_list_repr_html(result_list)
        assert "<tbody></tbody>" in html or "<tbody>\n</tbody>" in html


# ---------------------------------------------------------------------------
# Delegation: ResolutionResult methods call through to result_html
# ---------------------------------------------------------------------------


class TestDelegation:
    """Verify ResolutionResult delegators call through to result_html functions.

    Container IDs are unique by design (incremented per call), so content is
    compared with IDs stripped; non-HTML delegators are compared directly.
    """

    def _strip_ids(self, html: str) -> str:
        """Remove unique container IDs so two successive renders can be compared."""
        import re

        return re.sub(r'(id="|#)(rk-[a-z]+-)\d+', r"\1\2N", html)

    def test_repr_html_delegates(self) -> None:
        result = _resolved()
        # Two calls produce different IDs but identical structure.
        html_method = result._repr_html_()
        html_fn = rh.result_repr_html(result)
        assert self._strip_ids(html_method) == self._strip_ids(html_fn)

    def test_disambiguate_hint_delegates(self) -> None:
        result = _ambiguous()
        assert result._disambiguate_hint() == rh.disambiguate_hint(result)

    def test_did_you_mean_lines_delegates(self) -> None:
        result = _ambiguous()
        assert result._did_you_mean_lines() == rh.did_you_mean_lines(result)

    def test_refinement_hint_delegates(self) -> None:
        cand = CandidateSummary(
            entity_id="country/US", confidence=0.8, entity_type="geo.country"
        )
        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
            candidates=[cand],
            refinement_hints=[RefinementHint.ENTITY_TYPES],
            query_text="US",
        )
        assert result._refinement_hint() == rh.refinement_hint(result)

    def test_render_refinement_hint_delegates(self) -> None:
        cand = CandidateSummary(
            entity_id="country/US", confidence=0.8, entity_type="geo.country"
        )
        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
            candidates=[cand],
            refinement_hints=[RefinementHint.ENTITY_TYPES],
            query_text="US",
        )
        hint = RefinementHint.ENTITY_TYPES
        assert result._render_refinement_hint(hint) == rh.render_refinement_hint(
            result, hint
        )

    def test_result_list_repr_html_delegates(self) -> None:
        result_list = ResolutionResultList([_resolved()])
        html_method = result_list._repr_html_()
        html_fn = rh.result_list_repr_html(result_list)
        assert self._strip_ids(html_method) == self._strip_ids(html_fn)
