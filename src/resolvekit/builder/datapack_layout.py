"""Datapack filesystem layout helpers.

Module IDs use the dotted form ``"<domain>.<subpath>"``, where ``<domain>``
is the top-level category (e.g. ``"geo"``) and ``<subpath>`` may itself
contain dots that map to underscores on disk
(e.g. ``"geo.sub.pack"`` → ``_data/geo/sub_pack/``).

v1 flat layout: ``<datapacks_root>/<domain>/<subpath>/metadata.json``
A directory is a datapack dir if and only if it contains ``metadata.json``
— the directory name is irrelevant.
"""

from __future__ import annotations

from pathlib import Path

# Dotted module identifier, e.g. "geo.countries" or "geo.admin1".
type ModuleId = str


def find_latest_datapack_dir(*, module_dir: Path) -> Path | None:
    """Return the datapack directory for *module_dir*, or ``None`` if absent.

    A directory containing ``metadata.json`` is a flat datapack dir.

    Args:
        module_dir: The directory to inspect (one module's on-disk directory).

    Returns:
        The resolved datapack directory, or ``None`` when none is found.
    """
    if (module_dir / "metadata.json").is_file():
        return module_dir
    return None


def iter_datapack_dirs(*, datapacks_root: Path) -> list[Path]:
    """Return all datapack directories under *datapacks_root*.

    Walks every ``metadata.json`` under *datapacks_root* via ``rglob``; the
    parent of each is a flat datapack dir. Dot-prefixed directories are
    skipped — real datapack dirs are never hidden, and the packaging publish
    step uses transient ``.<name>.incoming`` / ``.<name>.prev`` staging dirs
    (which contain a ``metadata.json``) that must not be mistaken for packs.

    Args:
        datapacks_root: Root directory containing module subtrees
            (e.g. ``src/resolvekit/_data``).

    Returns:
        Ordered list of datapack directories.

    Raises:
        FileNotFoundError: If *datapacks_root* does not exist.
    """
    if not datapacks_root.exists():
        raise FileNotFoundError(f"Datapack root does not exist: {datapacks_root}")

    seen: set[Path] = set()
    found: list[Path] = []

    for meta_path in sorted(datapacks_root.rglob("metadata.json")):
        d = meta_path.parent
        if any(part.startswith(".") for part in d.relative_to(datapacks_root).parts):
            continue
        if d in seen:
            continue
        seen.add(d)
        found.append(d)

    return found


def module_pack_dir(*, module_id: ModuleId, datapacks_root: Path) -> Path:
    """Return the on-disk datapack directory for *module_id*.

    Converts the dotted module ID to a filesystem path:
    ``"geo.countries"`` → ``<datapacks_root>/geo/countries``
    ``"geo.sub.pack"`` → ``<datapacks_root>/geo/sub_pack``

    Args:
        module_id: Dotted module identifier (must contain at least one dot;
            neither the domain nor the subpath may be empty).
        datapacks_root: Root directory containing module subtrees.

    Returns:
        Path to the module's datapack directory (may not exist yet).

    Raises:
        ValueError: If *module_id* has no dot, or if the domain or subpath
            portion is empty.
    """
    domain, sep, subpath = module_id.partition(".")
    if not sep or not domain or not subpath:
        raise ValueError(
            f"module_id must be '<domain>.<subpath>' with non-empty parts; "
            f"got {module_id!r}"
        )
    return datapacks_root / domain / subpath.replace(".", "_")
