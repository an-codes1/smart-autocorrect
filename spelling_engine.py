"""Dictionary and frequency-based spelling correction engine.

This module is deliberately independent of the user interface so that it can be
tested on its own. It uses ``pyspellchecker``, which is a dictionary and
word-frequency based corrector. It is NOT a trained neural model.

What it can do
--------------
* Find likely misspelled English words and suggest alternatives.
* Preserve the original whitespace, line breaks, punctuation and capitalization
  as far as possible by working with character spans instead of blind string
  replacement.
* Protect URLs, e-mail addresses, numbers and acronyms from replacement.
* Accept a custom dictionary of names and technical terms.

What it cannot do
-----------------
* It cannot detect correctly spelled but contextually wrong words such as
  "their" vs "there", or "form" vs "from". Only a context-aware (neural) model
  can attempt that.

Bounds (performance safety)
---------------------------
* Words longer than ``MAX_WORD_LEN`` characters, and long runs of a single
  repeated character, are left unchanged to avoid pathological edit-distance
  work.
* Candidate results are memoized per engine instance (each app correction uses
  a fresh instance), so pathological text with many repeated typos costs a
  single lookup each.
* At most ``MAX_SUGGESTION_WORDS`` distinct words are examined per request.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from spellchecker import SpellChecker

DEFAULT_CUSTOM_WORDS: List[str] = [
    "Python",
    "Streamlit",
]

# Words longer than this are left unchanged (skip expensive edit-distance work).
MAX_WORD_LEN = 40
# Per-request cap on the number of suggestion entries produced. Repeated
# identical typos are corrected from cache, so this protects the interface
# from a deluge of suggestion widgets on pathological input. Tokens beyond
# this are left unchanged but preserved verbatim.
MAX_SUGGESTION_WORDS = 500

# Patterns that must never be treated as ordinary words.
URL_PATTERN = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)
EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# A "word" is a run of letters, optionally containing internal apostrophes or
# hyphens (e.g. "don't", "well-known"). This keeps spans meaningful.
WORD_PATTERN = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
NUMBER_PATTERN = re.compile(r"\d")


@dataclass
class WordSuggestion:
    """A single misspelled token and the alternatives found for it."""

    word: str
    start: int
    end: int
    candidates: List[str] = field(default_factory=list)
    chosen: Optional[str] = None

    @property
    def best(self) -> Optional[str]:
        """Return the chosen correction, or the first candidate, or None."""
        if self.chosen is not None:
            return self.chosen
        if self.candidates:
            return self.candidates[0]
        return None


@dataclass
class CorrectionResult:
    """Result of correcting a piece of text."""

    original: str
    corrected: str
    suggestions: List[WordSuggestion]

    @property
    def changed(self) -> bool:
        return self.original != self.corrected


def _is_acronym(word: str) -> bool:
    """Return True if a token looks like an acronym such as 'NASA' or 'OK'."""
    letters = [c for c in word if c.isalpha()]
    return len(letters) > 1 and all(c.isupper() for c in letters)


def _match_case(source: str, replacement: str) -> str:
    """Apply the capitalization style of ``source`` to ``replacement``."""
    if not replacement:
        return replacement
    if source.isupper():
        return replacement.upper()
    if source.islower():
        return replacement.lower()
    if source[:1].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement


def _protected_spans(text: str) -> List[Tuple[int, int]]:
    """Return character spans that must be protected from replacement."""
    spans: List[Tuple[int, int]] = []
    for pattern in (URL_PATTERN, EMAIL_PATTERN):
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))
    return spans


def _overlaps(start: int, end: int, spans: List[Tuple[int, int]]) -> bool:
    return any(start < s_end and end > s_start for s_start, s_end in spans)


def _is_repeated_run(word: str) -> bool:
    """True for long single-character runs like 'aaaaaaaaaaa'."""
    letters = [c for c in word if c.isalpha()]
    return len(letters) > 8 and len(set(c.lower() for c in letters)) == 1


class SpellingEngine:
    """Dictionary and frequency-based spelling corrector."""

    def __init__(self, custom_words: Optional[List[str]] = None) -> None:
        self._spell = SpellChecker()
        self._custom_words: List[str] = list(DEFAULT_CUSTOM_WORDS)
        self._candidate_cache: Dict[str, List[str]] = {}
        if custom_words:
            for word in custom_words:
                self.add_custom_word(word)

    # ------------------------------------------------------------------
    # Custom dictionary
    # ------------------------------------------------------------------
    def add_custom_word(self, word: str) -> None:
        """Add a word (name or technical term) that must not be corrected."""
        word = word.strip()
        if not word:
            return
        if word not in self._custom_words:
            self._custom_words.append(word)
        # Teach pyspellchecker that this word (and its lowercase form) is valid.
        self._spell.word_frequency.load_words([word, word.lower()])

    def set_custom_words(self, words: List[str]) -> None:
        for word in words:
            self.add_custom_word(word)

    @property
    def custom_words(self) -> List[str]:
        return list(self._custom_words)

    # ------------------------------------------------------------------
    # Candidate lookup
    # ------------------------------------------------------------------
    def _candidates(self, word: str, limit: int = 5) -> List[str]:
        """Return spelling candidates for a single word, best first."""
        lower = word.lower()

        if lower in self._candidate_cache:
            return list(self._candidate_cache[lower])

        result: List[str] = []

        # Never correct a word we were explicitly told about.
        if lower in {w.lower() for w in self._custom_words}:
            result = []
        elif _is_acronym(word):
            result = []
        elif _is_repeated_run(word):
            # Long repetitive runs have no meaningful neighbours; skip.
            result = []
        elif len(lower) > MAX_WORD_LEN:
            # Skip expensive edit-distance work on absurdly long tokens.
            result = []
        elif lower in self._spell:
            # pyspellchecker already knows this word: it is correct.
            result = []
        else:
            # ``candidates`` is an unordered set; ``unknown`` gives frequency
            # order via ``correction``. We combine both to build a ranking.
            corrections: List[str] = []
            best = self._spell.correction(lower)
            if best:
                corrections.append(best)
            for candidate in sorted(self._spell.candidates(lower) or []):
                if candidate not in corrections:
                    corrections.append(candidate)
            result = corrections[:limit]

        self._candidate_cache[lower] = list(result)
        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def suggest(self, text: str, limit: int = 5) -> List[WordSuggestion]:
        """Return suggestions for every misspelled word in ``text``."""
        if not text:
            return []

        protected = _protected_spans(text)
        suggestions: List[WordSuggestion] = []

        for match in WORD_PATTERN.finditer(text):
            start, end = match.start(), match.end()
            word = match.group()

            if _overlaps(start, end, protected):
                continue
            if NUMBER_PATTERN.search(word):
                continue

            candidates = self._candidates(word, limit=limit)
            if not candidates:
                # No candidate (or custom/acronym/long): leave unchanged.
                continue

            suggestions.append(
                WordSuggestion(
                    word=word,
                    start=start,
                    end=end,
                    candidates=[_match_case(word, c) for c in candidates],
                )
            )
            if len(suggestions) >= MAX_SUGGESTION_WORDS:
                # Bound the amount of work (and the number of suggestion
                # widgets the interface would otherwise render).
                break

        return suggestions

    def correct(
        self,
        text: str,
        limit: int = 5,
        choices: Optional[Dict[int, str]] = None,
    ) -> CorrectionResult:
        """Correct ``text`` and return the corrected string plus suggestions.

        ``choices`` maps the character start index of a word to the exact
        replacement the user wants. Words missing from ``choices`` use the
        best candidate. Words with no candidate are left unchanged.
        """
        suggestions = self.suggest(text, limit=limit)
        if not suggestions:
            return CorrectionResult(text, text, [])

        choices = choices or {}
        pieces: List[str] = []
        cursor = 0

        for suggestion in suggestions:
            replacement = choices.get(suggestion.start, suggestion.best)
            if replacement is None:
                # No candidate: keep the original word.
                replacement = suggestion.word
            else:
                replacement = _match_case(suggestion.word, replacement)
                suggestion.chosen = replacement

            pieces.append(text[cursor:suggestion.start])
            pieces.append(replacement)
            cursor = suggestion.end

        pieces.append(text[cursor:])
        return CorrectionResult(text, "".join(pieces), suggestions)