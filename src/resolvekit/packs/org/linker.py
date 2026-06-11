"""Org-specific linker for overlay composition."""

from resolvekit.core.linking import BaseLinker


class OrgLinker(BaseLinker):
    """Linker for org domain entities.

    Understands dcid, lei, duns, permid, ticker code systems.
    """

    KNOWN_CODE_SYSTEMS = frozenset({"dcid", "lei", "duns", "permid", "ticker"})
