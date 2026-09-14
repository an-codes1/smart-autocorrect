"""Basic tests for the AI grammar engine (model-independent logic only)."""

import unittest

from grammar_engine import (
    GrammarEngine,
    InputTooLongError,
    MAX_INPUT_TOKENS,
    PROMPT_PREFIX,
)


class GrammarEngineUnitTests(unittest.TestCase):
    """Tests that do not require the actual model to be loaded."""

    def test_empty_input_returns_original(self) -> None:
        engine = GrammarEngine()
        result = engine.correct("")
        self.assertEqual(result.corrected, "")
        self.assertEqual(result.original, "")

    def test_whitespace_input_returns_original(self) -> None:
        engine = GrammarEngine()
        result = engine.correct("   \n  ")
        self.assertEqual(result.corrected, "   \n  ")

    def test_prompt_prefix(self) -> None:
        self.assertEqual(PROMPT_PREFIX, "grammar: ")

    def test_max_input_tokens_is_positive(self) -> None:
        self.assertGreater(MAX_INPUT_TOKENS, 0)

    def test_model_load_error_is_none_before_loading(self) -> None:
        engine = GrammarEngine()
        self.assertIsNone(engine.load_error)
        self.assertFalse(engine.is_loaded)


if __name__ == "__main__":
    unittest.main()
