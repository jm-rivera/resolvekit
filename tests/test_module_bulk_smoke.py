"""Smoke test — ``rk.bulk()`` module-level function.

Verifies that the convenience-layer ``rk.bulk()`` correctly delegates to
``Resolver.bulk`` without argument mismatches (e.g., unknown kwargs).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_resolver_mock() -> MagicMock:
    """Return a mock Resolver whose .bulk() returns a sentinel value."""
    mock_resolver = MagicMock()
    mock_resolver.bulk.return_value = ["USA"]
    return mock_resolver


def test_module_bulk_does_not_raise_type_error() -> None:
    """rk.bulk(values=[...], to='iso3') must not raise TypeError.

    Regression guard: module-level bulk() must forward args correctly to core.
    """
    import resolvekit as rk

    mock_resolver = _make_resolver_mock()

    with patch("resolvekit._convenience._get_default", return_value=mock_resolver):
        rk.bulk(values=["United States"], to="iso3")

    mock_resolver.bulk.assert_called_once()
    call_kwargs = mock_resolver.bulk.call_args.kwargs
    # Must forward values, to, and the standard bulk kwargs
    assert call_kwargs["values"] == ["United States"]
    # to= is forwarded as UNSET-converted — "iso3" is not UNSET so it passes through
    assert call_kwargs["to"] == "iso3"
    # Must NOT pass include_entity or timeout (never part of bulk signature)
    assert "include_entity" not in call_kwargs
    assert "timeout" not in call_kwargs


def test_module_bulk_output_record_dispatches() -> None:
    """rk.bulk(output='record') forwards output='record' to Resolver.bulk."""
    import resolvekit as rk

    mock_resolver = _make_resolver_mock()

    with patch("resolvekit._convenience._get_default", return_value=mock_resolver):
        rk.bulk(values=["United States"], output="record")

    mock_resolver.bulk.assert_called_once()
    assert mock_resolver.bulk.call_args.kwargs["output"] == "record"


def test_module_bulk_output_frame_dispatches() -> None:
    """rk.bulk(output='frame') forwards output='frame' to Resolver.bulk."""
    import resolvekit as rk

    mock_resolver = _make_resolver_mock()

    with patch("resolvekit._convenience._get_default", return_value=mock_resolver):
        rk.bulk(values=["United States"], output="frame")

    mock_resolver.bulk.assert_called_once()
    assert mock_resolver.bulk.call_args.kwargs["output"] == "frame"
