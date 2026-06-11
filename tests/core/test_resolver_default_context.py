"""Pin the frozen contract of ``_DEFAULT_CONTEXT``.

``Resolver._resolve_inner`` reuses a single ``ResolutionContext`` instance
when the caller passes ``context=None``. The query cache keys results by
``id(context)``; mutating the singleton would silently poison cache
entries across calls. The assertion at module load in ``resolver.py`` is
the import-time guard for this; this test pins the *contract* (frozen
config + mutation raises) so the guard is preserved even if
``_DEFAULT_CONTEXT`` moves to another module.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from resolvekit.core.api.resolver import _DEFAULT_CONTEXT
from resolvekit.core.model import ResolutionContext


class TestDefaultContextFrozenContract:
    def test_resolution_context_is_frozen(self) -> None:
        assert ResolutionContext.model_config.get("frozen") is True

    def test_default_context_mutation_raises(self) -> None:
        # Pydantic v2 raises ValidationError on assignment to a frozen model.
        with pytest.raises((ValidationError, TypeError)):
            _DEFAULT_CONTEXT.entity_types = frozenset({"geo.country"})  # type: ignore[misc]
