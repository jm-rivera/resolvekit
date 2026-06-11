"""Tests for model package exports."""


def test_model_exports():
    """All key types should be importable from the model package."""
    from resolvekit.core.model import (
        # Candidate types
        ResolutionStatus,
        Severity,
    )

    # Verify they're the correct types
    assert ResolutionStatus.RESOLVED == "resolved"
    assert Severity.HARD == "hard"
