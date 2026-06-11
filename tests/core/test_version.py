"""Tests for SemVer version compatibility checking."""

import pytest

from resolvekit.core.version import (
    Version,
    VersionCheck,
    check_version_compatibility,
)


class TestVersion:
    """Tests for Version parsing and comparison."""

    def test_parse_valid_version(self):
        """Parse valid SemVer string."""
        v = Version.parse("1.2.3")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_zero_version(self):
        """Parse version with zeros."""
        v = Version.parse("0.0.0")
        assert v.major == 0
        assert v.minor == 0
        assert v.patch == 0

    def test_parse_large_numbers(self):
        """Parse version with large numbers."""
        v = Version.parse("100.200.300")
        assert v.major == 100
        assert v.minor == 200
        assert v.patch == 300

    def test_parse_two_part_version(self):
        """Parse MAJOR.MINOR format (patch defaults to 0)."""
        v = Version.parse("1.2")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 0

    def test_parse_common_two_part_versions(self):
        """Parse common two-part version strings."""
        v1 = Version.parse("1.0")
        assert v1 == Version(1, 0, 0)

        v2 = Version.parse("2.1")
        assert v2 == Version(2, 1, 0)

    def test_parse_invalid_format_raises(self):
        """Invalid format raises ValueError."""
        with pytest.raises(ValueError, match="Invalid version"):
            Version.parse("1")

    def test_parse_non_numeric_raises(self):
        """Non-numeric components raise ValueError."""
        with pytest.raises(ValueError, match="Invalid version"):
            Version.parse("1.x.3")

    def test_parse_extra_components_raises(self):
        """Extra components raise ValueError."""
        with pytest.raises(ValueError, match="Invalid version"):
            Version.parse("1.2.3.4")

    def test_parse_prerelease_ignored(self):
        """Prerelease suffix is stripped."""
        v = Version.parse("1.2.3-beta")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_parse_build_metadata_ignored(self):
        """Build metadata is stripped."""
        v = Version.parse("1.2.3+build123")
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3

    def test_str_representation(self):
        """String representation is MAJOR.MINOR.PATCH."""
        v = Version(major=1, minor=2, patch=3)
        assert str(v) == "1.2.3"

    def test_equality(self):
        """Versions with same components are equal."""
        v1 = Version.parse("1.2.3")
        v2 = Version.parse("1.2.3")
        assert v1 == v2

    def test_inequality(self):
        """Versions with different components are not equal."""
        v1 = Version.parse("1.2.3")
        v2 = Version.parse("1.2.4")
        assert v1 != v2


class TestVersionCheck:
    """Tests for VersionCheck result type."""

    def test_compatible_no_warning(self):
        """Compatible result with no warning."""
        check = VersionCheck(compatible=True, warning=None)
        assert check.compatible is True
        assert check.warning is None

    def test_compatible_with_warning(self):
        """Compatible result with warning."""
        check = VersionCheck(compatible=True, warning="Minor version mismatch")
        assert check.compatible is True
        assert check.warning == "Minor version mismatch"

    def test_incompatible(self):
        """Incompatible result."""
        check = VersionCheck(compatible=False, warning="Major version mismatch")
        assert check.compatible is False
        assert check.warning == "Major version mismatch"


class TestCheckVersionCompatibility:
    """Tests for check_version_compatibility function."""

    def test_exact_match_compatible(self):
        """Exact version match is compatible, no warning."""
        result = check_version_compatibility("1.2.3", "1.2.3")
        assert result.compatible is True
        assert result.warning is None

    def test_patch_difference_compatible_silent(self):
        """Patch difference is compatible and silent."""
        result = check_version_compatibility("1.2.3", "1.2.4")
        assert result.compatible is True
        assert result.warning is None

    def test_minor_overlay_newer_compatible_with_warning(self):
        """Overlay with newer minor version: compatible with warning."""
        result = check_version_compatibility("1.2.0", "1.3.0")
        assert result.compatible is True
        assert result.warning is not None
        assert "newer" in result.warning.lower() or "1.3.0" in result.warning

    def test_minor_base_newer_compatible_silent(self):
        """Base with newer minor version: compatible and silent."""
        result = check_version_compatibility("1.3.0", "1.2.0")
        assert result.compatible is True
        assert result.warning is None

    def test_major_mismatch_incompatible(self):
        """Major version mismatch is incompatible."""
        result = check_version_compatibility("1.0.0", "2.0.0")
        assert result.compatible is False
        assert result.warning is not None

    def test_major_mismatch_overlay_lower(self):
        """Overlay with lower major version is incompatible."""
        result = check_version_compatibility("2.0.0", "1.0.0")
        assert result.compatible is False

    def test_zero_major_version(self):
        """Zero major version follows same rules."""
        # Same major (0)
        result = check_version_compatibility("0.1.0", "0.2.0")
        assert result.compatible is True

        # Different major
        result = check_version_compatibility("0.1.0", "1.0.0")
        assert result.compatible is False

    def test_invalid_base_version_raises(self):
        """Invalid base version raises ValueError."""
        with pytest.raises(ValueError):
            check_version_compatibility("invalid", "1.0.0")

    def test_invalid_overlay_version_raises(self):
        """Invalid overlay version raises ValueError."""
        with pytest.raises(ValueError):
            check_version_compatibility("1.0.0", "invalid")
