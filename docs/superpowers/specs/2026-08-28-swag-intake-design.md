# Shark swag intake: design

Date: 2026-08-28
Status: approved in brainstorming, awaiting spec review

## Purpose

Let a new gift suggestion enter the shark-swag pipeline by emailing a link to
`simondedman+sharkswag@gmail.com`. The system scrapes what it can prove from
the product page, guesses a category, harvests candidate images, and parks the
result in a review workbook. Nothing reaches the shared Google Doc without
Simon accepting it.

## Decisions taken

| Question | Decision |
|---|---|
| Autonomy | Staging queue. Every submission waits for explicit acceptance. |
| Submitters | Simon only. Messages carry a link plus optional freeform notes. |
| Drafting | Scrape verifiable facts; Simon writes the description prose. No LLM. |
| Images | Harvest candidates and build a per-item contact sheet; Simon picks. |
| Trigger | IMAP IDLE push, with a catch-up scan and a 6-hourly reconciliation sweep. |
| Output | Local `.docx` and `items.json`. No Google Docs API, no new OAuth token. |

Rejected: Gmail API `users.watch` with Pub/Sub. It needs a Cloud project, a new
`gmail.readonly` scope, a public HTTPS endpoint this machine does not have (or
a local long-poll process, which is a daemon anyway), and re-registration every
seven days. IMAP IDLE reaches the same latency using the app password already
in `~/Documents/obsidian-pkm/.env`.

## Scope

In scope: mail watching, URL and note parsing, duplicate detection, fact
extraction, keyword categorisation, image candidate harvesting, review
workbook generation, and applying accepted rows back into `items.json` and the
docx.

Out of scope: writing to the shared Google Doc; LLM-written descriptions;
public submissions from strangers; any change to how the docx is laid out.

## Phase 0: stabilise entry identity (prerequisite)

Entry identity is currently positional. `picks.py` keys `PICKS` on the 1-based
index into flattened `items.json` order with the four `EXISTING` doc entries
appended, and `images/final/eNN_n.jpg` is named from that index. Inserting an
accepted item anywhere but the very end renumbers every later entry, so their
picks and image files silently pair with the wrong entries. This is the failure
that already cost one full round of picks when `images/pool/` went stale.

Fix, before any intake code runs:

1. Add an `id` field to every item in `items.json`, assigned in current
   positional order as `f"e{n:02d}"` for n starting at 1. The four `EXISTING`
   entries in `build_docx.py` take `e85` to `e88`. This reproduces the existing
   `images/final/` filenames exactly, so no file is renamed.
2. Re-key `PICKS` in `picks.py` from integers to those id strings, and derive
   output filenames from the id rather than the loop index.
3. Change `add_images.py` to pair doc paragraphs with images by id, resolving
   the id from the item name it already matches on, rather than by building a
   positional `names` list.
4. Move `PICKS` out of `picks.py`'s source into `images/picks.json`, keyed by
   id, with `picks.py` reading it. A pick must be addable by writing data, not
   by editing a Python literal from another script. The inline comments in the
   current `PICKS` move to a `note` field per entry so they are not lost.
5. New items are assigned the next unused id at accept time. Ids are never
   reused, never renumbered, and carry no meaning beyond identity.

Verification: after the migration, rebuilding the docx must produce byte-identical
image placement to the current `shark-swag-suggestions.docx`, checked by comparing
the ordered list of (entry name, image filenames) pairs before and after. A
mismatch anywhere means the migration is wrong, not the checker.

## Architecture

```
Gmail (+sharkswag alias)
  -> filter applies label "sharkswag", skips inbox
       -> intake_watch.py   systemd user service, IMAP IDLE
            -> intake_parse.py     message -> URLs + note + sender
            -> intake_extract.py   URL -> facts, images, fetch status
            -> intake/queue.json   pending rows
       -> intake_sheet.py   queue -> review_YYYY-MM-DD.xlsx + contact sheets
            (Simon edits the workbook)
       -> intake_apply.py   workbook -> items.json, images/final/, docx
```

Each stage reads a file and writes a file, so any stage can be rerun alone and
tested from fixtures without mail or network access.

## Components

### `intake_watch.py`
Holds an IMAP connection (IMAPClient) to `imap.gmail.com`, selects the
`sharkswag` folder, and IDLEs. Re-arms IDLE every 15 minutes because Gmail
drops an idle connection at around 29. On every start, and every 6 hours, it
lists the folder in full and stages anything whose `Message-ID` is absent from
`intake/ledger.json`. Touches `intake/heartbeat` after each successful cycle.

Depends on: `intake_parse`, `intake_extract`, the ledger, the queue.
Does not depend on: openpyxl, docx, images.

Messages are never marked `\Seen` and never moved. Reading the mail on a phone
must not change what the daemon does.

### `intake_parse.py`
Message bytes to a `Submission`: sender display name, date, `Message-ID`, the
list of URLs found in both the `text/plain` and `text/html` parts including
forwarded bodies, and the residual note text with quoted forward headers and
signatures stripped. URLs are normalised for comparison: lowercase host, strip
`utm_*`, `fbclid`, `gclid`, `ref`, drop a trailing slash, drop the fragment.
The original URL is kept verbatim for the entry; only the normalised form is
used for matching.

A message with no URL is staged anyway, with status `NO_URL`, so it is visible
rather than silently dropped.

### `intake_extract.py`
Per URL, reusing `harvest.py`'s fetcher and its `images/htmlcache/` cache:

- fetch outcome, one of `OK`, `BLOCKED` (403, 429, 503, or a challenge page),
  `DEAD` (404, or a redirect to a site root as `padigear.com` now does), or
  `EMPTY` (200 with nothing extractable). `BLOCKED` and `EMPTY` are different
  states and are never collapsed into "no data".
- title: JSON-LD `name`, then `og:title`, then `<title>`.
- price: JSON-LD `offers.price` with currency, then Shopify
  `/products/<handle>.json` variants, then `itemprop="price"` meta. Recorded
  with which source produced it.
- NGO wording: sentences matching `donat|proceeds|% of|charity|conservation|
  non-?profit|foundation`, captured verbatim, never paraphrased. Absence gives
  an empty cell, not a claim that the item has no charity link.
- image candidates: the existing candidate extractor, kept on the queue row
  itself rather than appended to `images/candidates.json`. The submission has
  no entry id until it is accepted, and `candidates.json` is keyed by entry, so
  there is nothing yet to file them under; they move into the pipeline's own
  files when the row is applied.

Only responses with status 200 are written to the HTML cache, so a transient
block never becomes permanent.

### `intake_sheet.py`
Builds `intake/review_YYYY-MM-DD.xlsx` from the queue, and a contact sheet per
item at `images/sheets/pending_<id>.jpg` with visible candidate indices, using
`pool.py`'s ranking and download path. `images/pool/` entries for a pending id
are cleared before the run, because stale index-keyed files are what made the
sheets lie last time.

Workbook layout follows the house rules: an Info tab ordered first, header row
frozen, bold, and autofiltered on every tab.

Info tab covers: why the workbook exists, that scraping and image harvesting
already happened, what each column means, numbered instructions for what to
fill in, the daemon's last successful poll time from the heartbeat, and counts
of rows by fetch status.

Review tab columns, editable first:

| Column | Notes |
|---|---|
| Status | blank, `ACCEPT`, `REJECT`, or `HOLD`. Blank is treated as `HOLD`. |
| Section | pre-filled with the guess, blank if no rule fired |
| Subsection | as above |
| Item | scraped title, editable |
| Age | pre-filled from the age rules |
| Link | the original URL |
| Price | scraped, prefixed `~` to match house style |
| Description | blank, wrapped, for Simon's prose |
| Suggested by | sender display name |
| NGO | the verbatim charity sentence, or blank |
| Image pick | candidate indices, comma separated, matching the contact sheet |

Evidence columns, read-only, to the right: fetch status, price source, section
guess keyword, duplicate-of id, message date, and a short `=HYPERLINK` to the
contact sheet. Empty evidence columns are hidden rather than shown blank.

### `intake_apply.py`
Takes a workbook path, defaulting to the newest `intake/review_*.xlsx` by
filename date. For each row:

- `ACCEPT`: assign the next unused id, insert into `items.json` under the named
  section and subsection, write the chosen candidates as `P:` specs into
  `picks.py`'s store, render to `images/final/<id>_n.jpg`, then rerun
  `build_docx.py` and `add_images.py`.
- `REJECT`: append the normalised URL to `intake/rejected.json`, so it is
  flagged instead of re-queued if it arrives again.
- `HOLD` or blank: leave in the queue for the next workbook.

Refuses to run if any `ACCEPT` row has an empty Section, Subsection, Item, or
Description, listing the offending rows rather than guessing.

## Data formats

`intake/ledger.json`: `{message_id: {"seen": iso8601, "urls": [...]}}`. Keyed on
`Message-ID` because IMAP UIDs reset when `UIDVALIDITY` changes.

`intake/queue.json`: a list of pending rows, each carrying its own extraction
results and provenance. Survives between workbook builds.

`intake/rejected.json`: a list of normalised URLs with the date and reason.

## Categorisation rules

Keyword matching over title plus note, first match wins, evaluated in this
order so that a book about equipment does not land in Equipment:

1. Books: `book|isbn|paperback|hardcover|picture book|author|publisher`
2. NGO merch: host matches a known NGO domain list
3. Equipment: `mask|snorkel|fins|wetsuit|rash guard|swim|net|binocular|microscope`
4. Arts and stationery: `sticker|colouring|coloring|craft|pencil|stationery|poster|print`
5. Toys and games: `plush|soft toy|figure|puzzle|lego|game|playset|figurine`
6. Clothing: `tee|t-shirt|shirt|onesie|bodysuit|sock|hoodie|hat|cap|necklace|bracelet|earring`
7. Wildcard: `adopt|adoption|experience|advent|subscription|gift card`

Age band: `baby|toddler|infant|onesie|bodysuit|newborn` gives Baby & Toddler;
`kid|child|junior` gives Kids; `youth|teen|junior sizes` gives Youth; anything
else in a clothing or book section gives Adult.

Section 4 is sub-headed by kind, not age, so it uses its own rules:
`mask|snorkel|fin` gives Mask, snorkel & fins sets; `rash|wetsuit|swim|suit`
gives Rash guards, wetsuits & swim gear; `net|bucket|rockpool|beach|tide`
gives Beach & rockpooling kit; `kit|microscope|experiment|stem|science` gives
Science & STEM kits; `binocular|camera|torch|light|watch|tech` gives Optics &
tech. An age band is still recorded in the Age column where it matters, per the
section's own note in `items.json`.

No match leaves the cell blank. The matched keyword is written to the evidence
column so a wrong guess is traceable to its rule rather than to a black box.

## Error handling

- A blocked fetch is reported as blocked. Coverage, not just results, is
  recorded per row, so a throttle can never read as "this product has no price".
- Only 200s are cached.
- The daemon is `Restart=always` under systemd; systemd owns liveness. Process
  liveness is never checked with `pgrep -f`, which matches the searcher in this
  harness.
- A silently deaf IDLE socket is caught by the 6-hourly reconciliation sweep,
  and its last-success time is printed on the Info tab of a workbook Simon is
  already reading.
- New staged items raise a `notify-send` and append to `intake/intake.log`.
  Failures are logged with their status and counted on the Info tab, never
  filtered out of it.

## Setup, one-off and manual

1. `pip install --user IMAPClient` (Python 3.13's `imaplib` has no IDLE).
   Record it in `~/.claude/INSTALLS-CATALOGUE.md`.
2. In the Gmail UI, create a filter `to:simondedman+sharkswag@gmail.com` that
   applies label `sharkswag` and skips the inbox.
3. `systemctl --user enable --now shark-swag-intake.service`.

Credentials are read from `~/Documents/obsidian-pkm/.env`
(`GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`). No secret is copied into this project.

## Testing

Fixture-driven, no network and no mailbox in the test run.

- Parser: a bare URL, a forwarded Shopify link, a link plus a note, a message
  with several links, a message with none, and an HTML-only message.
- Extractor: saved HTML for a Shopify product, a JSON-LD product, a page with
  charity wording, a 403 challenge page, and a 404.
- Categoriser: one case per rule, plus a deliberately ambiguous title that must
  come out blank rather than guessed.
- Apply: a workbook with one of each status, and a workbook with an `ACCEPT`
  row missing its description, which must refuse.
- Positive control on dedupe: a fixture whose URL is already in `items.json`
  must come out flagged `DUPLICATE`. If this passes while real duplicates slip
  through, the matcher is looking at the wrong field.
- Migration control for phase 0: the (entry name, image filenames) pairing must
  be identical before and after the id migration.

`--dry-run` on the watcher prints parsed rows and touches neither the ledger nor
the queue.
