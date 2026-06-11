"""Tests for markdown and HTML normalization flags on NormalizationProfile."""

import pytest

from resolvekit.core.util.normalization import NormalizationProfile, TextNormalizer
from resolvekit.packs.geo.pack import GEO_NORMALIZATION_PROFILE

# ---------------------------------------------------------------------------
# decode_html_entities
# ---------------------------------------------------------------------------


class TestDecodeHtmlEntities:
    def test_off_by_default(self):
        """HTML entities are not decoded when flag is False (the default)."""
        normalizer = TextNormalizer()
        # casefold turns & → & and amp → amp, so entity stays intact
        assert normalizer.normalize("&amp;A") == "&amp;a"

    def test_enabled_decodes_amp(self):
        """&amp; → & when decode_html_entities=True."""
        profile = NormalizationProfile(decode_html_entities=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("&amp;A") == "&a"

    def test_enabled_decodes_lt_gt(self):
        """&lt; and &gt; are decoded when flag is enabled."""
        profile = NormalizationProfile(decode_html_entities=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("&lt;tag&gt;") == "<tag>"

    def test_enabled_decodes_numeric_entity(self):
        """Numeric HTML entities (&#39;) are decoded."""
        profile = NormalizationProfile(decode_html_entities=True)
        normalizer = TextNormalizer(profile)
        # &#39; is an apostrophe; after casefold it stays as '
        result = normalizer.normalize("Cote&#39;d Ivoire")
        assert "'" in result

    def test_no_entities_in_input_unchanged(self):
        """Plain text with no entity hint characters is not affected."""
        profile = NormalizationProfile(decode_html_entities=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("France") == "france"


# ---------------------------------------------------------------------------
# strip_markdown_formatting
# ---------------------------------------------------------------------------


class TestStripMarkdownFormatting:
    def test_strip_bold_asterisks(self):
        """**United States** → united states."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("**United States**") == "united states"

    def test_strip_italic_underscore(self):
        """_Italy_ → italy."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("_Italy_") == "italy"

    def test_strip_strikethrough(self):
        """~~text~~ → text."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("~~Germany~~") == "germany"

    def test_strip_code_backtick(self):
        """`code` → code."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("`France`") == "france"

    def test_strip_leading_hash(self):
        """# Italy → italy (heading marker removed)."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("# Italy") == "italy"

    def test_strip_leading_at(self):
        """@mention → mention (leading @ removed)."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("@Italy") == "italy"

    def test_strip_leading_blockquote(self):
        """> blockquote line → content only."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("> France") == "france"

    def test_plain_text_unchanged(self):
        """Plain country name without markdown passes through unchanged."""
        profile = NormalizationProfile(strip_markdown_formatting=True)
        normalizer = TextNormalizer(profile)
        assert normalizer.normalize("Germany") == "germany"


# ---------------------------------------------------------------------------
# Geo profile flags
# ---------------------------------------------------------------------------


class TestGeoProfileFlags:
    def test_geo_profile_enables_strip_markdown(self):
        """GEO_NORMALIZATION_PROFILE has strip_markdown_formatting=True."""
        assert GEO_NORMALIZATION_PROFILE.strip_markdown_formatting is True

    def test_geo_profile_enables_decode_html(self):
        """GEO_NORMALIZATION_PROFILE has decode_html_entities=True."""
        assert GEO_NORMALIZATION_PROFILE.decode_html_entities is True


# ---------------------------------------------------------------------------
# Short-circuit guard
# ---------------------------------------------------------------------------


class TestShortCircuitGuard:
    def test_no_hint_character_skips_md_html_passes(self, monkeypatch):
        """Inputs without hint characters must not call html.unescape."""
        import html as html_module

        calls: list[str] = []
        original = html_module.unescape

        def _tracking_unescape(s: str) -> str:
            calls.append(s)
            return original(s)

        profile = NormalizationProfile(
            decode_html_entities=True, strip_markdown_formatting=True
        )
        monkeypatch.setattr(html_module, "unescape", _tracking_unescape)
        normalizer = TextNormalizer(profile)
        # No hint characters in "foo bar" — short-circuit must fire
        normalizer.normalize("foo bar")
        assert not calls, "html.unescape should not be called for plain text"


# ---------------------------------------------------------------------------
# Cache invariant: two profiles with different flags → different results
# ---------------------------------------------------------------------------


class TestCacheInvariantAcrossProfiles:
    def test_different_flag_settings_produce_different_results(self):
        """Same input through two profiles with different flags → different output."""
        input_text = "&amp;Italy"
        plain = TextNormalizer(NormalizationProfile())
        html_on = TextNormalizer(NormalizationProfile(decode_html_entities=True))
        assert plain.normalize(input_text) != html_on.normalize(input_text)

    def test_same_normalizer_instance_caches_correctly(self):
        """LRU cache on a single normalizer instance stays self-consistent."""
        profile = NormalizationProfile(decode_html_entities=True)
        normalizer = TextNormalizer(profile)
        result1 = normalizer.normalize("&amp;A")
        result2 = normalizer.normalize("&amp;A")
        assert result1 == result2 == "&a"


# ---------------------------------------------------------------------------
# Combined flags
# ---------------------------------------------------------------------------


class TestCombinedFlags:
    def test_html_then_markdown(self):
        """HTML entity decode runs before markdown strip."""
        profile = NormalizationProfile(
            decode_html_entities=True, strip_markdown_formatting=True
        )
        normalizer = TextNormalizer(profile)
        # &amp; decodes to & (not a markdown hint after decode), so markdown
        # pass doesn't interfere; bold markers are still stripped.
        result = normalizer.normalize("**&amp;Italy**")
        assert result == "&italy"

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("**France**", "france"),
            ("_Germany_", "germany"),
            ("# Italy", "italy"),
            ("&amp;Spain", "&spain"),
            ("> Brazil", "brazil"),
            ("`Japan`", "japan"),
        ],
    )
    def test_geo_normalizer_strips_common_patterns(self, raw: str, expected: str):
        """GEO_NORMALIZATION_PROFILE normalizer handles common markdown/HTML inputs."""
        normalizer = TextNormalizer(GEO_NORMALIZATION_PROFILE)
        assert normalizer.normalize(raw) == expected
