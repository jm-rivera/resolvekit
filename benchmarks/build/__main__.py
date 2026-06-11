"""`python -m benchmarks.build` — rebuild every committed dataset."""

from __future__ import annotations

import logging
import sys

from benchmarks.build import build_all


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    build_all()
    return 0


if __name__ == "__main__":
    sys.exit(main())
