"""SymSpell-based typo-tolerant source for org entities."""

from resolvekit.shared.sources import SymSpellSource


class OrgSymSpellSource(SymSpellSource):
    """SymSpell-based typo correction for org names.

    Uses a pre-built dictionary of org names for fast correction.
    Falls back gracefully if dictionary unavailable or symspellpy not installed.
    """

    def __init__(
        self,
        dictionary_path: str | None = None,
        max_edit_distance: int = 2,
        prefix_length: int = 7,
    ):
        super().__init__(
            name="org_symspell",
            domain="org",
            dictionary_path=dictionary_path,
            max_edit_distance=max_edit_distance,
            prefix_length=prefix_length,
            matched_field="symspell_correction",
        )
