"""BYOD (bring-your-own-data) pipeline package.

This package provides the intake, schema, build, cache, and result modules for
``Resolver.from_records`` and ``Resolver.augment``.
"""

from resolvekit.core.byod.intake import (
    ByodData,
    ByodRecord,
    RecordSchema,
    read_records,
    validate_namespace,
)

__all__ = [
    "ByodData",
    "ByodRecord",
    "RecordSchema",
    "read_records",
    "validate_namespace",
]
