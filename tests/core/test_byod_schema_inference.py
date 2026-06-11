"""Unit tests for _infer_augment_schema.

A pure helper with no I/O, directly importable from ``resolvekit.core.api._byod``
and independently testable without a full Resolver.
"""

from __future__ import annotations

import pytest

from resolvekit.core.api._byod import _infer_augment_schema


class TestInferAugmentSchema:
    def test_add_aliases_str_becomes_name_col(self) -> None:
        """Single string add_aliases → name_col is that string."""
        name_col, _ = _infer_augment_schema(
            link_on=["iso3"],
            add_aliases="local_name",
            add_codes=None,
        )
        assert name_col == "local_name"

    def test_add_aliases_list_single_item(self) -> None:
        """One-element list add_aliases → name_col is a bare string (not a list)."""
        name_col, _ = _infer_augment_schema(
            link_on=["iso3"],
            add_aliases=["local_name"],
            add_codes=None,
        )
        assert name_col == "local_name"

    def test_add_aliases_list_multi_item(self) -> None:
        """Multi-element add_aliases → name_col is the full list."""
        name_col, _ = _infer_augment_schema(
            link_on=["iso3"],
            add_aliases=["name_en", "name_fr"],
            add_codes=None,
        )
        assert name_col == ["name_en", "name_fr"]

    def test_no_aliases_non_name_link_on(self) -> None:
        """No add_aliases, link_on has a non-sentinel → first non-sentinel is name_col."""
        name_col, _ = _infer_augment_schema(
            link_on=["iso3", "iso2"],
            add_aliases=None,
            add_codes=None,
        )
        assert name_col == "iso3"

    def test_name_sentinel_plus_add_codes_dict(self) -> None:
        """link_on=['name'] + add_codes as dict → first code key is name_col."""
        name_col, codes = _infer_augment_schema(
            link_on=["name"],
            add_aliases=None,
            add_codes={"sku": "product_code"},
        )
        assert name_col == "sku"
        assert codes == ["sku"]

    def test_name_sentinel_plus_add_codes_list(self) -> None:
        """link_on=['name'] + add_codes as list → first list entry is name_col."""
        name_col, codes = _infer_augment_schema(
            link_on=["name"],
            add_aliases=None,
            add_codes=["sku", "barcode"],
        )
        assert name_col == "sku"
        assert codes == ["sku", "barcode"]

    def test_link_on_name_no_aliases_no_codes_raises(self) -> None:
        """link_on=['name'] with neither add_aliases nor add_codes → ValueError."""
        with pytest.raises(ValueError, match="link_on=\\['name'\\]"):
            _infer_augment_schema(
                link_on=["name"],
                add_aliases=None,
                add_codes=None,
            )

    def test_codes_merged_link_on_and_add_codes(self) -> None:
        """all_codes_raw merges link_on non-sentinel entries with add_codes."""
        _, codes = _infer_augment_schema(
            link_on=["iso3"],
            add_aliases=None,
            add_codes=["wikidata"],
        )
        assert codes == ["iso3", "wikidata"]

    def test_codes_only_link_on_no_add_codes(self) -> None:
        """all_codes_raw uses only link_on non-sentinel entries when no add_codes."""
        _, codes = _infer_augment_schema(
            link_on=["iso3", "iso2"],
            add_aliases=None,
            add_codes=None,
        )
        assert codes == ["iso3", "iso2"]

    def test_codes_none_when_only_name_sentinel_and_aliases(self) -> None:
        """link_on=['name'] + add_aliases only → all_codes_raw is None."""
        _, codes = _infer_augment_schema(
            link_on=["name"],
            add_aliases="local_name",
            add_codes=None,
        )
        assert codes is None
