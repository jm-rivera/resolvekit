"""Unit tests for shared Data Commons runtime client helpers."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from resolvekit.builder.sources.datacommons import client as client_module
from resolvekit.builder.sources.datacommons.client import DataCommons


class _FakeNode:
    def __init__(
        self,
        *,
        fail_if_more_than: int | None = None,
        sleep_seconds: float = 0.0,
    ) -> None:
        self.fail_if_more_than = fail_if_more_than
        self.sleep_seconds = sleep_seconds
        self.calls: list[tuple[str, ...]] = []
        self.max_active = 0
        self._active = 0
        self._lock = threading.Lock()

    def fetch_place_children(
        self,
        *,
        place_dcids: list[str],
        children_type: str,
    ) -> dict[str, list[dict[str, str]]]:
        _ = children_type
        if self.sleep_seconds > 0:
            with self._lock:
                self._active += 1
                self.max_active = max(self.max_active, self._active)
            time.sleep(self.sleep_seconds)
            with self._lock:
                self._active -= 1
        self.calls.append(tuple(place_dcids))
        if (
            self.fail_if_more_than is not None
            and len(place_dcids) > self.fail_if_more_than
        ):
            raise RuntimeError("response too large")
        return {
            parent: [{"dcid": f"{parent}/child-1"}, {"dcid": f"{parent}/child-2"}]
            for parent in place_dcids
        }


class _FakeClient:
    def __init__(self, node: _FakeNode) -> None:
        self.node = node


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get_properties(self) -> dict[str, Any]:
        return self._payload


class _FakeMetadataNode:
    def fetch_entity_names(
        self,
        *,
        entity_dcids: list[str],
        language: str,
        fallback_language: str | None = None,
    ) -> dict[str, Any]:
        _ = (entity_dcids, fallback_language)
        return {
            "org/BMGF": SimpleNamespace(
                value="Bill & Melinda Gates Foundation",
                language=language,
                property="name" if language == "en" else "nameWithLanguage",
            )
        }

    def fetch_all_classes(self) -> _FakeResponse:
        return _FakeResponse(
            {
                "Class": {
                    "typeOf": [
                        SimpleNamespace(value="Organization"),
                        SimpleNamespace(dcid="Company"),
                    ]
                }
            }
        )

    def fetch_property_labels(
        self,
        *,
        node_dcids: list[str],
        out: bool,
    ) -> _FakeResponse:
        _ = (node_dcids, out)
        return _FakeResponse(
            {
                "org/BMGF": {
                    "name": [],
                    "shortDisplayName": [],
                    "dacCodeStr": [],
                }
            }
        )


class _CapturingClient:
    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        type(self).calls.append(kwargs)
        self.node = _FakeNode()


def _runtime_with_client(client: Any) -> DataCommons:
    runtime = DataCommons(dc_instance="test")
    runtime._client = client
    return runtime


def _runtime_with_limited_client(
    client: Any, *, max_concurrent_requests: int
) -> DataCommons:
    runtime = DataCommons(
        dc_instance="test",
        max_concurrent_requests=max_concurrent_requests,
    )
    runtime._client = client
    return runtime


def test_fetch_place_children_for_parents_returns_children_by_parent() -> None:
    node = _FakeNode()
    runtime = _runtime_with_client(_FakeClient(node))

    rows = runtime.fetch_place_children_for_parents(
        place_type="Admin2",
        parent_places=["country/a", "country/b"],
        chunk_size=2,
    )

    assert rows == {
        "country/a": ["country/a/child-1", "country/a/child-2"],
        "country/b": ["country/b/child-1", "country/b/child-2"],
    }
    assert node.calls == [("country/a", "country/b")]


def test_fetch_place_children_for_parents_splits_batch_on_failure() -> None:
    node = _FakeNode(fail_if_more_than=2)
    runtime = _runtime_with_client(_FakeClient(node))

    rows = runtime.fetch_place_children_for_parents(
        place_type="Admin4",
        parent_places=["p1", "p2", "p3", "p4", "p5"],
        chunk_size=5,
    )

    assert set(rows) == {"p1", "p2", "p3", "p4", "p5"}
    assert all(children for children in rows.values())
    assert any(len(call) > 2 for call in node.calls)
    assert any(len(call) <= 2 for call in node.calls)


def test_fetch_place_children_for_parents_parallelizes_chunks() -> None:
    node = _FakeNode(sleep_seconds=0.03)
    runtime = _runtime_with_client(_FakeClient(node))

    rows = runtime.fetch_place_children_for_parents(
        place_type="Admin2",
        parent_places=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
        chunk_size=1,
        max_workers=4,
    )

    assert set(rows) == {"p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"}
    assert node.max_active > 1


def test_fetch_place_children_for_parents_respects_global_request_limit() -> None:
    node = _FakeNode(sleep_seconds=0.03)
    runtime = _runtime_with_limited_client(
        _FakeClient(node),
        max_concurrent_requests=1,
    )

    rows = runtime.fetch_place_children_for_parents(
        place_type="Admin2",
        parent_places=["p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"],
        chunk_size=1,
        max_workers=8,
    )

    assert set(rows) == {"p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8"}
    assert node.max_active == 1


def test_client_or_raise_uses_public_instance_for_datacommons_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingClient.calls.clear()
    monkeypatch.setattr(
        client_module,
        "_load_datacommons_client_class",
        lambda: _CapturingClient,
    )
    runtime = DataCommons(dc_instance="datacommons.org")

    runtime.client_or_raise()

    assert _CapturingClient.calls == [{"dc_instance": "datacommons.org"}]


def test_client_or_raise_uses_custom_instance_and_api_key_for_one_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingClient.calls.clear()
    monkeypatch.setattr(
        client_module,
        "_load_datacommons_client_class",
        lambda: _CapturingClient,
    )
    runtime = DataCommons(
        dc_instance="datacommons.one.org",
        api_key="secret-key",
    )

    runtime.client_or_raise()

    assert _CapturingClient.calls == [
        {
            "api_key": "secret-key",
            "dc_instance": "datacommons.one.org",
        }
    ]


def test_client_or_raise_falls_back_to_environment_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingClient.calls.clear()
    monkeypatch.setattr(
        client_module,
        "_load_datacommons_client_class",
        lambda: _CapturingClient,
    )
    monkeypatch.setenv("DATACOMMONS_API_KEY", "env-secret")
    runtime = DataCommons(dc_instance="datacommons.one.org")

    runtime.client_or_raise()

    assert _CapturingClient.calls == [
        {
            "api_key": "env-secret",
            "dc_instance": "datacommons.one.org",
        }
    ]


def test_client_or_raise_uses_url_when_fully_qualified_base_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _CapturingClient.calls.clear()
    monkeypatch.setattr(
        client_module,
        "_load_datacommons_client_class",
        lambda: _CapturingClient,
    )
    runtime = DataCommons(dc_instance="https://datacommons.one.org")

    runtime.client_or_raise()

    assert _CapturingClient.calls == [
        {"url": "https://datacommons.one.org/core/api/v2"}
    ]


def test_fetch_entity_name_rows_preserves_language_and_property() -> None:
    runtime = _runtime_with_client(_FakeClient(_FakeMetadataNode()))

    rows = runtime.fetch_entity_name_rows(["org/BMGF"], lang="fr")

    assert rows["org/BMGF"].value == "Bill & Melinda Gates Foundation"
    assert rows["org/BMGF"].language == "fr"
    assert rows["org/BMGF"].property == "nameWithLanguage"


def test_fetch_all_classes_returns_unique_class_names() -> None:
    runtime = _runtime_with_client(_FakeClient(_FakeMetadataNode()))

    classes = runtime.fetch_all_classes()

    assert classes == ["Organization", "Company"]


def test_fetch_property_labels_returns_available_property_keys() -> None:
    runtime = _runtime_with_client(_FakeClient(_FakeMetadataNode()))

    labels = runtime.fetch_property_labels(["org/BMGF"])

    assert labels == {"org/BMGF": ["name", "shortDisplayName", "dacCodeStr"]}


def test_fetch_property_labels_accepts_list_payload_shape() -> None:
    class _ListLabelNode:
        def fetch_property_labels(
            self, *, node_dcids: list[str], out: bool
        ) -> _FakeResponse:
            _ = (node_dcids, out)
            return _FakeResponse({"org/BMGF": ["name", "shortDisplayName", "name"]})

    runtime = _runtime_with_client(_FakeClient(_ListLabelNode()))

    labels = runtime.fetch_property_labels(["org/BMGF"])

    assert labels == {"org/BMGF": ["name", "shortDisplayName"]}


class _FakeHTTPError(RuntimeError):
    """Stand-in for datacommons_client APIError carrying status + response."""

    def __init__(self, *, status_code: int, retry_after: str | None = None) -> None:
        super().__init__(f"An API error occurred.\nStatus Code: {status_code}")
        self.status_code = status_code
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        self.response = SimpleNamespace(status_code=status_code, headers=headers)


def test_call_limited_retries_on_429_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise _FakeHTTPError(status_code=429)
        return "ok"

    assert runtime._call_limited(flaky) == "ok"
    assert attempts["n"] == 3
    # Two backoff sleeps, exponential from the base delay.
    assert slept == [
        client_module._RATE_LIMIT_BASE_DELAY_SEC,
        client_module._RATE_LIMIT_BASE_DELAY_SEC * 2.0,
    ]


def test_call_limited_does_not_retry_4xx_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4xx client error is permanent — propagate immediately (e.g. for the splitter)."""
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    def boom() -> str:
        attempts["n"] += 1
        raise _FakeHTTPError(status_code=400)

    with pytest.raises(_FakeHTTPError):
        runtime._call_limited(boom)
    assert attempts["n"] == 1
    assert slept == []


def test_call_limited_retries_on_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient 5xx (e.g. 503) backs off and retries rather than failing the stage."""
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise _FakeHTTPError(status_code=503)
        return "ok"

    assert runtime._call_limited(flaky) == "ok"
    assert attempts["n"] == 3
    assert slept == [
        client_module._RATE_LIMIT_BASE_DELAY_SEC,
        client_module._RATE_LIMIT_BASE_DELAY_SEC * 2.0,
    ]


def test_call_limited_retries_on_wrapped_mixer_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DC client wraps the mixer status (HTTP 500, body says 503) — still retried."""
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    class _MixerError(RuntimeError):
        # No status_code attribute — only the wrapped message, as seen in prod.
        pass

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _MixerError(
                "The Data Commons API returned a non-2xx status code.\n"
                "Status Code: 500\n"
                'Response: {"message":"remote mixer response not ok: '
                '503 Service Unavailable"}'
            )
        return "ok"

    assert runtime._call_limited(flaky) == "ok"
    assert attempts["n"] == 2


def test_call_limited_honors_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []
    monkeypatch.setattr(client_module.time, "sleep", slept.append)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    def flaky() -> str:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _FakeHTTPError(status_code=429, retry_after="7")
        return "ok"

    assert runtime._call_limited(flaky) == "ok"
    assert slept == [7.0]


def _runtime_with_cache(client: Any, *, cache_dir: Path) -> DataCommons:
    runtime = DataCommons(dc_instance="test", cache_dir=cache_dir)
    runtime._client = client
    return runtime


def test_place_children_cache_hit_avoids_second_request(tmp_path: Path) -> None:
    node = _FakeNode()
    runtime = _runtime_with_cache(_FakeClient(node), cache_dir=tmp_path)

    first = runtime.fetch_place_children(place_type="Country", parent_place="Earth")
    second = runtime.fetch_place_children(place_type="Country", parent_place="Earth")

    assert first == second == ["Earth/child-1", "Earth/child-2"]
    # The second call is served entirely from disk — the node is hit only once.
    assert node.calls == [("Earth",)]


def test_place_children_cache_persists_across_runtimes(tmp_path: Path) -> None:
    node = _FakeNode()
    _runtime_with_cache(_FakeClient(node), cache_dir=tmp_path).fetch_place_children(
        place_type="Country", parent_place="Earth"
    )

    # A fresh runtime (new build process) over the same cache dir re-fetches nothing.
    fresh_node = _FakeNode()
    result = _runtime_with_cache(
        _FakeClient(fresh_node), cache_dir=tmp_path
    ).fetch_place_children(place_type="Country", parent_place="Earth")

    assert result == ["Earth/child-1", "Earth/child-2"]
    assert fresh_node.calls == []


def test_no_cache_dir_writes_nothing_and_always_fetches(tmp_path: Path) -> None:
    node = _FakeNode()
    runtime = _runtime_with_client(_FakeClient(node))  # no cache_dir

    runtime.fetch_place_children(place_type="Country", parent_place="Earth")
    runtime.fetch_place_children(place_type="Country", parent_place="Earth")

    assert node.calls == [("Earth",), ("Earth",)]
    assert list(tmp_path.iterdir()) == []


def test_genuine_empty_children_cached_and_not_refetched(tmp_path: Path) -> None:
    class _EmptyNode:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def fetch_place_children(
            self, *, place_dcids: list[str], children_type: str
        ) -> dict[str, list[dict[str, str]]]:
            _ = children_type
            self.calls.append(tuple(place_dcids))
            return {place_dcids[0]: []}

    node = _EmptyNode()
    runtime = _runtime_with_cache(_FakeClient(node), cache_dir=tmp_path)

    assert runtime.fetch_place_children(place_type="City", parent_place="p") == []
    # An empty result is a cached hit, not a perpetual miss.
    assert runtime.fetch_place_children(place_type="City", parent_place="p") == []
    assert node.calls == [("p",)]


def test_corrupt_cache_file_is_treated_as_miss(tmp_path: Path) -> None:
    node = _FakeNode()
    runtime = _runtime_with_cache(_FakeClient(node), cache_dir=tmp_path)
    cache_name = runtime._place_cache_name("children", "Country", ["Earth"])
    (tmp_path / cache_name).write_text("{ not valid json", encoding="utf-8")

    result = runtime.fetch_place_children(place_type="Country", parent_place="Earth")

    assert result == ["Earth/child-1", "Earth/child-2"]
    assert node.calls == [("Earth",)]


def test_for_parents_resumes_completed_chunks_after_failure(tmp_path: Path) -> None:
    """A transient failure mid-walk leaves completed chunks cached; the re-run
    re-fetches only the chunks that never finished."""

    class _FailOnNode:
        def __init__(self, fail_parents: set[str]) -> None:
            self.fail_parents = fail_parents
            self.calls: list[tuple[str, ...]] = []

        def fetch_place_children(
            self, *, place_dcids: list[str], children_type: str
        ) -> dict[str, list[dict[str, str]]]:
            _ = children_type
            self.calls.append(tuple(place_dcids))
            if self.fail_parents.intersection(place_dcids):
                raise RuntimeError("transient")
            return {p: [{"dcid": f"{p}/c"}] for p in place_dcids}

    parents = ["p1", "p2", "p3"]
    node1 = _FailOnNode(fail_parents={"p2"})
    runtime1 = _runtime_with_cache(_FakeClient(node1), cache_dir=tmp_path)
    with pytest.raises(RuntimeError):
        runtime1.fetch_place_children_for_parents(
            place_type="Admin1", parent_places=parents, chunk_size=1
        )
    # p1 completed and is cached before p2 raised.
    assert ("p1",) in node1.calls

    node2 = _FailOnNode(fail_parents=set())
    runtime2 = _runtime_with_cache(_FakeClient(node2), cache_dir=tmp_path)
    rows = runtime2.fetch_place_children_for_parents(
        place_type="Admin1", parent_places=parents, chunk_size=1
    )

    assert rows == {"p1": ["p1/c"], "p2": ["p2/c"], "p3": ["p3/c"]}
    # The completed chunk (p1) is served from cache; only p2 and p3 re-fetch.
    assert ("p1",) not in node2.calls
    assert ("p2",) in node2.calls and ("p3",) in node2.calls


def test_call_limited_gives_up_after_max_429_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client_module.time, "sleep", lambda _seconds: None)
    runtime = DataCommons(dc_instance="test")
    attempts = {"n": 0}

    def always_429() -> str:
        attempts["n"] += 1
        raise _FakeHTTPError(status_code=429)

    with pytest.raises(_FakeHTTPError):
        runtime._call_limited(always_429)
    assert attempts["n"] == client_module._RATE_LIMIT_MAX_RETRIES + 1
