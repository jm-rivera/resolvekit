"""Unit tests for output_spec module.

Tests cover:
- UNSET singleton semantics
- parse_name_grammar token handling
- compile_output_spec chain building and validation
- apply_output chain-walk and on_missing policy
- apply_name precedence and zero-length filtering
- grammar-only validation
- error hints for malformed selectors and unknown codes
- zero-length name filtering
"""

from __future__ import annotations

import pytest

from resolvekit.core.api.output_spec import (
    KNOWN_KINDS,
    UNSET,
    OutputSpec,
    OutputTarget,
    _Unset,
    _validate_grammar_only,
    apply_name,
    apply_output,
    compile_output_spec,
    parse_name_grammar,
)
from resolvekit.core.errors import OutputMissingError, UnknownOutputError
from resolvekit.core.model import ResolutionResult
from resolvekit.core.model.entity import EntityRecord, NameRecord

# ---------------------------------------------------------------------------
# EntityRecord helpers
# ---------------------------------------------------------------------------


def _make_entity(
    *,
    entity_id: str = "country/USA",
    canonical_name: str = "United States",
    codes: list[tuple[str, str]] | None = None,
    names: list[NameRecord] | None = None,
) -> EntityRecord:
    """Build a minimal EntityRecord for testing."""
    from resolvekit.core.model.entity import CodeRecord

    code_records = [
        CodeRecord(system=sys, value=val, value_norm=val.lower())
        for sys, val in (codes or [])
    ]
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        names=names or [],
        codes=code_records,
    )


def _name(
    value: str,
    *,
    kind: str = "alias",
    lang: str | None = None,
    script: str | None = None,
    is_preferred: bool = False,
) -> NameRecord:
    """Build a minimal NameRecord for testing."""
    return NameRecord(
        value=value,
        value_norm=value.lower(),
        kind=kind,
        lang=lang,
        script=script,
        is_preferred=is_preferred,
    )


# ---------------------------------------------------------------------------
# UNSET singleton
# ---------------------------------------------------------------------------


class TestUnset:
    def test_repr(self) -> None:
        assert repr(UNSET) == "UNSET"

    def test_singleton(self) -> None:
        assert _Unset() is UNSET

    def test_not_none(self) -> None:
        assert UNSET is not None

    def test_identity_check(self) -> None:
        x: object = UNSET
        assert x is UNSET
        assert x is not None


# ---------------------------------------------------------------------------
# parse_name_grammar
# ---------------------------------------------------------------------------


class TestParseNameGrammar:
    def test_bare_name_is_computed(self) -> None:
        t = parse_name_grammar("name")
        assert t.kind == "computed"
        assert t.raw == "name"
        assert t.name_lang is None
        assert t.name_kind is None

    def test_lang_fr(self) -> None:
        t = parse_name_grammar("name:fr")
        assert t.kind == "name"
        assert t.name_lang == "fr"
        assert t.name_kind is None
        assert t.name_script is None

    def test_kind_acronym(self) -> None:
        t = parse_name_grammar("name:acronym")
        assert t.kind == "name"
        assert t.name_kind == "acronym"
        assert t.name_lang is None

    def test_abbr_folds_to_acronym(self) -> None:
        t = parse_name_grammar("name:abbr")
        assert t.kind == "name"
        assert t.name_kind == "acronym"

    def test_lang_and_script(self) -> None:
        t = parse_name_grammar("name:fr:Latn")
        assert t.kind == "name"
        assert t.name_lang == "fr"
        assert t.name_script == "Latn"
        assert t.name_kind is None

    def test_kind_and_script(self) -> None:
        t = parse_name_grammar("name:acronym:Latn")
        assert t.kind == "name"
        assert t.name_kind == "acronym"
        assert t.name_script == "Latn"

    def test_bad_token_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("naem")

    def test_empty_middle_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:")

    def test_too_many_parts_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:fr:Latn:extra")

    def test_empty_script_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:fr:")

    def test_known_kinds_in_hint_on_bad_grammar(self) -> None:
        """Hint lists sorted(KNOWN_KINDS) for malformed name: selectors."""
        with pytest.raises(UnknownOutputError) as exc_info:
            parse_name_grammar("name:")
        err = exc_info.value
        # hint should contain kind vocabulary
        assert err.hint is not None
        for kind in sorted(KNOWN_KINDS):
            assert kind in err.hint


# ---------------------------------------------------------------------------
# compile_output_spec
# ---------------------------------------------------------------------------


class TestCompileOutputSpec:
    def test_single_str_normalizes_to_one_chain(self) -> None:
        # "wikidata" is not in KNOWN_PIVOTS — classified as code.
        spec = compile_output_spec(
            "wikidata", "auto", known_systems=frozenset({"wikidata"})
        )
        assert len(spec.chain) == 1
        assert spec.chain[0].raw == "wikidata"
        assert spec.chain[0].kind == "code"

    def test_list_two_chain(self) -> None:
        # "wikidata" is not in KNOWN_PIVOTS — code; bare "name" → computed.
        spec = compile_output_spec(
            ["wikidata", "name"], "auto", known_systems=frozenset({"wikidata"})
        )
        assert len(spec.chain) == 2
        assert spec.chain[0].kind == "code"
        assert spec.chain[1].kind == "computed"  # bare "name"

    def test_known_pivot_classified_computed(self) -> None:
        spec = compile_output_spec("flag", "auto", known_systems=frozenset())
        assert spec.chain[0].kind == "computed"

    def test_unknown_code_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            compile_output_spec(
                "iso33", "auto", known_systems=frozenset({"iso3", "iso2"})
            )

    def test_unknown_code_hint_contains_close_match(self) -> None:
        with pytest.raises(UnknownOutputError) as exc_info:
            compile_output_spec(
                "iso33", "auto", known_systems=frozenset({"iso3", "iso2"})
            )
        err = exc_info.value
        assert err.hint is not None
        assert "iso3" in err.hint

    def test_grammar_typo_raises_regardless_of_known_systems(self) -> None:
        with pytest.raises(UnknownOutputError):
            compile_output_spec(
                "naem:en", "auto", known_systems=frozenset({"iso3", "naem"})
            )

    def test_on_missing_stored(self) -> None:
        spec = compile_output_spec("iso3", "raise", known_systems=frozenset({"iso3"}))
        assert spec.on_missing == "raise"

    def test_name_grammar_token_classified_name(self) -> None:
        spec = compile_output_spec("name:fr", "auto", known_systems=frozenset())
        assert spec.chain[0].kind == "name"
        assert spec.chain[0].name_lang == "fr"


# ---------------------------------------------------------------------------
# apply_name
# ---------------------------------------------------------------------------


class TestApplyName:
    def test_preferred_returned_first(self) -> None:
        entity = _make_entity(
            names=[
                _name("Allemagne", lang="fr", kind="alias", is_preferred=False),
                _name(
                    "Allemagne officielle", lang="fr", kind="alias", is_preferred=True
                ),
            ]
        )
        target = OutputTarget(raw="name:fr", kind="name", name_lang="fr")
        result = apply_name(entity, target)
        assert result == "Allemagne officielle"

    def test_declaration_order_when_no_preferred(self) -> None:
        entity = _make_entity(
            names=[
                _name("second", lang="fr"),
                _name("first", lang="fr"),
            ]
        )
        # first in declaration order
        target = OutputTarget(raw="name:fr", kind="name", name_lang="fr")
        result = apply_name(entity, target)
        assert result == "second"

    def test_acronym_hit(self) -> None:
        entity = _make_entity(names=[_name("USA", kind="acronym", is_preferred=True)])
        target = OutputTarget(raw="name:acronym", kind="name", name_kind="acronym")
        assert apply_name(entity, target) == "USA"

    def test_acronym_miss(self) -> None:
        entity = _make_entity(names=[_name("United States", kind="alias")])
        target = OutputTarget(raw="name:acronym", kind="name", name_kind="acronym")
        assert apply_name(entity, target) is None

    def test_lang_absent_returns_none(self) -> None:
        entity = _make_entity(names=[_name("Estados Unidos", lang="es")])
        target = OutputTarget(raw="name:zh", kind="name", name_lang="zh")
        assert apply_name(entity, target) is None

    def test_abbr_fold_in_data_kind(self) -> None:
        """Kind 'abbr' in data is matched by name_kind='acronym' (fold applied)."""
        entity = _make_entity(names=[_name("US", kind="abbr")])
        target = OutputTarget(raw="name:acronym", kind="name", name_kind="acronym")
        assert apply_name(entity, target) == "US"

    def test_empty_value_filtered_returns_none(self) -> None:
        """Zero-length name values are treated as a miss."""
        # Build an EntityRecord with a NameRecord whose value is empty.
        # NameRecord has min_length=1, so we must construct it via model_construct.
        from resolvekit.core.model.entity import NameRecord as _NameRecord

        empty_name = _NameRecord.model_construct(
            value="",
            value_norm="",
            kind="alias",
            lang="fr",
            script=None,
            is_preferred=False,
        )
        entity = EntityRecord.model_construct(
            entity_id="test/X",
            entity_type="geo.country",
            canonical_name="X",
            canonical_name_norm="x",
            names=[empty_name],
            codes=[],
            relations=[],
            valid_from=None,
            valid_until=None,
            attributes={},
        )
        target = OutputTarget(raw="name:fr", kind="name", name_lang="fr")
        assert apply_name(entity, target) is None


# ---------------------------------------------------------------------------
# apply_output — chain-walk and on_missing
# ---------------------------------------------------------------------------


class TestApplyOutput:
    def test_returns_iso3_when_present(self) -> None:
        entity = _make_entity(codes=[("iso3", "USA")])
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="auto",
        )
        assert apply_output(entity, spec, scalar=True) == "USA"

    def test_falls_through_to_second_target(self) -> None:
        """Entity lacking iso3 falls through to canonical_name via bare 'name'."""
        entity = _make_entity(canonical_name="European Union")
        spec = OutputSpec(
            chain=(
                OutputTarget(raw="iso3", kind="code"),
                OutputTarget(raw="name", kind="computed"),
            ),
            on_missing="auto",
        )
        result = apply_output(entity, spec, scalar=True)
        assert result == "European Union"

    def test_whole_chain_miss_scalar_auto_raises(self) -> None:
        entity = _make_entity()
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="auto",
        )
        with pytest.raises(OutputMissingError) as exc_info:
            apply_output(entity, spec, scalar=True)
        err = exc_info.value
        assert err.entity_id == "country/USA"
        # available_codes is empty since no codes were set
        assert isinstance(err.available_codes, list)

    def test_whole_chain_miss_bulk_auto_returns_none(self) -> None:
        entity = _make_entity()
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="auto",
        )
        assert apply_output(entity, spec, scalar=False) is None

    def test_on_missing_null_scalar_returns_none(self) -> None:
        entity = _make_entity()
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="null",
        )
        assert apply_output(entity, spec, scalar=True) is None

    def test_on_missing_raise_bulk_raises(self) -> None:
        entity = _make_entity()
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="raise",
        )
        with pytest.raises(OutputMissingError):
            apply_output(entity, spec, scalar=False)

    def test_output_missing_error_carries_entity_id(self) -> None:
        entity = _make_entity(entity_id="geo/EU", codes=[("wikidata", "Q458")])
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="raise",
        )
        with pytest.raises(OutputMissingError) as exc_info:
            apply_output(entity, spec, scalar=True)
        err = exc_info.value
        assert err.entity_id == "geo/EU"
        assert "wikidata" in err.available_codes

    def test_name_lang_target_hit(self) -> None:
        entity = _make_entity(
            names=[_name("Allemagne", lang="fr", kind="alias", is_preferred=True)]
        )
        spec = OutputSpec(
            chain=(OutputTarget(raw="name:fr", kind="name", name_lang="fr"),),
            on_missing="auto",
        )
        assert apply_output(entity, spec, scalar=True) == "Allemagne"

    def test_name_lang_target_miss_falls_through(self) -> None:
        entity = _make_entity(
            canonical_name="Germany",
            names=[_name("Allemagne", lang="fr", kind="alias")],
        )
        spec = OutputSpec(
            chain=(
                OutputTarget(raw="name:zh", kind="name", name_lang="zh"),
                OutputTarget(raw="name", kind="computed"),
            ),
            on_missing="auto",
        )
        assert apply_output(entity, spec, scalar=True) == "Germany"


# ---------------------------------------------------------------------------
# _validate_grammar_only
# ---------------------------------------------------------------------------


class TestValidateGrammarOnly:
    def test_none_is_noop(self) -> None:
        _validate_grammar_only(None)  # must not raise

    def test_valid_list_does_not_raise(self) -> None:
        _validate_grammar_only(["iso3", "name:fr"])  # must not raise

    def test_valid_str_does_not_raise(self) -> None:
        _validate_grammar_only("iso3")  # must not raise

    def test_invalid_name_grammar_raises(self) -> None:
        # "name:" has an empty middle segment — malformed name grammar.
        with pytest.raises(UnknownOutputError):
            _validate_grammar_only("name:")

    def test_invalid_name_grammar_in_list_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            _validate_grammar_only(["iso3", "name:"])

    def test_unknown_code_system_does_not_raise(self) -> None:
        """Code-system check is deferred — unknown code names pass grammar-only."""
        _validate_grammar_only("totally_unknown_system")  # must not raise

    def test_empty_middle_name_token_raises(self) -> None:
        with pytest.raises(UnknownOutputError):
            _validate_grammar_only("name:")


# ---------------------------------------------------------------------------
# apply_resolved_output
# ---------------------------------------------------------------------------


class TestApplyResolvedOutput:
    def test_resolved_with_spec_returns_scalar(self) -> None:
        """Resolved result + spec → apply_output scalar value."""
        from resolvekit.core.api.output_spec import apply_resolved_output

        entity = _make_entity(codes=[("iso3", "USA")])
        spec = OutputSpec(
            chain=(OutputTarget(raw="iso3", kind="code"),),
            on_missing="auto",
        )
        result = _make_resolved_result(entity)
        out = apply_resolved_output(result, spec=spec)
        assert out == "USA"

    def test_resolved_with_to_returns_pivot(self) -> None:
        """Resolved result + explicit to= → dispatch_pivot value."""
        from resolvekit.core.api.output_spec import apply_resolved_output

        entity = _make_entity()
        result = _make_resolved_result(entity)
        # dispatch_pivot("name") returns the canonical_name.
        out = apply_resolved_output(result, to="name")
        assert out == entity.canonical_name

    def test_not_resolved_non_ambiguous_returns_none(self) -> None:
        """Non-resolved, non-ambiguous result → None (no exception)."""
        from resolvekit.core.api.output_spec import apply_resolved_output
        from resolvekit.core.model import ResolutionResult, ResolutionStatus

        result = ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[],
            query_text="x",
        )
        out = apply_resolved_output(result, spec=None)
        assert out is None

    def test_ambiguous_raises(self) -> None:
        """Ambiguous result → AmbiguousResolutionError."""
        from resolvekit.core.api.output_spec import apply_resolved_output
        from resolvekit.core.errors import AmbiguousResolutionError
        from resolvekit.core.model import (
            CandidateSummary,
            ResolutionResult,
            ResolutionStatus,
        )

        result = ResolutionResult(
            status=ResolutionStatus.AMBIGUOUS,
            reasons=[],
            query_text="x",
            candidates=[
                CandidateSummary(entity_id="a/A", confidence=0.8),
                CandidateSummary(entity_id="a/B", confidence=0.79),
            ],
        )
        with pytest.raises(AmbiguousResolutionError):
            apply_resolved_output(result, spec=None)


def _make_resolved_result(entity: EntityRecord) -> ResolutionResult:
    """Build a minimal RESOLVED ResolutionResult with entity hydrated."""
    from resolvekit.core.model import ResolutionResult, ResolutionStatus

    return ResolutionResult(
        status=ResolutionStatus.RESOLVED,
        entity_id=entity.entity_id,
        entity=entity,
        confidence=0.9,
        reasons=[],
        query_text="test",
    )
