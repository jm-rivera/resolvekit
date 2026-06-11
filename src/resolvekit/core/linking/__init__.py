"""Linking protocols and utilities for overlay composition.

This module provides the core abstractions for linking overlay rows
to base entities:

- LinkResult: Structured result of a link resolution attempt
- Linker: Protocol for domain-specific link resolvers
- BaseLinker: Base class with common link resolution logic
- Normalizer: Protocol for domain-specific normalization (for merge dedup)
- BaseNormalizer: Base class with common normalization logic
"""

from resolvekit.core.linking.base_linker import BaseLinker
from resolvekit.core.linking.base_normalizer import BaseNormalizer
from resolvekit.core.linking.linker import Linker, LinkResult
from resolvekit.core.linking.normalizer import Normalizer

__all__ = [
    "BaseLinker",
    "BaseNormalizer",
    "LinkResult",
    "Linker",
    "Normalizer",
]
