"""Shared components for domain packs.

This module provides reusable constraint and source implementations
that can be configured for domain-specific behavior.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.shared.build import BaseDataPackBuilder
    from resolvekit.shared.constraints import (
        TemporalConstraint,
        TypeConstraint,
        temporal_constraint,
        type_constraint,
    )
    from resolvekit.shared.sources import (
        BM25ScoreTiers,
        FTSSource,
        FuzzySource,
        SymSpellSource,
    )

__all__ = [
    "BM25ScoreTiers",
    "BaseDataPackBuilder",
    "FTSSource",
    "FuzzySource",
    "SymSpellSource",
    "TemporalConstraint",
    "TypeConstraint",
    "temporal_constraint",
    "type_constraint",
]

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "BaseDataPackBuilder": ("resolvekit.shared.build", "BaseDataPackBuilder"),
    "TemporalConstraint": ("resolvekit.shared.constraints", "TemporalConstraint"),
    "TypeConstraint": ("resolvekit.shared.constraints", "TypeConstraint"),
    "temporal_constraint": ("resolvekit.shared.constraints", "temporal_constraint"),
    "type_constraint": ("resolvekit.shared.constraints", "type_constraint"),
    "BM25ScoreTiers": ("resolvekit.shared.sources", "BM25ScoreTiers"),
    "FTSSource": ("resolvekit.shared.sources", "FTSSource"),
    "FuzzySource": ("resolvekit.shared.sources", "FuzzySource"),
    "SymSpellSource": ("resolvekit.shared.sources", "SymSpellSource"),
}


def __getattr__(name: str) -> object:
    if name in _LAZY_IMPORTS:
        module_path, attr = _LAZY_IMPORTS[name]
        import importlib

        module = importlib.import_module(module_path)
        value = getattr(module, attr)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
