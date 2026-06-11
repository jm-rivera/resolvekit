"""Unit tests for numeric-input coercion helpers and bulk integration.

Covers:
- _numeric_to_str: int / float canonical string conversion
- _coerce_item_to_str: collection-element coercion (used in _flatten_input)
- bulk() _flatten_input paths: list, tuple, dict, pandas, polars, numpy
- resolve() / resolve_id() TypeError surface for bool and unsupported types
"""

from __future__ import annotations

import importlib.util
import math
from typing import Any

import pytest

from resolvekit.core.api.bulk import _coerce_item_to_str, _numeric_to_str

# ---------------------------------------------------------------------------
# _numeric_to_str unit tests
# ---------------------------------------------------------------------------


class TestNumericToStr:
    def test_int_unchanged(self) -> None:
        assert _numeric_to_str(840) == "840"

    def test_zero_int(self) -> None:
        assert _numeric_to_str(0) == "0"

    def test_negative_int(self) -> None:
        assert _numeric_to_str(-1) == "-1"

    def test_integral_float_strips_decimal(self) -> None:
        assert _numeric_to_str(840.0) == "840"

    def test_integral_float_zero(self) -> None:
        assert _numeric_to_str(0.0) == "0"

    def test_non_integral_float_unchanged(self) -> None:
        assert _numeric_to_str(840.5) == "840.5"

    def test_nan_falls_back_to_str(self) -> None:
        # NaN is not equal to its int cast — falls back to str().
        result = _numeric_to_str(float("nan"))
        assert result == "nan"

    def test_inf_falls_back_to_str(self) -> None:
        result = _numeric_to_str(math.inf)
        assert result == "inf"

    def test_large_integral_float(self) -> None:
        assert _numeric_to_str(1_000_000.0) == "1000000"


# ---------------------------------------------------------------------------
# _coerce_item_to_str unit tests
# ---------------------------------------------------------------------------


class TestCoerceItemToStr:
    def test_str_passthrough(self) -> None:
        assert _coerce_item_to_str("France") == "France"

    def test_int_coerced(self) -> None:
        assert _coerce_item_to_str(840) == "840"

    def test_integral_float_coerced(self) -> None:
        assert _coerce_item_to_str(840.0) == "840"

    def test_non_integral_float_str(self) -> None:
        assert _coerce_item_to_str(840.5) == "840.5"

    def test_bool_true_not_coerced_numerically(self) -> None:
        # bool is an int subclass, but _coerce_item_to_str must NOT
        # call _numeric_to_str for bool — it falls back to str().
        assert _coerce_item_to_str(True) == "True"
        assert _coerce_item_to_str(False) == "False"

    def test_arbitrary_object_fallback(self) -> None:
        assert _coerce_item_to_str(None) == "None"  # caller should filter None first


# ---------------------------------------------------------------------------
# _flatten_input list/tuple/dict paths
# ---------------------------------------------------------------------------


class TestFlattenInputListPath:
    """_flatten_input uses _coerce_item_to_str for list/tuple/dict values."""

    def _flatten(self, kind: str, raw: Any) -> list[str | None]:
        from resolvekit.core.api.bulk import _flatten_input

        items, *_ = _flatten_input(kind, raw)  # type: ignore[arg-type]
        return items

    def test_list_int_coerced(self) -> None:
        assert self._flatten("list", [840, None, "France"]) == ["840", None, "France"]

    def test_list_integral_float_coerced(self) -> None:
        assert self._flatten("list", [840.0, None]) == ["840", None]

    def test_tuple_int_coerced(self) -> None:
        assert self._flatten("tuple", (840,)) == ["840"]

    def test_dict_values_coerced(self) -> None:
        result = self._flatten("dict", {"a": 840, "b": None, "c": "France"})
        assert result == ["840", None, "France"]

    def test_bool_values_unchanged_in_bulk(self) -> None:
        # bulk() does NOT reject bools — they become "True"/"False" (existing behaviour).
        assert self._flatten("list", [True, False]) == ["True", "False"]


# ---------------------------------------------------------------------------
# Pandas/numpy paths (conditional on library presence)
# ---------------------------------------------------------------------------

_HAS_NUMPY = importlib.util.find_spec("numpy") is not None
_HAS_PANDAS = importlib.util.find_spec("pandas") is not None
_HAS_POLARS = importlib.util.find_spec("polars") is not None


@pytest.mark.skipif(not _HAS_NUMPY, reason="numpy not installed")
class TestFlattenInputNumpyPath:
    def _flatten(self, raw: Any) -> list[str | None]:
        from resolvekit.core.api.bulk import _flatten_input

        items, *_ = _flatten_input("numpy", raw)
        return items

    def test_float64_integral_coerced(self) -> None:
        import numpy as np

        arr = np.array([840.0, 250.0], dtype=np.float64)
        result = self._flatten(arr)
        assert result == ["840", "250"]

    def test_int_array_coerced(self) -> None:
        import numpy as np

        arr = np.array([840, 250], dtype=np.int64)
        result = self._flatten(arr)
        assert result == ["840", "250"]

    def test_nan_becomes_none(self) -> None:
        import numpy as np

        arr = np.array([840.0, float("nan")], dtype=np.float64)
        result = self._flatten(arr)
        assert result == ["840", None]


@pytest.mark.skipif(not _HAS_PANDAS, reason="pandas not installed")
class TestFlattenInputPandasPath:
    def _flatten(self, raw: Any) -> list[str | None]:
        from resolvekit.core.api.bulk import _flatten_input

        items, *_ = _flatten_input("pandas", raw)
        return items

    def test_float64_integral_coerced(self) -> None:
        import pandas as pd

        s = pd.Series([840.0, 250.0])
        result = self._flatten(s)
        assert result == ["840", "250"]

    def test_int_series_coerced(self) -> None:
        import pandas as pd

        s = pd.Series([840, 250], dtype=int)
        result = self._flatten(s)
        assert result == ["840", "250"]

    def test_na_becomes_none(self) -> None:
        import pandas as pd

        s = pd.Series([840.0, float("nan")])
        result = self._flatten(s)
        assert result == ["840", None]


@pytest.mark.skipif(not _HAS_POLARS, reason="polars not installed")
class TestFlattenInputPolarsPath:
    def _flatten(self, raw: Any) -> list[str | None]:
        from resolvekit.core.api.bulk import _flatten_input

        items, *_ = _flatten_input("polars", raw)
        return items

    def test_float_integral_coerced(self) -> None:
        import polars as pl

        s = pl.Series([840.0, 250.0])
        result = self._flatten(s)
        assert result == ["840", "250"]

    def test_int_series_coerced(self) -> None:
        import polars as pl

        s = pl.Series([840, 250])
        result = self._flatten(s)
        assert result == ["840", "250"]

    def test_null_becomes_none(self) -> None:
        import polars as pl

        s = pl.Series([840.0, None])
        result = self._flatten(s)
        assert result == ["840", None]


# ---------------------------------------------------------------------------
# resolve() / resolve_id() TypeError surface (no data needed — uses mock)
# ---------------------------------------------------------------------------


class TestResolveTypeErrors:
    """TypeError is raised for bool and other unsupported scalar types."""

    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        yield r
        r.close()

    def test_bool_true_raises(self, resolver: Any) -> None:
        with pytest.raises(TypeError, match="bool"):
            resolver.resolve(True)

    def test_bool_false_raises(self, resolver: Any) -> None:
        with pytest.raises(TypeError, match="bool"):
            resolver.resolve(False)

    def test_bytes_raises(self, resolver: Any) -> None:
        with pytest.raises(TypeError):
            resolver.resolve(b"US")

    def test_none_returns_no_match_result(self, resolver: Any) -> None:
        from resolvekit.core.model import ResolutionStatus

        result = resolver.resolve(None, to=None)
        assert result.status == ResolutionStatus.NO_MATCH

    def test_none_resolve_id_returns_none(self, resolver: Any) -> None:
        assert resolver.resolve_id(None) is None

    def test_bool_resolve_id_raises(self, resolver: Any) -> None:
        with pytest.raises(TypeError, match="bool"):
            resolver.resolve_id(True)
