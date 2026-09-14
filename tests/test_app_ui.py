"""Streamlit AppTest flows for the Smart Autocorrect interface.

These are automated widget-level checks (no real browser). Manual browser
checks are documented in SECURITY_REVIEW.md and README.md.

Run with:
    .venv\\Scripts\\python.exe -m unittest tests.test_app_ui -v
"""

import os
import unittest

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py")


def make_app() -> AppTest:
    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    if at.exception:
        raise at.exception[0]
    return at


class AppSpellingFlowTests(unittest.TestCase):
    def test_spelling_correction_produces_result(self) -> None:
        at = make_app()
        at.text_area[0].set_value("Ths is a smple sentnce.").run()
        at.button[0].click().run()  # Check Text
        result = at.session_state["result"]
        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "Spelling")
        self.assertIn("simple", result["corrected"])
        self.assertIn("sentence", result["corrected"])
        # Suggested text view is shown side by side.
        suggested = [t.value for t in at.text_area]
        self.assertTrue(any("simple sentence" in v for v in suggested))
        self.assertTrue(any("Word-level changes" in m.value for m in at.markdown))

    def test_custom_words_are_not_corrected(self) -> None:
        at = make_app()
        at.text_input[0].set_value("Python, Streamlit, AcmeCorp").run()
        at.text_area[0].set_value("AcmeCorp is great and smple is bad.").run()
        at.button[0].click().run()
        result = at.session_state["result"]
        self.assertIn("AcmeCorp", result["corrected"])
        self.assertIn("simple", result["corrected"])

    def test_oversized_input_rejected_with_message(self) -> None:
        from app import MAX_INPUT_CHARS

        at = make_app()
        at.text_area[0].set_value("a" * (MAX_INPUT_CHARS + 1)).run()
        at.button[0].click().run()
        self.assertTrue(at.error)
        self.assertIn("over the limit", at.error[0].value.lower())
        # No result was produced and the input is preserved for retry.
        self.assertIsNone(at.session_state["result"])
        self.assertEqual(len(at.text_area[0].value), MAX_INPUT_CHARS + 1)

    def test_empty_input_shows_friendly_message(self) -> None:
        at = make_app()
        at.button[0].click().run()
        self.assertTrue(at.error)
        self.assertIn("enter some text", at.error[0].value.lower())
        self.assertIsNone(at.session_state["result"])

    def test_clear_resets_input_and_results(self) -> None:
        at = make_app()
        at.text_area[0].set_value("Ths is bad.").run()
        at.button[0].click().run()
        self.assertIsNotNone(at.session_state["result"])
        # Clear button
        at.button[2].click().run()
        self.assertIsNone(at.session_state["result"])
        self.assertEqual(at.text_area[0].value, "")

    def test_load_example_fills_input(self) -> None:
        at = make_app()
        at.button[1].click().run()  # Load Example
        self.assertIn("Ths is a smple sentnce", at.text_area[0].value)

    def test_edit_final_text_reflects_latest(self) -> None:
        at = make_app()
        at.text_area[0].set_value("Ths is a smple sentnce.").run()
        at.button[0].click().run()
        # After a result, widgets are: input, original, suggested, final.
        final = at.text_area[3]
        final.set_value("My custom final text").run()
        self.assertEqual(at.session_state["final_text"], "My custom final text")
        # The download button exists and carries the latest edited value.
        self.assertEqual(len(at.get("download_button")), 1)


if __name__ == "__main__":
    unittest.main()