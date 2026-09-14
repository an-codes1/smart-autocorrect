"""Smart Autocorrect - a beginner-friendly Streamlit autocorrect app.

Two modes:
* Spelling      - dictionary and frequency-based correction (pyspellchecker).
* AI Grammar    - local inference with a pretrained T5 grammar model.

Run with:
    .venv\\Scripts\\python.exe -m streamlit run app.py
"""

from __future__ import annotations

import difflib
import html
import re
from typing import Dict, List, Optional

import streamlit as st

from grammar_engine import (
    MAX_INPUT_CHARS as ENGINE_MAX_INPUT_CHARS,
    MAX_INPUT_TOKENS,
    GrammarEngine,
    GrammarModelError,
    InputTooLongError,
)
from spelling_engine import DEFAULT_CUSTOM_WORDS, SpellingEngine, WordSuggestion

# ----------------------------------------------------------------------
# Server-side limits (reject oversized input before expensive processing;
# the text is never silently truncated).
# ----------------------------------------------------------------------
MAX_INPUT_CHARS = 10_000
MAX_CUSTOM_DICT_CHARS = 2_000
MAX_CUSTOM_WORDS = 100
MAX_CUSTOM_WORD_LEN = 40
DOWNLOAD_FILE_NAME = "smart_autocorrect_final.txt"

EXAMPLE_TEXT = (
    "Ths is a smple sentnce.\n"
    "She go to college every day.\n"
    "Visit https://python.org or email me at student@example.com.\n"
    "Python is useful for machine learning."
)

SPELLING_EXPLANATION = (
    "**Spelling mode** uses a dictionary and word-frequency method "
    "(pyspellchecker). It suggests corrections for individual misspelled "
    "words and preserves your spacing, punctuation and capitalization. It "
    "cannot detect correctly spelled but contextually wrong words such as "
    "'their' vs 'there'."
)

AI_EXPLANATION = (
    "**AI Grammar mode** runs the pretrained model "
    "`vennify/t5-base-grammar-correction` on the server that hosts this app "
    "(your computer when you run it locally; the hosting provider's server "
    "when you access the public demo). No text is sent to a paid external API. "
    "The processing happens in this app's server process - not inside the "
    "website visitor's browser. The output is only a suggestion and may change "
    "meaning or add mistakes."
)

st.set_page_config(page_title="Smart Autocorrect", page_icon="✍️", layout="wide")


# ----------------------------------------------------------------------
# Cached resources
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_grammar_engine() -> GrammarEngine:
    """Load the grammar engine once and reuse it across Streamlit reruns."""
    return GrammarEngine()


# ----------------------------------------------------------------------
# Session state helpers
# ----------------------------------------------------------------------
def init_state() -> None:
    if "reset_counter" not in st.session_state:
        st.session_state.reset_counter = 0
    if "result" not in st.session_state:
        st.session_state.result = None
    if "final_text" not in st.session_state:
        st.session_state.final_text = ""
    if "result_id" not in st.session_state:
        st.session_state.result_id = 0


def keys() -> Dict[str, str]:
    counter = st.session_state.reset_counter
    return {
        "input": f"input_text_{counter}",
        "mode": f"mode_{counter}",
        "custom": f"custom_dict_{counter}",
        "final": f"final_text_{counter}",
    }


def on_load_example() -> None:
    st.session_state[keys()["input"]] = EXAMPLE_TEXT


def on_clear() -> None:
    # Changing the key suffix gives us brand new, empty widgets on the next
    # run without ever trying to modify a widget that already exists. This
    # also clears the session's displayed input, custom words and results.
    st.session_state.reset_counter += 1
    st.session_state.result = None
    st.session_state.final_text = ""


# ----------------------------------------------------------------------
# Validation (pure functions, unit-testable)
# ----------------------------------------------------------------------
def validate_input(
    text: str, max_chars: int = MAX_INPUT_CHARS
) -> Optional[str]:
    """Return a user-facing error string, or None if the text is acceptable.

    ``max_chars`` defaults to the app-wide spelling bound; AI Grammar mode
    passes the grammar engine's stricter character bound so the message shown
    before submission matches the limit enforced by the engine.
    """
    if not text.strip():
        return "Please enter some text before checking it."
    if len(text) > max_chars:
        return (
            f"This text is {len(text)} characters, which is over the limit of "
            f"{max_chars} for this mode. Please shorten it before checking. "
            "Nothing was truncated - your text is unchanged."
        )
    return None


def mode_input_limit(mode: str) -> int:
    """Return the character limit that applies to the selected mode."""
    if mode == "AI Grammar":
        return ENGINE_MAX_INPUT_CHARS
    return MAX_INPUT_CHARS


def validate_custom_words(words: List[str]) -> Optional[str]:
    """Return a user-facing error string, or None if the dictionary is OK."""
    if len(words) > MAX_CUSTOM_WORDS:
        return (
            f"The custom dictionary has {len(words)} words, which is over the "
            f"limit of {MAX_CUSTOM_WORDS}. Please remove some entries."
        )
    too_long = [w for w in words if len(w) > MAX_CUSTOM_WORD_LEN]
    if too_long:
        return (
            f"These custom words are over {MAX_CUSTOM_WORD_LEN} characters "
            f"each: {', '.join(too_long[:5])}. Please shorten or remove them."
        )
    return None


def validate_custom_dict_raw(raw: str) -> Optional[str]:
    """Reject an oversized custom-dictionary input instead of truncating it."""
    if len(raw) > MAX_CUSTOM_DICT_CHARS:
        return (
            f"The custom dictionary input is {len(raw)} characters, which is "
            f"over the limit of {MAX_CUSTOM_DICT_CHARS}. Please shorten it. "
            "Nothing was truncated."
        )
    return None


def parse_custom_words(raw: str) -> List[str]:
    """Split and sanitize the custom-dictionary text input (no truncation)."""
    if not raw:
        return []
    parts = re.split(r"[,\n;]+", raw)
    return [p.strip() for p in parts if p.strip()]


# ----------------------------------------------------------------------
# Correction helpers
# ----------------------------------------------------------------------
def run_spelling(text: str, custom_words: List[str]):
    engine = SpellingEngine(custom_words)
    return engine.correct(text)


def apply_choices(result, choices: Dict[str, str]) -> str:
    """Rebuild the corrected text using the user's selected alternatives.

    ``choices`` maps the lowercase misspelled word to the chosen replacement;
    the choice applies to every occurrence of that word.
    """
    suggestions = result["suggestions"]
    original = result["original"]
    pieces: List[str] = []
    cursor = 0
    for suggestion in suggestions:
        replacement = choices.get(suggestion.word.lower(), suggestion.best)
        if replacement is None:
            replacement = suggestion.word
        pieces.append(original[cursor:suggestion.start])
        pieces.append(replacement)
        cursor = suggestion.end
    pieces.append(original[cursor:])
    return "".join(pieces)


def word_diff_html(old: str, new: str) -> str:
    """Return a safe, word-level diff highlighted with escaped HTML.

    Every user-controlled token is HTML-escaped before being placed in the
    highlighted view, so submitted text can never inject markup or scripts.
    """
    old_tokens = re.findall(r"\s+|\S+", old)
    new_tokens = re.findall(r"\s+|\S+", new)
    matcher = difflib.SequenceMatcher(a=old_tokens, b=new_tokens)

    parts: List[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_text = html.escape("".join(old_tokens[i1:i2]))
        new_text = html.escape("".join(new_tokens[j1:j2]))
        if tag == "equal":
            parts.append(old_text)
        elif tag == "delete":
            parts.append(f'<span style="background:#ffd6d6;">{old_text}</span>')
        elif tag == "insert":
            parts.append(f'<span style="background:#d6f5d6;">{new_text}</span>')
        elif tag == "replace":
            parts.append(f'<span style="background:#ffd6d6;">{old_text}</span>')
            parts.append(f'<span style="background:#d6f5d6;">{new_text}</span>')

    body = "".join(parts)
    return (
        '<div style="white-space:pre-wrap;font-family:monospace;'
        'border:1px solid #d0d0d0;border-radius:6px;padding:10px;">'
        f"{body}</div>"
    )


def render_diff(old: str, new: str) -> None:
    st.markdown("**Word-level changes** (red = removed, green = added)")
    st.markdown(word_diff_html(old, new), unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Main app
# ----------------------------------------------------------------------
init_state()
k = keys()

st.title("Smart Autocorrect")
st.write(
    "Paste or type English text, then choose a mode and click **Check Text**. "
    "Spelling mode fixes individual misspelled words. AI Grammar mode uses a "
    "pretrained model to suggest a more fluent sentence."
)

mode = st.radio(
    "Mode",
    options=["Spelling", "AI Grammar"],
    key=k["mode"],
    horizontal=True,
)

with st.expander("How the two modes differ", expanded=False):
    st.markdown(SPELLING_EXPLANATION)
    st.markdown(AI_EXPLANATION)

input_text = st.text_area(
    "Your text",
    key=k["input"],
    height=180,
    placeholder="Type or paste English text here...",
)
st.caption(
    f"Limit for this mode: {mode_input_limit(mode):,} characters."
    + (
        f" AI Grammar also enforces ~{MAX_INPUT_TOKENS} tokens, which is "
        "checked after the model is loaded."
        if mode == "AI Grammar"
        else ""
    )
)

custom_raw = ""
if mode == "Spelling":
    custom_raw = st.text_input(
        "Custom dictionary (names and technical terms)",
        key=k["custom"],
        value=", ".join(DEFAULT_CUSTOM_WORDS),
        help=(
            "Comma-separated names or technical terms that must never be "
            f"changed. Limits: {MAX_CUSTOM_WORDS} words, "
            f"{MAX_CUSTOM_WORD_LEN} characters each."
        ),
    )

button_cols = st.columns([1, 1, 1, 3])
with button_cols[0]:
    check_clicked = st.button("Check Text", type="primary", use_container_width=True)
with button_cols[1]:
    st.button(
        "Load Example",
        on_click=on_load_example,
        use_container_width=True,
    )
with button_cols[2]:
    st.button(
        "Clear",
        on_click=on_clear,
        use_container_width=True,
    )

# ----------------------------------------------------------------------
# Run correction on explicit button click only. Input is never cleared here:
# if validation or the AI model fails, the user keeps their text and can retry.
# ----------------------------------------------------------------------
if check_clicked:
    st.session_state.result = None
    st.session_state.result_id += 1

    input_error = validate_input(input_text, max_chars=mode_input_limit(mode))
    if input_error:
        st.error(input_error)
    elif mode == "Spelling":
        custom_words = parse_custom_words(custom_raw)
        custom_error = (
            validate_custom_dict_raw(custom_raw) or validate_custom_words(custom_words)
        )
        if custom_error:
            st.error(custom_error)
        else:
            with st.spinner("Checking spelling..."):
                spelling_result = run_spelling(input_text, custom_words)
            st.session_state.result = {
                "mode": "Spelling",
                "source_text": input_text,
                "original": spelling_result.original,
                "corrected": spelling_result.corrected,
                "suggestions": spelling_result.suggestions,
            }
            st.session_state[k["final"]] = spelling_result.corrected
    else:
        engine = get_grammar_engine()
        try:
            with st.spinner(
                "Loading and running the AI model. The first run may download "
                "files and take several minutes..."
            ):
                grammar_result = engine.correct(input_text)
            st.session_state.result = {
                "mode": "AI Grammar",
                "source_text": input_text,
                "original": grammar_result.original,
                "corrected": grammar_result.corrected,
                "suggestions": [],
                "token_count": grammar_result.token_count,
            }
            st.session_state[k["final"]] = grammar_result.corrected
        except InputTooLongError as exc:
            st.error(str(exc))
        except GrammarModelError as exc:
            st.error(str(exc))
            st.info("Spelling mode still works and does not need the AI model.")

# ----------------------------------------------------------------------
# Results
# ----------------------------------------------------------------------
result = st.session_state.result
if result:
    stale = (
        result["mode"] != mode or result["source_text"] != input_text
    )
    if stale:
        st.warning(
            "The text or mode changed since these results were created. "
            "Click **Check Text** to refresh them."
        )

    if result["mode"] == "AI Grammar":
        st.caption(
            "AI output is a suggestion to review. The model can change meaning "
            "or introduce mistakes. "
            f"Input limit: {ENGINE_MAX_INPUT_CHARS:,} characters / "
            f"{MAX_INPUT_TOKENS} tokens."
        )
    else:
        st.caption(
            "Spelling corrections are dictionary and frequency based, not a "
            "trained neural model."
        )

    rid = st.session_state.result_id
    left, right = st.columns(2)
    with left:
        st.text_area(
            "Original text",
            value=result["original"],
            height=180,
            disabled=True,
            key=f"original_view_{rid}",
        )
    with right:
        st.text_area(
            "Suggested text",
            value=result["corrected"],
            height=180,
            disabled=True,
            key=f"suggested_view_{rid}",
        )

    render_diff(result["original"], result["corrected"])

    # Spelling: let the user review alternatives and keep the original word.
    # One widget is shown per distinct misspelled word (repeated typos would
    # otherwise flood the interface with hundreds of identical widgets), and
    # the chosen replacement applies to every occurrence of that word.
    if result["mode"] == "Spelling" and result["suggestions"]:
        st.markdown("#### Review alternatives")
        chosen: Dict[str, str] = {}
        seen: set = set()
        for suggestion in result["suggestions"]:
            word_key = suggestion.word.lower()
            if word_key in seen:
                continue
            seen.add(word_key)
            options = list(suggestion.candidates)
            if suggestion.word not in options:
                options.append(suggestion.word)
            label = f"'{suggestion.word}'"
            selected = st.selectbox(
                label,
                options=options,
                index=0,
                key=f"choice_{rid}_{word_key}",
            )
            chosen[word_key] = selected

        if st.button("Apply selected corrections"):
            new_corrected = apply_choices(result, chosen)
            result["corrected"] = new_corrected
            st.session_state.result = result
            st.session_state[k["final"]] = new_corrected
            st.rerun()

    # Editable final text
    st.markdown("#### Final text (edit before downloading)")
    if k["final"] not in st.session_state:
        st.session_state[k["final"]] = result["corrected"]
    final_value = st.text_area(
        "Final text",
        height=180,
        key=k["final"],
        label_visibility="collapsed",
    )
    st.session_state.final_text = final_value

    st.download_button(
        "Download final text (.txt)",
        data=st.session_state.final_text,
        file_name=DOWNLOAD_FILE_NAME,
        mime="text/plain",
    )

st.divider()
st.caption(
    "Text you submit is processed by this app's hosting server (your computer "
    "when run locally; the hosting provider's server in the public demo). "
    "Smart Autocorrect is a learning project. AI Grammar uses the public model "
    "'vennify/t5-base-grammar-correction' (CC BY-NC-SA 4.0), pinned to a "
    "verified revision, with remote code execution disabled. No accuracy claims "
    "are made and the model was not trained by the authors of this app."
)