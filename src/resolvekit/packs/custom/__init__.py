"""Custom domain pack.

Exports ``GenericPack`` — the domain-agnostic pack for user-supplied record
sets (``domain="custom"``).

NOTE: factory registration is done in ``core/registry.py``, not here, to keep
import-time side-effects out of the package init.
"""

from resolvekit.packs.custom.pack import GenericPack

__all__ = ["GenericPack"]
