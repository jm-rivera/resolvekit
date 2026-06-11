"""Regression tests for BuildReport / LastError wire-format compatibility.

Guards three invariants:
1. dump_for_build_report() re-derives the legacy 'error' field for build_report.json.
2. model_dump() (state.sqlite path) does NOT include 'error'.
3. model_validate() tolerates legacy state.sqlite rows that still carry 'error'.
"""

from __future__ import annotations

from resolvekit.builder.pipeline.types import LastError


def test_build_report_payload_contains_legacy_error_field() -> None:
    """Verify the actual on-disk legacy-error preservation: the build_report.json
    payload must contain payload['last_error']['error']."""
    err = LastError(stage="discover", error_type="RuntimeError", message="boom")
    payload = err.dump_for_build_report()
    # This is the assertion the broken v1 of this test missed: the on-disk shape
    # of payload["last_error"] must include the legacy 'error' field.
    assert payload["error"] == "RuntimeError: boom"
    assert payload["stage"] == "discover"
    assert payload["error_type"] == "RuntimeError"
    assert payload["message"] == "boom"
    assert payload["timestamp"]  # non-empty default


def test_last_error_default_dump_excludes_legacy_error_field() -> None:
    """The plain model_dump (used for state.sqlite persistence) must NOT include
    the legacy 'error' field — it's recomputed only at the build_report.json
    write boundary. This guards against a future maintainer "modernizing" the
    @property to @computed_field, which would silently re-add the field."""
    err = LastError(stage="discover", error_type="RuntimeError", message="boom")
    payload = err.model_dump(mode="json")
    assert "error" not in payload
    assert set(payload) == {"stage", "error_type", "message", "timestamp"}


def test_last_error_loads_legacy_state_with_error_field() -> None:
    """Existing state.sqlite rows that contain the legacy 'error' key must
    load cleanly through model_validate via extra='ignore'."""
    legacy_payload = {
        "stage": "discover",
        "error_type": "RuntimeError",
        "message": "boom",
        "error": "RuntimeError: boom",  # legacy field — should be ignored on load
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    err = LastError.model_validate(legacy_payload)
    assert err.stage == "discover"
    assert err.error_type == "RuntimeError"
    assert err.message == "boom"
    assert err.timestamp == "2026-01-01T00:00:00+00:00"
    # The @property still derives the legacy string for build_report.json:
    assert err.error == "RuntimeError: boom"
