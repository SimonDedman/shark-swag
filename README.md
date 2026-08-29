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

## Design notes

`docs/superpowers/specs/` carries the design documents, including the planned
email intake system for onboarding new suggestions.

## Caches

`images/raw`, `images/htmlcache`, `images/pool`, and `images/sheets` are
gitignored and regenerable, at the cost of re-fetching every source. Some
sources have since gone dead, so `images/final/` is the durable copy of the
chosen images.
