"""Unit tests for BuildOptions defaults and validation."""

from __future__ import annotations

from resolvekit.builder.models import BuildOptions


def test_build_options_reconcile_defaults_include_subsidiary_of() -> None:
    assert BuildOptions().reconcile_relation_types == ["contained_in", "subsidiary_of"]
