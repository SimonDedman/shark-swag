# shark-swag

Tooling behind a shark-themed gift guide: a curated list of items for babies
through adults, weighted towards products whose proceeds reach marine
conservation NGOs. `items.json` is the source of truth; everything else builds
a Word document from it, illustrated with product images harvested from each
retailer.

## Pipeline

Run in this order:

| Script | Does |
|---|---|
| `build_docx.py` | `items.json` to `shark-swag-suggestions.docx`, text only |
| `harvest.py` | fetches each entry's URL, extracts candidate image URLs |
| `supplement.py` | extra sources for shops whose product grid is JS-rendered |
| `pool.py` | ranks and downloads candidates, builds contact sheets |
| `picks.py` | renders the chosen image per entry to `images/final/` |
| `add_images.py` | edits the docx in place, inserting an image row per entry |
| `verify_sheet.py` | contact sheets of the final picks, for a last look |

`imgproc.py` holds the shared download, autocrop, and resize helpers.

## Adding a suggestion

Email a product link to `simondedman+sharkswag@gmail.com`, with any notes in
the body. A systemd user service (`shark-swag-intake.service`) watches the
`sharkswag` Gmail label over IMAP IDLE and stages the submission within
seconds: it fetches the page, reads off the title, price, and any sentence
about donations, guesses a section and age band from keywords (left blank when
no rule matches, so a blank section is a question rather than an omission), and
downloads candidate product images.

Nothing reaches `items.json` until it is reviewed:

    ~/.venvs/scrape/bin/python intake_sheet.py    # queue -> intake/review_<date>.xlsx
    # fill in the Description, correct the guesses, set Status, save
    ~/.venvs/scrape/bin/python intake_apply.py    # accepted rows -> items.json + docx

The Info tab of each workbook explains the columns and the fetch statuses. A
blocked fetch is reported as blocked, never as an absent price.

Service state:

    systemctl --user status shark-swag-intake.service
    journalctl --user -u shark-swag-intake.service -f
    cat intake/heartbeat        # last successful poll

## Design notes

`docs/superpowers/specs/` carries the design documents, including the planned
email intake system for onboarding new suggestions.

## Caches

`images/raw`, `images/htmlcache`, `images/pool`, and `images/sheets` are
gitignored and regenerable, at the cost of re-fetching every source. Some
sources have since gone dead, so `images/final/` is the durable copy of the
chosen images.
