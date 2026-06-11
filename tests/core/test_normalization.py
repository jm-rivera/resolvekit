"""Tests for text normalization utilities."""


class TestTextNormalizer:
    """Tests for core text normalization."""

    def test_unicode_normalization(self):
        from resolvekit.core.util.normalization import TextNormalizer

        normalizer = TextNormalizer()

        # NFC normalization (composed form)
        assert normalizer.normalize("cafe\u0301") == "café"  # Should be NFC

    def test_casefolding(self):
        from resolvekit.core.util.normalization import TextNormalizer

        normalizer = TextNormalizer()

        result = normalizer.normalize("United States")
        assert result == "united states"

    def test_whitespace_normalization(self):
        from resolvekit.core.util.normalization import TextNormalizer

        normalizer = TextNormalizer()

        result = normalizer.normalize("  United   States  ")
        assert result == "united states"

    def test_preserves_original(self):
        from resolvekit.core.util.normalization import TextNormalizer

        normalizer = TextNormalizer()

        text = "United States"
        result = normalizer.normalize_with_original(text)

        assert result.original == "United States"
        assert result.normalized == "united states"


class TestNormalizationProfile:
    """Tests for normalization profiles."""

    def test_default_profile(self):
        from resolvekit.core.util.normalization import NormalizationProfile

        profile = NormalizationProfile()
        assert profile.casefold is True
        assert profile.unicode_nfc is True

    def test_custom_profile(self):
        from resolvekit.core.util.normalization import NormalizationProfile

        profile = NormalizationProfile(
            casefold=False,
            strip_punctuation=True,
        )
        assert profile.casefold is False
        assert profile.strip_punctuation is True
