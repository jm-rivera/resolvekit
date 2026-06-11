"""Tests for run state store transitions."""

from concurrent.futures import ThreadPoolExecutor

from resolvekit.builder.state import RunStateStore


def test_state_store_tracks_chunk_retries_and_success(tmp_path):
    db_path = tmp_path / "state.sqlite"
    store = RunStateStore(db_path)
    store.initialize_stages(["extract", "normalize", "materialize"])
    store.upsert_chunk("geo:000000", "geo", ["country/USA"])

    extract_rows = store.chunks_for_stage("extract", max_retries=2)
    assert len(extract_rows) == 1
    assert extract_rows[0]["status"] == "pending"

    store.mark_chunk_failure(chunk_id="geo:000000", stage="extract", error="boom")
    extract_rows = store.chunks_for_stage("extract", max_retries=2)
    assert len(extract_rows) == 1
    assert extract_rows[0]["extract_attempts"] == 1

    store.mark_chunk_success(
        chunk_id="geo:000000",
        stage="extract",
        raw_path="/tmp/raw.json.gz",
    )
    normalize_rows = store.chunks_for_stage("normalize", max_retries=2)
    assert len(normalize_rows) == 1
    assert normalize_rows[0]["status"] == "extracted"

    store.mark_chunk_success(
        chunk_id="geo:000000",
        stage="normalize",
        normalized_path="/tmp/normalized.json.gz",
    )
    materialize_rows = store.chunks_for_stage("materialize", max_retries=2)
    assert len(materialize_rows) == 1
    assert materialize_rows[0]["status"] == "normalized"

    store.mark_chunk_success(chunk_id="geo:000000", stage="materialize")
    assert store.chunks_for_stage("materialize", max_retries=2) == []
    assert store.domains() == ["geo"]


def test_state_store_blocks_after_retry_budget(tmp_path):
    store = RunStateStore(tmp_path / "state.sqlite")
    store.upsert_chunk("geo:000001", "geo", ["country/FRA"])

    store.mark_chunk_failure(chunk_id="geo:000001", stage="extract", error="fail1")
    assert store.has_blocking_failures("extract", max_retries=1)


def test_state_store_parallel_writes_do_not_deadlock(tmp_path):
    store = RunStateStore(tmp_path / "state.sqlite")
    chunk_ids = [f"geo:{index:06d}" for index in range(12)]
    for chunk_id in chunk_ids:
        store.upsert_chunk(chunk_id, "geo", [f"country/{chunk_id}"])

    def _mark_success(chunk_id: str) -> None:
        store.mark_chunk_success(
            chunk_id=chunk_id,
            stage="extract",
            raw_path=f"/tmp/{chunk_id}.raw.json.gz",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(_mark_success, chunk_ids))

    rows = {
        row["chunk_id"]: row
        for row in store.chunks_for_stage("normalize", max_retries=2)
    }
    assert set(rows.keys()) == set(chunk_ids)
