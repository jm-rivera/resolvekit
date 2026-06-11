"""Tests for the parse baseline adapters.

Covers:
- GazetteerAdapter: functional test on a tiny custom Resolver (no spaCy).
- SpacyNerAdapter: graceful-skip test (monkeypatched ImportError carries the
  resolvekit[baselines] hint) plus a positive path guarded by importorskip.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

from benchmarks.parse.metrics import PredSpan

# ---------------------------------------------------------------------------
# Gazetteer functional test
# ---------------------------------------------------------------------------


def test_gazetteer_predicts_known_entity(parse_geo_resolver) -> None:
    """GazetteerAdapter.predict('Kenya') yields a PredSpan for country/KEN.

    The fixture resolver contains Kenya (entity_id='country/KEN').  After
    building the gazetteer from the geo store, predicting the text 'Kenya'
    must return at least one PredSpan with entity_id='country/KEN'.
    """
    from benchmarks.parse.baselines.gazetteer import GazetteerAdapter

    adapter = GazetteerAdapter(parse_geo_resolver, domain="geo")
    spans = adapter.predict("Kenya")

    assert len(spans) >= 1, f"expected at least 1 span, got: {spans}"
    entity_ids = {s.entity_id for s in spans}
    assert "country/KEN" in entity_ids, (
        f"country/KEN not found in predictions: {entity_ids}"
    )


def test_gazetteer_returns_pred_spans(parse_geo_resolver) -> None:
    """All objects returned by predict() are PredSpan instances."""
    from benchmarks.parse.baselines.gazetteer import GazetteerAdapter

    adapter = GazetteerAdapter(parse_geo_resolver, domain="geo")
    spans = adapter.predict("Kenya and Somalia visited the embassy.")

    assert all(isinstance(s, PredSpan) for s in spans), (
        f"Non-PredSpan items in output: {spans}"
    )


def test_gazetteer_empty_text_returns_no_spans(parse_geo_resolver) -> None:
    """predict('') and predict('  ') must return an empty list."""
    from benchmarks.parse.baselines.gazetteer import GazetteerAdapter

    adapter = GazetteerAdapter(parse_geo_resolver, domain="geo")
    assert adapter.predict("") == []
    assert adapter.predict("   ") == []


# ---------------------------------------------------------------------------
# SpacyNerAdapter graceful-skip test (no spaCy required)
# ---------------------------------------------------------------------------


def test_spacy_adapter_raises_import_error_with_hint_when_spacy_absent() -> None:
    """SpacyNerAdapter raises ImportError with the resolvekit[baselines] hint.

    Patches sys.modules so that 'spacy' appears absent, simulating an
    environment where spaCy is not installed.  The resulting ImportError
    message must mention 'resolvekit[baselines]'.
    """
    import importlib

    from benchmarks.parse.baselines import spacy_ner as _spacy_ner_mod

    # Use a minimal resolver mock — constructor only reaches the spacy import.
    mock_resolver = MagicMock()

    # Mapping 'spacy' to None makes `import spacy` raise ImportError whether or
    # not spaCy is actually installed, so the absence is simulated reliably.
    had_key = "spacy" in sys.modules
    saved = sys.modules.get("spacy")
    sys.modules["spacy"] = None  # type: ignore[assignment]
    try:
        # Reload the module so the lazy import runs fresh in this test.
        importlib.reload(_spacy_ner_mod)

        with pytest.raises(ImportError) as exc_info:
            _spacy_ner_mod.SpacyNerAdapter(mock_resolver)
    finally:
        # Restore original state.
        if had_key:
            sys.modules["spacy"] = saved
        else:
            sys.modules.pop("spacy", None)
        # Re-reload to leave the module in a consistent state for later tests.
        importlib.reload(_spacy_ner_mod)

    msg = str(exc_info.value)
    assert "resolvekit[baselines]" in msg, (
        f"ImportError message does not mention 'resolvekit[baselines]': {msg!r}"
    )


# ---------------------------------------------------------------------------
# SpacyNerAdapter positive path (skipped when spaCy not installed)
# ---------------------------------------------------------------------------


def test_spacy_adapter_predicts_with_model(parse_geo_resolver) -> None:
    """SpacyNerAdapter returns PredSpan objects for known geo entities.

    Skipped automatically when spaCy or en_core_web_sm is not available.
    """
    spacy = pytest.importorskip("spacy")

    # Also skip if the model is not downloaded.
    try:
        spacy.load(
            "en_core_web_sm",
            exclude=[
                "tok2vec",
                "tagger",
                "parser",
                "senter",
                "attribute_ruler",
                "lemmatizer",
            ],
        )
    except OSError:
        pytest.skip("en_core_web_sm model not downloaded")

    from benchmarks.parse.baselines.spacy_ner import SpacyNerAdapter

    adapter = SpacyNerAdapter(parse_geo_resolver)
    spans = adapter.predict("Kenya and Somalia discussed the conflict.")

    # spaCy + resolver should link at least one geo entity.
    assert all(isinstance(s, PredSpan) for s in spans), f"Non-PredSpan items: {spans}"
    # All returned spans must be resolved (entity_id not None).
    assert all(s.entity_id is not None for s in spans), (
        f"Unresolved spans returned (should be omitted): {spans}"
    )
