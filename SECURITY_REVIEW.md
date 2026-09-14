# Smart Autocorrect - Security, Stability & Performance Review

Date: 2026-09-14
Scope: `app.py`, `spelling_engine.py`, `grammar_engine.py`, `.streamlit/config.toml`, `requirements*.txt`, `tests/`.
Runtime: Windows, Python 3.12.10, local-only + public demo on Streamlit Community Cloud.

This review records what was inspected, what was fixed, what was verified, and
what remains genuinely unresolved. It deliberately does **not** claim that the
app is "secure", unlimited-traffic-safe, or crash-proof.

---

## 1. Confirmed findings and fixes (in priority order)

| # | Finding | Severity | Affected file | Fix |
| --- | --- | --- | --- | --- |
| 1 | Model downloaded without a pinned revision; any Hub change would silently alter behaviour. | Medium | `grammar_engine.py` | Pinned `MODEL_REVISION = 9e4a09d2…3ed78` (verified against the official repo API) and passed `revision=` + explicit `trust_remote_code=False` to both `from_pretrained` calls. |
| 2 | Transformers 4.57.6 had 8 open advisories (`PYSEC-2025-217`, `PYSEC-2026-2288/2289/2290/3929`). Fixes only exist in the 5.x line. | Medium/High context | `requirements-ai.txt` | Upgraded to `transformers>=5.10.0,<6.0`; installed 5.17.0. `pip-audit --local` now reports **no known vulnerabilities**. None of the 4.5x advisories were reachable from this app, but the upgrade removes the question entirely. The model still loads on 5.x and inference output was re-verified. |
| 3 | No server-side input limits anywhere; pathological pastes could reach the model or the diff view unbounded. | Medium | `app.py`, `grammar_engine.py`, `spelling_engine.py` | Added hard caps: 10,000 chars (spelling), 8,000 chars + 400 tokens (AI), 256 output tokens, 100 custom words / 40 chars each / 2,000 raw chars, 500 suggestion entries. Oversized input is **rejected with a message, never truncated**. The two character bounds (10,000 app-wide vs 8,000 engine) are intentional and now consistent in the UI: the applicable per-mode limit is shown under the text box **before** submission, and validation happens at the app layer against the mode's own bound, so the message can never contradict the engine. |
| 4 | Repeated typos and long/repetitive words could produce thousands of suggestion widgets and heavy edit-distance work. | Medium | `spelling_engine.py`, `app.py` | Candidate results are memoized per request; words over 40 chars or long single-character runs are skipped; a 500-entry suggestion cap stops scanning; the reviewer now shows **one selectbox per distinct word** instead of one per occurrence. |
| 5 | No bound on concurrent AI inference; a shared cached model could run overlapping generations. | Medium | `grammar_engine.py` | Added `InferenceGuard`, a process-wide single-slot semaphore with a **short bounded wait (10 s)** and a clear busy/retry message, so a second caller is not left staring at a spinner (a 90 s wait had this risk). The slot always releases, including on error (context-manager + verified by a test). |
| 6 | `assert` statements used for runtime checks (stripped under `-O`) and raw exception detail (which can contain internal paths) shown in the UI. | Low | `grammar_engine.py` | Replaced asserts with explicit checks that raise `GrammarModelError`; the UI error is now a friendly, generic message and the exception *type* is logged (never user text) to the terminal logger. |
| 7 | Privacy wording implied inference happens "in the browser". | Informational | `app.py` | AI explanation and the footer now state processing runs on the app's **hosting server** (your computer locally; the hosting provider's server on the public demo), not the visitor's browser, and clarified no external API is used. |
| 8 | Streamlit ran with telemetry on and default binding. | Informational | `.streamlit/config.toml` (new) | Keeps CORS and XSRF protection explicitly enabled, `maxUploadSize` reduced, `browser.gatherUsageStats = false`. `server.address` is intentionally **not** pinned so the same file works locally (Streamlit's default localhost bind keeps local runs private) and on Community Cloud (the platform manages the public bind). |
| 9 | No regression tests for the risky paths. | Informational | `tests/` | Added `test_limits.py`, `test_grammar_engine.py` and `test_app_ui.py` (AppTest flows); full suite is **56 tests**, all green. |

Confirmed **not** present (no change needed): no `exec`/`eval` of user text, no
shell command invocation, no URL fetching from submitted text, no persistent
file writes of user text, no logging of submitted text, and the diff view
already HTML-escapes every token before the single `unsafe_allow_html=True`
render.

---

## 2. Dependency audit

* `pip-audit --local` on the fixed environment: **"No known vulnerabilities found."**
* `pip check`: **"No broken requirements found."** (the installed environment is
  internally consistent - required for reproducing the tested setup).
* Before the transformers upgrade it reported 8 findings, all in
  `transformers 4.57.6`
  (`PYSEC-2025-217`, `PYSEC-2026-2288`, `PYSEC-2026-2289`, `PYSEC-2026-2290`,
  `PYSEC-2026-3929`).
* Relevance assessment of the original findings (before fixing): all five
  advisories target code paths this app never calls (the `Trainer`
  `_load_rng_state` checkpoint path, the X-CLIP conversion script,
  `save_pretrained` on chat-template tokenizers, and causal-LM
  `config.json`/LightGlue tricks that expect an attacker-controlled model
  repository). They were not suppressed - they were fixed by upgrading
  `requirements-ai.txt` to `transformers>=5.10.0,<6.0` (5.17.0 installed).

## 3. Static analysis

* `bandit -r app.py spelling_engine.py grammar_engine.py` and
  `bandit -r . -x "*.venv*"` (whole project):
  * Before: 2 × **B615** (medium, `huggingface_unsafe_download` - unpinned
    revision) and 4 × **B101** (low, `assert` usage).
  * After: **No issues identified** over 1,172 lines of project code.
* Tooling note: on Windows, the exclude pattern must be `"*.venv*"`; the plain
  `-x .venv` form does not match backslash paths, so bandit walks the whole
  virtual environment instead of excluding it (slow, not a security finding).
* Manual review notes: the only `unsafe_allow_html=True` render is the word
  diff, which escapes content with `html.escape`; test coverage confirms
  `<script>`/attribute-injection strings never appear raw.

## 4. Model safety

* Model repo file list (checked via the Hub API): `config.json`,
  `pytorch_model.bin`, `spiece.model`, `tokenizer.json`,
  `special_tokens_map.json`, `tokenizer_config.json`. **No safetensors weights
  exist** in this repo, so safetensors could not be preferred.
* `pytorch_model.bin` is a legacy PyTorch pickle. In transformers 5.17.0 the
  weight loader calls `torch.load(..., weights_only=True)` by default, which
  blocks pickle gadget deserialization. Combined with the pinned revision of
  the well-known upstream repo and `trust_remote_code=False`, the loading path
  is as safe as this format allows. This limitation is documented, not hidden.
* Certificate verification is never disabled; the download uses the normal
  Hugging Face Hub transport with the default local cache.

## 5. What was verified (automated)

* **56/56 unit + AppTest tests pass** (`python -m unittest discover -s tests`),
  including new regression tests for:
  * HTML/script-like content displayed safely in the diff;
  * oversized text and dictionary input rejected before expensive work
    (engine-level char check proven to run *before* any model load);
  * per-mode input limit consistency (Spelling 10,000 vs AI Grammar 8,000) and
    the mode-specific message shown before submission;
  * long-word/repeated-run spelling performance (pathological 7,900-char input
    completes in ~0.02 s on this machine, capped at 500 suggestions);
  * separate sessions cannot share custom words (engine A protects a word that
    engine B then flags as misspelled);
  * the concurrency guard releases after success and after failure, times out
    with a friendly error when busy, and uses the short 10 s default wait;
  * normal spelling correction, Clear, Load Example, editing the final text and
    the download button via Streamlit `AppTest`.
* Changed limits exercised in tests; nothing is silently truncated.

## 6. Streamlit server security verification (localhost / CORS / XSRF)

Two kinds of evidence were collected. Only the behaviour that was actually
observed is reported; nothing below is assumed.

### Configuration checks
* `.streamlit/config.toml` sets `server.headless = true`,
  `server.enableCORS = true`, `server.enableXsrfProtection = true`,
  `server.maxUploadSize = 1` and `browser.gatherUsageStats = false`. It does
  **not** set `server.address`/`server.port`, so local runs keep Streamlit's
  default `localhost` bind (external machines cannot connect) while cloud
  deploys let the platform choose the bind.
* `streamlit config show` (installed Streamlit 1.63.0) recognises
  `server.enableCORS` and `server.enableXsrfProtection` as valid options with
  default `true`; our TOML keeps them enabled explicitly. `gatherUsageStats`
  default is `false`; our TOML sets it explicitly.
* The server process loads this TOML: locally it started on `localhost:8501`
  (see below); on the cloud the platform controls the address/port.

### Behavioural checks (observed live, not assumed)
Started with `.venv\Scripts\python.exe -m streamlit run app.py`, then:
* **localhost bind:** `Get-NetTCPConnection -LocalPort 8501` showed a single
  listen socket on `127.0.0.1` only (no `0.0.0.0`); Uvicorn logs
  "started on localhost:8501".
* **Health:** `GET /healthz` returned HTTP **200**.
* **host-config:** `GET /_stcore/host-config` returned the expected client
  config JSON, including the `allowedOrigins` whitelist Streamlit serves to
  browsers (used for CORS origin checks). It does **not** expose the
  `enableCORS`/`enableXsrfProtection` flags themselves, so flags were verified
  via config (above), not via this endpoint.
* **CORS (behavioral):** a WebSocket handshake to `/_stcore/stream` with
  `Origin: https://evil.example.com` (not in the whitelist) was rejected with
  HTTP **403**.
* **XSRF (behavioral):** a WebSocket handshake to `/_stcore/stream` with an
  *allowed* origin (`https://streamlit.app`) but **without the XSRF token**
  header was also rejected with HTTP **403** - i.e. the origin passed the CORS
  check and the connection was still refused, which is the XSRF protection
  refusing a handshake that carries no token.
* Plain `GET` requests to `/_stcore/host-config` returned `200` with **no
  `Access-Control-Allow-Origin` header** for both evil and allowed origins;
  CORS on Streamlit is enforced at the WebSocket handshake layer (where the
  403s above were observed), not by adding ACAO headers to these JSON/static
  GET endpoints.
* The server was stopped cleanly; port 8501 was confirmed released afterwards
  (no leftover background process).

### Honest caveat
The **positive** XSRF flow (correct origin + valid token -> successful
connection) needs a real browser session, which was not driven here; the
headless AppTest flows cover the widget layer only. What is verified is that a
token-less WebSocket handshake is refused (403), which is the behavioural
signal that XSRF checking is live.

## 7. Manual checks (browser / live process)

* App started with `streamlit run app.py`: health endpoint `200`, Uvicorn
  reports `started on localhost:8501` (config applied).
* Real grammar smoke test (model cached, CPU, transformers 5.17.0):
  * `"She go to college every day and don't has idea."`
    → `"She goes to college every day and doesn't have an idea."`
  * `"This sentences has has bads grammar."` → `"This sentence has bad grammar."`
* Real browser interaction (clicking buttons in a human session) was **not**
  performed in a browser; the AppTest flows cover the same widget paths
  headlessly. A quick look at the opened page is recommended after starting it.

## 8. Measured performance (bounded, local only)

Environment: Windows, CPU only, unchanged hardware while measuring.

| Test | Input size | Time |
| --- | --- | --- |
| Spelling, typical sentence | 41 chars | 0.000 s |
| Spelling, pathological (repeats + long run + unknowns) | 7,907 chars | 0.015 s (0.5 s before memoization + caps) |
| Grammar inference, model cached on CPU | 35 chars | 7 s – 20 s (varies with system load) |
| Grammar oversized rejection | 9,000 chars | 0.000 s (rejected before load) |

These are single measurements on a shared consumer laptop, not a benchmark
suite. The grammar number in particular varies run to run.

## 9. Unresolved issues + reasons (honest)

* **CPU inference latency (7-20 s).** Expected, not a bug: T5-base beam search
  on CPU. Mitigated by lazy loading, caching, and a concurrency guard.
  A Python thread timeout would **not** interrupt PyTorch inference; the guard
  therefore *waits* rather than claiming to cancel computation. The guard's 10 s
  wait is a deliberate trade-off: because a real inference can outlast it, a
  second request may receive the "model is busy" message while an earlier
  correction is still legitimately running; the message says to retry briefly.
* **Operating-system out-of-memory / hard crashes** cannot always be caught by
  Python. If a future public deployment's memory is exhausted, the process may
  be killed with no Python handler involved.
* **`.pytorch_model.bin` format** (no safetensors in the repo) is inherently
  less safe than safetensors; the protection relies on `weights_only=True` in
  modern transformers. Fully eliminating this would require a safetensors
  conversion, which we chose not to invent/overwrite, since the pinned upstream
  repo is the intended source.
* **Session vs. process isolation.** Custom words and correction text are
  session-local (verified by test). The grammar *model* itself is one shared
  cached object; that is intentional (it is static code, not user data).
* **Per-session throttling would be a cooldown, not abuse protection.** Opening
  new sessions bypasses it, and the process-wide inference guard does not
  coordinate across *multiple* processes. That level of control belongs only in
  a deployed environment (below).
* **Hugging Face cache symlink warning on Windows** (harmless, cosmetic) and
  the unauthenticated-request warning (`HF_TOKEN`) remain; neither affects
  attack surface here.
* **Free-tier container memory vs. AI Grammar (open question).** Local
  measurement on this machine (Windows, Python 3.12.10) shows ~**447 MB RSS**
  after the model is loaded and ~**1.2 GB peak RSS during an AI inference**
  (~1.7 GB pagefile/commit). The public demo runs on Streamlit's free tier,
  whose exact RAM limit is a provider secret; AI Grammar may exhaust it. If so,
  Spelling mode (which never loads the model) remains fully usable; the in-app
  privacy note already says processing happens on the hosting server. The
  outcome is recorded in section 10. This is why the deploy uses CPU-only torch (`+cpu` wheel on
  Linux) and why the app fails gracefully for Spelling mode if AI cannot fit.
* **Public deployment items (HTTPS/proxy/supervision) are now the provider's
  responsibility.** Streamlit Community Cloud manages TLS, the WebSocket proxy,
  process supervision and the ingress; this project's `.streamlit/config.toml`
  deliberately does not fight that (no `server.address` pin).

## 10. Local versus public deployment

**Local** (`app.py` + `.streamlit/config.toml` on your machine):
* Streamlit's default `localhost` bind - external machines cannot connect;
* no TLS, no auth, no quotas beyond the input caps;
* fine for a project/demo on your machine.

**Public demo** (Streamlit Community Cloud, free tier) - deployed from the same
commit (`702c2db`), repo <https://github.com/an-codes1/smart-autocorrect>,
live at
<https://smart-autocorrect-nkbdlv6jkscf9tea5xwz6d.streamlit.app/>:

Provider-managed (not re-implemented by us): HTTPS/TLS termination, WebSocket
compatible proxy for `/_stcore/stream`, process supervision/restart, ingress.
Our `.streamlit/config.toml` keeps `enableCORS`/`enableXsrfProtection` **on**
and does not pin `server.address`, so those settings hold on the cloud.

Observed on the deployed app (2026-09-14, anonymous automated probes):
* `GET https://…/` -> **200**, Streamlit SPA shell served; TLS active.
* `GET http://…/` -> **303** redirect to Streamlit's auth/gateway flow
  (`share.streamlit.io/-/auth/app?redirect_uri=…`), i.e. cleartext HTTP is not
  served.
* `GET https://…/_stcore/health` and `/_stcore/host-config` -> the gateway
  returns the SPA shell (200 HTML), **not** internal config JSON - the private
  `_stcore` endpoints are not reachable through the gateway.
* The repo contains no `.env`, no `secrets.toml`, no model weights, and a
  secret-pattern scan found nothing. Submit-text and model behaviour are the
  same code paths verified locally by the 56 tests (CPU-only torch wheel,
  `trust_remote_code=False`, pinned model revision, input caps, inference
  guard).

Honest caveats for the public demo:
* The free tier's RAM limit is unpublished. Local measurement of AI Grammar
  shows ~1.2 GB RSS peak during inference; **AI Grammar may be memory-limited
  on the free tier** and, if so, is the one feature that can fail there
  (Spelling mode is unaffected). Verified result: Spelling mode works.
  AI Grammar: **verified working** on the live free-tier instance (test input
  `She go to college every day.` returned the corrected output).
* The "busy" retry message and 7-20 s CPU inference times still apply; the
  free tier is a shared, limited CPU.
* Browser-driven, positive XSRF flow was not automated; the behavioural
  403-on-tokenless-handshake verification above, plus the provider's own
  enforcement, is what the cloud relies on.
* No WAF, IP throttles or account-level quotas exist beyond the provider's
  free-tier rate limits; the app's own input/output caps are the app-level
  limits. This is an open, single-user-learning demo, not a hardening target.

## 11. Dependency maintenance & recovery

```powershell
# Periodic audits (install the tools once):
.venv\Scripts\python.exe -m pip install pip-audit bandit
.venv\Scripts\python.exe -m pip_audit --local
.venv\Scripts\python.exe -m pip check
# Whole-project scan (the "*.venv*" pattern is required on Windows):
.venv\Scripts\python.exe -m bandit -r . -x "*.venv*"

# Apply AI-dependency updates within the allowed ranges:
.venv\Scripts\python.exe -m pip install --upgrade -r requirements-ai.txt

# If a dependency upgrade ever breaks the model load, recover with:
.venv\Scripts\python.exe -m pip install -r requirements-ai.txt -r requirements.txt
# or reinstall the venv from scratch:
#   python -m venv --clear .venv
#   .venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-ai.txt
# Then re-run:  .venv\Scripts\python.exe -m unittest discover -s tests
```

A pre-hardening checkpoint of all project files was also saved to
`%TEMP%\opencode\smart-autocorrect-checkpoint-before-hardening\` for easy
restore if needed.

## 12. Restart instructions

Stop the running server (Ctrl+C in its terminal), then:

```powershell
.venv\Scripts\python.exe -m streamlit run app.py
```