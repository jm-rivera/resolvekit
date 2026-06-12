"""Unit tests for coerce_context (Layer 1 — context channel + coercion).

Covers:
- dict accepted on resolve/suggest (surface-level smoke)
- {} ≡ None (empty dict treated as no context)
- typo'd key raises UnknownContextKeyError with valid-keys list and close-match hint
- {"country": "France"} resolves to ISO code via the country tier
- {"country": "Georgia"} resolves to the country GEO (not the US state)
- ambiguous country name raises with verbatim message
- unresolvable country name raises with verbatim message
- rk.suggest importable and first positional is prefix
- AmbiguousResolutionError.hint uses dict form (no "ResolutionContext(" substring)
- key validation does not touch the store for a pure key-typo (no resolver needed
  beyond passing one — coerce raises before any store read)
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from resolvekit.core.api.context_input import (
    _VALID_CONTEXT_KEYS,
    _VALID_CONTEXT_KEYS_SORTED,
    coerce_context,
)
from resolvekit.core.errors import UnknownContextKeyError
from resolvekit.core.model import CandidateSummary, ResolutionContext

# ---------------------------------------------------------------------------
# Minimal stub resolver — raises if its store is actually read for key-typo tests
# ---------------------------------------------------------------------------


class _StoreReadError(RuntimeError):
    """Raised if the stub resolver's store is accessed (should not happen for key-typo)."""


class _StubStore:
    def get_entity(self, entity_id: str) -> None:
        raise _StoreReadError(
            "store accessed during key-typo coercion — should not happen"
        )


class _StubResolver:
    """Minimal resolver stub.  The ``_runner`` attribute mimics Resolver._runner."""

    def __init__(self) -> None:
        self._runner = _StubStore()

    def resolve(self, text: str, **kwargs: object) -> object:  # type: ignore[override]
        raise _StoreReadError(
            f"resolver.resolve called during key-typo test with {text!r}"
        )


# ---------------------------------------------------------------------------
# _VALID_CONTEXT_KEYS metadata
# ---------------------------------------------------------------------------


class TestValidContextKeys:
    def test_includes_expected_fields(self) -> None:
        expected = {
            "as_of",
            "entity_types",
            "parent_ids",
            "country",
            "languages",
            "attributes",
        }
        assert expected <= _VALID_CONTEXT_KEYS

    def test_sorted_list_matches_frozenset(self) -> None:
        assert sorted(_VALID_CONTEXT_KEYS) == _VALID_CONTEXT_KEYS_SORTED


# ---------------------------------------------------------------------------
# coerce_context: None and empty dict
# ---------------------------------------------------------------------------


class TestNoneAndEmptyDict:
    def test_none_returns_none(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        assert coerce_context(None, resolver=resolver) is None  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def test_empty_dict_returns_none(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        assert coerce_context({}, resolver=resolver) is None  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def test_resolution_context_passthrough(self) -> None:
        ctx = ResolutionContext(country="FR")
        resolver = _StubResolver()  # type: ignore[arg-type]
        result = coerce_context(ctx, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        assert result is ctx


# ---------------------------------------------------------------------------
# coerce_context: unknown key raises UnknownContextKeyError without store access
# ---------------------------------------------------------------------------


class TestUnknownKeyError:
    def test_single_typo_raises_before_store_access(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        with pytest.raises(UnknownContextKeyError) as exc_info:
            coerce_context({"countyr": "FR"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        err = exc_info.value
        assert "countyr" in str(err)
        assert "country" in (err.hint or "")
        assert "valid keys" in (err.hint or "")

    def test_valid_keys_list_in_hint(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        with pytest.raises(UnknownContextKeyError) as exc_info:
            coerce_context({"zzz_unknown": "x"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        err = exc_info.value
        # All valid keys must appear in the hint.
        for key in _VALID_CONTEXT_KEYS_SORTED:
            assert key in (err.hint or ""), f"{key!r} missing from hint: {err.hint!r}"

    def test_multiple_unknown_keys(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        with pytest.raises(UnknownContextKeyError) as exc_info:
            coerce_context({"countyr": "FR", "zzz_bad": "x"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        err = exc_info.value
        assert "countyr" in str(err)
        assert "zzz_bad" in str(err)

    def test_no_store_access_on_key_typo(self) -> None:
        """Key validation must raise before any store/resolve call."""
        resolver = _StubResolver()  # type: ignore[arg-type]
        # _StoreReadError would propagate if coerce_context reached the store.
        with pytest.raises(UnknownContextKeyError):
            coerce_context({"countyr": "FR"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# UnknownContextKeyError structure
# ---------------------------------------------------------------------------


class TestUnknownContextKeyErrorClass:
    def test_inherits_from_value_error(self) -> None:
        err = UnknownContextKeyError(["countyr"], _VALID_CONTEXT_KEYS_SORTED)
        assert isinstance(err, ValueError)

    def test_hint_suggests_close_match(self) -> None:
        err = UnknownContextKeyError(["countyr"], _VALID_CONTEXT_KEYS_SORTED)
        assert err.hint is not None
        assert "country" in err.hint

    def test_hint_without_close_match_lists_valid_keys(self) -> None:
        err = UnknownContextKeyError(
            ["completely_random_xyz"], _VALID_CONTEXT_KEYS_SORTED
        )
        assert err.hint is not None
        assert "valid keys" in err.hint

    def test_attributes_preserved(self) -> None:
        err = UnknownContextKeyError(["a", "b"], _VALID_CONTEXT_KEYS_SORTED)
        assert err.unknown == ["a", "b"]
        assert err.valid == _VALID_CONTEXT_KEYS_SORTED


# ---------------------------------------------------------------------------
# coerce_context: valid dict keys produce a ResolutionContext
# ---------------------------------------------------------------------------


class TestValidDictCoercion:
    def test_iso_code_country_passthrough(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        result = coerce_context({"country": "FR"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        assert result is not None
        assert result.country == "FR"

    def test_iso3_code_country_passthrough(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        result = coerce_context({"country": "FRA"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        assert result is not None
        assert result.country == "FRA"

    def test_entity_types_coerced(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        result = coerce_context({"entity_types": {"geo.country"}}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        assert result is not None
        assert result.entity_types == frozenset({"geo.country"})

    def test_mixed_valid_fields(self) -> None:
        resolver = _StubResolver()  # type: ignore[arg-type]
        result = coerce_context(
            {"country": "US", "languages": ["en"]},
            resolver=resolver,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )
        assert result is not None
        assert result.country == "US"
        assert result.languages == ["en"]


# ---------------------------------------------------------------------------
# AmbiguousResolutionError hint uses dict form
# ---------------------------------------------------------------------------


class TestAmbiguousHintDictForm:
    def test_cross_type_hint_uses_dict_form(self) -> None:
        from resolvekit.core.errors import AmbiguousResolutionError

        candidates = [
            CandidateSummary(
                entity_id="city/X", entity_type="geo.city", confidence=0.90
            ),
            CandidateSummary(
                entity_id="admin1/Y", entity_type="geo.admin1", confidence=0.89
            ),
        ]
        err = AmbiguousResolutionError(candidates=candidates)
        assert err.hint is not None
        assert "ResolutionContext(" not in err.hint
        assert "context=" in err.hint or "entity_types" in err.hint

    def test_same_type_hint_no_resolution_context(self) -> None:
        from resolvekit.core.errors import AmbiguousResolutionError

        candidates = [
            CandidateSummary(
                entity_id="country/COD", entity_type="geo.country", confidence=0.92
            ),
            CandidateSummary(
                entity_id="country/COG", entity_type="geo.country", confidence=0.91
            ),
        ]
        err = AmbiguousResolutionError(candidates=candidates)
        assert err.hint is not None
        assert "ResolutionContext(" not in err.hint


# ---------------------------------------------------------------------------
# suggest() importable from resolvekit and accepts prefix as first positional
# ---------------------------------------------------------------------------


class TestSuggestExport:
    def test_suggest_importable_from_resolvekit(self) -> None:
        import resolvekit as rk

        assert hasattr(rk, "suggest")
        assert callable(rk.suggest)

    def test_suggest_first_param_is_prefix(self) -> None:
        import inspect

        import resolvekit as rk

        sig = inspect.signature(rk.suggest)
        params = list(sig.parameters)
        assert params[0] == "prefix"

    def test_suggest_key_validation_before_store_access(self) -> None:
        """suggest() with a bad key raises UnknownContextKeyError without resolving."""
        from resolvekit.core.api.context_input import coerce_context
        from resolvekit.core.errors import UnknownContextKeyError

        resolver = _StubResolver()  # type: ignore[arg-type]
        with pytest.raises(UnknownContextKeyError):
            coerce_context({"countyr": "FR"}, resolver=resolver)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]


# ---------------------------------------------------------------------------
# _resolve_country_name: fixture + tests
#
# Uses a local resolver backed by an in-process SQLite datapack with France,
# Georgia (country GEO), North Korea (KP), and South Korea (KR).
# ---------------------------------------------------------------------------


def _build_country_datapack(tmp_path: Path) -> Path:  # noqa: F821
    """Build a minimal geo datapack with France, Georgia, and both Koreas."""
    from pathlib import Path

    from resolvekit.core.datapack import NORMALIZER_VERSION

    pack_dir = Path(tmp_path) / "country_name_pack"
    pack_dir.mkdir(parents=True, exist_ok=True)
    db_path = pack_dir / "entities.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);

        INSERT INTO entities VALUES
            ('country/FRA', 'geo.country', 'France', 'france', NULL, NULL),
            ('country/GEO', 'geo.country', 'Georgia', 'georgia', NULL, NULL),
            ('country/PRK', 'geo.country', 'North Korea', 'north korea', NULL, NULL),
            ('country/KOR', 'geo.country', 'South Korea', 'south korea', NULL, NULL);

        INSERT INTO codes VALUES
            ('country/FRA', 'iso2', 'FR', 'fr'),
            ('country/FRA', 'iso3', 'FRA', 'fra'),
            ('country/GEO', 'iso2', 'GE', 'ge'),
            ('country/GEO', 'iso3', 'GEO', 'geo'),
            ('country/PRK', 'iso2', 'KP', 'kp'),
            ('country/PRK', 'iso3', 'PRK', 'prk'),
            ('country/KOR', 'iso2', 'KR', 'kr'),
            ('country/KOR', 'iso3', 'KOR', 'kor');

        INSERT INTO names VALUES
            ('country/FRA', 'canonical', 'France', 'france', 'en', 1),
            ('country/GEO', 'canonical', 'Georgia', 'georgia', 'en', 1),
            ('country/PRK', 'canonical', 'North Korea', 'north korea', 'en', 1),
            ('country/PRK', 'alias',     'Korea',       'korea',       'en', 0),
            ('country/KOR', 'canonical', 'South Korea', 'south korea', 'en', 1),
            ('country/KOR', 'alias',     'Korea',       'korea',       'en', 0);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('country/FRA', 'france'),
            ('country/GEO', 'georgia'),
            ('country/PRK', 'north korea'),
            ('country/PRK', 'korea'),
            ('country/KOR', 'south korea'),
            ('country/KOR', 'korea');
        """
    )
    conn.commit()
    conn.close()

    (pack_dir / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "country_name_test_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2024-01-15T10:00:00Z",
                "source_datasets": ["test-fixture"],
            }
        )
    )
    return pack_dir


@pytest.fixture(scope="module")
def country_name_resolver(tmp_path_factory: pytest.TempPathFactory):
    """Resolver backed by a fixture datapack with France, Georgia, and both Koreas."""
    from resolvekit.core.api.resolver import Resolver

    tmp = tmp_path_factory.mktemp("country_name_resolver")
    pack_dir = _build_country_datapack(tmp)
    return Resolver.from_datapacks(datapack_paths=[pack_dir])


class TestResolveCountryName:
    """Tests for _resolve_country_name called via coerce_context."""

    def test_france_resolves_to_fr(self, country_name_resolver) -> None:
        result = coerce_context({"country": "France"}, resolver=country_name_resolver)
        assert result is not None
        assert result.country == "FR"

    def test_georgia_resolves_to_country_not_us_state(
        self, country_name_resolver
    ) -> None:
        """'Georgia' → country GEO (iso2 GE), not the US state."""
        result = coerce_context({"country": "Georgia"}, resolver=country_name_resolver)
        assert result is not None
        assert result.country == "GE"

    def test_ambiguous_korea_raises_with_canonical_message(
        self, country_name_resolver
    ) -> None:
        """'Korea' matches both KP and KR → raises with ambiguous message."""
        with pytest.raises(ValueError) as exc_info:
            coerce_context({"country": "Korea"}, resolver=country_name_resolver)
        msg = str(exc_info.value)
        assert "ambiguous" in msg
        assert "did you mean" in msg
        assert "pass an ISO code" in msg

    def test_unresolvable_name_raises_with_canonical_message(
        self, country_name_resolver
    ) -> None:
        """'Atlantis' cannot be resolved → raises with unresolvable message."""
        with pytest.raises(ValueError) as exc_info:
            coerce_context({"country": "Atlantis"}, resolver=country_name_resolver)
        msg = str(exc_info.value)
        assert "cannot resolve country name" in msg
        assert "Atlantis" in msg
        assert "ISO" in msg
