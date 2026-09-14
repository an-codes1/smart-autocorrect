# Smart Autocorrect

A beginner-friendly English autocorrect app for a college project. It detects
misspelled words and offers AI-powered grammar suggestions to improve text
accuracy and fluency.

> **Live demo:** <https://smart-autocorrect-nkbdlv6jkscf9tea5xwz6d.streamlit.app/>
>
> Free Streamlit Community Cloud hosting. Runs over HTTPS with the app's
> security settings enabled. Spelling mode needs no model and is fast; AI Grammar
> downloads the ~900 MB model on first use and can take several seconds per
> check on the free tier. See "Deploying your own copy" below.

## Project objective and features

* **Spelling mode** (dictionary/frequency based, using `pyspellchecker`):
  - Detects individual misspelled English words and suggests alternatives.
  - Preserves spaces, line breaks, punctuation and capitalization by editing
    word *spans*, never blind string replacement.
  - Protects URLs, e-mail addresses, numbers and acronyms.
  - Supports a custom dictionary of names and technical terms (Python and
    Streamlit are included by default and are always editable).
* **AI Grammar mode** (local neural inference):
  - Uses the public pretrained model `vennify/t5-base-grammar-correction`.
  - Runs entirely on the server that hosts the app - no paid API, no keys, no
    data upload. Processing happens in the app's server process (your computer
    when run locally; the hosting provider's server on the public demo), not
    inside the visitor's browser.
  - Loads the model lazily and only when you ask for AI correction, then caches
    it so Streamlit reruns do not reload it. Loading is serialized with a
    process-wide concurrency guard, and `model.eval()` + `torch.inference_mode()`
    are used for deterministic inference.
  - Uses deterministic beam search with the model card's documented settings.
  - The model repo is pinned to a verified revision with `trust_remote_code`
    disabled, never silent truncation: input is rejected (not clipped) when it
    exceeds the char or token limits.
* **Clean Streamlit interface**:
  - Mode selector, text area, Check Text / Load Example / Clear buttons.
  - Original and suggested text side by side, an editable final text box,
    a safe word-level difference view, and a `.txt` download button.
  - Correction only happens when you press the button, not on every keystroke.
  - Stale results are clearly labelled whenever the input or mode changes.

## Prerequisites

* Windows with PowerShell.
* Python 3.9 or newer (3.11 was the target; 3.12.10 was verified on the
  development machine).
* VS Code (optional) with the Python extension.

> This project was verified on Python 3.12.10. It should also run on 3.11. If
> you do not have Python installed, install it from <https://www.python.org/downloads/>
> and tick **"Add python.exe to PATH"** during installation. Do not install from
> the Microsoft Store alias for this project.

## Installation (Windows PowerShell)

Run every command from the project folder:

```powershell
cd <your-local-project-folder>   # e.g. C:\Users\<you>\Documents\AutocorrectTool

# 1. Create the virtual environment
python -m venv .venv

# 2. Install ALL dependencies (requirements.txt already includes
#    requirements-ai.txt, so this single command installs the spelling stack
#    AND the AI Grammar stack)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

We use `.venv\Scripts\python.exe` directly in these instructions, so pointing
the command at the virtual environment's interpreter works even before the
virtual environment is "active".

## Launching the app

Option A - activate the virtual environment, then run:

```powershell
.venv\Scripts\activate
.venv\Scripts\python.exe -m streamlit run app.py
```

In PowerShell you may use `.venv\Scripts\Activate.ps1` instead of
`.venv\Scripts\activate` if the latter is preferred by your shell.

Option B - no activation, call the interpreter directly:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```

Both options start the same server. Your browser opens at
<http://localhost:8501>. To stop it, press `Ctrl + C` in the terminal.

The included `.streamlit\config.toml` keeps CORS and XSRF protection on, limits
upload size, and turns off usage-stats telemetry. Streamlit binds to `localhost`
by default, so when run locally the app is not reachable from other computers
on the network. This is for local development; the same file is also suitable
for Streamlit Community Cloud, where the platform manages the public bind,
HTTPS and WebSocket proxy (see `SECURITY_REVIEW.md`).

## Selecting the interpreter in VS Code

1. Open the project folder in VS Code.
2. Install the **Python** extension (ms-python.python) if not already present.
3. Press `Ctrl + Shift + P` and run **Python: Select Interpreter**.
4. Choose **Enter interpreter path...** and point it at the virtual
   environment's interpreter:
   `<your-local-project-folder>\.venv\Scripts\python.exe`
5. Open a new terminal; there is no need to "activate" anything. To run the app
   from the VS Code terminal, paste the launch command above.

## Running the tests

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The suite includes:
* spelling-engine tests (correction, preservation, protected tokens);
* grammar-engine unit tests (bounds, pinned revision, concurrency guard);
* security/limits regression tests (HTML escaping, oversized input, per-mode
  limit consistency, long-word performance, session isolation);
* Streamlit `AppTest` flows (spelling check, Clear, Load Example, oversized
  rejection, editing the final text).

## Deploying your own copy on Streamlit Community Cloud (free)

The repo is already wired for cloud deploys:

* `requirements.txt` includes `requirements-ai.txt`, so one dependency file
  installs everything (Streamlit, pyspellchecker, **and** the AI stack).
* `requirements-ai.txt` installs PyTorch's **CPU-only** build on Linux via the
  official `download.pytorch.org/whl/cpu` extra index - no multi-gigabyte CUDA
  wheels, no GPU required. On Windows/macOS the regular PyPI wheel is used.
* `.streamlit/config.toml` does **not** pin `server.address`, so it works both
  locally (Streamlit's default localhost bind keeps your local run private) and
  on the cloud (the platform manages the public bind, HTTPS and the WebSocket
  proxy). CORS and XSRF protection stay enabled.
* No model weights are in the repo. The grammar model downloads from the
  Hugging Face Hub on first AI use and is pinned to a verified revision with
  `trust_remote_code=False`.

To publish your own copy:

1. Push this code to your own GitHub repo (public or private).
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. **Create app** -> choose your repo, branch `main`, main file `app.py`.
4. Advanced settings -> Python version **3.12**.
5. **Deploy**. The app appears at `https://<subdomain>.streamlit.app/`.

Notes for the free tier:

* The first build installs CPU-only PyTorch, so expect several minutes.
* The free tier has limited CPU and RAM. Spelling mode is lightweight. AI
  Grammar downloads ~900 MB of weights on its first run, then performs CPU beam
  search; each check can take several seconds and may be memory-constrained on
  the smallest instances. If AI Grammar cannot run inside the container's RAM
  limit, the app remains fully usable in Spelling mode (ergo the in-app note
  that AI runs on the hosting server).

## Input limits (server-side, enforced before expensive work)

| Limit | Value |
| --- | --- |
| Max main text length (spelling mode) | 10,000 characters |
| Max AI text length (AI Grammar mode) | 8,000 characters and ~400 tokens |
| Max generated AI output | 256 tokens |
| Max custom dictionary words | 100 words, max 40 characters each |
| Max custom dictionary raw input | 2,000 characters |
| Max words examined per spelling request | 500 suggestion entries |

Inputs over a limit are **rejected with a helpful message** - never silently
truncated. Your entered text always stays in the text box so you can retry.

The two character bounds are intentional: the spelling engine has no token
limit and tolerates longer text; the grammar engine applies a stricter bound
before loading the model. The limit that applies to the mode you selected is
shown directly under the text box **before** you submit, so the message you see
always matches the limit that is actually enforced.

## Security checks

Run these from the project folder (optional, they are not installed by the
runtime requirements - install them once with
`.venv\Scripts\python.exe -m pip install pip-audit bandit`):

```powershell
.venv\Scripts\python.exe -m pip_audit --local
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -m bandit -r app.py spelling_engine.py grammar_engine.py
```

Static results and the full security review are in `SECURITY_REVIEW.md`. These
scans reduce known risk classes (known-vulnerable packages, common Python
smells); they do **not** prove the app is "secure" - see the honest caveats in
`SECURITY_REVIEW.md`.

## Source files

| File | Purpose |
| --- | --- |
| `app.py` | The Streamlit user interface. Manages session state, buttons, downloading, and the safe diff view. |
| `spelling_engine.py` | The dictionary/frequency spelling corrector. Pure logic, no UI. |
| `grammar_engine.py` | Lazy loader and local inference wrapper for the T5 grammar model. |
| `requirements.txt` | Basic dependencies (Streamlit + pyspellchecker); it also includes `requirements-ai.txt`. |
| `requirements-ai.txt` | AI dependencies (CPU-only PyTorch, Transformers, SentencePiece) with a Linux CPU-extra index for cloud deploys. |
| `.streamlit/config.toml` | Server settings (CORS/XSRF on, upload cap, telemetry off). Locally the default localhost bind keeps the app private; the same file is safe for Community Cloud. |
| `SECURITY_REVIEW.md` | Hardening report: findings, fixes, audits and limitations. |
| `tests/` | Unit tests for both engines, limits/security, and AppTest UI flows. |
| `.gitignore` | Ignores `.venv`, caches, logs and editor folders. |

## Concepts for beginners

* **Edit distance:** how different two words are - the minimum number of
  insertions, deletions or substitutions to turn one into the other. The
  spelling engine (via pyspellchecker) uses a symmetric edit-distance algorithm
  to find words "close" to the typo.
* **Word frequency:** how often a word appears in normal English. When several
  candidates are equally close to a typo, the most frequent one is ranked
  first. This is why frequency is baked into the suggestions.
* **Tokenization:** splitting text into smaller pieces (tokens). The T5 model
  uses a SentencePiece tokenizer, and tokens are often sub-word chunks, not
  full words.
* **Pretrained models:** a neural network that someone else already trained on a
  large corpus. Here, *vennify* fine-tuned Google's T5 on the JFLEG grammar
  dataset. We only *run* the model (inference); we did not train it.
* **Inference:** running a trained model on new input to get an output. Our app
  loads the model once, remembers it in a cache, and performs beam search
  (deterministic) to propose a corrected sentence.

## Data flow

1. You type text and press **Check Text**.
2. **Spelling:** `app.py` hands the text to `spelling_engine.py`, which
   tokenizes by word spans, skips protected spans (URLs, e-mails, numbers,
   acronyms, custom words), and looks up candidates with
   `pyspellchecker`. It returns the corrected string plus the list of
   suggestions.
3. **AI Grammar:** `app.py` gets a cached `GrammarEngine`, which loads
   `vennify/t5-base-grammar-correction` on first use, prepends the required
   `"grammar: "` prefix, checks the token length, and runs beam search. The
   decoded text is returned (a suggestion).
4. The UI shows original vs. suggested text, a word-level diff, and an editable
   final text box that you can download as `.txt`.

## Limitations and future improvements

* Spelling mode cannot catch correctly spelled but contextually wrong words
  ("their" vs "there"). A context-aware model could help but is heavier.
* The grammar model can change meaning or introduce new mistakes; treat its
  output as a suggestion. It is licensed non-commercial (CC BY-NC-SA 4.0).
* First AI run downloads ~900 MB of model files to your Hugging Face cache.
* The input limit (~400 tokens) is intentionally conservative.
* Future ideas: per-sentence grammar checking, a loadable custom dictionary
  file, GPU detection for faster inference, and a simpler auto-correct backend
  built on `textblob` for comparison.

## Troubleshooting

* **First AI run is slow or fails with "Could not load the AI grammar model".**
  The model downloads once from the Hugging Face Hub (~900 MB). Check your
  internet connection, then click Check Text again. Once cached, no network is
  needed. Spelling mode always keeps working.
* **"The AI grammar model is busy with another correction."** happens when two
  corrections overlap. On this CPU-only app only one inference runs at a time;
  the app waits up to ~10 seconds and then asks you to click Check Text again
  rather than leaving the page stuck in a spinner.
* **AI Grammar takes several seconds per check.** That is expected on CPU:
  T5-base beam search typically finishes in roughly 7-20 seconds in this
  project's tests, depending on system load.
* **"Text is ... characters, which is over the limit..."** Your input exceeds
  the server-side caps above. Shorten the text; nothing was truncated. The
  limit shown under the text box is the one that applies to your selected mode.
* **Custom dictionary validation errors.** Up to 100 words, each up to 40
  characters, and a 2,000-character raw input. Oversized input is rejected with
  a message, never silently truncated.
* **"Could not load..." on a fresh machine.** Make sure you installed
  `requirements-ai.txt` in *this* project's `.venv` before launching.
* **PyTorch is using 100% of one CPU core during AI mode.** That is expected:
  the T5-base model runs on your CPU for several seconds per check.
* **The model revision is intentionally pinned.** The app only ever downloads
  the exact revision written in `grammar_engine.py` (`MODEL_REVISION`), so an
  update to the upstream repo cannot silently change behaviour. Do not "fix"
  this unless you deliberately want a different revision.
* **The app is intentionally localhost-only when run locally.** Streamlit binds
  to `127.0.0.1` by default (we do not pin `server.address`, so nothing in the
  config overrides that), meaning other computers cannot reach your local
  instance. To expose it you would be disabling a safety property; public
  hosting needs HTTPS/proxy/etc. - see `SECURITY_REVIEW.md`. On the public
  Community Cloud demo the platform provides the HTTPS-backed public address.
* **Windows warns about Hugging Face cache symlinks.** Harmless and cosmetic;
  downloads still work in a slower, non-symlink mode.
* **App console shows "missing ScriptRunContext".** Only appears when running
  the modules outside Streamlit (tests, benchmarks); ignore it.

## Model attribution and license

* **Model:** `vennify/t5-base-grammar-correction`
  <https://huggingface.co/vennify/t5-base-grammar-correction>
* **Trained on:** the JFLEG grammar-correction dataset
  (Napoles et al., 2017; arXiv:1702.04066).
* **License:** CC BY-NC-SA 4.0 - non-commercial, share-alike, attribution
  required.
* **Authorship:** this model was trained by Vennify AI; it was **not** trained
  or modified by the authors of Smart Autocorrect. We make no accuracy claims.

## Viva questions (with answers)

**Q1. How does the spelling mode decide that a word is wrong?**
It checks each word span against a frequency-weighted English dictionary
(pyspellchecker). Words missing from the dictionary are candidates for
correction, and alternatives are ranked by edit distance plus word frequency.

**Q2. Why do you use word spans instead of replacing the whole string?**
Replacing the whole string risks changing protected text such as URLs, e-mails
or the user's original spacing and capitalization. Span-based replacement only
swaps the exact characters of a misspelled word while everything around it is
copied unchanged.

**Q3. What is the purpose of the `"grammar: "` prefix?**
The T5 grammar model was fine-tuned on inputs that start with that prefix, so
the model card instructs us to add it. Feeding the model text in the same
format it was trained on gives much better results.

**Q4. Why is the grammar model loaded lazily and cached?**
Loading it downloads and loads ~900 MB of files and takes a long time.
Streamlit reruns the whole script on every interaction, so without caching the
model would be reloaded constantly. The cache makes the first run slow and
later runs fast.

**Q5. What is beam search and why `num_beams=5`?**
Beam search keeps the five most promising partial sentences at each step and
picks the single best complete sentence at the end, which makes the output
deterministic (with `do_sample=False`). `num_beams=5` matches the setting shown
on the model card and gave good quality results in the project.

## Verified dependency versions

Actually tested on this machine (Python 3.12.10, Windows) at the time of the
hardening pass:

* streamlit 1.63.0
* pyspellchecker 0.9.0
* torch 2.14.0 (CPU build; `torch.cuda.is_available()` = False)
* transformers 5.17.0 (upgraded from 4.57.6 to clear known advisories)
* sentencepiece 0.2.2
* tokenizers 0.23.2 (pulled in by transformers)
* numpy 2.5.3, pandas 3.0.5 (pulled in by streamlit)
* Dev/audit tools: bandit, pip-audit (not runtime dependencies)
* `pip check` on this environment: "No broken requirements found."

The `requirements*.txt` files use exact pins (`==`) for the versions tested
together in this project. `requirements.txt` includes `requirements-ai.txt`, so
there is a single entry point for installs. No lockfile is shipped. To
reproduce the tested environment, install inside a fresh `.venv` with
`requirements.txt` (pip resolves `requirements-ai.txt` automatically), then run
`.venv\Scripts\python.exe -m pip check`.