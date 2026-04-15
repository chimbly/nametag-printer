from unittest import TestCase

from nametags.sanitize import sanitize_label_text, sanitize_text_line


class TestSanitize(TestCase):
    def test_strips_controls_and_normalizes_whitespace(self):
        cleaned = sanitize_text_line("  Jo\nse\u0000 \t", 100)
        self.assertEqual(cleaned, "Jose")

    def test_preserves_zwj_sequences(self):
        value = sanitize_text_line("\U0001f469\u200d\U0001f4bb", 10)
        self.assertEqual(value, "\U0001f469\u200d\U0001f4bb")

    def test_truncates_on_grapheme_boundaries(self):
        cleaned = sanitize_text_line("A\U0001f469\u200d\U0001f4bbB", 2)
        self.assertEqual(cleaned, "A\U0001f469\u200d\U0001f4bb")

    def test_name_must_not_be_empty(self):
        with self.assertRaises(ValueError):
            sanitize_label_text("\u0000\n", None)
