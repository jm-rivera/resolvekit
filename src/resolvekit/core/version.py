"""SemVer version compatibility checking.

This module provides utilities for parsing and comparing semantic versions,
used to validate that overlay packs are compatible with base packs.

Version compatibility rules:
- Major version must match exactly (incompatible if different)
- Minor version: overlay newer than base produces a warning
- Patch version: differences are silent (compatible)
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Version:
    """Parsed semantic version.

    Attributes:
        major: Major version number (breaking changes)
        minor: Minor version number (backward-compatible additions)
        patch: Patch version number (bug fixes)
    """

    major: int
    minor: int
    patch: int

    # Pattern matches MAJOR.MINOR or MAJOR.MINOR.PATCH, ignoring prerelease/build metadata
    _PATTERN = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:[-+].*)?$")

    @classmethod
    def parse(cls, version_str: str) -> "Version":
        """Parse a SemVer string.

        Args:
            version_str: Version string in format "MAJOR.MINOR" or "MAJOR.MINOR.PATCH"
                        When patch is omitted, it defaults to 0.
                        Prerelease (-beta) and build (+build) suffixes are ignored.

        Returns:
            Parsed Version instance

        Raises:
            ValueError: If version string is invalid
        """
        match = cls._PATTERN.match(version_str.strip())
        if not match:
            raise ValueError(f"Invalid version format: {version_str!r}")

        return cls(
            major=int(match.group(1)),
            minor=int(match.group(2)),
            patch=int(match.group(3)) if match.group(3) else 0,
        )

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class VersionCheck:
    """Result of version compatibility check.

    Attributes:
        compatible: Whether versions are compatible
        warning: Optional warning message (e.g., for minor version mismatch)
    """

    compatible: bool
    warning: str | None = None


def check_version_compatibility(
    base_version: str,
    overlay_version: str,
) -> VersionCheck:
    """Check if overlay version is compatible with base version.

    Compatibility rules (per design doc):
    - Major mismatch: INCOMPATIBLE (error)
    - Minor mismatch (overlay newer): COMPATIBLE with warning
    - Minor mismatch (base newer): COMPATIBLE (silent)
    - Patch mismatch: COMPATIBLE (silent)

    Args:
        base_version: Base pack's schema version string
        overlay_version: Overlay pack's schema version string

    Returns:
        VersionCheck with compatibility result and optional warning

    Raises:
        ValueError: If either version string is invalid
    """
    base = Version.parse(base_version)
    overlay = Version.parse(overlay_version)

    if base.major != overlay.major:
        return VersionCheck(
            compatible=False,
            warning=(
                f"Major version mismatch: base has {base}, overlay has {overlay}. "
                f"Major versions must match for compatibility."
            ),
        )

    if overlay.minor > base.minor:
        return VersionCheck(
            compatible=True,
            warning=(
                f"Overlay uses newer schema ({overlay}) than base ({base}). "
                f"Overlay may reference fields not present in base pack."
            ),
        )

    return VersionCheck(compatible=True, warning=None)
