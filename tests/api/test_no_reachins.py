"""Guard: api/ must contain no getattr reach-ins on private runner attributes."""

import re
from pathlib import Path

_API_DIR = Path(__file__).parent.parent.parent / "src" / "resolvekit" / "core" / "api"
_PATTERN = re.compile(r'getattr\([^,]+,\s*"_(packs|stores|pack_id)"')

_FILES = [
    _API_DIR / "resolver.py",
    _API_DIR / "inspect.py",
]


def test_no_private_runner_reachins() -> None:
    """Assert that the facade uses backend methods, not private reach-ins."""
    violations: list[str] = []
    for path in _FILES:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _PATTERN.search(line):
                violations.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not violations, (
        "Found getattr reach-ins on private runner attributes:\n"
        + "\n".join(violations)
    )
