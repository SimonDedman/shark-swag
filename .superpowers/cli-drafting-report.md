# Switch description drafting from the Anthropic API to the local Claude Code CLI

## Why

The owner's Anthropic API account carries no credit. Drafting now runs through
the local `claude` CLI (`/home/simon/.local/bin/claude`), which authenticates
against his Claude Max subscription instead.

## What changed

`intake_draft.py`:

- Removed `import anthropic`, `_api_key()`, `ConfigError`, `DRAFT_SCHEMA`,
  the `MODEL`/`MAX_TOKENS` constants, and the `Accept-Encoding: gzip` brotli
  workaround (all SDK-specific, no longer relevant).
- Added `CLAUDE_BIN = "/home/simon/.local/bin/claude"` (hardcoded absolute
  path, since the systemd service's `PATH` does not include `~/.local/bin`)
  and `TIMEOUT_S = 180`.
- `_build_prompt(row)` folds the former system prompt (grounding rules +
  house-style examples), the page text, and an explicit "reply with exactly
  one JSON object" instruction into a single prompt string, since
  `--system-prompt` / `--exclude-dynamic-system-prompt-sections` measurably
  increase token usage and lose cache reuse rather than trimming anything
  (per the owner's own measurement) and are not used.
- `_call_claude(prompt)` runs
  `subprocess.run([CLAUDE_BIN, "-p", prompt, "--output-format", "json",
  "--no-session-persistence"], capture_output=True, text=True, timeout=180)`,
  parses the CLI's JSON stdout, and returns `(None, note)` on any of: missing
  binary (`FileNotFoundError`), timeout, non-zero exit, unparsable stdout, or
  `is_error: true` in the payload (using `subtype` in the note). On success
  it returns the raw `result` string.
- `_extract_json_object(text)` is a balanced-brace scanner that pulls the
  first complete `{...}` object out of a reply, whether bare, fenced in
  ```` ```json ```` , or wrapped in a sentence.
- `_parse_reply(text)` tries that extracted object first; if nothing with
  both `description` and `grounded` keys parses, it falls back to treating
  the whole reply as the description **only** if `_looks_like_plain_sentence`
  says it reads like a bare one- or two-sentence draft (no braces, no code
  fence, 1-3 sentence-enders, under 400 chars) — otherwise it returns `None`
  with "could not parse the reply", and `draft_description` never lets that
  reach the Description cell.
- `draft_description(row) -> (description, note)` keeps its exact signature
  and grounding semantics: empty blurb -> no call at all; ungrounded ->
  empty description with a fixed note (the model is no longer asked for a
  free-text "reason", since the new prompt only requests `description` and
  `grounded`); grounded but empty text -> empty description with a note;
  grounded with text -> `f"drafted from {source}"`, with a
  `(reply was not JSON; used verbatim)` suffix when the plain-sentence
  fallback fired.

`tests/test_intake_draft.py`: every case now stubs `intake_draft.subprocess.run`
instead of `anthropic.Anthropic`, returning a `subprocess.CompletedProcess`
whose `stdout` is the JSON shape the real CLI prints
(`{"result": ..., "is_error": ..., "subtype": ...}`). Tests removed because
they no longer apply (API-key file handling, SDK exception classes) were
replaced with subprocess/CLI-shaped equivalents so the same behaviours stay
pinned:

| Old test (SDK) | New test (CLI) |
|---|---|
| `test_a_row_with_no_blurb_never_touches_the_client` | `test_a_row_with_no_blurb_never_touches_the_cli` |
| `test_a_grounded_response_is_returned_verbatim` | same name, CLI-shaped stub |
| `test_an_ungrounded_response_returns_an_empty_description_with_the_reason` | `test_an_ungrounded_response_returns_an_empty_description` |
| `test_a_grounded_true_but_empty_description_is_still_empty` | same name |
| `test_an_unparsable_response_leaves_the_row_staged` | `test_unparsable_cli_stdout_leaves_the_row_staged` |
| `test_a_refusal_returns_empty_and_names_the_category` / `..._with_no_content_does_not_crash` | `test_an_error_reported_by_the_cli_leaves_the_row_staged` |
| `test_a_missing_api_key_leaves_the_row_staged` / `test_an_unreadable_env_file_leaves_the_row_staged` | dropped — no API key involved any more |
| `test_a_rate_limit_error_leaves_the_row_staged` / `test_a_server_error_leaves_the_row_staged` / `test_a_connection_error_leaves_the_row_staged` / `test_a_not_found_model_leaves_the_row_staged` | `test_a_nonzero_exit_leaves_the_row_staged`, `test_a_missing_binary_leaves_the_row_staged`, `test_a_timeout_leaves_the_row_staged`, `test_a_missing_result_key_leaves_the_row_staged` |
| `test_the_api_key_never_reaches_the_note` | dropped — no secret in play |
| `test_the_request_uses_the_documented_model_and_parameters` | `test_the_cli_is_invoked_with_the_documented_flags` |

New tests added purely for the tolerant-parsing requirement (none of these
existed before, each written to fail against the old anthropic-only module
and pass against the new one):

- `test_a_bare_json_object_reply_parses`
- `test_a_fenced_json_reply_parses`
- `test_a_json_reply_wrapped_in_a_sentence_parses`
- `test_a_bare_plausible_sentence_reply_is_used_verbatim`
- `test_a_reply_that_parses_to_nothing_is_never_used_as_a_description`

## Test output

```
$ /home/simon/.venvs/scrape/bin/python -m pytest -q
........................................................................ [ 23%]
........................................................................ [ 46%]
........................................................................ [ 69%]
........................................................................ [ 92%]
......................                                                   [100%]
310 passed in 2.90s
```

309 baseline tests (all still passing) + 1 net new (16 tests in
`test_intake_draft.py` replacing the 15 that were there before). No test
invokes the real `claude` CLI; every case stubs `subprocess.run`.

## Live check (by hand, not run by the suite)

Row `q0001` in `intake/queue.json` (Hide & Drink zippered coin pouch,
`https://www.amazon.com/dp/B07MXKZJDP`) predates the `blurb`/`blurb_source`
fields in the queue schema, so its page text was read straight from the
existing HTML cache (`images/htmlcache/4320dd132363d87fdba8576371bed36ced85e73f.html`,
a cache hit — no network fetch) via `intake_extract.extract_blurb`, then
passed through `intake_draft.draft_description` on a copy of the row held
only in memory. Nothing was written back to `intake/queue.json`.

Drafted description, verbatim:

> "Hand cut and stitched from full grain leather by artisans in Pastores, Guatemala, a town given over entirely to leatherwork, with the loose ends passed over a flame so the stitching can't unravel."

Note: `drafted from amazon`

CLI usage for that call:

- `total_cost_usd`: 0.0351785
- `usage.input_tokens`: 2
- `usage.cache_read_input_tokens`: 53087
- `usage.cache_creation_input_tokens`: 0
- `usage.output_tokens`: 345 (of which `thinking_tokens`: 262)

## File integrity check

md5sums of the three protected files, before and after this work:

| File | Before | After |
|---|---|---|
| `intake/queue.json` | `a5c80a2c54867e1502d425f868dfe744` | `a5c80a2c54867e1502d425f868dfe744` |
| `intake/review_2026-08-29.xlsx` | `006cc41f68e89e33eadead46f5468354` | `006cc41f68e89e33eadead46f5468354` |
| `images/sheets/pending_q0001.jpg` | `70eb4a25af0e7ac76302513c847127e7` | `70eb4a25af0e7ac76302513c847127e7` |

All three unchanged.
