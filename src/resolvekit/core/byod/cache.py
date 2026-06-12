"""Content-hash cache for BYOD built packs.

Cache key
---------
The key is a SHA-256 digest streamed over:

1. Each normalised record row (one ``h.update`` per row, sorted keys) — O(n)
   streaming, never a full in-memory canonical JSON of all rows.
2. A small JSON blob: ``{schema, options, BYOD_CACHE_VERSION, base_identity?}``.

Directory layout
----------------
::

    <cache_dir>/byod/<key_prefix>/

A cache hit is ``dir.exists() and (dir / "metadata.json").exists()``.

Atomicity and cleanup
---------------------
On a cache miss the build writes to a sibling ``<key>.tmp`` directory, then
``commit_build`` promotes it to the final location (first-writer-wins: if a
valid pack already exists at the target it is kept and the redundant build is
discarded; a corrupt leftover without ``metadata.json`` is cleared first).
When ``cache=False``, the build writes to a fresh temp directory that is NOT
moved into the cache — it is kept for the resolver's lifetime.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from resolvekit.core.config import get_cache_dir
from resolvekit.core.datapack import NORMALIZER_VERSION

# Bump when the build logic or metadata schema changes in a way that
# invalidates all existing cached BYOD packs.
BYOD_CACHE_VERSION = "3"

# Sub-directory inside the resolvekit cache dir for BYOD packs.
_BYOD_SUBDIR = "byod"

# Length of the hex prefix used as the directory name.
_KEY_PREFIX_LEN = 40


def byod_cache_key(
    *,
    records: list[dict[str, Any]],
    schema: Any,
    domain: str,
    namespace: str,
    pack_type: str,
    options: dict[str, Any],
    base_identity: list[tuple[str, str, int, float]] | None = None,
) -> str:
    """Return a hex SHA-256 cache key for the given BYOD build inputs.

    The hash is streamed row-by-row (``h.update`` per row with ``sort_keys=True``)
    so it never requires an in-memory canonical JSON string of all rows.

    Args:
        records: Normalised row dicts in processing order.
        schema: The resolved ``RecordSchema`` (serialised via ``repr`` for
            consistency; the schema is a frozen dataclass so its repr is stable).
        domain: Domain string (``"geo"``, ``"org"``, ``"custom"``, …).
        namespace: Pack namespace (entity_id prefix).
        pack_type: ``"base"`` or ``"overlay"``.
        options: Build options dict (e.g. link_on, on_miss).
        base_identity: For overlay packs — list of
            ``(module_id, datapack_id, db_size_bytes, db_mtime)`` tuples
            identifying the base.  ``None`` for base packs.

    Returns:
        40-character hex prefix of the SHA-256 digest.
    """
    h = hashlib.sha256()

    for row in records:
        h.update(
            json.dumps(row, sort_keys=True, ensure_ascii=True, default=str).encode()
        )

    meta_blob = json.dumps(
        {
            "schema": repr(schema),
            "domain": domain,
            "namespace": namespace,
            "pack_type": pack_type,
            "options": options,
            "version": BYOD_CACHE_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
            "base_identity": base_identity,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    h.update(meta_blob.encode())

    return h.hexdigest()[:_KEY_PREFIX_LEN]


def byod_cache_dir() -> Path:
    """Return the root BYOD cache directory (not key-specific)."""
    return get_cache_dir() / _BYOD_SUBDIR


def cached_pack_dir(key: str) -> Path:
    """Return the pack directory path for a given cache key.

    The directory may or may not exist; call ``is_cache_hit`` to check.

    Args:
        key: Cache key from ``byod_cache_key``.

    Returns:
        ``<cache_dir>/byod/<key>/``
    """
    return byod_cache_dir() / key


def is_cache_hit(pack_dir: Path) -> bool:
    """Return True when *pack_dir* exists and contains a ``metadata.json``.

    Args:
        pack_dir: Candidate pack directory (from ``cached_pack_dir``).
    """
    return pack_dir.is_dir() and (pack_dir / "metadata.json").is_file()


def prepare_build_dir(key: str, *, cache: bool) -> tuple[Path, Path | None]:
    """Return ``(build_dir, final_dir)`` for a BYOD build.

    When ``cache=True`` and there is a cache hit on *key*, the caller should
    skip the build entirely — check with ``is_cache_hit(cached_pack_dir(key))``
    first.

    - ``cache=True`` (cache miss): ``build_dir`` is a sibling temp directory
      (``<key>.tmp.XXXXXX`` under ``<cache_dir>/byod/``).  ``final_dir`` is
      ``cached_pack_dir(key)``.  After a successful build the caller should
      call ``commit_build(build_dir, final_dir)``.
    - ``cache=False``: ``build_dir`` is a fresh temp directory under the system
      temp space.  ``final_dir`` is ``None`` — the caller must NOT call
      ``commit_build``.

    Args:
        key: Cache key from ``byod_cache_key``.
        cache: Whether to cache the result.

    Returns:
        ``(build_dir, final_dir)`` where ``final_dir`` is ``None`` iff
        ``cache=False``.
    """
    if cache:
        parent = byod_cache_dir()
        parent.mkdir(parents=True, exist_ok=True)
        tmp_str = tempfile.mkdtemp(dir=parent, prefix=f"{key}.tmp.")
        return Path(tmp_str), cached_pack_dir(key)

    tmp_str = tempfile.mkdtemp(prefix="resolvekit-byod-")
    return Path(tmp_str), None


def commit_build(build_dir: Path, final_dir: Path) -> None:
    """Promote *build_dir* into *final_dir*, tolerating an existing pack.

    The cache key is a content hash, so a pack already present at *final_dir* —
    left by a concurrent build, a retry, or a re-submit of identical content —
    is equivalent to the one just built. First writer wins: an existing valid
    pack is kept and *build_dir* is discarded. A corrupt leftover (a directory
    without ``metadata.json``) is cleared and replaced.

    ``os.replace`` cannot rename a directory onto a non-empty one (POSIX raises
    ENOTEMPTY / EEXIST), so the swap is attempted optimistically and the
    populated-target case is recovered below. An ``OSError`` that does not
    correspond to a populated *final_dir* (e.g. ENOSPC, a permission error) is
    re-raised rather than silently swallowed.

    Args:
        build_dir: Temp directory where the build was written.
        final_dir: Target cache directory (``cached_pack_dir(key)``).
    """
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(build_dir, final_dir)
    except OSError:
        if is_cache_hit(final_dir):
            # A concurrent build, retry, or re-submit already committed an
            # equivalent pack; keep it and drop our redundant build below.
            pass
        elif final_dir.exists():
            # Corrupt/incomplete leftover (no metadata.json): clear it and move
            # our build in. If another writer races a valid pack into the slot
            # first, accept that pack rather than surfacing the error.
            shutil.rmtree(final_dir, ignore_errors=True)
            try:
                os.replace(build_dir, final_dir)
            except OSError:
                if not is_cache_hit(final_dir):
                    raise
        else:
            # final_dir is absent, so the failure was not "target populated"
            # (e.g. ENOSPC, EACCES). Surface it instead of hiding it.
            raise
    shutil.rmtree(build_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Tally sidecar helpers
# ---------------------------------------------------------------------------

_TALLY_FILE = "byod_tally.json"


def write_tally(
    pack_dir: Path,
    *,
    linked: int,
    minted: int,
    skipped: int,
    ambiguous: int,
) -> None:
    """Write ``{linked, minted, skipped, ambiguous}`` to a sidecar in *pack_dir*.

    Must be called BEFORE ``commit_build`` so the file is moved atomically with
    the rest of the pack directory.

    Args:
        pack_dir: Build directory (not yet committed to the cache).
        linked: Rows linked to an existing base entity.
        minted: Rows minted as new entities.
        skipped: Unlinked rows silently dropped.
        ambiguous: Rows with >1 base match.
    """
    tally = {
        "linked": linked,
        "minted": minted,
        "skipped": skipped,
        "ambiguous": ambiguous,
    }
    (pack_dir / _TALLY_FILE).write_text(
        json.dumps(tally, indent=2, ensure_ascii=True, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def read_tally(pack_dir: Path) -> dict[str, int]:
    """Read the tally sidecar from *pack_dir*.

    Returns an empty dict when the sidecar is absent (defensive for any
    pre-version-2 cached directory that did not write a tally file).

    Args:
        pack_dir: Pack directory (cache hit path).

    Returns:
        Dict with ``linked``, ``minted``, ``skipped``, ``ambiguous`` keys, or
        ``{}`` when the sidecar is absent.
    """
    tally_path = pack_dir / _TALLY_FILE
    if not tally_path.is_file():
        return {}
    return json.loads(tally_path.read_text(encoding="utf-8"))
