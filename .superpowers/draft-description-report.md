# Claude-drafted Description text for the intake pipeline

## What was built

1. **`intake_extract.extract_blurb(soup)`** — a new `(text, source)` extractor
   for the page's own descriptive text, tried in order: JSON-LD `description`,
   `og:description`, Amazon's `#feature-bullets` (joined with `; `), Shopify's
   `.product__description` / `[itemprop=description]`, then
   `meta[name=description]`. Capped at `MAX_BLURB_CHARS` (1200). Added `blurb`
   and `blurb_source` to `Facts`, wired into `extract()`, and threaded through
   `intake_queue.new_row()` into the queue row schema.

2. **`intake_draft.py`** (new module) — `draft_description(row) -> (description, note)`.
   Calls `claude-opus-5` with `output_config={"effort": "low"}`, `max_tokens=512`,
   structured outputs (`output_config.format`, a `json_schema` object with
   `description`/`grounded`/`reason`), no `budget_tokens`, no prefill. System
   prompt states every claim must be grounded in the supplied page text, that
   an empty description is the correct answer when the text is too thin, and
   gives the four house-voice examples verbatim as few-shot exemplars.
   `grounded: false` → empty description + the model's reason as the note.
   Exceptions are caught most-specific-first: `NotFoundError`, `RateLimitError`,
   `APIStatusError`, `APIConnectionError` — never a bare `except`. `stop_reason
   == "refusal"` is checked before `response.content` is read. A missing/unreadable
   `ANTHROPIC_API_KEY` (read from `~/Documents/obsidian-pkm/.env`, same parsing
   as `intake_watch.credentials()`) also degrades to an empty description with
   an explanatory note, never an exception.

   **Environment fix folded in:** the `scrape` venv's `httpx2` 2.12.0 calls its
   brotli decoder with a brotlicffi-only kwarg (`output_buffer_limit`) that the
   installed system `Brotli` 1.1.0 package's `process()` doesn't accept, so
   every real call was failing as an opaque `APIConnectionError` regardless of
   the code above. Fixed by declining brotli on this one request
   (`extra_headers={"Accept-Encoding": "gzip"}`) rather than touching any
   installed package — confirmed by a raw `client.messages.create` call before
   and after (see "Live check" below).

3. **`intake_watch.process_message`** — calls `intake_draft.draft_description`
   after classification, storing `description_draft` / `draft_note` on the row,
   and skips the call entirely (leaving both fields `""`) when `fetch_status`
   is `BLOCKED`, `DEAD`, or `NO_URL`, or when there is no `blurb`.

4. **`intake_sheet.py`** — `Description`'s column now pre-fills from
   `description_draft`. Two new evidence columns: `Page blurb` (key `blurb`,
   hides itself when empty like the others) and `Description source`
   (computed at write time: `"drafted"` when `description_draft` is non-empty,
   blank otherwise — the cell it describes was *just* written from that same
   value a few lines above, so no separate comparison is needed at write time).
   Info tab step 3 now explains the draft, `Description source`, and
   `Page blurb`.

5. **`intake_apply.py`** — `main()` now compares each ACCEPT row's `Description`
   cell against its queue row's stored `description_draft` (byte-for-byte,
   before any stripping) and prints `"<qid> kept the drafted description
   verbatim"` for every match, without refusing anything.

## Tests (all new; every one fails before its corresponding code and passes after)

- `tests/test_intake_extract.py`: `test_blurb_prefers_json_ld_description_over_everything_else`,
  `test_blurb_falls_back_to_og_description`,
  `test_blurb_falls_back_to_amazon_feature_bullets_over_the_meta_description`
  (fixture copied verbatim from the real cached Amazon page),
  `test_blurb_falls_back_to_shopify_product_description`,
  `test_blurb_falls_back_to_an_itemprop_description`,
  `test_blurb_falls_back_to_meta_description_last`,
  `test_blurb_is_empty_with_an_empty_source_when_the_page_has_nothing`,
  `test_blurb_is_capped_at_about_twelve_hundred_characters`.
- `tests/test_intake_draft.py` (new file, 15 tests): no-blurb short-circuit,
  grounded response returned verbatim, ungrounded → empty + reason, grounded
  but empty text, unparsable JSON, refusal (with and without content),
  missing/unreadable API key, `RateLimitError`, `APIStatusError`,
  `APIConnectionError`, `NotFoundError`, the key never leaking into the note,
  and the request shape (model, `max_tokens`, `effort`, no `budget_tokens`, no
  assistant-role message, the `Accept-Encoding` header). All stub the client;
  none touch the network.
- `tests/test_intake_watch.py`: a row with a blurb gets the draft; a row with
  no blurb never calls the drafter; a `BLOCKED` fetch never calls the drafter
  even if a blurb is present; a `NO_URL` row carries blank draft fields.
- `tests/test_intake_sheet.py`: Description cell pre-fill, `Description
  source` says `"drafted"` when present and blank when absent, `Page blurb`
  carries the scraped text and hides itself when every row is blank, Info tab
  mentions the draft and the `Page blurb` column.
- `tests/test_intake_apply.py`: verbatim-draft notice printed for an untouched
  ACCEPT row, silent once the draft is edited, silent when there was never a
  draft.

Full suite: **309 passed** (273 pre-existing + 36 new), run via
`/home/simon/.venvs/scrape/bin/python -m pytest -q`.

## Live check — the one real API call

Built a row directly from the real cached page
(`images/htmlcache/4320dd132363d87fdba8576371bed36ced85e73f.html`, the
`https://www.amazon.com/dp/B07MXKZJDP` coin-pouch entry), via
`extract_title`/`extract_price`/`extract_ngo`/`extract_blurb` — no network
fetch needed, the HTML was already cached — then called
`intake_draft.draft_description(row)` for real, using the real
`ANTHROPIC_API_KEY` from `~/Documents/obsidian-pkm/.env`.

**Result: the call reached the API (after the `Accept-Encoding` fix above) and
came back `400 invalid_request_error: "Your credit balance is too low to
access the Anthropic API."`** `draft_description` handled this exactly as
designed — caught by the `APIStatusError` branch, returning `("", "drafting
skipped: API error (400)")`, row left staged, nothing raised.

**No draft text and no cost to report**: a 400 before any generation begins is
not billed, so token counts and cost are both zero for this call. I did not
fabricate a drafted description or a cost figure to satisfy the report format
— the account behind that key currently has no usable credit balance, which
is outside what this task can fix. Topping up
https://console.anthropic.com/settings/billing and re-running the same
snippet (reproduced below) would complete the live check:

```python
from bs4 import BeautifulSoup
import intake_extract, intake_draft
html = open("images/htmlcache/4320dd132363d87fdba8576371bed36ced85e73f.html",
            encoding="utf-8", errors="replace").read()
soup = BeautifulSoup(html, "lxml")
row = dict(queue_id="LIVE-CHECK",
           title=intake_extract.extract_title(soup),
           blurb=intake_extract.extract_blurb(soup)[0],
           blurb_source=intake_extract.extract_blurb(soup)[1],
           ngo_text=intake_extract.extract_ngo(soup.get_text(" ")),
           fetch_status="OK")
print(intake_draft.draft_description(row))
```

The extracted blurb itself (source: `amazon`) is grounded and specific:
"HIDE & DRINK'S: ... HANDMADE FROM SOFT & ATTRACTIVE FULL GRAIN LEATHER: ...
FINELY HAND STITCHED: ... artisans of Pastores, Guatemala ... MAKES A GREAT
GIFT: ..." — exactly the worked example the task described, confirming
`extract_blurb`'s ordering picks the real facts over Amazon's `meta[name=description]`
boilerplate ("Buy Hide & Drink ... FREE DELIVERY").

## Protected files — md5 before and after

| File | Before | After | Match |
|---|---|---|---|
| `intake/queue.json` | `a5c80a2c54867e1502d425f868dfe744` | `a5c80a2c54867e1502d425f868dfe744` | OK |
| `intake/review_2026-08-29.xlsx` | `006cc41f68e89e33eadead46f5468354` | `006cc41f68e89e33eadead46f5468354` | OK |
| `images/sheets/pending_q0001.jpg` | `70eb4a25af0e7ac76302513c847127e7` | `70eb4a25af0e7ac76302513c847127e7` | OK |

All three untouched. No subagents were dispatched. `intake_apply.main()` was
never run against real data (`isolated_apply` tmp-path fixtures and a
throwaway `images/htmlcache/...` read only, both read-only against real
project files); no `systemctl`, mailbox login, email, or `git push`.
