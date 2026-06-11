"""Decision policy for the custom domain pack."""

from resolvekit.core.engine.decision import ThresholdDecisionPolicy

# Threshold defaults: conservative enough to avoid false positives on
# programmatically-built packs where names may be ambiguous.
_CONFIDENCE_THRESHOLD = 0.7
_MIN_GAP = 0.1


class CustomDecisionPolicy(ThresholdDecisionPolicy):
    """Threshold-based decision policy for custom entities.

    Uses gap_inclusive=True (``>=``) to match OrgDecisionPolicy semantics.
    No domain-specific early-accept, tiebreak, or acronym logic.
    """

    def __init__(
        self,
        confidence_threshold: float = _CONFIDENCE_THRESHOLD,
        min_gap: float = _MIN_GAP,
    ) -> None:
        super().__init__(
            confidence_threshold=confidence_threshold,
            min_gap=min_gap,
            gap_inclusive=True,
        )
