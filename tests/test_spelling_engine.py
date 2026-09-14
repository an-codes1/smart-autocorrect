"""Tests for the dictionary and frequency-based spelling engine."""

import unittest

from spelling_engine import SpellingEngine


class SpellingEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = SpellingEngine()

    # 1. Empty input -----------------------------------------------------
    def test_empty_input(self) -> None:
        result = self.engine.correct("")
        self.assertEqual(result.corrected, "")
        self.assertEqual(result.suggestions, [])
        self.assertFalse(result.changed)

    def test_whitespace_only(self) -> None:
        result = self.engine.correct("   \n  ")
        self.assertEqual(result.corrected, "   \n  ")

    # 2. Known spelling mistakes ----------------------------------------
    def test_known_mistake_is_suggested(self) -> None:
        result = self.engine.correct("Ths is a smple sentnce.")
        self.assertTrue(result.suggestions)
        misspelled = {s.word.lower() for s in result.suggestions}
        self.assertIn("ths", misspelled)
        self.assertIn("smple", misspelled)
        self.assertIn("sentnce", misspelled)

    def test_suggestion_has_candidates(self) -> None:
        suggestions = self.engine.suggest("Ths")
        self.assertEqual(len(suggestions), 1)
        self.assertTrue(suggestions[0].candidates)

    # 3. Already-correct text -------------------------------------------
    def test_correct_text_unchanged(self) -> None:
        text = "Python is useful for machine learning."
        result = self.engine.correct(text)
        self.assertEqual(result.corrected, text)
        self.assertFalse(result.changed)

    # 4. Whitespace and punctuation preservation ------------------------
    def test_whitespace_and_punctuation_preserved(self) -> None:
        text = "Ths  is\na smple sentnce."
        result = self.engine.correct(text)
        self.assertEqual(result.corrected.count("\n"), 1)
        self.assertIn("  is", result.corrected)
        self.assertTrue(result.corrected.endswith("."))

    def test_newlines_preserved_after_correction(self) -> None:
        text = "Ths is line one.\nSmple line two."
        result = self.engine.correct(text)
        self.assertEqual(result.corrected.count("\n"), 1)
        self.assertEqual(result.corrected.count("."), 2)

    # 5. Protected tokens ------------------------------------------------
    def test_url_protected(self) -> None:
        text = "Visit https://python.org for more."
        result = self.engine.correct(text)
        self.assertIn("https://python.org", result.corrected)

    def test_email_protected(self) -> None:
        text = "Write to student@example.com today."
        result = self.engine.correct(text)
        self.assertIn("student@example.com", result.corrected)

    def test_number_protected(self) -> None:
        text = "The year 2026 is here."
        result = self.engine.correct(text)
        self.assertIn("2026", result.corrected)

    def test_acronym_protected(self) -> None:
        text = "NASA and NATO are organizations."
        result = self.engine.correct(text)
        self.assertIn("NASA", result.corrected)
        self.assertIn("NATO", result.corrected)

    def test_custom_words_protected(self) -> None:
        engine = SpellingEngine(["Streamlit", "Python", "MyName"])
        text = "Streamlit, Python and MyName are tools."
        result = engine.correct(text)
        self.assertIn("Streamlit", result.corrected)
        self.assertIn("Python", result.corrected)
        self.assertIn("MyName", result.corrected)

    def test_default_custom_words_are_python_and_streamlit(self) -> None:
        from spelling_engine import DEFAULT_CUSTOM_WORDS

        self.assertEqual(DEFAULT_CUSTOM_WORDS, ["Python", "Streamlit"])

    # 6. Case-preserving replacements -----------------------------------
    def test_lowercase_preserved(self) -> None:
        suggestions = self.engine.suggest("ths")
        self.assertTrue(suggestions)
        self.assertTrue(suggestions[0].candidates[0].islower())

    def test_all_caps_word_protected_as_acronym(self) -> None:
        # All-caps tokens are treated as acronyms and never changed by design.
        self.assertEqual(self.engine.suggest("THS"), [])

    def test_capitalized_word_preserved(self) -> None:
        suggestions = self.engine.suggest("Ths")
        self.assertTrue(suggestions)
        self.assertTrue(suggestions[0].candidates[0][0].isupper())

    def test_correction_does_not_drop_punctuation(self) -> None:
        text = "Ths, smple: sentnce!"
        result = self.engine.correct(text)
        for mark in [",", ":", "!"]:
            self.assertIn(mark, result.corrected)


if __name__ == "__main__":
    unittest.main()
