"""Regression tests for the security, stability and performance fixes.

These tests exercise the pure logic; the Streamlit-widget level flows live in
``test_app_ui.py`` (using Streamlit AppTest).
"""

import time
import unittest

import html as html_module

from grammar_engine import (
    MODEL_NAME,
    MODEL_REVISION,
    MAX_INPUT_CHARS as ENGINE_MAX_INPUT_CHARS,
    GrammarEngine,
    GrammarModelError,
    InferenceGuard,
    InputTooLongError,
)
from spelling_engine import MAX_SUGGESTION_WORDS, MAX_WORD_LEN, SpellingEngine

from app import (
    MAX_CUSTOM_DICT_CHARS,
    MAX_CUSTOM_WORDS,
    MAX_CUSTOM_WORD_LEN,
    MAX_INPUT_CHARS,
    mode_input_limit,
    parse_custom_words,
    validate_custom_dict_raw,
    validate_custom_words,
    validate_input,
    word_diff_html,
)


class InputLimitTests(unittest.TestCase):
    def test_empty_input_rejected(self) -> None:
        self.assertIn("enter some text", validate_input("   ").lower())

    def test_oversized_input_rejected(self) -> None:
        big = "a" * (MAX_INPUT_CHARS + 1)
        msg = validate_input(big)
        self.assertIsNotNone(msg)
        self.assertIn("over the limit", msg)

    def test_valid_input_accepted(self) -> None:
        self.assertIsNone(validate_input("Ths is a smple sentnce."))

    def test_mode_specific_limits_consistent_before_submission(self) -> None:
        # Spelling uses the app-wide 10,000 bound; AI Grammar uses the engine's
        # stricter 8,000 bound. A text between the two is accepted for Spelling
        # but rejected with the correct message for AI Grammar.
        self.assertEqual(mode_input_limit("Spelling"), MAX_INPUT_CHARS)
        self.assertEqual(mode_input_limit("AI Grammar"), ENGINE_MAX_INPUT_CHARS)
        between = MAX_INPUT_CHARS - 500  # 9,500 characters
        self.assertIsNone(validate_input("a" * between))
        msg = validate_input("a" * between, max_chars=mode_input_limit("AI Grammar"))
        self.assertIsNotNone(msg)
        self.assertIn(str(ENGINE_MAX_INPUT_CHARS), msg)

    def test_engine_rejects_oversized_without_loading_model(self) -> None:
        engine = GrammarEngine()
        big = "x" * (ENGINE_MAX_INPUT_CHARS + 10)
        with self.assertRaises(InputTooLongError):
            engine.correct(big)
        # The character bound must be enforced before any model load.
        self.assertFalse(engine.is_loaded)

    def test_custom_dict_limit_errors(self) -> None:
        too_many = [f"word{i}" for i in range(MAX_CUSTOM_WORDS + 1)]
        msg = validate_custom_words(too_many)
        self.assertIsNotNone(msg)
        self.assertIn("over the limit", msg)
        too_long = ["a" * (MAX_CUSTOM_WORD_LEN + 1)]
        msg = validate_custom_words(too_long)
        self.assertIn("over 40 characters", msg)

    def test_custom_dict_raw_length_rejected_not_truncated(self) -> None:
        raw = "x" * (MAX_CUSTOM_DICT_CHARS + 100)
        msg = validate_custom_dict_raw(raw)
        self.assertIsNotNone(msg)
        self.assertIn("over the limit", msg)
        # parse must not silently truncate: the long token is returned whole.
        words = parse_custom_words(raw)
        self.assertEqual(words, [raw])

    def test_custom_dict_limits_are_sane(self) -> None:
        self.assertGreater(MAX_CUSTOM_DICT_CHARS, 0)
        self.assertGreater(MAX_CUSTOM_WORDS, 0)
        self.assertGreater(MAX_CUSTOM_WORD_LEN, 0)


class HTMLSafetyTests(unittest.TestCase):
    def test_script_tag_is_escaped_in_diff(self) -> None:
        output = word_diff_html(
            "<script>alert(1)</script>", "<script>alert(2)</script>"
        )
        self.assertNotIn("<script>", output)
        self.assertIn("&lt;script&gt;", output)
        self.assertIn("&lt;/script&gt;", output)

    def test_attribute_injection_is_escaped_in_diff(self) -> None:
        evil = '<a href="x" onmouseover="y">'
        output = word_diff_html(evil, "safe text")
        # Forbidden: the raw attacker token appearing verbatim. Quotes and
        # angle brackets must be escaped even though letters remain.
        self.assertNotIn('<a href="x" onmouseover="y">', output)
        self.assertIn("&lt;a", output)
        self.assertIn('onmouseover=&quot;y&quot;', output)

    def test_escape_matches_stdlib_html_escape(self) -> None:
        # A single whitespace-free token, so the whole string stays one token.
        evil = '<script>alert(1)</script>'
        self.assertIn(html_module.escape(evil), word_diff_html(evil, evil))


class SpellingBoundsTests(unittest.TestCase):
    def test_long_word_left_unchanged(self) -> None:
        engine = SpellingEngine()
        word = "a" * (MAX_WORD_LEN + 1)
        self.assertNotIn("a" * (MAX_WORD_LEN + 1), [s.word for s in engine.suggest(word)])

    def test_long_word_never_crashes_in_full_text(self) -> None:
        engine = SpellingEngine()
        result = engine.correct("Ths is fine " + "a" * 100 + ".")
        self.assertIn("a" * 100, result.corrected)

    def test_repeated_character_run_left_unchanged(self) -> None:
        engine = SpellingEngine()
        self.assertEqual(engine.suggest("a" * 20), [])

    def test_pathological_input_completes_quickly(self) -> None:
        engine = SpellingEngine()
        pathological = ("Ths " + "zzzzqq " * 400 + "a" * 60 + " " * 20)
        started = time.monotonic()
        result = engine.correct(pathological)
        elapsed = time.monotonic() - started
        self.assertIsInstance(result.corrected, str)
        self.assertLess(elapsed, 10.0, f"spelling took too long: {elapsed:.2f}s")

    def test_suggestion_word_cap_is_bounded(self) -> None:
        self.assertGreater(MAX_SUGGESTION_WORDS, 0)


class SessionIsolationTests(unittest.TestCase):
    def test_custom_words_do_not_leak_between_engines(self) -> None:
        first = SpellingEngine(["Garbagge"])
        # "Garbagge" is protected (treated as correct) in the session that
        # declared it...
        self.assertEqual(first.suggest("Garbagge"), [])
        self.assertIn("garbagge", {w.lower() for w in first.custom_words})

        # ...but a fresh engine must NOT know it: it gets flagged and
        # corrected to "Garbage" (no cross-session dictionary sharing).
        second = SpellingEngine()
        flagged = second.suggest("Garbagge")
        self.assertEqual([s.word for s in flagged], ["Garbagge"])
        self.assertIn("Garbage", flagged[0].candidates)

    def test_default_words_do_not_leak_user_additions(self) -> None:
        first = SpellingEngine(["SessionAlpha"])
        second = SpellingEngine(["SessionBeta"])
        self.assertNotEqual(
            {w.lower() for w in first.custom_words},
            {w.lower() for w in second.custom_words},
        )


class GrammarEngineUnitTestsExtra(unittest.TestCase):
    def test_empty_input_returns_original(self) -> None:
        engine = GrammarEngine()
        result = engine.correct("")
        self.assertEqual(result.corrected, "")
        self.assertEqual(result.original, "")

    def test_whitespace_input_returns_original(self) -> None:
        engine = GrammarEngine()
        result = engine.correct("   \n  ")
        self.assertEqual(result.corrected, "   \n  ")

    def test_load_uses_pinned_revision_and_disables_remote_code(self) -> None:
        import unittest.mock as mock

        engine = GrammarEngine()
        fake_tokenizer = mock.MagicMock()
        fake_model = mock.MagicMock()

        with mock.patch(
            "transformers.AutoTokenizer.from_pretrained",
            return_value=fake_tokenizer,
        ) as tk, mock.patch(
            "transformers.AutoModelForSeq2SeqLM.from_pretrained",
            return_value=fake_model,
        ) as mod:
            engine.load()

        tk.assert_called_once_with(
            MODEL_NAME, revision=MODEL_REVISION, trust_remote_code=False
        )
        mod.assert_called_once_with(
            MODEL_NAME, revision=MODEL_REVISION, trust_remote_code=False
        )
        fake_model.eval.assert_called_once()

    def test_pinned_revision_matches_official_repo(self) -> None:
        self.assertEqual(
            MODEL_REVISION, "9e4a09d21dca1072a69302df9261289d03c3ed78"
        )


class InferenceGuardTests(unittest.TestCase):
    def test_release_after_success(self) -> None:
        guard = InferenceGuard()
        with guard:
            pass
        guard.acquire()
        guard.release()

    def test_release_after_failure(self) -> None:
        guard = InferenceGuard()
        with self.assertRaises(RuntimeError):
            with guard:
                raise RuntimeError("boom")
        # The guard must be free again after the failure.
        guard.acquire()
        guard.release()

    def test_timeout_when_busy(self) -> None:
        guard = InferenceGuard(wait_seconds=0.2)
        guard.acquire()
        started = time.monotonic()
        with self.assertRaises(GrammarModelError):
            guard.acquire()
        self.assertGreater(time.monotonic() - started, 0.15)
        guard.release()
        guard.acquire()
        guard.release()

    def test_busy_flag(self) -> None:
        guard = InferenceGuard()
        self.assertFalse(guard._slot._value == 0)  # free initially
        guard.acquire()
        self.assertTrue(guard._slot._value == 0)   # now busy

    def test_default_wait_is_short_bounded(self) -> None:
        # The 90 s wait was replaced with a short bounded wait so the interface
        # shows a busy/retry message instead of appearing stuck.
        self.assertLessEqual(InferenceGuard().wait_seconds, 10.0)


if __name__ == "__main__":
    unittest.main()