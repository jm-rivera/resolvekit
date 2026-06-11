"""Guard test: engine/ source files must contain zero domain-specific strings.

Greps runner.py, multi_runner.py, and enrichment.py for literals that encode
domain knowledge (pack names, entity-type prefixes, constraint names, source names).
A match here means domain logic leaked into the generic engine.
"""

import re
from pathlib import Path

# Forbidden literals — exact patterns the CI grep gate looks for
FORBIDDEN_PATTERNS = [
    r"geo\.",
    r"country/",
    r"org_parent_constraint",
    r"org_country_relevance",
    r"_symspell_exact_name",
    r"_fuzzy_retrieval",
]

ENGINE_DIR = Path(__file__).parents[2] / "src" / "resolvekit" / "core" / "engine"

CHECKED_FILES = [
    ENGINE_DIR / "runner.py",
    ENGINE_DIR / "multi_runner.py",
    ENGINE_DIR / "enrichment.py",
]


def _search_file(path: Path, pattern: str) -> list[str]:
    compiled = re.compile(pattern)
    hits: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if compiled.search(line):
            hits.append(f"  {path.name}:{lineno}: {line.rstrip()}")
    return hits


class TestEngineDomainStringFree:
    def test_no_forbidden_literals_in_engine_files(self) -> None:
        all_hits: list[str] = []
        for path in CHECKED_FILES:
            assert path.exists(), f"Expected engine file not found: {path}"
            for pattern in FORBIDDEN_PATTERNS:
                hits = _search_file(path, pattern)
                all_hits.extend(hits)

        if all_hits:
            lines = "\n".join(all_hits)
            raise AssertionError(
                f"Found {len(all_hits)} forbidden domain string(s) in engine/:\n{lines}"
            )
