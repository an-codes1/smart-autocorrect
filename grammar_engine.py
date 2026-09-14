"""Local neural grammar correction using a pretrained T5 model.

This module wraps the public model ``vennify/t5-base-grammar-correction`` with
``AutoTokenizer`` and ``AutoModelForSeq2SeqLM``. Inference runs entirely on this
machine (the process that runs the app); the user's text is never sent to a
paid external API.

Model card details that matter
------------------------------
* The model expects the input prefix ``"grammar: "`` (see the model card).
* The recommended generation settings are ``num_beams=5`` and ``min_length=1``.
* The base T5 architecture accepts a maximum of 512 input tokens. We use a
  smaller, visible safety limit and reject longer text instead of silently
  truncating it.
* The model is licensed CC BY-NC-SA 4.0 (non-commercial). See README.md.

Safety properties
-----------------
* The repository is pinned to a verified revision, and
  ``trust_remote_code=False`` is set explicitly, so no custom Python code from
  the Hub is ever executed.
* The repository ships ``pytorch_model.bin`` (no safetensors weights). Modern
  Transformers load it with ``weights_only=True`` by default, which mitigates
  the historical pickle deserialization risk.
* Input is bounded before any expensive work, output is bounded, and inference
  is serialized with a process-wide concurrency guard so concurrent browser
  sessions cannot run overlapping generations on this CPU-oriented app.

Important
---------
* The first successful run downloads model files from the internet (hundreds of
  megabytes) and can take several minutes. Later runs reuse the cache.
* The model output is a *suggestion*, not ground truth. It can change meaning
  or introduce new mistakes. Always review it.
* We did not train or fine-tune this model, and we make no accuracy claims.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Optional

MODEL_NAME = "vennify/t5-base-grammar-correction"
# Pinned revision verified against the public repository on 2026-09-13.
MODEL_REVISION = "9e4a09d21dca1072a69302df9261289d03c3ed78"
PROMPT_PREFIX = "grammar: "

# T5 supports up to 512 tokens. We deliberately use a smaller limit and show it
# to the user so text is never silently truncated.
MAX_INPUT_TOKENS = 400
# A cheap character bound applied *before* the model is loaded so pasting huge
# text never triggers a download or inference.
MAX_INPUT_CHARS = 8000
# Cap generated text so a malformed prompt cannot produce a very long output.
MAX_OUTPUT_TOKENS = 256

_logger = logging.getLogger("smart_autocorrect.grammar")


class GrammarModelError(RuntimeError):
    """Raised when the grammar model cannot be loaded or used."""


class InputTooLongError(ValueError):
    """Raised when the input exceeds a supported limit (chars or tokens)."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InferenceGuard:
    """Process-wide, single-slot concurrency guard for CPU inference.

    Only one generation runs at a time. A second caller waits up to
    ``wait_seconds`` (default: a short 10 s) and then receives a clear
    busy/retry message instead of appearing stuck. The wait is intentionally
    short: wall-clock inference already takes several seconds, and a long wait
    would only trap the interface in a spinner. The slot is always released,
    even when the guarded block raises.
    """

    def __init__(self, wait_seconds: float = 10.0) -> None:
        self._slot = threading.Semaphore(1)
        self.wait_seconds = wait_seconds

    def acquire(self) -> None:
        if not self._slot.acquire(timeout=self.wait_seconds):
            raise GrammarModelError(
                "The AI grammar model is busy with another correction. "
                "A single inference can take about 7-20 seconds on this "
                "CPU-only setup. Please wait a moment, then click Check Text "
                "again."
            )

    def release(self) -> None:
        self._slot.release()

    def __enter__(self) -> "InferenceGuard":
        self.acquire()
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.release()
        return False


@dataclass
class GrammarResult:
    """Result of a grammar correction request."""

    original: str
    corrected: str
    token_count: int


class GrammarEngine:
    """Lazily loads and runs the pretrained grammar correction model."""

    def __init__(
        self,
        model_name: str = MODEL_NAME,
        revision: str = MODEL_REVISION,
    ) -> None:
        self.model_name = model_name
        self.revision = revision
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None
        self._load_lock = threading.Lock()
        self._load_error: Optional[str] = None
        self._guard = InferenceGuard()

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._tokenizer is not None

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def busy(self) -> bool:
        """True while another call is currently generating output."""
        return self._guard._slot._value == 0  # noqa: SLF001 - simple status probe

    def load(self) -> None:
        """Load the tokenizer and model, caching them on the instance.

        Raises ``GrammarModelError`` with a friendly message on failure so the
        caller can keep spelling mode usable.
        """
        if self.is_loaded:
            return

        with self._load_lock:
            # Another thread may have finished loading while we waited.
            if self.is_loaded:
                return
            try:
                import torch  # noqa: PLC0415 (imported lazily on purpose)
                from transformers import (  # noqa: PLC0415
                    AutoModelForSeq2SeqLM,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                    revision=self.revision,
                    trust_remote_code=False,
                )
                model = AutoModelForSeq2SeqLM.from_pretrained(
                    self.model_name,
                    revision=self.revision,
                    trust_remote_code=False,
                )
                model.eval()
                self._torch = torch
                self._tokenizer = tokenizer
                self._model = model
                self._load_error = None
            except Exception as exc:  # noqa: BLE001 - surface any load failure
                _logger.error("grammar model load failed: %s", type(exc).__name__)
                self._load_error = (
                    "Could not load the AI grammar model. The most common cause "
                    "is no internet connection on the first run (the model must "
                    "be downloaded once). It can also mean the AI dependencies "
                    "(requirements-ai.txt) are not installed in the virtual "
                    "environment. Details are kept in the terminal log, not "
                    "shown here, because they can contain internal paths."
                )
                raise GrammarModelError(self._load_error) from exc

    # ------------------------------------------------------------------
    # Bounds and token handling
    # ------------------------------------------------------------------
    def count_tokens(self, text: str) -> int:
        """Return the token count of the full prefixed prompt."""
        if not self.is_loaded:
            self.load()
        if self._tokenizer is None:
            raise GrammarModelError("The grammar tokenizer is not loaded.")
        encoded = self._tokenizer(PROMPT_PREFIX + text)
        return len(encoded["input_ids"])

    def _validate_length(self, text: str) -> int:
        if len(text) > MAX_INPUT_CHARS:
            raise InputTooLongError(
                f"Text is {len(text)} characters, which is over the limit of "
                f"{MAX_INPUT_CHARS}. Please shorten the text and try again."
            )
        token_count = self.count_tokens(text)
        if token_count > MAX_INPUT_TOKENS:
            raise InputTooLongError(
                f"Text is {token_count} tokens, which is over the limit of "
                f"{MAX_INPUT_TOKENS} tokens. Please shorten the text and try "
                "again. Spelling mode has no token limit and is still available."
            )
        return token_count

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def correct(
        self,
        text: str,
        progress: Optional[Callable[[str], None]] = None,
    ) -> GrammarResult:
        """Return a grammar-corrected suggestion for ``text``.

        ``progress`` is an optional callback used to report status messages to
        the interface (for example while the model is downloading).
        """
        if not text or not text.strip():
            return GrammarResult(text, text, 0)

        # Reject texts that are clearly over the character limit before we do
        # any loading or tokenization work.
        if len(text) > MAX_INPUT_CHARS:
            raise InputTooLongError(
                f"Text is {len(text)} characters, which is over the limit of "
                f"{MAX_INPUT_CHARS}. Please shorten the text and try again."
            )

        if progress:
            progress("Loading the AI grammar model (first run may download files)...")
        self.load()

        token_count = self._validate_length(text)

        if progress:
            progress("Generating a grammar suggestion...")

        if self._tokenizer is None or self._model is None or self._torch is None:
            raise GrammarModelError("The grammar model is not loaded.")

        prompt = PROMPT_PREFIX + text
        inputs = self._tokenizer(
            prompt,
            return_tensors="pt",
            truncation=False,
        )

        with self._guard:
            with self._torch.inference_mode():
                output_ids = self._model.generate(
                    **inputs,
                    num_beams=5,
                    min_length=1,
                    do_sample=False,
                    max_new_tokens=MAX_OUTPUT_TOKENS,
                    early_stopping=True,
                )

        corrected = self._tokenizer.decode(
            output_ids[0], skip_special_tokens=True
        ).strip()

        return GrammarResult(original=text, corrected=corrected, token_count=token_count)