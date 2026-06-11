"""Tests for SuggestionResult, MatchClass, and normalization fold helpers."""

import pytest

# ---------------------------------------------------------------------------
# MatchClass
# ---------------------------------------------------------------------------


class TestMatchClass:
    def test_values(self) -> None:
        from resolvekit.core.model.result import MatchClass

        assert MatchClass.EXACT_PREFIX == "exact_prefix"
        assert MatchClass.TOKEN_PREFIX == "token_prefix"
        assert MatchClass.INFIX == "infix"
        assert MatchClass.FUZZY == "fuzzy"

    def test_is_str(self) -> None:
        from resolvekit.core.model.result import MatchClass

        assert isinstance(MatchClass.EXACT_PREFIX, str)


# ---------------------------------------------------------------------------
# SuggestionResult
# ---------------------------------------------------------------------------


class TestSuggestionResult:
    def test_minimal_construction(self) -> None:
        from resolvekit.core.model.result import MatchClass, SuggestionResult

        r = SuggestionResult(
            entity_id="country/USA",
            match_class=MatchClass.EXACT_PREFIX,
            ranking_quality="ranked",
        )
        assert r.entity_id == "country/USA"
        assert r.fuzzy_score is None
        assert r.display is None
        assert r.highlight_ranges == []

    def test_frozen_enforcement(self) -> None:
        from resolvekit.core.model.result import MatchClass, SuggestionResult

        r = SuggestionResult(
            entity_id="country/USA",
            match_class=MatchClass.FUZZY,
            ranking_quality="unranked",
            fuzzy_score=87.5,
        )
        with pytest.raises(
            Exception
        ):  # pydantic raises ValidationError on frozen models
            r.entity_id = "country/GBR"  # type: ignore[misc]

    def test_fuzzy_score_field(self) -> None:
        from resolvekit.core.model.result import MatchClass, SuggestionResult

        r = SuggestionResult(
            entity_id="country/FRA",
            match_class=MatchClass.FUZZY,
            ranking_quality="ranked",
            fuzzy_score=72.0,
        )
        assert r.fuzzy_score == 72.0

    def test_highlight_ranges_default_factory(self) -> None:
        from resolvekit.core.model.result import MatchClass, SuggestionResult

        r1 = SuggestionResult(
            entity_id="a",
            match_class=MatchClass.INFIX,
            ranking_quality="unranked",
        )
        r2 = SuggestionResult(
            entity_id="b",
            match_class=MatchClass.INFIX,
            ranking_quality="unranked",
        )
        # Each instance must get its own list, not share a mutable default.
        assert r1.highlight_ranges is not r2.highlight_ranges

    def test_ranking_quality_literals(self) -> None:
        from resolvekit.core.model.result import MatchClass, SuggestionResult

        for quality in ("ranked", "unranked"):
            r = SuggestionResult(
                entity_id="x",
                match_class=MatchClass.TOKEN_PREFIX,
                ranking_quality=quality,  # type: ignore[arg-type]
            )
            assert r.ranking_quality == quality

    def test_exported_from_model_init(self) -> None:
        from resolvekit.core.model import MatchClass, SuggestionResult

        assert MatchClass is not None
        assert SuggestionResult is not None


# ---------------------------------------------------------------------------
# fold_for_match
# ---------------------------------------------------------------------------


class TestFoldForMatch:
    def test_sao_paulo(self) -> None:
        from resolvekit.core.util.normalization import fold_for_match

        assert fold_for_match("São Paulo") == "sao paulo"

    def test_cote(self) -> None:
        from resolvekit.core.util.normalization import fold_for_match

        assert fold_for_match("Côte d'Ivoire") == "cote d'ivoire"

    def test_casefold(self) -> None:
        from resolvekit.core.util.normalization import fold_for_match

        assert fold_for_match("São") == "sao"

    def test_plain_ascii(self) -> None:
        from resolvekit.core.util.normalization import fold_for_match

        assert fold_for_match("United States") == "united states"

    def test_eszett_expansion(self) -> None:
        from resolvekit.core.util.normalization import fold_for_match

        # "ß" casefolds to "ss"
        result = fold_for_match("Straße")
        assert "ss" in result
        assert "ß" not in result


# ---------------------------------------------------------------------------
# fold_with_offsets
# ---------------------------------------------------------------------------


class TestFoldWithOffsets:
    def test_plain_ascii_offset_identity(self) -> None:
        from resolvekit.core.util.normalization import fold_with_offsets

        folded, offsets = fold_with_offsets("abc")
        assert folded == "abc"
        assert offsets == [0, 1, 2]

    def test_cote_offsets(self) -> None:
        """Diacritic fold of "Côte" → "cote" with correct code-point offsets."""
        from resolvekit.core.util.normalization import fold_with_offsets

        folded, offsets = fold_with_offsets("Côte")
        assert folded == "cote"
        assert len(offsets) == 4
        # Each folded char maps back to the correct original index.
        assert offsets[0] == 0  # C → c, orig index 0
        assert offsets[1] == 1  # ô → o, orig index 1
        assert offsets[2] == 2  # t → t, orig index 2
        assert offsets[3] == 3  # e → e, orig index 3

    def test_eszett_both_map_to_original_index(self) -> None:
        """fold_with_offsets("ß") maps both "s" chars back to original index 0."""
        from resolvekit.core.util.normalization import fold_with_offsets

        folded, offsets = fold_with_offsets("ß")
        assert folded == "ss"
        assert offsets == [0, 0]

    def test_round_trip_span_extraction(self) -> None:
        """Slicing original through offset_map recovers the original span."""
        from resolvekit.core.util.normalization import fold_with_offsets

        text = "Côte d'Ivoire"
        folded, offsets = fold_with_offsets(text)

        # Find "cote" in folded text.
        start_folded = folded.find("cote")
        assert start_folded == 0
        end_folded = start_folded + len("cote")

        # Map back to original code-point offsets.
        orig_start = offsets[start_folded]
        orig_end = offsets[end_folded - 1] + 1

        assert text[orig_start:orig_end] == "Côte"

    def test_length_relationship(self) -> None:
        """offset_map length equals folded string length."""
        from resolvekit.core.util.normalization import fold_with_offsets

        for text in ("abc", "São", "ß", "Côte d'Ivoire"):
            folded, offsets = fold_with_offsets(text)
            assert len(offsets) == len(folded)
