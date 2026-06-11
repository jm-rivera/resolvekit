"""Regression tests for output-grammar, configure(), and ResolutionContext validation.

#9  ResolutionContext.country validates ISO alpha-2 shape with actionable errors.
#10 parse_name_grammar rejects invalid lang shapes (whitespace, locale tags).
#16 dispatch_pivot lets UnknownCodeSystemError's built-in did-you-mean run.
#17 configure() omitting default_to leaves previous value unchanged.
#31 configure() rejects non-str/list/None default_to with a clear ValueError.
#35 configure(cache_dir=None) resets to platform default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import resolvekit
from resolvekit.core.config import _reset_config, get_default_to
from resolvekit.core.errors import UnknownCodeSystemError, UnknownOutputError
from resolvekit.core.model.name_grammar import parse_name_grammar

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_after_each() -> None:  # type: ignore[return]
    """Reset config + singleton after every test to prevent bleed."""
    yield
    _reset_config()
    resolvekit.reset()


# ---------------------------------------------------------------------------
# #9 — ResolutionContext.country validation
# ---------------------------------------------------------------------------


class TestResolutionContextCountry:
    def test_iso2_accepted(self) -> None:
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="US")
        assert ctx.country == "US"

    def test_iso2_lowercase_normalised(self) -> None:
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="us")
        assert ctx.country == "US"

    def test_none_accepted(self) -> None:
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country=None)
        assert ctx.country is None

    def test_iso3_rejected_with_alpha2_guidance(self) -> None:
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError) as exc_info:
            ResolutionContext(country="USA")
        msg = str(exc_info.value)
        # Must mention alpha-2 guidance, not just a generic max_length error.
        assert "alpha-2" in msg
        assert "USA" in msg

    def test_single_char_rejected(self) -> None:
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="U")

    def test_empty_string_rejected(self) -> None:
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="")

    def test_non_alpha_rejected(self) -> None:
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="1!")

    def test_four_char_alpha_rejected(self) -> None:
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="USAA")

    def test_iso3_hint_mentions_alpha2_not_usa(self) -> None:
        """USA hint message should say 'alpha-2 code' and suggest the pattern."""
        from pydantic import ValidationError

        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError) as exc_info:
            ResolutionContext(country="USA")
        msg = str(exc_info.value)
        assert "alpha-2" in msg


# ---------------------------------------------------------------------------
# #10 — parse_name_grammar lang shape validation
# ---------------------------------------------------------------------------


class TestParseNameGrammarLangShape:
    def test_valid_two_letter_lang_accepted(self) -> None:
        target = parse_name_grammar("name:en")
        assert target.name_lang == "en"
        assert target.kind == "name"

    def test_valid_three_letter_lang_accepted(self) -> None:
        target = parse_name_grammar("name:zho")
        assert target.name_lang == "zho"
        assert target.kind == "name"

    def test_whitespace_lang_raises(self) -> None:
        # 'name: en' has a leading space — must raise, not silently return None.
        with pytest.raises(UnknownOutputError) as exc_info:
            parse_name_grammar("name: en")
        err = exc_info.value
        assert "en" in err.hint or " en" in err.hint

    def test_locale_tag_raises(self) -> None:
        # 'name:en-US' is a BCP-47 locale tag, not ISO 639-1 — must raise.
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:en-US")

    def test_long_invalid_lang_raises(self) -> None:
        # 'name:invalidkind' is not a kind and not a 2-3 letter code - must raise.
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:invalidkind")

    def test_uppercase_lang_raises(self) -> None:
        # 'name:EN' — uppercase, should raise since _LANG_RE requires lowercase.
        with pytest.raises(UnknownOutputError):
            parse_name_grammar("name:EN")

    def test_hint_mentions_iso639(self) -> None:
        """Hint for invalid lang should reference ISO 639."""
        with pytest.raises(UnknownOutputError) as exc_info:
            parse_name_grammar("name:en-US")
        err = exc_info.value
        assert err.hint is not None
        assert "639" in err.hint

    def test_valid_lang_with_script_accepted(self) -> None:
        target = parse_name_grammar("name:zh:Hant")
        assert target.name_lang == "zh"
        assert target.name_script == "Hant"

    def test_known_kind_with_invalid_lang_shape_not_triggered(self) -> None:
        # 'name:canonical' is a valid kind — lang validation must not fire.
        target = parse_name_grammar("name:canonical")
        assert target.name_kind == "canonical"
        assert target.name_lang is None


# ---------------------------------------------------------------------------
# #16 — dispatch_pivot lets UnknownCodeSystemError's did-you-mean run
# ---------------------------------------------------------------------------


class TestDispatchPivotDidYouMean:
    def _make_entity(self) -> EntityRecord:  # type: ignore[name-defined]  # noqa: F821
        from resolvekit.core.model.entity import CodeRecord, EntityRecord

        return EntityRecord(
            entity_id="country/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[],
            codes=[
                CodeRecord(system="iso3", value="FRA", value_norm="fra"),
                CodeRecord(system="iso2", value="FR", value_norm="fr"),
            ],
        )

    def test_typo_raises_unknown_code_system_error(self) -> None:
        from resolvekit.core.model.entity_attributes import dispatch_pivot

        entity = self._make_entity()
        with pytest.raises(UnknownCodeSystemError):
            dispatch_pivot(entity, "iso33")

    def test_typo_hint_contains_did_you_mean(self) -> None:
        from resolvekit.core.model.entity_attributes import dispatch_pivot

        entity = self._make_entity()
        with pytest.raises(UnknownCodeSystemError) as exc_info:
            dispatch_pivot(entity, "iso33")
        err = exc_info.value
        assert err.hint is not None
        assert "did you mean" in err.hint.lower()

    def test_typo_hint_suggests_iso3(self) -> None:
        from resolvekit.core.model.entity_attributes import dispatch_pivot

        entity = self._make_entity()
        with pytest.raises(UnknownCodeSystemError) as exc_info:
            dispatch_pivot(entity, "iso33")
        err = exc_info.value
        assert "iso3" in err.hint

    def test_available_list_no_duplicates(self) -> None:
        """The available list passed to the error must not contain duplicates."""
        from resolvekit.core.model.entity_attributes import dispatch_pivot

        entity = self._make_entity()
        with pytest.raises(UnknownCodeSystemError) as exc_info:
            dispatch_pivot(entity, "iso99")
        err = exc_info.value
        assert len(err.available) == len(set(err.available))


# ---------------------------------------------------------------------------
# #17 — configure() incremental update: omitting default_to leaves it unchanged
# ---------------------------------------------------------------------------


class TestConfigureIncremental:
    def test_omitting_default_to_preserves_previous_value(self) -> None:
        """configure(on_missing='null') must not wipe a previously set default_to."""
        resolvekit.configure(default_to="iso3")
        assert get_default_to() == "iso3"
        resolvekit.configure(on_missing="null")
        assert get_default_to() == "iso3"

    def test_omitting_on_missing_preserves_previous_value(self) -> None:
        """configure(default_to=None) must not wipe a previously set on_missing."""
        from resolvekit.core.config import get_on_missing

        resolvekit.configure(on_missing="raise")
        assert get_on_missing() == "raise"
        resolvekit.configure(default_to=None)
        assert get_on_missing() == "raise"

    def test_configure_chain_preserves_all_settings(self) -> None:
        """Multiple incremental configure() calls leave all settings intact."""
        from resolvekit.core.config import get_cache_dir, get_on_missing

        resolvekit.configure(default_to="iso3")
        resolvekit.configure(on_missing="null")
        resolvekit.configure(cache_dir="/tmp/test-rk-cache")
        assert get_default_to() == "iso3"
        assert get_on_missing() == "null"
        assert get_cache_dir() == Path("/tmp/test-rk-cache")

    def test_explicit_none_clears_default_to(self) -> None:
        """configure(default_to=None) explicitly clears the default output."""
        resolvekit.configure(default_to="iso3")
        assert get_default_to() == "iso3"
        resolvekit.configure(default_to=None)
        assert get_default_to() is None


# ---------------------------------------------------------------------------
# #31 — configure() type validation on default_to
# ---------------------------------------------------------------------------


class TestConfigureDefaultToTypeValidation:
    def test_str_accepted(self) -> None:
        resolvekit.configure(default_to="iso3")  # must not raise

    def test_list_of_str_accepted(self) -> None:
        resolvekit.configure(default_to=["iso3", "name"])  # must not raise

    def test_none_accepted(self) -> None:
        resolvekit.configure(default_to=None)  # must not raise

    def test_ellipsis_raises_clear_value_error(self) -> None:
        with pytest.raises(ValueError, match="default_to"):
            resolvekit.configure(default_to=...)

    def test_int_raises_clear_value_error(self) -> None:
        with pytest.raises(ValueError, match="default_to"):
            resolvekit.configure(default_to=42)  # type: ignore[arg-type]

    def test_bytes_raises_clear_value_error(self) -> None:
        with pytest.raises(ValueError, match="default_to"):
            resolvekit.configure(default_to=b"iso3")  # type: ignore[arg-type]

    def test_dict_raises_clear_value_error(self) -> None:
        with pytest.raises(ValueError, match="default_to"):
            resolvekit.configure(default_to={"a": 1})  # type: ignore[arg-type]

    def test_list_of_non_str_raises_clear_value_error(self) -> None:
        with pytest.raises(ValueError, match="default_to"):
            resolvekit.configure(default_to=[1, 2])  # type: ignore[arg-type]

    def test_error_message_names_parameter(self) -> None:
        """ValueError message must name the parameter."""
        with pytest.raises(ValueError) as exc_info:
            resolvekit.configure(default_to=42)  # type: ignore[arg-type]
        assert "default_to" in str(exc_info.value)


# ---------------------------------------------------------------------------
# #35 — configure(cache_dir=None) resets to platform default
# ---------------------------------------------------------------------------


class TestConfigureCacheDirReset:
    def test_cache_dir_none_resets_to_default(self) -> None:
        from resolvekit.core.config import _default_cache_dir, get_cache_dir

        resolvekit.configure(cache_dir="/tmp/rk-test-custom")
        assert get_cache_dir() == Path("/tmp/rk-test-custom")

        resolvekit.configure(cache_dir=None)
        assert get_cache_dir() == _default_cache_dir()

    def test_omitting_cache_dir_preserves_custom(self) -> None:
        from resolvekit.core.config import get_cache_dir

        resolvekit.configure(cache_dir="/tmp/rk-test-preserve")
        assert get_cache_dir() == Path("/tmp/rk-test-preserve")

        resolvekit.configure(on_missing="null")  # omit cache_dir
        assert get_cache_dir() == Path("/tmp/rk-test-preserve")
