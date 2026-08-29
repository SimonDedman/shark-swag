# Shark Swag Email Intake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a gift suggestion emailed to `simondedman+sharkswag@gmail.com` be scraped, categorised, illustrated with candidate images, and staged in a review workbook that Simon accepts row by row into `items.json` and the docx.

**Architecture:** An IMAP IDLE daemon watches a Gmail label and pushes each new message through parse, extract, and classify stages into a JSON queue. A workbook builder turns the queue into an xlsx with contact sheets; an apply stage reads the reviewed workbook back and rebuilds the document. Every stage reads a file and writes a file, so each is testable from fixtures with no mail and no network.

**Tech Stack:** Python 3.13, IMAPClient (IMAP IDLE), curl_cffi (fetching, already used by `harvest.py`), BeautifulSoup + lxml, openpyxl, python-docx, Pillow, pytest.

**Spec:** `docs/superpowers/specs/2026-08-28-swag-intake-design.md`

## Global Constraints

- **Interpreter is `/home/simon/.venvs/scrape/bin/python`.** `curl_cffi` is installed there, not in system Python, and `harvest.py` and `imgproc.py` both import it. Every `python` and `pytest` command in this plan uses that interpreter. The venv is built with `--system-site-packages`, so `pip install --user` packages are visible to it.
- **One new dependency, installed user-wide:** `pip install --user IMAPClient`. Python 3.13's `imaplib` has no IDLE support. Record the install in `~/.claude/INSTALLS-CATALOGUE.md`.
- **Project root is `/media/simon/data/Projects/shark-swag`.** `~/Projects/shark-swag` is the same directory; `build_docx.py` currently uses the second spelling. All new code imports `ROOT` from `paths.py` and never hardcodes either.
- **Entry ids are immutable.** Once assigned, an id is never renumbered or reused. Image filenames and `images/picks.json` keys derive from ids.
- **Fetch status vocabulary is exactly `OK`, `BLOCKED`, `DEAD`, `EMPTY`.** A block and an empty result are different states and must never be collapsed into one. Only HTTP 200 responses are cached.
- **Row status vocabulary is exactly `ACCEPT`, `REJECT`, `HOLD`.** An empty Status cell is treated as `HOLD`.
- **No credential is copied into this repository.** `GMAIL_ADDRESS` and `GMAIL_APP_PASSWORD` are read at runtime from `~/Documents/obsidian-pkm/.env`. No secret is ever printed to a log or a workbook.
- **Review workbooks:** Info tab ordered first, header row frozen, bold, and autofiltered on every tab. This is a house rule and applies however small the workbook is.
- **Process liveness is never checked with `pgrep -f`.** In this harness the pattern matches the searching command itself. systemd owns the daemon's liveness; the heartbeat file reports its progress.
- **User-facing prose is British English** with Oxford commas, in the workbook Info tab, the README, and log messages.

## File Structure

**New, identity and shared paths:**

| File | Responsibility |
|---|---|
| `paths.py` | Every filesystem location in one place. No logic. |
| `entries.py` | Load `items.json` and `existing.json`, flatten to `Entry` records with stable ids, allocate the next id, write `items.json` back in its existing one-item-per-line format. |
| `existing.json` | The four entries already in the shared Google Doc, moved out of `build_docx.py`'s inline `EXISTING` dict so they have exactly one home. |
| `images/picks.json` | The chosen image specs per entry id, moved out of `picks.py`'s inline `PICKS` dict so a pick can be added by writing data. |
| `migrate_ids.py` | One-off: stamp ids onto `items.json`. Idempotent, refuses to renumber. |

**New, intake pipeline:**

| File | Responsibility |
|---|---|
| `intake_parse.py` | Raw message bytes to a `Submission`: sender, date, URLs, residual note. URL normalisation for matching. |
| `intake_extract.py` | A URL to a `Facts` record: fetch status, title, price with provenance, verbatim charity sentence, image candidates. |
| `intake_classify.py` | Title, note, and host to a `Guess`: section, subsection, age band, and the keyword that fired. |
| `intake_queue.py` | The ledger of processed messages, the pending queue, the rejected list, and duplicate detection against `items.json`. |
| `intake_watch.py` | The daemon: IMAP IDLE, catch-up scan, reconciliation sweep, heartbeat. |
| `intake_sheet.py` | Queue to review workbook plus a per-item contact sheet. |
| `intake_apply.py` | Reviewed workbook back into `items.json`, `images/picks.json`, `images/final/`, and the docx. |
| `shark-swag-intake.service` | systemd user unit. |

**Modified:** `build_docx.py` (reads `existing.json`), `harvest.py` (uses `entries.iter_entries()`, gains `fetch_full`), `pool.py` (pools keyed by id), `picks.py` (reads `images/picks.json`), `add_images.py` (pairs by id).

**Tests:** `tests/conftest.py`, one `tests/test_<module>.py` per module, fixtures under `tests/fixtures/`.

---

### Task 1: Stable entry identity

Gives every entry an id stored in the data, so inserting a new item never renumbers an existing one. Ids are assigned in the current file order, which reproduces the existing `images/final/eNN_n.jpg` filenames exactly, so no image is renamed.

**Files:**
- Create: `paths.py`, `entries.py`, `existing.json`, `migrate_ids.py`, `tests/conftest.py`, `tests/test_entries.py`
- Modify: `items.json` (data migration), `build_docx.py:19-46` (inline `EXISTING` dict removed), `build_docx.py:157` (`EXISTING.get` call site)

**Interfaces:**
- Consumes: nothing.
- Produces: `paths.ROOT`, `paths.ITEMS`, `paths.EXISTING_JSON`, `paths.IMAGES`, `paths.FINAL`, `paths.POOL_DIR`, `paths.SHEETS`, `paths.PICKS_JSON`, `paths.INTAKE`, `paths.LEDGER`, `paths.QUEUE`, `paths.REJECTED`, `paths.HEARTBEAT`, `paths.HTMLCACHE`; `entries.Entry` (dataclass: `id, section, sub, item, link, age, price, desc, by, ngo, existing`), `entries.load_items() -> dict`, `entries.save_items(dict) -> None`, `entries.load_existing() -> list[dict]`, `entries.iter_entries(data=None, include_existing=True) -> list[Entry]`, `entries.id_num(str) -> int`, `entries.next_id(data=None) -> str`, `entries.entry_by_id(str) -> Entry | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/conftest.py`:

```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

Create `tests/test_entries.py`:

```python
import json
import re

import entries
from paths import ITEMS


def test_every_item_has_a_well_formed_id():
    data = entries.load_items()
    for section in data["sections"]:
        for sub in section["subsections"]:
            for item in sub["items"]:
                assert re.fullmatch(r"e\d{2,}", item["id"]), item


def test_ids_are_unique_across_items_and_existing():
    ids = [e.id for e in entries.iter_entries()]
    assert len(ids) == len(set(ids))


def test_ids_follow_the_original_positional_order():
    """The first 84 items are e01..e84 and the four doc entries are e85..e88,
    which is the numbering picks.py used positionally. Anything else would
    orphan the files already in images/final/."""
    ids = [e.id for e in entries.iter_entries()]
    assert ids[:3] == ["e01", "e02", "e03"]
    assert ids == [f"e{n:02d}" for n in range(1, len(ids) + 1)]


def test_existing_entries_are_flagged_and_come_last():
    all_entries = entries.iter_entries()
    existing = [e for e in all_entries if e.existing]
    assert [e.id for e in existing] == ["e85", "e86", "e87", "e88"]
    assert existing[0].item.startswith("SPHYRNAS")
    assert existing[0].section == "1"
    assert existing[0].sub == "Adult"


def test_next_id_continues_past_the_highest():
    assert entries.next_id() == "e89"


def test_next_id_ignores_gaps_and_never_reuses():
    data = entries.load_items()
    data["sections"][0]["subsections"][0]["items"][0]["id"] = "e99"
    assert entries.next_id(data) == "e100"


def test_entry_by_id_round_trips():
    assert entries.entry_by_id("e01").id == "e01"
    assert entries.entry_by_id("e85").existing is True
    assert entries.entry_by_id("e999") is None


def test_save_items_is_byte_stable():
    before = ITEMS.read_bytes()
    entries.save_items(entries.load_items())
    assert ITEMS.read_bytes() == before


def test_save_items_keeps_one_item_per_line():
    text = ITEMS.read_text()
    assert '"item":' in text
    for line in text.splitlines():
        assert line.count('"item":') <= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_entries.py -v`
Expected: FAIL, collection error `ModuleNotFoundError: No module named 'entries'`.

- [ ] **Step 3: Create `paths.py`**

```python
#!/usr/bin/env python3
"""Every filesystem location the shark-swag pipeline uses, in one place.

`~/Projects/shark-swag` and `/media/simon/data/Projects/shark-swag` are the same
directory; the second spelling is canonical here so two modules can never
disagree about whether a cache entry already exists.
"""
from pathlib import Path

ROOT = Path("/media/simon/data/Projects/shark-swag")

ITEMS = ROOT / "items.json"
EXISTING_JSON = ROOT / "existing.json"
DOCX = ROOT / "shark-swag-suggestions.docx"

IMAGES = ROOT / "images"
RAW = IMAGES / "raw"
FINAL = IMAGES / "final"
POOL_DIR = IMAGES / "pool"
SHEETS = IMAGES / "sheets"
HTMLCACHE = IMAGES / "htmlcache"
CANDIDATES = IMAGES / "candidates.json"
EXTRAS = IMAGES / "extras.json"
POOL_JSON = IMAGES / "pool.json"
PICKS_JSON = IMAGES / "picks.json"

INTAKE = ROOT / "intake"
LEDGER = INTAKE / "ledger.json"
QUEUE = INTAKE / "queue.json"
REJECTED = INTAKE / "rejected.json"
HEARTBEAT = INTAKE / "heartbeat"
INTAKE_LOG = INTAKE / "intake.log"

ENV_FILE = Path.home() / "Documents" / "obsidian-pkm" / ".env"

for _d in (IMAGES, FINAL, INTAKE):
    _d.mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 4: Create `existing.json`**

The four entries lifted verbatim from `build_docx.py`'s `EXISTING` dict, in the order `harvest.py` appended them, which is the order that produced `images/final/e85`-`e88`.

```json
[
  {
    "id": "e85",
    "section": "1",
    "sub": "Adult",
    "item": "SPHYRNAS — tees, hoodies, hats, accessories",
    "age": "Youth / Adult",
    "link": "https://www.sphyrnas.com/products",
    "price": "$30-70",
    "desc": "Great quality, small business, socially conscious, amazing people behind it!",
    "by": "Jenny Bortoluzzi",
    "ngo": "Some collections support specific orgs, in the past have included MISS for example."
  },
  {
    "id": "e86",
    "section": "3",
    "sub": "Kids",
    "item": "Sharks Preschool Activity Book",
    "age": "Kids",
    "link": "https://a.co/d/0aaGljoi",
    "price": "$11.99 USD",
    "desc": "Preschoolers will have fun sinking their teeth into shark exploration: tracing numbers and ABCs, matching, mazes and spot-the-difference, plus what scientists wear underwater to study sharks.",
    "by": "Chelsea Black (also the author)",
    "ngo": ""
  },
  {
    "id": "e87",
    "section": "3",
    "sub": "Adult",
    "item": "Underwater Photography and Editing Ebooks",
    "age": "Adult",
    "link": "https://www.gillianshark.com/ebooks",
    "price": "AUD 59 (beginner), AUD 65 (advanced), AUD 99 (bundle)",
    "desc": "Master underwater photography: from your first photo to your final edit.",
    "by": "Gillian Shark",
    "ngo": "Gillian Shark (my own business)"
  },
  {
    "id": "e88",
    "section": "5",
    "sub": "Kids",
    "item": "Colouring & Facts Book (currently only available as PDF)",
    "age": "Kids / Youth / Adult",
    "link": "https://www.gillianshark.com/colouring-book",
    "price": "AUD 14",
    "desc": "10 sharks to colour in and learn 3 facts per shark!",
    "by": "Gillian Shark",
    "ngo": "Gillian Shark (my own business)"
  }
]
```

Verify it matches what is currently in the code, rather than trusting the transcription:

Run: `~/.venvs/scrape/bin/python -c "
import json, build_docx
from pathlib import Path
disk = {e['item']: e for e in json.loads(Path('existing.json').read_text())}
n = 0
for (sec, sub), items in build_docx.EXISTING.items():
    for e in items:
        d = disk[e['item']]
        assert (d['section'], d['sub']) == (sec, sub), e['item']
        for k in ('age', 'link', 'price', 'desc', 'by', 'ngo'):
            assert d[k] == e.get(k, ''), (e['item'], k)
        n += 1
print(n, 'existing entries match the code they were copied from')
"`
Expected: `4 existing entries match the code they were copied from`

- [ ] **Step 5: Create `entries.py`**

```python
#!/usr/bin/env python3
"""Stable entry identity for the shark-swag pipeline.

Every entry carries an `id` stored in the data: in items.json for researched
entries, in existing.json for the four that were already in the shared Google
Doc. Ids are assigned once, when an entry joins the list, and are never
renumbered or reused. Image filenames in images/final/ and the keys of
images/picks.json derive from them, so a renumber would silently pair every
later entry with the wrong picture.
"""
import copy
import json
import re
from dataclasses import dataclass

from paths import ITEMS, EXISTING_JSON

ID_RE = re.compile(r"^e(\d{2,})$")


@dataclass
class Entry:
    id: str
    section: str
    sub: str
    item: str
    link: str
    age: str = ""
    price: str = ""
    desc: str = ""
    by: str = ""
    ngo: str = ""
    existing: bool = False


def load_items():
    return json.loads(ITEMS.read_text())


def save_items(data):
    """Write items.json keeping one item object per line, as the file already is.

    json.dumps(indent=2) would explode every item across eight lines and turn a
    one-item change into an unreadable diff.
    """
    d = copy.deepcopy(data)
    blobs = []
    for section in d["sections"]:
        for sub in section["subsections"]:
            for i, item in enumerate(sub["items"]):
                blobs.append(json.dumps(item, ensure_ascii=False))
                sub["items"][i] = f"\x00{len(blobs) - 1}\x00"
    text = json.dumps(d, indent=2, ensure_ascii=False)
    for n, blob in enumerate(blobs):
        text = text.replace(json.dumps(f"\x00{n}\x00"), blob)
    ITEMS.write_text(text + "\n")


def load_existing():
    return json.loads(EXISTING_JSON.read_text())


def iter_entries(data=None, include_existing=True):
    data = data if data is not None else load_items()
    out = []
    for section in data["sections"]:
        for sub in section["subsections"]:
            for item in sub["items"]:
                out.append(Entry(
                    id=item["id"], section=section["number"], sub=sub["name"],
                    item=item["item"], link=item["link"], age=item.get("age", ""),
                    price=item.get("price", ""), desc=item.get("desc", ""),
                    by=item.get("by", "Simon Dedman (web search)"),
                    ngo=item.get("ngo", "")))
    if include_existing:
        for e in load_existing():
            out.append(Entry(
                id=e["id"], section=e["section"], sub=e["sub"], item=e["item"],
                link=e["link"], age=e.get("age", ""), price=e.get("price", ""),
                desc=e.get("desc", ""), by=e.get("by", ""), ngo=e.get("ngo", ""),
                existing=True))
    return out


def id_num(entry_id):
    m = ID_RE.match(entry_id)
    if not m:
        raise ValueError(f"malformed entry id: {entry_id!r}")
    return int(m.group(1))


def next_id(data=None):
    highest = max(id_num(e.id) for e in iter_entries(data))
    return f"e{highest + 1:02d}"


def entry_by_id(entry_id, data=None):
    for e in iter_entries(data):
        if e.id == entry_id:
            return e
    return None
```

- [ ] **Step 6: Create `migrate_ids.py` and run it once**

```python
#!/usr/bin/env python3
"""One-off: stamp a stable id onto every item in items.json.

Ids are assigned in the file's current order as e01, e02, ..., which is exactly
the numbering picks.py used positionally, so the existing images/final/eNN_n.jpg
filenames stay correct and no image is renamed. Refuses to renumber anything
that already carries an id.
"""
import json

from paths import ITEMS
import entries


def main():
    data = json.loads(ITEMS.read_text())
    already = [it["id"] for s in data["sections"] for sub in s["subsections"]
               for it in sub["items"] if "id" in it]
    if already:
        print(f"already migrated: {len(already)} items carry an id, nothing to do")
        return
    n = 0
    for section in data["sections"]:
        for sub in section["subsections"]:
            for i, item in enumerate(sub["items"]):
                n += 1
                sub["items"][i] = {"id": f"e{n:02d}", **item}
    entries.save_items(data)
    print(f"{n} items stamped e01..e{n:02d}")


if __name__ == "__main__":
    main()
```

Run: `~/.venvs/scrape/bin/python migrate_ids.py`
Expected: `84 items stamped e01..e84`

Run it a second time to prove it is idempotent: `~/.venvs/scrape/bin/python migrate_ids.py`
Expected: `already migrated: 84 items carry an id, nothing to do`

- [ ] **Step 7: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_entries.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 8: Point `build_docx.py` at `existing.json`**

Delete the inline `EXISTING` dict at `build_docx.py:19-46`. Replace the `ROOT` definition and add the loader:

```python
from paths import ROOT, DOCX
import entries

# Entries already present in the Google Doc, reproduced in place so coverage is
# visible. They live in existing.json so entries.py and build_docx.py cannot
# disagree about them.
EXISTING = {}
for _e in entries.load_existing():
    EXISTING.setdefault((_e["section"], _e["sub"]), []).append(_e)
```

Change the save at the end of `main()` from `out = ROOT / "shark-swag-suggestions.docx"` to `out = DOCX`.

- [ ] **Step 9: Verify the document is unchanged by the refactor**

Run: `~/.venvs/scrape/bin/python -c "
import hashlib, shutil
from paths import DOCX
before = hashlib.sha1(DOCX.read_bytes()).hexdigest()
shutil.copy(DOCX, 'images/docx-before.docx')
print('saved current docx, sha1', before[:12])
"`
Expected: a sha1 prefix printed.

Run: `~/.venvs/scrape/bin/python build_docx.py`
Expected: `84 new entries + 4 existing -> /media/simon/data/Projects/shark-swag/shark-swag-suggestions.docx`

Compare the text of the rebuild against the pre-refactor copy. The bytes will differ (the images have been stripped by the rebuild, and docx zips are not reproducible), so compare the paragraph text instead:

Run: `~/.venvs/scrape/bin/python -c "
import docx
a = [p.text for p in docx.Document('images/docx-before.docx').paragraphs]
b = [p.text for p in docx.Document('shark-swag-suggestions.docx').paragraphs]
a = [t for t in a if t.strip()]
b = [t for t in b if t.strip()]
assert a == b, [(x, y) for x, y in zip(a, b) if x != y][:3]
print(len(b), 'paragraphs identical to the pre-refactor document')
"`
Expected: `... paragraphs identical to the pre-refactor document`

Note the rebuilt docx has lost its images; Task 4 restores them with `add_images.py`. Do not hand this document to anyone until Task 4 is done.

- [ ] **Step 10: Commit**

```bash
git add paths.py entries.py existing.json migrate_ids.py items.json build_docx.py tests/
git commit -m "Give every entry a stable id stored in the data

Entry identity was positional: picks.py keyed on the index into flattened
items.json order and images/final/eNN_n.jpg was named from it, so inserting
an item anywhere but the end repaired every later entry with the wrong
image. Ids are assigned in the current order, so existing filenames are
unchanged and nothing is renamed.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Key the image pools by id

`pool.py` keys its pools by the positional index and names pool files `<index>_<n>.jpg`. Move both onto ids so a new entry cannot shift them.

**Files:**
- Modify: `harvest.py:143-170` (`main`), `pool.py:36-77` (`build_pools`), `pool.py:80-118` (`fetch_pool`), `pool.py:121-160` (`sheets`)
- Test: `tests/test_pool_keys.py`

**Interfaces:**
- Consumes: `entries.iter_entries`, `paths.CANDIDATES`, `paths.POOL_JSON`, `paths.EXTRAS`.
- Produces: `images/pool.json` keyed by entry id (`"e15"`, not `"15"`); pool files named `images/pool/e15_00.jpg`; `pool.build_pools() -> dict[str, dict]` unchanged in shape apart from the keys.

- [ ] **Step 1: Write the failing test**

Create `tests/test_pool_keys.py`:

```python
import json
import re

import pool
from paths import POOL_JSON


def test_build_pools_keys_on_entry_id():
    pools = pool.build_pools()
    for key in pools:
        assert re.fullmatch(r"e\d{2,}", key), key
    assert "e01" in pools
    assert "e88" in pools


def test_pool_entries_carry_their_item_and_link():
    pools = pool.build_pools()
    assert pools["e85"]["item"].startswith("SPHYRNAS")
    assert pools["e85"]["link"] == "https://www.sphyrnas.com/products"


def test_written_pool_json_matches_returned_pools():
    pools = pool.build_pools()
    assert json.loads(POOL_JSON.read_text()).keys() == pools.keys()


def test_extras_are_still_prepended_by_id():
    """extras.json is keyed by the old positional index; the migration must
    carry it across or the supplemented shops lose their catalogue images."""
    pools = pool.build_pools()
    extras = json.loads((POOL_JSON.parent / "extras.json").read_text())
    for key in extras:
        assert key.startswith("e"), f"extras.json key {key!r} was not migrated"
        assert pools[key]["cands"][0]["score"] == 999
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_pool_keys.py -v`
Expected: FAIL, `assert re.fullmatch(r"e\d{2,}", "1")` is None.

- [ ] **Step 3: Migrate `extras.json` keys**

Run: `~/.venvs/scrape/bin/python -c "
import json
from paths import EXTRAS
d = json.loads(EXTRAS.read_text())
if all(k.startswith('e') for k in d):
    print('already migrated')
else:
    out = {f'e{int(k):02d}': v for k, v in d.items()}
    EXTRAS.write_text(json.dumps(out, indent=1))
    print(f'{len(out)} extras keys migrated:', sorted(out))
"`
Expected: a list of `eNN` keys.

- [ ] **Step 4: Rewrite `pool.build_pools` to key on id**

Replace the body of `build_pools` in `pool.py`:

```python
def build_pools():
    """Rank each entry's candidates, keyed by the entry's stable id.

    Candidate URLs come from candidates.json, which is keyed by product URL, so
    entry order in that file is irrelevant here.
    """
    d = json.loads(CANDIDATES.read_text())
    extras = json.loads(EXTRAS.read_text()) if EXTRAS.exists() else {}
    pools = {}
    for e in iter_entries():
        v = d["per_url"][e.link]
        words = set(re.findall(r"[a-z]{4,}", e.item.lower()))
        cands, seen = [], set()
        # supplementary sources first: they are catalogue products, not page furniture
        for c in extras.get(e.id, []):
            u = clean(c["url"])
            if u.split("?")[0] in seen:
                continue
            seen.add(u.split("?")[0])
            cands.append(dict(url=u, title=c.get("title", ""), src=c["src"], score=999))
        for c in v["candidates"]:
            u = clean(c["url"])
            if BAD.search(u):
                continue
            k = u.split("?")[0]
            if k in seen:
                continue
            seen.add(k)
            cands.append(dict(url=u, title=c.get("title", ""), src=c["src"],
                              score=score(c, words)))
        cands.sort(key=lambda c: -c["score"])
        pools[e.id] = dict(item=e.item, link=e.link, section=e.section,
                           sub=e.sub, cands=cands[:24])
    POOL_JSON.write_text(json.dumps(pools, indent=1))
    return pools
```

Replace `pool.py`'s path constants and imports at the top:

```python
from paths import POOL_DIR, SHEETS, CANDIDATES, EXTRAS, POOL_JSON, ROOT
from entries import iter_entries
```

Delete the now-unused `ROOT`, `POOLDIR`, and `SHEETS` definitions in `pool.py` and rename every use of `POOLDIR` to `POOL_DIR`.

In `sheets()`, change the key ordering from `sorted(pools, key=int)` to `sorted(pools, key=lambda k: int(k[1:]))`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_pool_keys.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 6: Point `harvest.py` at `entries.py`**

Replace the entry-building block in `harvest.main()` (the loop over `data["sections"]` and the hardcoded four-tuple list) with:

```python
    from entries import iter_entries
    entries_ = iter_entries()
    entries = [dict(id=e.id, section=e.section, sub=e.sub, item=e.item, link=e.link)
               for e in entries_]
```

The four already-in-doc entries now come from `existing.json`, so the hardcoded list of their titles and links is deleted. Replace `harvest.py`'s `ROOT`, `CACHE`, and `OUT` constants with `from paths import ROOT, HTMLCACHE as CACHE, CANDIDATES as OUT, ITEMS`.

- [ ] **Step 7: Verify harvest still enumerates the same 88 entries and the same URLs**

This must not re-fetch anything; every page is already in the HTML cache.

Run: `~/.venvs/scrape/bin/python -c "
import json
from entries import iter_entries
from paths import CANDIDATES
old = json.loads(CANDIDATES.read_text())
new = [e.link for e in iter_entries()]
assert len(new) == 88, len(new)
assert [e['link'] for e in old['entries']] == new, 'entry order changed'
missing = [u for u in set(new) if u not in old['per_url']]
assert not missing, missing
print('88 entries, order and URLs identical to candidates.json')
"`
Expected: `88 entries, order and URLs identical to candidates.json`

- [ ] **Step 8: Commit**

```bash
git add pool.py harvest.py images/extras.json images/pool.json tests/test_pool_keys.py
git commit -m "Key image pools on entry id rather than list position

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Move picks out of source and onto ids

`PICKS` is a dict literal in `picks.py`. `intake_apply.py` must be able to record a chosen image by writing data, not by editing another script's source.

**Files:**
- Create: `images/picks.json`, `migrate_picks.py`, `tests/test_picks.py`
- Modify: `picks.py:29-148` (the `PICKS` literal and its module constants), `picks.py:150-160` (`resolve`), `picks.py:163-186` (`main`)

**Interfaces:**
- Consumes: `paths.PICKS_JSON`, `paths.POOL_JSON`, `entries.iter_entries`.
- Produces: `picks.load_picks() -> dict[str, dict]` where each value is `{"specs": [str], "note": str}`; `picks.save_picks(dict) -> None`; `picks.resolve(spec) -> (url, referer, crop)`; `picks.render(entry_id, specs) -> list[str]` returning the filenames written.

- [ ] **Step 1: Write the failing test**

Create `tests/test_picks.py`:

```python
import json
import re

import picks
from paths import PICKS_JSON, FINAL


def test_picks_json_is_keyed_by_entry_id():
    data = picks.load_picks()
    for key in data:
        assert re.fullmatch(r"e\d{2,}", key), key


def test_every_entry_has_a_picks_record():
    import entries
    ids = {e.id for e in entries.iter_entries()}
    assert set(picks.load_picks()) == ids


def test_pool_specs_reference_ids_not_positions():
    for key, rec in picks.load_picks().items():
        for spec in rec["specs"]:
            if spec.startswith("P:"):
                assert re.match(r"P:e\d{2,}_\d{2}", spec), (key, spec)


def test_notes_survived_the_migration():
    data = picks.load_picks()
    assert "JS-only" in data["e02"]["note"]
    assert "JS-only" in data["e14"]["note"]
    assert "wrong title" in data["e42"]["note"]


def test_deliberately_empty_entries_are_still_empty():
    """Three storefronts render client-side and have no usable image. An empty
    spec list means 'looked, found nothing', and must not become 'not looked at'."""
    data = picks.load_picks()
    assert data["e02"]["specs"] == []
    assert data["e14"]["specs"] == []
    assert data["e66"]["specs"] == []


def test_resolve_pool_spec_returns_a_url_and_referer():
    url, referer, crop = picks.resolve("P:e01_00")
    assert url.startswith("http")
    assert referer.startswith("http")
    assert crop is None


def test_resolve_direct_spec_passes_the_url_through():
    url, referer, crop = picks.resolve("U:https://example.com/a.jpg")
    assert url == "https://example.com/a.jpg"
    assert referer is None


def test_resolve_parses_a_crop():
    url, referer, crop = picks.resolve("P:e16_00|crop=0,0.44,1,1")
    assert crop == [0.0, 0.44, 1.0, 1.0]


def test_rendered_filenames_match_what_is_on_disk():
    """e16 has one pick, so images/final/e16_0.jpg exists and e16_1.jpg does not."""
    assert (FINAL / "e16_0.jpg").exists()
    assert not (FINAL / "e16_1.jpg").exists()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_picks.py -v`
Expected: FAIL, `AttributeError: module 'picks' has no attribute 'load_picks'`.

- [ ] **Step 3: Write `migrate_picks.py` and run it once**

```python
#!/usr/bin/env python3
"""One-off: move picks.PICKS out of source and into images/picks.json, keyed by
entry id. Pool specs "P:15_01" become "P:e15_01"; the inline comments in the
source become a `note` field so the reasoning is not lost.
"""
import json
import re

import picks
from paths import PICKS_JSON
from entries import iter_entries

# The comments that sit beside individual entries in the current PICKS literal.
NOTES = {
    2: "PADI Gear storefront is JS-only",
    3: "first hit on the shop search; it is the octopus bodysuit, not a shark print",
    14: "Wix storefront is JS-only",
    42: "Amazon /images/P/<isbn> returns the wrong title for this one",
    66: "Wix storefront is JS-only",
}


def migrate_spec(spec):
    return re.sub(r"^P:(\d+)_", lambda m: f"P:e{int(m.group(1)):02d}_", spec)


def main():
    if PICKS_JSON.exists():
        print("images/picks.json already exists, nothing to do")
        return
    ids = {int(e.id[1:]): e.id for e in iter_entries()}
    out = {}
    for n, specs in sorted(picks.PICKS.items()):
        out[ids[n]] = dict(specs=[migrate_spec(s) for s in specs], note=NOTES.get(n, ""))
    missing = [e.id for e in iter_entries() if e.id not in out]
    for eid in missing:
        out[eid] = dict(specs=[], note="no pick recorded")
    PICKS_JSON.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(out)} entries written to {PICKS_JSON}"
          f" ({len(missing)} had no PICKS entry)")


if __name__ == "__main__":
    main()
```

Run: `~/.venvs/scrape/bin/python migrate_picks.py`
Expected: `88 entries written to /media/simon/data/Projects/shark-swag/images/picks.json (0 had no PICKS entry)`

- [ ] **Step 4: Rewrite `picks.py` to read the JSON**

Delete the `PICKS` literal and the `S4K_BOOKS`, `MISS_TEE`, `CDN`, and `O31` constants that only existed to shorten it; the URLs are now expanded in the JSON. Keep `resolve`, and replace the module header and `main`:

```python
#!/usr/bin/env python3
"""Render the chosen image per entry at the size the docx embeds.

Specs live in images/picks.json, keyed by entry id: "P:<pool_key>" reuses a
pool candidate, "U:<url>" is a source the pool missed, and an optional
"|crop=l,t,r,b" gives fractional crop bounds applied before the automatic
padding trim. An empty spec list means the entry was looked at and has no
usable image, which is not the same as an entry nobody has reached yet.
"""
import json
import sys

from PIL import Image

from paths import PICKS_JSON, POOL_JSON, FINAL
from imgproc import download, load, autocrop, to_height, TARGET_H

POOL = json.loads(POOL_JSON.read_text())


def load_picks():
    return json.loads(PICKS_JSON.read_text())


def save_picks(data):
    PICKS_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def resolve(spec):
    body, _, opts = spec.partition("|")
    crop = None
    for o in opts.split("|"):
        if o.startswith("crop="):
            crop = [float(x) for x in o[5:].split(",")]
    kind, _, val = body.partition(":")
    if kind == "P":
        k, j = val.rsplit("_", 1)
        return POOL[k]["cands"][int(j)]["url"], POOL[k]["link"], crop
    return val, None, crop


def render(entry_id, specs):
    """Write images/final/<entry_id>_<n>.jpg for each spec. Returns the names
    written; a spec that could not be fetched is skipped and reported."""
    written, failures = [], []
    for n, spec in enumerate(specs):
        url, referer, crop = resolve(spec)
        p, note = download(url, referer=referer)
        if p is None:
            failures.append((entry_id, n, note, url))
            continue
        im = load(p)
        if crop:
            w, h = im.size
            im = im.crop((int(crop[0] * w), int(crop[1] * h),
                          int(crop[2] * w), int(crop[3] * h)))
        im, _ = autocrop(im)
        im = to_height(im, TARGET_H)
        name = f"{entry_id}_{n}.jpg"
        im.save(FINAL / name, "JPEG", quality=92, subsampling=0)
        written.append(name)
    return written, failures


def main(only=None):
    picks = load_picks()
    written, failures = [], []
    for entry_id, rec in sorted(picks.items()):
        if only and entry_id not in only:
            continue
        w, f = render(entry_id, rec["specs"])
        written += w
        failures += f
    print(f"{len(written)} images written, {len(failures)} failed")
    for f in failures:
        print("   ", f)
    empty = [k for k, v in picks.items() if not v["specs"]]
    print("entries deliberately without an image:", empty)


if __name__ == "__main__":
    main(only=set(sys.argv[1:]) or None)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_picks.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 6: Prove the specs still resolve to the same URLs as before**

This is the control on the spec rewrite: it re-resolves every migrated spec and compares against what the old integer-keyed form resolved to. It touches no network.

Run: `~/.venvs/scrape/bin/python -c "
import json, re
import picks
from paths import POOL_JSON
pool = json.loads(POOL_JSON.read_text())
data = picks.load_picks()
n = 0
for eid, rec in data.items():
    for spec in rec['specs']:
        url, ref, crop = picks.resolve(spec)
        assert url.startswith('http'), (eid, spec, url)
        n += 1
print(n, 'specs resolve to a URL')
"`
Expected: a count near 155, with no assertion error.

- [ ] **Step 7: Commit**

```bash
git add picks.py images/picks.json migrate_picks.py tests/test_picks.py
git commit -m "Move image picks from a source literal into images/picks.json

A pick must be addable by writing data, so intake_apply.py never edits
another script's source.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Pair document images by id, and prove the rebuild is unchanged

`add_images.py` finds an entry's images by rebuilding the positional name list. This is the last place a renumber could bite.

**Files:**
- Modify: `add_images.py:14-24` (imports and constants), `add_images.py:30-46` (`entry_key`, `build_order`), `add_images.py:76-95` (name matching and file glob)
- Test: `tests/test_add_images.py`

**Interfaces:**
- Consumes: `entries.iter_entries`, `paths.FINAL`, `paths.DOCX`.
- Produces: `add_images.name_to_ids() -> dict[str, list[str]]`, `add_images.images_for(entry_id) -> list[Path]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_add_images.py`:

```python
from pathlib import Path

import add_images
import entries
from paths import FINAL


def test_name_to_ids_covers_every_entry():
    mapping = add_images.name_to_ids()
    all_ids = {e.id for e in entries.iter_entries()}
    flat = {i for ids in mapping.values() for i in ids}
    assert flat == all_ids


def test_duplicate_item_names_keep_both_ids_in_order():
    """Two entries can share a name (the same book listed for two age bands);
    the mapping must hand them out in id order, not collapse them."""
    mapping = add_images.name_to_ids()
    for name, ids in mapping.items():
        assert ids == sorted(ids, key=lambda i: int(i[1:])), name


def test_images_for_globs_on_the_id():
    files = add_images.images_for("e01")
    assert files == [FINAL / "e01_0.jpg"]


def test_images_for_returns_empty_when_the_entry_has_none():
    assert add_images.images_for("e02") == []


def test_id_pairing_matches_the_old_positional_pairing():
    """The migration control. The old code paired the Nth entry name with
    images/final/eNN_*.jpg; the new code pairs by stored id. If Task 1 assigned
    ids in any other order, this fails and the ids are wrong, not this test."""
    old = {}
    for n, e in enumerate(entries.iter_entries(), 1):
        old.setdefault(e.item, []).append(sorted(FINAL.glob(f"e{n:02d}_*.jpg")))
    new = {}
    for e in entries.iter_entries():
        new.setdefault(e.item, []).append(add_images.images_for(e.id))
    assert old == new
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_add_images.py -v`
Expected: FAIL, `AttributeError: module 'add_images' has no attribute 'name_to_ids'`.

- [ ] **Step 3: Rewrite the pairing in `add_images.py`**

Replace the `ROOT`, `FIN`, and `DOC` constants with `from paths import FINAL, DOCX`, and rename their uses. Delete `entry_key` and `build_order`, and add:

```python
def name_to_ids():
    """Item name to the ids that carry it, in id order.

    The docx is matched by name because that is what the heading line holds,
    but the images are found by id, so inserting an entry cannot shift them.
    """
    mapping = {}
    for e in sorted(iter_entries(), key=lambda e: int(e.id[1:])):
        mapping.setdefault(e.item, []).append(e.id)
    return mapping


def images_for(entry_id):
    return sorted(FINAL.glob(f"{entry_id}_*.jpg"))
```

In `main()`, replace `names = build_order()` with `mapping = name_to_ids()`, delete the `name_to_idx` block, and change the per-entry lookup to:

```python
        cands = [i for i in mapping.get(nm, []) if i not in used]
        if not cands:
            missing.append(nm)
            continue
        entry_id = cands[0]
        used.add(entry_id)

        files = images_for(entry_id)
```

Add `from entries import iter_entries` to the imports.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_add_images.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Rebuild the document end to end**

Run: `~/.venvs/scrape/bin/python build_docx.py && ~/.venvs/scrape/bin/python add_images.py`
Expected: `84 new entries + 4 existing -> ...` then `88 entry headings promoted to Heading 3` and `NN image rows inserted`, with no unmatched entry names.

- [ ] **Step 6: Verify the rebuilt document against the pre-refactor copy**

`images/docx-before.docx` was saved in Task 1 Step 9, before any of this changed. This compares the image row under each entry heading, which is the pairing the whole migration exists to preserve.

Run: `~/.venvs/scrape/bin/python -c "
import docx
from collections import Counter

def rows(path):
    d = docx.Document(path)
    out, current = {}, None
    for p in d.paragraphs:
        if p.text.startswith(chr(9656) + ' ') or p.style.name == 'Heading 3':
            current = p.text.lstrip(chr(9656) + ' ').strip()
            out.setdefault(current, 0)
        n = len(p._p.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline'))
        if n and current:
            out[current] += n
    return out

a, b = rows('images/docx-before.docx'), rows('shark-swag-suggestions.docx')
diff = {k: (a.get(k), b.get(k)) for k in set(a) | set(b) if a.get(k) != b.get(k)}
assert not diff, diff
print(len(b), 'entries, image counts identical to the pre-migration document')
"`
Expected: `88 entries, image counts identical to the pre-migration document`

If this fails, the ids are wrong. Do not paper over it by adjusting the checker.

- [ ] **Step 7: Commit**

```bash
git add add_images.py tests/test_add_images.py
git commit -m "Pair document images by entry id

Closes the last positional dependency: an inserted entry can no longer
shift another entry's images.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Parse a submission out of a message

**Files:**
- Create: `intake_parse.py`, `tests/fixtures/make_mail.py`, `tests/test_intake_parse.py`
- Test: `tests/test_intake_parse.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `intake_parse.Submission` (dataclass: `message_id: str, sender: str, date: str, subject: str, urls: list[str], note: str`), `intake_parse.normalise_url(str) -> str`, `intake_parse.parse_message(bytes) -> Submission`, `intake_parse.extract_urls(str) -> list[str]`.

- [ ] **Step 1: Write the fixture builder**

Create `tests/fixtures/make_mail.py`:

```python
#!/usr/bin/env python3
"""Write the .eml fixtures used by tests/test_intake_parse.py."""
from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent / "mail"
HERE.mkdir(exist_ok=True)


def msg(mid, subject, body, html=None):
    m = EmailMessage()
    m["From"] = "Simon Dedman <simondedman@gmail.com>"
    m["To"] = "simondedman+sharkswag@gmail.com"
    m["Subject"] = subject
    m["Date"] = "Thu, 28 Aug 2026 09:14:02 -0700"
    m["Message-ID"] = f"<{mid}@mail.gmail.com>"
    m.set_content(body)
    if html:
        m.add_alternative(html, subtype="html")
    return m


CASES = {
    "bare_url": msg("bare1", "", "https://luckybugclothing.com/products/shark-onesie\n"),
    "link_plus_note": msg(
        "note1", "shark socks",
        "These are great, my nephew has a pair and the proceeds go somewhere useful.\n"
        "https://www.barekind.co.uk/products/shark-socks?utm_source=newsletter&utm_medium=email\n"
        "-- \nSimon\n"),
    "multi_url": msg(
        "multi1", "three of them",
        "https://example.com/a\nhttps://example.com/b\nand https://example.com/c.\n"),
    "no_url": msg("none1", "idea", "Something about a shark advent calendar, I will find it later.\n"),
    "forwarded": msg(
        "fwd1", "Fwd: Your order",
        "---------- Forwarded message ---------\n"
        "From: Shark Trust <shop@sharktrust.org>\n"
        "Date: Wed, 27 Aug 2026 at 11:02\n"
        "Subject: New in the shop\n"
        "To: <simondedman@gmail.com>\n"
        "\n"
        "> New organic cotton tees are in stock now.\n"
        "https://www.sharktrustclothing.com/products/oceanic-31-tee\n"
        "\n"
        "Worth a look for the Youth band.\n"),
    "html_only": msg(
        "html1", "link", "",
        "<html><body><p>This one is lovely.</p>"
        "<a href='https://shop.sheddaquarium.org/products/plush-shark'>plush shark</a>"
        "</body></html>"),
}

if __name__ == "__main__":
    for name, m in CASES.items():
        (HERE / f"{name}.eml").write_bytes(bytes(m))
    print(f"{len(CASES)} fixtures written to {HERE}")
```

Run: `~/.venvs/scrape/bin/python tests/fixtures/make_mail.py`
Expected: `6 fixtures written to /media/simon/data/Projects/shark-swag/tests/fixtures/mail`

- [ ] **Step 2: Write the failing test**

Create `tests/test_intake_parse.py`:

```python
from pathlib import Path

import pytest

import intake_parse

MAIL = Path(__file__).resolve().parent / "fixtures" / "mail"


def load(name):
    return intake_parse.parse_message((MAIL / f"{name}.eml").read_bytes())


def test_bare_url_yields_one_url_and_an_empty_note():
    s = load("bare_url")
    assert s.urls == ["https://luckybugclothing.com/products/shark-onesie"]
    assert s.note == ""


def test_sender_and_date_are_captured():
    s = load("bare_url")
    assert s.sender == "Simon Dedman"
    assert s.date.startswith("2026-08-28T09:14:02")
    assert s.message_id == "bare1@mail.gmail.com"


def test_note_keeps_prose_and_drops_the_url_and_signature():
    s = load("link_plus_note")
    assert "proceeds go somewhere useful" in s.note
    assert "http" not in s.note
    assert "-- " not in s.note


def test_several_urls_are_kept_in_order_and_trailing_punctuation_stripped():
    s = load("multi_url")
    assert s.urls == ["https://example.com/a", "https://example.com/b",
                      "https://example.com/c"]


def test_a_message_with_no_url_still_parses():
    s = load("no_url")
    assert s.urls == []
    assert "advent calendar" in s.note


def test_forwarded_headers_and_quotes_are_stripped_from_the_note():
    s = load("forwarded")
    assert s.urls == ["https://www.sharktrustclothing.com/products/oceanic-31-tee"]
    assert "Forwarded message" not in s.note
    assert "shop@sharktrust.org" not in s.note
    assert "New organic cotton tees" not in s.note
    assert "Worth a look for the Youth band." in s.note


def test_html_only_message_yields_the_href():
    s = load("html_only")
    assert s.urls == ["https://shop.sheddaquarium.org/products/plush-shark"]
    assert "This one is lovely" in s.note


@pytest.mark.parametrize("raw,expected", [
    ("https://WWW.Example.COM/Products/Shark/",
     "https://example.com/Products/Shark"),
    ("https://example.com/p?utm_source=x&utm_medium=y",
     "https://example.com/p"),
    ("https://example.com/p?variant=4471#reviews",
     "https://example.com/p?variant=4471"),
    ("http://example.com/p?fbclid=abc&colour=blue",
     "http://example.com/p?colour=blue"),
])
def test_normalise_url(raw, expected):
    assert intake_parse.normalise_url(raw) == expected


def test_normalise_url_keeps_the_product_variant():
    """A Shopify variant is part of the identity of the thing being suggested;
    dropping it would merge two genuinely different items."""
    a = intake_parse.normalise_url("https://shop.com/p?variant=1")
    b = intake_parse.normalise_url("https://shop.com/p?variant=2")
    assert a != b
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_parse.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_parse'`.

- [ ] **Step 4: Write `intake_parse.py`**

```python
#!/usr/bin/env python3
"""Turn a raw email into a Submission: who sent it, what they linked, and what
they said about it.

Normalised URLs exist only for matching. The original URL is what goes into the
entry, because a shop's canonical link is the one a reader should follow.
"""
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+")
TRAILING = ".,;:!?’”"

TRACK_PREFIXES = ("utm_", "mc_", "_branch", "pk_")
TRACK_EXACT = {"fbclid", "gclid", "igsh", "ref", "ref_", "si", "source", "mkt_tok",
               "gad_source", "srsltid"}

FORWARD_LINE = re.compile(
    r"^\s*(>|-{2,}\s*Forwarded message|From:|To:|Cc:|Sent:|Date:|Subject:|"
    r"On .*wrote:)", re.I)


@dataclass
class Submission:
    message_id: str
    sender: str
    date: str
    subject: str
    urls: list = field(default_factory=list)
    note: str = ""


def normalise_url(url):
    """A comparison key, not a link. Lowercases the host, drops www, drops the
    fragment and tracking parameters, and strips a trailing slash."""
    p = urlsplit(url.strip())
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not (k.lower().startswith(TRACK_PREFIXES) or k.lower() in TRACK_EXACT)]
    path = p.path.rstrip("/")
    return urlunsplit((p.scheme.lower(), host, path, urlencode(query), ""))


def extract_urls(text):
    out, seen = [], set()
    for m in URL_RE.finditer(text or ""):
        u = m.group(0).rstrip(TRAILING)
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _bodies(msg):
    """Return (plain_text, html) with either possibly empty."""
    plain, html = "", ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            if part.get_content_disposition() == "attachment":
                continue
            ctype = part.get_content_type()
            try:
                payload = part.get_content()
            except Exception:
                continue
            if ctype == "text/plain":
                plain += payload
            elif ctype == "text/html":
                html += payload
    else:
        payload = msg.get_content()
        if msg.get_content_type() == "text/html":
            html = payload
        else:
            plain = payload
    return plain, html


def _note_from(text, urls):
    """Prose only: no URLs, no forwarded headers, no quoted lines, no signature."""
    lines = []
    for line in (text or "").splitlines():
        if line.strip() in ("--", "-- "):
            break
        if FORWARD_LINE.match(line):
            continue
        for u in urls:
            line = line.replace(u, "")
        if line.strip():
            lines.append(line.strip())
    return " ".join(lines).strip()


def parse_message(raw):
    msg = message_from_bytes(raw, policy=policy.default)
    plain, html = _bodies(msg)

    urls = extract_urls(plain)
    html_text = ""
    if html:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith("http") and href not in urls:
                urls.append(href)
        html_text = soup.get_text("\n")
        urls += [u for u in extract_urls(html_text) if u not in urls]

    note = _note_from(plain, urls) or _note_from(html_text, urls)

    name, addr = parseaddr(msg.get("From", ""))
    try:
        date = parsedate_to_datetime(msg.get("Date", "")).isoformat()
    except Exception:
        date = ""
    return Submission(
        message_id=(msg.get("Message-ID", "") or "").strip("<> \t"),
        sender=name or addr,
        date=date,
        subject=(msg.get("Subject", "") or "").strip(),
        urls=urls,
        note=note,
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_parse.py -v`
Expected: PASS, 13 passed.

- [ ] **Step 6: Commit**

```bash
git add intake_parse.py tests/test_intake_parse.py tests/fixtures/make_mail.py tests/fixtures/mail/
git commit -m "Parse a swag submission out of an email

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Extract facts from a product page

**Files:**
- Create: `intake_extract.py`, `tests/fixtures/pages/`, `tests/test_intake_extract.py`
- Modify: `harvest.py:29-42` (`fetch` gains a `fetch_full` sibling that also returns the final URL)

**Interfaces:**
- Consumes: `harvest.fetch_full`, `harvest.harvest`.
- Produces: `intake_extract.Facts` (dataclass: `url, status, http, title, price, price_source, ngo_text, note, candidates`), `intake_extract.classify_status(http, text, requested, final) -> str`, `intake_extract.extract_title(soup) -> str`, `intake_extract.extract_price(soup, url) -> tuple[str, str]`, `intake_extract.extract_ngo(text) -> str`, `intake_extract.extract(url) -> Facts`.

- [ ] **Step 1: Write the page fixtures**

Create `tests/fixtures/pages/jsonld_product.html`:

```html
<html><head><title>Lemon shark onesie | Lucky Bug</title>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Lemon Shark Onesie",
 "offers":{"@type":"Offer","price":"28.00","priceCurrency":"USD"}}
</script></head>
<body><p>10% of all lemon shark print sales go to Sharks4Kids. Made in New York.</p></body></html>
```

Create `tests/fixtures/pages/itemprop_product.html`:

```html
<html><head><title>Shark socks</title>
<meta itemprop="price" content="12.50"><meta itemprop="priceCurrency" content="GBP">
</head><body><p>Bamboo socks. No donation is made from this product.</p></body></html>
```

Create `tests/fixtures/pages/challenge.html`:

```html
<html><head><title>Just a moment...</title></head>
<body><div class="cf-browser-verification">Checking your browser before accessing.</div></body></html>
```

Create `tests/fixtures/pages/bare.html`:

```html
<html><head><title></title></head><body></body></html>
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_intake_extract.py`:

```python
from pathlib import Path

from bs4 import BeautifulSoup

import intake_extract

PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"


def soup(name):
    return BeautifulSoup((PAGES / name).read_text(), "lxml")


def test_title_prefers_json_ld_name():
    assert intake_extract.extract_title(soup("jsonld_product.html")) == "Lemon Shark Onesie"


def test_title_falls_back_to_the_title_tag():
    assert intake_extract.extract_title(soup("itemprop_product.html")) == "Shark socks"


def test_price_from_json_ld_is_formatted_in_house_style():
    price, source = intake_extract.extract_price(soup("jsonld_product.html"),
                                                 "https://example.com/p")
    assert price == "~$28"
    assert source == "json-ld"


def test_price_from_itemprop_uses_the_stated_currency():
    price, source = intake_extract.extract_price(soup("itemprop_product.html"),
                                                 "https://example.com/p")
    assert price == "~£12.50"
    assert source == "itemprop"


def test_missing_price_is_blank_with_a_blank_source():
    assert intake_extract.extract_price(soup("bare.html"), "https://e.com/p") == ("", "")


def test_ngo_sentence_is_captured_verbatim():
    text = soup("jsonld_product.html").get_text(" ")
    assert intake_extract.extract_ngo(text) == \
        "10% of all lemon shark print sales go to Sharks4Kids."


def test_a_stated_absence_of_donation_is_still_captured():
    """The doc's NGO line says so when a shop states no donation, rather than
    leaving a reader to assume either way."""
    text = soup("itemprop_product.html").get_text(" ")
    assert "No donation is made" in intake_extract.extract_ngo(text)


def test_no_charity_wording_gives_an_empty_string():
    assert intake_extract.extract_ngo("Bamboo socks in three sizes.") == ""


def test_challenge_page_is_blocked_not_empty():
    html = (PAGES / "challenge.html").read_text()
    assert intake_extract.classify_status(200, html, "https://e.com/p", "https://e.com/p") \
        == "BLOCKED"


def test_403_and_429_are_blocked():
    assert intake_extract.classify_status(403, None, "https://e.com/p", None) == "BLOCKED"
    assert intake_extract.classify_status(429, None, "https://e.com/p", None) == "BLOCKED"


def test_404_is_dead():
    assert intake_extract.classify_status(404, None, "https://e.com/p", None) == "DEAD"


def test_a_redirect_to_the_site_root_is_dead():
    """padigear.com does exactly this: the product URL 302s to a shop home page
    that no longer carries the catalogue."""
    assert intake_extract.classify_status(
        200, "<html><title>PADI</title></html>",
        "https://www.padigear.com/products/great-white-baby-onesie",
        "https://www.padi.com/shop-online") == "DEAD"


def test_a_page_with_nothing_extractable_is_empty():
    assert intake_extract.classify_status(
        200, (PAGES / "bare.html").read_text(),
        "https://e.com/p", "https://e.com/p") == "EMPTY"


def test_a_good_page_is_ok():
    assert intake_extract.classify_status(
        200, (PAGES / "jsonld_product.html").read_text(),
        "https://e.com/p", "https://e.com/p") == "OK"


def test_an_exception_is_blocked_never_empty():
    """A connection that never completed proves nothing about the page. Calling
    it EMPTY would turn a network fault into a finding about the product."""
    assert intake_extract.classify_status(None, None, "https://e.com/p", None) == "BLOCKED"
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_extract.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_extract'`.

- [ ] **Step 4: Add `fetch_full` to `harvest.py`**

Replace `harvest.fetch` with the pair, keeping the existing three-value signature so `fetch_json`, `scrape_html`, and `shopify_*` are untouched:

```python
def fetch_full(url, timeout=30):
    """Return (status, text_or_None, final_url, note). Cache 200s only.

    The final URL matters: a product page that 302s to a shop's front door is
    dead, and looks identical to a healthy 200 without it.
    """
    key = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html")
    if key.exists():
        return 200, key.read_text(errors="replace"), url, "cached"
    try:
        r = creq.get(url, impersonate=IMPERSONATE, timeout=timeout,
                     headers={"Accept-Language": "en-US,en;q=0.9"})
    except Exception as e:
        return None, None, None, f"exception: {type(e).__name__}: {e}"
    if r.status_code == 200:
        key.write_text(r.text, errors="replace")
        return 200, r.text, str(r.url), "fetched"
    return r.status_code, None, str(r.url), f"http {r.status_code}"


def fetch(url, timeout=30):
    """Return (status, text_or_None, note)."""
    status, text, _final, note = fetch_full(url, timeout)
    return status, text, note
```

- [ ] **Step 5: Write `intake_extract.py`**

```python
#!/usr/bin/env python3
"""Product page to the facts an entry needs, with each fact's provenance.

Nothing here infers or paraphrases. A price is the number the page states; the
NGO line is a sentence copied verbatim. A fetch that was blocked is reported as
blocked, never as an absence of information about the product, because those
two lead to opposite decisions.
"""
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

import harvest

CHALLENGE = re.compile(
    r"just a moment|cf-browser-verification|captcha|access denied|"
    r"unusual traffic|are you a robot|enable javascript and cookies", re.I)

NGO_SENTENCE = re.compile(
    r"[^.!?\n]*\b(?:donat\w*|proceeds|charitable|charity|conservation|"
    r"non-?profit|nonprofit|foundation|\d{1,3}\s?%\s+of)\b[^.!?\n]*[.!?]", re.I)

SYMBOL = {"USD": "$", "GBP": "£", "EUR": "€", "AUD": "AUD ", "CAD": "CAD "}


@dataclass
class Facts:
    url: str
    status: str = "EMPTY"
    http: int = None
    title: str = ""
    price: str = ""
    price_source: str = ""
    ngo_text: str = ""
    note: str = ""
    candidates: list = field(default_factory=list)


def _jsonld(soup):
    """Every JSON-LD node on the page, flattened."""
    out = []
    for tag in soup.find_all("script", type=re.compile(r"ld\+json", re.I)):
        try:
            blob = json.loads(tag.string or "{}")
        except Exception:
            continue
        stack = [blob]
        while stack:
            n = stack.pop()
            if isinstance(n, list):
                stack.extend(n)
            elif isinstance(n, dict):
                out.append(n)
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
    return out


def extract_title(soup):
    for node in _jsonld(soup):
        if node.get("@type") in ("Product", "Book") and node.get("name"):
            return str(node["name"]).strip()
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    return ""


def _format_price(amount, currency):
    try:
        value = float(str(amount).replace(",", ""))
    except (TypeError, ValueError):
        return ""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    sym = SYMBOL.get((currency or "USD").upper(), (currency or "").upper() + " ")
    return f"~{sym}{text}"


def extract_price(soup, url):
    """Returns (price, source). Source is one of json-ld, shopify, itemprop, ''."""
    for node in _jsonld(soup):
        offers = node.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict) and offers.get("price"):
            p = _format_price(offers["price"], offers.get("priceCurrency"))
            if p:
                return p, "json-ld"

    if "/products/" in urlsplit(url).path:
        data, _note = harvest.fetch_json(url.split("?")[0].rstrip("/") + ".json")
        variants = (data or {}).get("product", {}).get("variants") or []
        if variants and variants[0].get("price"):
            p = _format_price(variants[0]["price"], "USD")
            if p:
                return p, "shopify"

    meta = soup.find("meta", attrs={"itemprop": "price"})
    if meta and meta.get("content"):
        cur = soup.find("meta", attrs={"itemprop": "priceCurrency"})
        p = _format_price(meta["content"], cur.get("content") if cur else None)
        if p:
            return p, "itemprop"
    return "", ""


def extract_ngo(text):
    """The first sentence that talks about money going somewhere, verbatim.

    A statement that no donation is made is as useful as one that says there is,
    so both are kept.
    """
    m = NGO_SENTENCE.search(re.sub(r"\s+", " ", text or ""))
    return m.group(0).strip() if m else ""


def classify_status(http, text, requested, final):
    if http is None:
        return "BLOCKED"
    if http in (401, 403, 429, 503):
        return "BLOCKED"
    if http in (404, 410):
        return "DEAD"
    if http != 200:
        return "BLOCKED"
    if text and CHALLENGE.search(text[:4000]):
        return "BLOCKED"
    if final and urlsplit(requested).path.strip("/") and not urlsplit(final).path.strip("/"):
        return "DEAD"
    soup = BeautifulSoup(text or "", "lxml")
    if not extract_title(soup) and not extract_price(soup, requested)[0]:
        return "EMPTY"
    return "OK"


def extract(url):
    http, text, final, note = harvest.fetch_full(url)
    status = classify_status(http, text, url, final)
    facts = Facts(url=url, status=status, http=http, note=note)
    if status in ("BLOCKED", "DEAD"):
        return facts
    soup = BeautifulSoup(text or "", "lxml")
    facts.title = extract_title(soup)
    facts.price, facts.price_source = extract_price(soup, url)
    facts.ngo_text = extract_ngo(soup.get_text(" "))
    try:
        facts.candidates, cnote = harvest.harvest(url)
        facts.note = f"{note}; images: {cnote}"[:400]
    except Exception as e:
        facts.note = f"{note}; image harvest failed: {type(e).__name__}"
    return facts
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_extract.py -v`
Expected: PASS, 15 passed.

- [ ] **Step 7: Verify `harvest.py` still works after the `fetch` split**

Run: `~/.venvs/scrape/bin/python -m pytest tests/ -v`
Expected: PASS, every test from Tasks 1 to 6.

- [ ] **Step 8: Commit**

```bash
git add intake_extract.py harvest.py tests/test_intake_extract.py tests/fixtures/pages/
git commit -m "Extract product facts with provenance and an honest fetch status

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Guess the section, subsection, and age band

**Files:**
- Create: `intake_classify.py`, `tests/test_intake_classify.py`

**Interfaces:**
- Consumes: `entries.load_items`.
- Produces: `intake_classify.Guess` (dataclass: `section: str, sub: str, age: str, keyword: str`), `intake_classify.classify(title, note, url) -> Guess`, `intake_classify.ngo_hosts() -> dict[str, str]`, `intake_classify.valid_subs(section) -> list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_classify.py`:

```python
import intake_classify as ic


def g(title, note="", url="https://example.com/products/thing"):
    return ic.classify(title, note, url)


def test_a_book_goes_to_section_three_even_when_it_mentions_gear():
    r = g("Snorkelling with Sharks: a picture book for young readers")
    assert r.section == "3"
    assert "book" in r.keyword


def test_an_ngo_host_wins_over_the_product_words():
    r = g("Organic cotton tee", url="https://www.sharktrustclothing.com/products/tee")
    assert r.section == "6"
    assert r.keyword.startswith("host:")


def test_equipment_keywords():
    assert g("Junior mask and snorkel set").section == "4"


def test_arts_keywords():
    assert g("Shark sticker sheet and colouring pencils").section == "5"


def test_toy_keywords():
    assert g("Great white plush soft toy").section == "2"


def test_clothing_keywords():
    assert g("Hammerhead hoodie").section == "1"


def test_wildcard_keywords():
    assert g("Adopt a basking shark, annual subscription").section == "7"


def test_an_unmatched_title_leaves_everything_blank():
    """No rule firing must read as 'nobody has classified this', not as a
    silent default into whichever section happens to be first."""
    r = g("A thing")
    assert r.section == ""
    assert r.sub == ""
    assert r.keyword == ""


def test_age_bands():
    assert g("Shark bodysuit for newborns").age == "Baby & Toddler"
    assert g("Kids shark tee").age == "Kids"
    assert g("Youth shark hoodie").age == "Youth"
    assert g("Shark tee").age == "Adult"


def test_baby_clothing_lands_in_a_subsection_that_exists():
    r = g("Lemon shark organic cotton onesie")
    assert r.section == "1"
    assert r.sub == "Baby & Toddler"
    assert r.sub in ic.valid_subs("1")


def test_an_age_with_no_matching_subsection_leaves_the_subsection_blank():
    """Section 2 has no Adult band. Guessing one would put the entry in a
    heading that does not exist in the document."""
    r = g("Shark chess set")
    assert r.section == "2"
    assert r.age == "Adult"
    assert r.sub == ""


def test_section_four_uses_kind_not_age():
    r = g("Junior rash guard, UPF 50")
    assert r.section == "4"
    assert r.sub == "Rash guards, wetsuits & swim gear"


def test_section_seven_subsections():
    assert g("Shark advent calendar").sub == "Advent calendars & seasonal"
    assert g("Adopt a shark for a year").sub == "Adoptions & subscriptions"
    assert g("Cage diving experience day").sub == "Experiences"


def test_ngo_hosts_are_derived_from_the_data_not_hardcoded():
    hosts = ic.ngo_hosts()
    assert "sharktrust.org" in " ".join(hosts)
    for host, sub in hosts.items():
        assert sub in ic.valid_subs("6")


def test_the_note_is_searched_as_well_as_the_title():
    r = g("Untitled listing", note="it is a lovely plush toy")
    assert r.section == "2"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_classify.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_classify'`.

- [ ] **Step 3: Write `intake_classify.py`**

```python
#!/usr/bin/env python3
"""Guess a section, subsection, and age band from a product title and a note.

Every guess carries the keyword that produced it, so a wrong one is traceable
to its rule. No rule firing leaves the field blank: an unclassified entry is a
visible question, whereas a default would be an invisible wrong answer.

The NGO host list is derived from section 6 of items.json rather than
hardcoded, so adding an organisation to the document teaches this too.
"""
import re
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlsplit

from entries import load_items

# Order matters: a book about snorkelling is a book, not equipment.
SECTION_RULES = [
    ("3", r"\b(books?|isbn|paperback|hardcover|picture book|author|publisher|ebooks?|"
          r"activity book|colouring book|coloring book)\b"),
    ("4", r"\b(masks?|snorkel\w*|fins?|wetsuits?|rash ?guards?|swim\w*|nets?|"
          r"binoculars?|microscopes?|dive|diving)\b"),
    ("5", r"\b(stickers?|colouring|coloring|crafts?|pencils?|stationery|posters?|"
          r"prints?|paint\w*|notebooks?)\b"),
    ("2", r"\b(plush|soft toys?|toys?|figures?|figurines?|puzzles?|lego|games?|"
          r"playsets?|chess)\b"),
    ("1", r"\b(tees?|t-shirts?|shirts?|onesies?|bodysuits?|socks?|hoodies?|hats?|"
          r"caps?|necklaces?|bracelets?|earrings?|jewell?ery|scarf|leggings)\b"),
    ("7", r"\b(adopt\w*|experiences?|advent|subscriptions?|gift cards?|day out)\b"),
]

AGE_RULES = [
    ("Baby & Toddler", r"\b(baby|babies|toddlers?|infants?|onesies?|bodysuits?|newborns?)\b"),
    ("Kids", r"\b(kids?|child|children|junior)\b"),
    ("Youth", r"\b(youth|teens?|teenagers?)\b"),
]

SECTION_4_RULES = [
    ("Mask, snorkel & fins sets", r"\b(masks?|snorkel\w*|fins?)\b"),
    ("Rash guards, wetsuits & swim gear", r"\b(rash ?guards?|wetsuits?|swim\w*|suits?)\b"),
    ("Beach & rockpooling kit", r"\b(nets?|buckets?|rockpool\w*|beach|tide)\b"),
    ("Science & STEM kits", r"\b(kits?|microscopes?|experiments?|stem|science)\b"),
    ("Optics & tech", r"\b(binoculars?|cameras?|torch\w*|lights?|watch\w*|tech)\b"),
]

SECTION_7_RULES = [
    ("Advent calendars & seasonal", r"\b(advent|christmas|seasonal|stocking)\b"),
    ("Adoptions & subscriptions", r"\b(adopt\w*|subscriptions?|sponsor\w*|membership)\b"),
    ("Experiences", r"\b(experiences?|day out|dive|trip|tour|cage)\b"),
]


@dataclass
class Guess:
    section: str = ""
    sub: str = ""
    age: str = ""
    keyword: str = ""


@lru_cache(maxsize=1)
def _sections():
    return {s["number"]: s for s in load_items()["sections"]}


def valid_subs(section):
    s = _sections().get(str(section))
    return [sub["name"] for sub in s["subsections"]] if s else []


@lru_cache(maxsize=1)
def ngo_hosts():
    """Host to section 6 subsection name, read from the entries already filed
    under each organisation."""
    out = {}
    for sub in _sections()["6"]["subsections"]:
        for item in sub["items"]:
            host = urlsplit(item["link"]).netloc.lower()
            if host.startswith("www."):
                host = host[4:]
            out[host] = sub["name"]
    return out


def _first_match(rules, text):
    for label, pattern in rules:
        m = re.search(pattern, text, re.I)
        if m:
            return label, m.group(0).lower()
    return "", ""


def classify(title, note="", url=""):
    text = f"{title} {note}".strip()
    host = urlsplit(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    for known_host, sub in ngo_hosts().items():
        if host and (host == known_host or host.endswith("." + known_host)):
            return Guess(section="6", sub=sub, age=_age(text), keyword=f"host:{known_host}")

    section, keyword = _first_match(SECTION_RULES, text)
    if not section:
        return Guess()

    age = _age(text)
    if section == "4":
        sub, kind = _first_match(SECTION_4_RULES, text)
        return Guess(section=section, sub=sub, age=age, keyword=f"{keyword}|{kind}".strip("|"))
    if section == "7":
        sub, kind = _first_match(SECTION_7_RULES, text)
        return Guess(section=section, sub=sub, age=age, keyword=f"{keyword}|{kind}".strip("|"))

    sub = age if age in valid_subs(section) else ""
    return Guess(section=section, sub=sub, age=age, keyword=keyword)


def _age(text):
    label, _kw = _first_match(AGE_RULES, text)
    return label or "Adult"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_classify.py -v`
Expected: PASS, 15 passed.

- [ ] **Step 5: Sanity-check the rules against the entries already filed**

This is a positive control on the classifier: it re-classifies the 84 entries whose true section is already known, and reports agreement. Perfect agreement is not expected, since the real filing used judgement; a figure below about 60% means a rule is broken rather than merely coarse.

Run: `~/.venvs/scrape/bin/python -c "
import intake_classify as ic
from entries import iter_entries
hit = miss = blank = 0
wrong = []
for e in iter_entries(include_existing=False):
    r = ic.classify(e.item, e.desc, e.link)
    if not r.section:
        blank += 1
    elif r.section == e.section:
        hit += 1
    else:
        miss += 1
        wrong.append((e.id, e.section, r.section, r.keyword, e.item[:48]))
total = hit + miss + blank
print(f'agreed {hit}/{total}, disagreed {miss}, unclassified {blank}')
for w in wrong[:12]:
    print('   ', w)
"`
Expected: an agreement figure with a short list of disagreements. Read the list. If a disagreement reveals a rule that is plainly wrong (rather than a judgement call), fix the rule and rerun.

- [ ] **Step 6: Commit**

```bash
git add intake_classify.py tests/test_intake_classify.py
git commit -m "Guess section, subsection and age from keywords, with evidence

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The ledger, the queue, and duplicate detection

**Files:**
- Create: `intake_queue.py`, `tests/test_intake_queue.py`

**Interfaces:**
- Consumes: `paths.LEDGER`, `paths.QUEUE`, `paths.REJECTED`, `entries.iter_entries`, `intake_parse.normalise_url`.
- Produces: `intake_queue.seen(message_id, path=LEDGER) -> bool`, `record_message(message_id, urls, path=LEDGER)`, `load_queue(path=QUEUE) -> list[dict]`, `save_queue(rows, path=QUEUE)`, `next_queue_id(rows) -> str`, `add_row(row, path=QUEUE) -> dict`, `load_rejected(path=REJECTED) -> dict`, `reject(norm_url, reason, path=REJECTED)`, `known_links(data=None) -> dict[str, str]`, `duplicate_of(norm_url, queue_path=QUEUE, rejected_path=REJECTED) -> str`, `new_row(submission, url, facts, guess) -> dict`.

The queue row schema, which Tasks 9, 10, and 11 all depend on:

```python
{
  "queue_id": "q0001",      # allocated here, stable for the row's life
  "message_id": "abc@mail.gmail.com",
  "received": "2026-08-28T09:14:02-07:00",
  "sender": "Simon Dedman",
  "note": "my nephew has a pair",
  "url": "https://shop.com/products/thing?variant=1",   # verbatim, for the entry
  "url_norm": "https://shop.com/products/thing?variant=1",  # for matching only
  "fetch_status": "OK",     # OK | BLOCKED | DEAD | EMPTY
  "http": 200,
  "fetch_note": "fetched; images: shopify-product",
  "title": "Shark socks",
  "price": "~£12.50",
  "price_source": "itemprop",
  "ngo_text": "5% of profits go to the Shark Trust.",
  "section": "1",
  "sub": "Adult",
  "age": "Adult",
  "keyword": "socks",
  "duplicate_of": "",       # entry id, queue id, "REJECTED", or ""
  "candidates": [ ... ],    # as harvest.harvest returns them
  "picked": ""              # filled in from the workbook by Task 11
}
```

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_queue.py`:

```python
import json

import pytest

import intake_queue as q


@pytest.fixture
def paths(tmp_path):
    return dict(ledger=tmp_path / "ledger.json",
                queue=tmp_path / "queue.json",
                rejected=tmp_path / "rejected.json")


def test_an_unseen_message_is_not_seen(paths):
    assert q.seen("a@b", path=paths["ledger"]) is False


def test_a_recorded_message_is_seen(paths):
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    assert q.seen("a@b", path=paths["ledger"]) is True


def test_recording_twice_does_not_duplicate(paths):
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    q.record_message("a@b", ["https://x.com/1"], path=paths["ledger"])
    assert len(json.loads(paths["ledger"].read_text())) == 1


def test_queue_ids_increment_and_are_zero_padded(paths):
    assert q.next_queue_id([]) == "q0001"
    assert q.next_queue_id([{"queue_id": "q0001"}, {"queue_id": "q0009"}]) == "q0010"


def test_add_row_allocates_an_id_and_persists(paths):
    row = q.add_row({"url": "https://x.com/1"}, path=paths["queue"])
    assert row["queue_id"] == "q0001"
    assert q.load_queue(path=paths["queue"])[0]["url"] == "https://x.com/1"


def test_known_links_maps_normalised_links_to_entry_ids():
    links = q.known_links()
    assert links["https://luckybugclothing.com/products/shark-onesie"] == "e01"


def test_duplicate_of_finds_an_existing_entry(paths):
    dup = q.duplicate_of("https://luckybugclothing.com/products/shark-onesie",
                         queue_path=paths["queue"], rejected_path=paths["rejected"])
    assert dup == "e01"


def test_duplicate_of_finds_a_row_already_queued(paths):
    q.add_row({"url": "https://x.com/1", "url_norm": "https://x.com/1"},
              path=paths["queue"])
    assert q.duplicate_of("https://x.com/1", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == "q0001"


def test_duplicate_of_reports_a_previously_rejected_link(paths):
    q.reject("https://x.com/2", "not shark themed", path=paths["rejected"])
    assert q.duplicate_of("https://x.com/2", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == "REJECTED"


def test_duplicate_of_is_empty_for_something_new(paths):
    assert q.duplicate_of("https://x.com/brand-new", queue_path=paths["queue"],
                          rejected_path=paths["rejected"]) == ""


def test_duplicate_detection_positive_control(paths):
    """The control on the matcher: every link already in the document must be
    found as a duplicate. If this passes while real duplicates slip through,
    the matcher is reading the wrong field. Several entries deliberately share a
    link (a shop listed under two age bands), so the match is asserted against
    the set of ids carrying that link rather than one id."""
    from collections import defaultdict
    from entries import iter_entries
    from intake_parse import normalise_url
    by_link = defaultdict(set)
    for e in iter_entries():
        by_link[normalise_url(e.link)].add(e.id)
    for link, ids in by_link.items():
        found = q.duplicate_of(link, queue_path=paths["queue"],
                               rejected_path=paths["rejected"])
        assert found in ids, (link, found, ids)


def test_new_row_carries_every_field_the_sheet_needs():
    from intake_parse import Submission
    from intake_extract import Facts
    from intake_classify import Guess
    sub = Submission(message_id="m1", sender="Simon Dedman",
                     date="2026-08-28T09:14:02-07:00", subject="s",
                     urls=["https://x.com/1"], note="nice")
    facts = Facts(url="https://x.com/1", status="OK", http=200, title="Shark socks",
                  price="~$12", price_source="json-ld", ngo_text="5% donated.",
                  note="fetched", candidates=[{"url": "https://x.com/i.jpg"}])
    guess = Guess(section="1", sub="Adult", age="Adult", keyword="socks")
    row = q.new_row(sub, "https://x.com/1", facts, guess)
    for key in ("message_id", "received", "sender", "note", "url", "url_norm",
                "fetch_status", "http", "fetch_note", "title", "price",
                "price_source", "ngo_text", "section", "sub", "age", "keyword",
                "duplicate_of", "candidates", "picked"):
        assert key in row, key
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_queue.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_queue'`.

- [ ] **Step 3: Write `intake_queue.py`**

```python
#!/usr/bin/env python3
"""Durable state for the intake: which messages have been processed, which rows
are waiting for review, and which links have already been turned down.

Messages are tracked by Message-ID rather than by IMAP UID, because UIDs are
only meaningful until the folder's UIDVALIDITY changes, and are never marked
\\Seen, because reading the mail on a phone must not change what the daemon does.
"""
import json
from datetime import datetime

from paths import LEDGER, QUEUE, REJECTED
from entries import iter_entries
from intake_parse import normalise_url


def _load(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def seen(message_id, path=LEDGER):
    return message_id in _load(path, {})


def record_message(message_id, urls, path=LEDGER):
    ledger = _load(path, {})
    ledger.setdefault(message_id, dict(seen=datetime.now().astimezone().isoformat(),
                                       urls=list(urls)))
    _save(path, ledger)


def load_queue(path=QUEUE):
    return _load(path, [])


def save_queue(rows, path=QUEUE):
    _save(path, rows)


def next_queue_id(rows):
    highest = max((int(r["queue_id"][1:]) for r in rows if r.get("queue_id")), default=0)
    return f"q{highest + 1:04d}"


def add_row(row, path=QUEUE):
    rows = load_queue(path)
    row = dict(row)
    row["queue_id"] = next_queue_id(rows)
    rows.append(row)
    save_queue(rows, path)
    return row


def load_rejected(path=REJECTED):
    return _load(path, {})


def reject(norm_url, reason, path=REJECTED):
    data = load_rejected(path)
    data[norm_url] = dict(date=datetime.now().astimezone().isoformat(), reason=reason)
    _save(path, data)


def known_links(data=None):
    """Normalised link to entry id, for everything already in the document."""
    return {normalise_url(e.link): e.id for e in iter_entries(data)}


def duplicate_of(norm_url, queue_path=QUEUE, rejected_path=REJECTED, data=None):
    """Entry id, queue id, "REJECTED", or "" for something genuinely new."""
    match = known_links(data).get(norm_url)
    if match:
        return match
    if norm_url in load_rejected(rejected_path):
        return "REJECTED"
    for row in load_queue(queue_path):
        if row.get("url_norm") == norm_url:
            return row["queue_id"]
    return ""


def new_row(submission, url, facts, guess):
    """Assemble one pending row. No queue_id yet; add_row allocates that."""
    return dict(
        message_id=submission.message_id,
        received=submission.date,
        sender=submission.sender,
        note=submission.note,
        url=url,
        url_norm=normalise_url(url),
        fetch_status=facts.status,
        http=facts.http,
        fetch_note=facts.note,
        title=facts.title,
        price=facts.price,
        price_source=facts.price_source,
        ngo_text=facts.ngo_text,
        section=guess.section,
        sub=guess.sub,
        age=guess.age,
        keyword=guess.keyword,
        duplicate_of="",
        candidates=facts.candidates,
        picked="",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_queue.py -v`
Expected: PASS, 12 passed.

- [ ] **Step 5: Commit**

```bash
git add intake_queue.py tests/test_intake_queue.py
git commit -m "Add the intake ledger, pending queue, and duplicate detection

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: The watcher

**Files:**
- Create: `intake_watch.py`, `tests/test_intake_watch.py`

**Interfaces:**
- Consumes: `intake_parse.parse_message`, `intake_extract.extract`, `intake_classify.classify`, `intake_queue.*`, `paths.ENV_FILE`, `paths.HEARTBEAT`, `paths.INTAKE_LOG`.
- Produces: `intake_watch.credentials() -> tuple[str, str]`, `intake_watch.process_message(raw, dry_run=False) -> list[dict]`, `intake_watch.catch_up(client, dry_run=False) -> int`, `intake_watch.beat() -> None`, `intake_watch.watch(dry_run=False) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_watch.py`:

```python
import json
from pathlib import Path

import pytest

import intake_watch
from intake_extract import Facts

MAIL = Path(__file__).resolve().parent / "fixtures" / "mail"


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """No network, no real queue: extraction is stubbed and state goes to tmp."""
    monkeypatch.setattr(intake_watch, "QUEUE", tmp_path / "queue.json")
    monkeypatch.setattr(intake_watch, "LEDGER", tmp_path / "ledger.json")
    monkeypatch.setattr(intake_watch, "REJECTED", tmp_path / "rejected.json")
    monkeypatch.setattr(intake_watch, "HEARTBEAT", tmp_path / "heartbeat")
    monkeypatch.setattr(intake_watch, "INTAKE_LOG", tmp_path / "intake.log")

    def fake_extract(url):
        return Facts(url=url, status="OK", http=200, title="Shark socks",
                     price="~£12.50", price_source="itemprop",
                     ngo_text="5% of profits go to the Shark Trust.",
                     note="fetched", candidates=[{"url": "https://x.com/i.jpg",
                                                  "title": "socks", "src": "img"}])
    monkeypatch.setattr(intake_watch.intake_extract, "extract", fake_extract)
    return tmp_path


def test_a_message_becomes_one_queue_row_per_url(isolated):
    raw = (MAIL / "multi_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert len(rows) == 3
    assert [r["queue_id"] for r in rows] == ["q0001", "q0002", "q0003"]


def test_the_message_is_recorded_so_it_is_not_processed_twice(isolated):
    raw = (MAIL / "bare_url.eml").read_bytes()
    assert len(intake_watch.process_message(raw)) == 1
    assert intake_watch.process_message(raw) == []


def test_a_message_with_no_url_is_still_queued_visibly(isolated):
    raw = (MAIL / "no_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert len(rows) == 1
    assert rows[0]["fetch_status"] == "NO_URL"
    assert "advent calendar" in rows[0]["note"]


def test_a_duplicate_link_is_flagged_not_dropped(isolated, monkeypatch):
    raw = (MAIL / "bare_url.eml").read_bytes()
    rows = intake_watch.process_message(raw)
    assert rows[0]["duplicate_of"] == "e01", \
        "the lemon shark onesie is already entry e01"


def test_the_note_and_sender_reach_the_row(isolated):
    rows = intake_watch.process_message((MAIL / "link_plus_note.eml").read_bytes())
    assert rows[0]["sender"] == "Simon Dedman"
    assert "proceeds go somewhere useful" in rows[0]["note"]


def test_dry_run_writes_nothing(isolated):
    raw = (MAIL / "bare_url.eml").read_bytes()
    rows = intake_watch.process_message(raw, dry_run=True)
    assert len(rows) == 1
    assert not (isolated / "queue.json").exists()
    assert not (isolated / "ledger.json").exists()


def test_beat_writes_a_parseable_timestamp(isolated):
    intake_watch.beat()
    from datetime import datetime
    datetime.fromisoformat((isolated / "heartbeat").read_text().strip())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_watch.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_watch'`.

- [ ] **Step 3: Install the one dependency**

Run: `pip install --user IMAPClient`
Expected: `Successfully installed IMAPClient-...`

Verify the venv can see it: `~/.venvs/scrape/bin/python -c "import imapclient; print(imapclient.__version__)"`
Expected: a version number.

Append to `~/.claude/INSTALLS-CATALOGUE.md`, under the Python section: `IMAPClient <version>, user site-packages, installed 2026-08-28 for shark-swag email intake. Python 3.13's stdlib imaplib has no IDLE support; this provides idle()/idle_check(). Visible to ~/.venvs/* because those venvs use --system-site-packages.`

- [ ] **Step 4: Write `intake_watch.py`**

```python
#!/usr/bin/env python3
"""Watch the sharkswag Gmail label and stage every new submission.

IDLE gives push delivery, but a dead IDLE socket looks exactly like a quiet
inbox, and this machine sleeps. So the daemon also scans the whole folder on
every start and every SWEEP_SECONDS, staging anything absent from the ledger.
Push is for latency; the sweep is for truth.

systemd owns liveness. Nothing here checks for a running process: in this
harness a pgrep pattern matches the searching command itself and always says
yes.
"""
import os
import ssl
import sys
import time
from datetime import datetime

from imapclient import IMAPClient

import intake_classify
import intake_extract
import intake_parse
import intake_queue
from paths import ENV_FILE, HEARTBEAT, INTAKE_LOG, LEDGER, QUEUE, REJECTED

HOST = "imap.gmail.com"
FOLDER = "sharkswag"
IDLE_SECONDS = 15 * 60          # Gmail drops an idle connection at about 29 minutes
SWEEP_SECONDS = 6 * 60 * 60
RECONNECT_BACKOFF = (30, 60, 120, 300, 600)


def log(message):
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')}  {message}"
    print(line, flush=True)
    INTAKE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with INTAKE_LOG.open("a") as fh:
        fh.write(line + "\n")


def beat():
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(datetime.now().astimezone().isoformat() + "\n")


def credentials():
    """Read the Gmail app password from the shared .env. Never logged."""
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    address = values.get("GMAIL_ADDRESS")
    password = values.get("GMAIL_APP_PASSWORD")
    if not address or not password:
        raise SystemExit(f"GMAIL_ADDRESS or GMAIL_APP_PASSWORD missing from {ENV_FILE}")
    return address, password


def notify(count):
    if not count:
        return
    os.system(f'notify-send "Shark swag" "{count} new submission(s) staged" >/dev/null 2>&1')


def process_message(raw, dry_run=False):
    """Message bytes to queue rows. Returns [] if the message was already seen."""
    submission = intake_parse.parse_message(raw)
    if submission.message_id and intake_queue.seen(submission.message_id, path=LEDGER):
        return []

    rows = []
    if not submission.urls:
        row = dict(
            message_id=submission.message_id, received=submission.date,
            sender=submission.sender, note=submission.note, url="", url_norm="",
            fetch_status="NO_URL", http=None,
            fetch_note="the message carried no link", title=submission.subject,
            price="", price_source="", ngo_text="", section="", sub="", age="",
            keyword="", duplicate_of="", candidates=[], picked="")
        rows.append(row if dry_run else intake_queue.add_row(row, path=QUEUE))
    else:
        for url in submission.urls:
            facts = intake_extract.extract(url)
            guess = intake_classify.classify(facts.title, submission.note, url)
            row = intake_queue.new_row(submission, url, facts, guess)
            row["duplicate_of"] = intake_queue.duplicate_of(
                row["url_norm"], queue_path=QUEUE, rejected_path=REJECTED)
            rows.append(row if dry_run else intake_queue.add_row(row, path=QUEUE))

    if not dry_run:
        intake_queue.record_message(submission.message_id, submission.urls, path=LEDGER)
    return rows


def catch_up(client, dry_run=False):
    """Stage everything in the folder that the ledger has never seen.

    Runs on every start and on every sweep, so a missed IDLE notification, a
    sleeping machine, or a socket that went quiet costs at most one sweep.
    """
    uids = client.search(["ALL"])
    if not uids:
        return 0
    staged = 0
    for uid, data in client.fetch(uids, ["RFC822"]).items():
        raw = data.get(b"RFC822")
        if not raw:
            continue
        try:
            staged += len(process_message(raw, dry_run=dry_run))
        except Exception as e:
            log(f"ERROR processing uid {uid}: {type(e).__name__}: {e}")
    return staged


def watch(dry_run=False):
    address, password = credentials()
    attempt = 0
    while True:
        try:
            with IMAPClient(HOST, ssl_context=ssl.create_default_context()) as client:
                client.login(address, password)
                client.select_folder(FOLDER)
                attempt = 0
                log(f"connected, watching {FOLDER}")
                staged = catch_up(client, dry_run)
                beat()
                notify(staged)
                log(f"catch-up staged {staged} row(s)")

                last_sweep = time.time()
                while True:
                    client.idle()
                    responses = client.idle_check(timeout=IDLE_SECONDS)
                    client.idle_done()
                    due = time.time() - last_sweep > SWEEP_SECONDS
                    if responses or due:
                        staged = catch_up(client, dry_run)
                        if due:
                            last_sweep = time.time()
                            log(f"sweep staged {staged} row(s)")
                        elif staged:
                            log(f"push staged {staged} row(s)")
                        notify(staged)
                    beat()
        except KeyboardInterrupt:
            log("stopped by hand")
            return
        except Exception as e:
            wait = RECONNECT_BACKOFF[min(attempt, len(RECONNECT_BACKOFF) - 1)]
            attempt += 1
            log(f"connection lost ({type(e).__name__}: {e}); retrying in {wait}s")
            time.sleep(wait)


if __name__ == "__main__":
    watch(dry_run="--dry-run" in sys.argv)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_watch.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 6: Commit**

```bash
git add intake_watch.py tests/test_intake_watch.py
git commit -m "Add the IMAP IDLE watcher with a catch-up scan and a sweep

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: The review workbook

**Files:**
- Create: `intake_sheet.py`, `tests/test_intake_sheet.py`

**Interfaces:**
- Consumes: `intake_queue.load_queue`, `paths.SHEETS`, `paths.HEARTBEAT`, `imgproc.download/load/autocrop`.

Note on the spec's "clear `images/pool/` for the pending id first": contact sheets here are built straight from the row's own candidate list through `imgproc.download`, whose cache is keyed on the URL rather than on a candidate index. The stale-index hazard that made the last round of sheets lie therefore cannot arise, and there is nothing to clear.
- Produces: `intake_sheet.COLUMNS` (list of `(header, width, editable)`), `intake_sheet.contact_sheet(row) -> Path | None`, `intake_sheet.write_workbook(rows, path) -> Path`, `intake_sheet.build(path=None) -> Path`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_sheet.py`:

```python
import openpyxl
import pytest

import intake_sheet


ROW = dict(queue_id="q0001", message_id="m1", received="2026-08-28T09:14:02-07:00",
           sender="Simon Dedman", note="nephew has a pair",
           url="https://shop.com/products/socks", url_norm="https://shop.com/products/socks",
           fetch_status="OK", http=200, fetch_note="fetched", title="Shark socks",
           price="~£12.50", price_source="itemprop",
           ngo_text="5% of profits go to the Shark Trust.", section="1", sub="Adult",
           age="Adult", keyword="socks", duplicate_of="", candidates=[], picked="")

BLOCKED = dict(ROW, queue_id="q0002", fetch_status="BLOCKED", http=403, title="",
               price="", price_source="", ngo_text="", section="", sub="", keyword="")


@pytest.fixture
def book(tmp_path):
    path = tmp_path / "review.xlsx"
    intake_sheet.write_workbook([ROW, BLOCKED], path)
    return openpyxl.load_workbook(path)


def test_info_tab_is_first(book):
    assert book.sheetnames[0] == "Info"


def test_review_tab_exists(book):
    assert "Review" in book.sheetnames


def test_header_row_is_frozen_bold_and_filtered(book):
    ws = book["Review"]
    assert ws.freeze_panes == "A2"
    assert ws["A1"].font.bold is True
    assert ws.auto_filter.ref is not None


def test_status_column_is_first_and_empty(book):
    ws = book["Review"]
    assert ws["A1"].value == "Status"
    assert ws["A2"].value in (None, "")


def test_every_row_reaches_the_sheet(book):
    ws = book["Review"]
    assert ws.max_row == 3


def test_scraped_values_are_pre_filled(book):
    ws = book["Review"]
    headers = [c.value for c in ws[1]]
    row = {h: ws.cell(row=2, column=i + 1).value for i, h in enumerate(headers)}
    assert row["Item"] == "Shark socks"
    assert row["Approx. price"] == "~£12.50"
    assert row["Suggested by"] == "Simon Dedman"
    assert row["Description"] in (None, "")


def test_a_blocked_row_says_blocked_and_does_not_look_empty(book):
    ws = book["Review"]
    headers = [c.value for c in ws[1]]
    row = {h: ws.cell(row=3, column=i + 1).value for i, h in enumerate(headers)}
    assert row["Fetch"] == "BLOCKED"
    assert row["Item"] in (None, "")


def test_info_tab_states_the_counts_and_the_last_poll(book):
    text = " ".join(str(c.value) for r in book["Info"].iter_rows() for c in r if c.value)
    assert "BLOCKED" in text
    assert "last successful poll" in text.lower()
    assert "ACCEPT" in text and "REJECT" in text and "HOLD" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_sheet.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_sheet'`.

- [ ] **Step 3: Write `intake_sheet.py`**

```python
#!/usr/bin/env python3
"""Turn the pending queue into a review workbook, with a contact sheet per item.

House rules: the Info tab is ordered first and says what was already done and
what the reader must do; every tab has a frozen, bold, autofiltered header row.
Evidence columns sit to the right of the editable ones, so a guess can always be
traced to what produced it.
"""
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from PIL import Image, ImageDraw, ImageFont

import intake_queue
from imgproc import autocrop, download, load
from paths import HEARTBEAT, INTAKE, SHEETS

# (header, width, source key, editable)
COLUMNS = [
    ("Status", 9, None, True),
    ("Section", 10, "section", True),
    ("Subsection", 20, "sub", True),
    ("Item", 40, "title", True),
    ("Age", 14, "age", True),
    ("Link", 34, "url", True),
    ("Approx. price", 13, "price", True),
    ("Description", 52, None, True),
    ("Suggested by", 18, "sender", True),
    ("NGO / proceeds to conservation?", 40, "ngo_text", True),
    ("Image pick", 11, "picked", True),
    ("Fetch", 9, "fetch_status", False),
    ("Price source", 12, "price_source", False),
    ("Section keyword", 16, "keyword", False),
    ("Duplicate of", 12, "duplicate_of", False),
    ("Their note", 34, "note", False),
    ("Received", 20, "received", False),
    ("Contact sheet", 14, None, False),
    ("Queue id", 10, "queue_id", False),
]

EVIDENCE_FILL = PatternFill("solid", fgColor="F2F2F2")
CELL, HDR, COLS = 190, 30, 12


def contact_sheet(row):
    """A numbered grid of this item's candidate images. Returns None when the
    fetch was blocked or produced no candidates: an absent sheet must not be
    read as 'no good image exists'."""
    cands = row.get("candidates") or []
    if not cands:
        return None
    SHEETS.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 18)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 15)
    except OSError:
        font = small = ImageFont.load_default()

    cands = cands[:COLS]
    sheet = Image.new("RGB", (COLS * CELL + 20, CELL + HDR + 20), (250, 250, 250))
    draw = ImageDraw.Draw(sheet)
    draw.text((10, 6), f"[{row['queue_id']}] {(row.get('title') or row['url'])[:110]}",
              fill=(0, 0, 0), font=font)
    x, y = 10, HDR
    for j, c in enumerate(cands):
        draw.rectangle([x, y, x + CELL - 6, y + CELL - 6], outline=(200, 200, 200))
        draw.text((x + 3, y + CELL - 22), str(j), fill=(120, 120, 120), font=small)
        path, _note = download(c["url"], referer=row["url"])
        if path:
            try:
                im, _ = autocrop(load(path))
                im.thumbnail((CELL - 14, CELL - 14))
                sheet.paste(im, (x + 3 + (CELL - 14 - im.size[0]) // 2,
                                 y + 3 + (CELL - 14 - im.size[1]) // 2))
            except Exception:
                draw.text((x + 8, y + 8), "decode failed", fill=(160, 0, 0), font=small)
        x += CELL
    out = SHEETS / f"pending_{row['queue_id']}.jpg"
    sheet.save(out, "JPEG", quality=88)
    return out


def _last_poll():
    if not HEARTBEAT.exists():
        return "never - the watcher has not run"
    return HEARTBEAT.read_text().strip()


def _info(ws, rows):
    counts = {}
    for r in rows:
        counts[r.get("fetch_status", "?")] = counts.get(r.get("fetch_status", "?"), 0) + 1
    lines = [
        ("Shark swag: submissions awaiting review", True),
        ("", False),
        (f"Generated {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M %Z')} "
         f"from intake/queue.json.", False),
        (f"Watcher's last successful poll: {_last_poll()}.", False),
        (f"Rows by fetch status: "
         f"{', '.join(f'{k} {v}' for k, v in sorted(counts.items()))}.", False),
        ("", False),
        ("What has already happened", True),
        ("Each link was fetched, its title, price, and any sentence about donations "
         "were read off the page, a section and age band were guessed from keywords, "
         "and candidate product images were downloaded into a contact sheet.", False),
        ("Nothing has been written to items.json or the document. No description "
         "prose has been written: that part is yours.", False),
        ("", False),
        ("What you need to do, on the Review tab", True),
        ("1. Read the Fetch column first. OK means the page was read. BLOCKED means "
         "the site refused the request, so its blank fields say nothing about the "
         "product. DEAD means the link no longer resolves to a product. EMPTY means "
         "the page was read and held nothing usable. NO_URL means the message carried "
         "no link at all.", False),
        ("2. Check Duplicate of. An eNN value means this item is already in the "
         "document; a qNNNN value means it is already elsewhere in this sheet.", False),
        ("3. Fill in Description. This is the only field with no scraped source, and "
         "an accepted row will be refused without it.", False),
        ("4. Correct Section, Subsection, Item, Age, and Approx. price where the "
         "guess is wrong. Section keyword shows which rule produced the guess.", False),
        ("5. Open the contact sheet linked in the last column and put the index of "
         "the image you want in Image pick. Several are allowed, comma separated. "
         "Leave it blank for no image.", False),
        ("6. Set Status to ACCEPT, REJECT, or HOLD. Blank counts as HOLD. ACCEPT adds "
         "the entry; REJECT records the link so it is never queued again; HOLD leaves "
         "it for the next workbook.", False),
        ("", False),
        ("7. Save the workbook, then run:", True),
        ("   ~/.venvs/scrape/bin/python intake_apply.py", False),
        ("It refuses to run if an accepted row is missing its Section, Subsection, "
         "Item, or Description, and names the rows rather than guessing.", False),
    ]
    for n, (text, bold) in enumerate(lines, 1):
        cell = ws.cell(row=n, column=1, value=text)
        cell.font = Font(bold=bold)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 118
    ws.freeze_panes = "A2"
    ws["A1"].font = Font(bold=True, size=13)


def write_workbook(rows, path):
    wb = Workbook()
    info = wb.active
    info.title = "Info"
    _info(info, rows)

    ws = wb.create_sheet("Review")
    for i, (header, width, _key, editable) in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=i, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical="bottom")
        if not editable:
            cell.fill = EVIDENCE_FILL
        ws.column_dimensions[get_column_letter(i)].width = width

    for r, row in enumerate(rows, 2):
        for i, (header, _w, key, editable) in enumerate(COLUMNS, 1):
            if header == "Contact sheet":
                sheet_path = SHEETS / f"pending_{row['queue_id']}.jpg"
                value = (f'=HYPERLINK("{sheet_path}","images")'
                         if sheet_path.exists() else "")
            else:
                value = row.get(key, "") if key else ""
            cell = ws.cell(row=r, column=i, value=value)
            if not editable:
                cell.fill = EVIDENCE_FILL
            if header in ("Description", "NGO / proceeds to conservation?", "Their note"):
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(2, len(rows) + 1)}"

    # hide evidence columns that are empty for every row, to keep the sheet
    # readable on one screen
    for i, (header, _w, key, editable) in enumerate(COLUMNS, 1):
        if editable or not key:
            continue
        if not any(str(row.get(key, "")).strip() for row in rows):
            ws.column_dimensions[get_column_letter(i)].hidden = True

    wb.save(path)
    return path


def build(path=None):
    rows = intake_queue.load_queue()
    if not rows:
        print("queue is empty, nothing to review")
        return None
    for row in rows:
        contact_sheet(row)
    path = path or INTAKE / f"review_{datetime.now().strftime('%Y-%m-%d')}.xlsx"
    write_workbook(rows, path)
    print(f"{len(rows)} rows -> {path}")
    return path


if __name__ == "__main__":
    build()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_sheet.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add intake_sheet.py tests/test_intake_sheet.py
git commit -m "Build the review workbook and per-item contact sheets

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: Apply the reviewed workbook

**Files:**
- Create: `intake_apply.py`, `tests/test_intake_apply.py`

**Interfaces:**
- Consumes: `entries.load_items/save_items/next_id`, `picks.load_picks/save_picks/render`, `intake_queue.load_queue/save_queue/reject`, `intake_sheet.COLUMNS`, `paths.INTAKE`.
- Produces: `intake_apply.read_workbook(path) -> list[dict]`, `intake_apply.validate(rows) -> list[str]`, `intake_apply.newest_workbook() -> Path`, `intake_apply.apply_row(row, data, queue_row) -> str`, `intake_apply.main(path=None, rebuild=True) -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake_apply.py`:

```python
import json

import pytest

import intake_apply
import intake_sheet


def sheet_row(**over):
    base = dict(queue_id="q0001", message_id="m1", received="2026-08-28T09:14:02-07:00",
                sender="Simon Dedman", note="", url="https://shop.com/products/socks",
                url_norm="https://shop.com/products/socks", fetch_status="OK", http=200,
                fetch_note="fetched", title="Shark socks", price="~£12.50",
                price_source="itemprop", ngo_text="5% donated.", section="1",
                sub="Adult", age="Adult", keyword="socks", duplicate_of="",
                candidates=[], picked="")
    base.update(over)
    return base


@pytest.fixture
def workbook(tmp_path):
    def build(rows, statuses, descriptions=None):
        path = tmp_path / "review.xlsx"
        intake_sheet.write_workbook(rows, path)
        import openpyxl
        wb = openpyxl.load_workbook(path)
        ws = wb["Review"]
        headers = [c.value for c in ws[1]]
        for i, (status, desc) in enumerate(zip(statuses, descriptions or [""] * len(rows)), 2):
            ws.cell(row=i, column=headers.index("Status") + 1, value=status)
            ws.cell(row=i, column=headers.index("Description") + 1, value=desc)
        wb.save(path)
        return path
    return build


def test_read_workbook_returns_one_dict_per_row(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    rows = intake_apply.read_workbook(path)
    assert len(rows) == 1
    assert rows[0]["Status"] == "ACCEPT"
    assert rows[0]["Description"] == "Bamboo socks."
    assert rows[0]["Queue id"] == "q0001"


def test_a_blank_status_reads_as_hold(workbook):
    path = workbook([sheet_row()], [None])
    assert intake_apply.read_workbook(path)[0]["Status"] == "HOLD"


def test_validate_refuses_an_accepted_row_with_no_description(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], [""])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert errors
    assert "q0001" in errors[0]
    assert "Description" in errors[0]


def test_validate_refuses_an_accepted_row_with_no_section(workbook):
    path = workbook([sheet_row(section="")], ["ACCEPT"], ["Bamboo socks."])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert any("Section" in e for e in errors)


def test_validate_refuses_a_subsection_that_does_not_exist(workbook):
    path = workbook([sheet_row(sub="Grown-ups")], ["ACCEPT"], ["Bamboo socks."])
    errors = intake_apply.validate(intake_apply.read_workbook(path))
    assert any("Grown-ups" in e for e in errors)


def test_validate_passes_a_complete_row(workbook):
    path = workbook([sheet_row()], ["ACCEPT"], ["Bamboo socks."])
    assert intake_apply.validate(intake_apply.read_workbook(path)) == []


def test_rejected_and_held_rows_are_not_validated(workbook):
    path = workbook([sheet_row(section=""), sheet_row(queue_id="q0002", section="")],
                    ["REJECT", "HOLD"], ["", ""])
    assert intake_apply.validate(intake_apply.read_workbook(path)) == []


def test_apply_row_inserts_into_the_named_subsection_with_a_fresh_id():
    data = {"sections": [{"number": "1", "title": "t", "subsections":
                          [{"name": "Adult", "items": [{"id": "e01", "item": "x",
                                                        "link": "https://a"}]}]}]}
    row = {"Status": "ACCEPT", "Section": "1", "Subsection": "Adult",
           "Item": "Shark socks", "Age": "Adult", "Link": "https://shop.com/p",
           "Approx. price": "~£12.50", "Description": "Bamboo socks.",
           "Suggested by": "Simon Dedman",
           "NGO / proceeds to conservation?": "5% donated.", "Image pick": "",
           "Queue id": "q0001"}
    new_id = intake_apply.apply_row(row, data)
    items = data["sections"][0]["subsections"][0]["items"]
    assert len(items) == 2
    assert items[1]["id"] == new_id
    assert items[1]["item"] == "Shark socks"
    assert items[1]["desc"] == "Bamboo socks."
    assert items[1]["by"] == "Simon Dedman"
    assert new_id != "e01"


def test_apply_row_does_not_disturb_existing_ids():
    data = {"sections": [{"number": "1", "title": "t", "subsections":
                          [{"name": "Adult", "items": [{"id": "e01", "item": "x",
                                                        "link": "https://a"}]}]}]}
    row = {"Status": "ACCEPT", "Section": "1", "Subsection": "Adult",
           "Item": "Shark socks", "Age": "Adult", "Link": "https://shop.com/p",
           "Approx. price": "", "Description": "d", "Suggested by": "s",
           "NGO / proceeds to conservation?": "", "Image pick": "", "Queue id": "q0001"}
    intake_apply.apply_row(row, data)
    assert data["sections"][0]["subsections"][0]["items"][0]["id"] == "e01"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_apply.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'intake_apply'`.

- [ ] **Step 3: Write `intake_apply.py`**

```python
#!/usr/bin/env python3
"""Read a reviewed workbook back into items.json, the picks, and the document.

Refuses to guess. An accepted row missing a section, a subsection, an item name,
or a description stops the run and is named, because a wrong entry in the shared
document costs more than a second pass over the sheet.
"""
import subprocess
import sys
from pathlib import Path

import openpyxl

import entries
import intake_queue
import picks as picks_mod
from paths import INTAKE, ROOT

VENV_PYTHON = "/home/simon/.venvs/scrape/bin/python"
REQUIRED = ["Section", "Subsection", "Item", "Description"]


def newest_workbook():
    books = sorted(INTAKE.glob("review_*.xlsx"))
    if not books:
        raise SystemExit(f"no review_*.xlsx in {INTAKE}")
    return books[-1]


def read_workbook(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Review"]
    headers = [c.value for c in ws[1]]
    rows = []
    for values in ws.iter_rows(min_row=2, values_only=True):
        if not any(v not in (None, "") for v in values):
            continue
        row = {h: ("" if v is None else v) for h, v in zip(headers, values)}
        row["Status"] = (str(row.get("Status") or "").strip().upper() or "HOLD")
        rows.append(row)
    return rows


def validate(rows):
    errors = []
    for row in rows:
        if row["Status"] != "ACCEPT":
            continue
        qid = row.get("Queue id") or "?"
        for field in REQUIRED:
            if not str(row.get(field, "")).strip():
                errors.append(f"{qid}: {field} is empty on an ACCEPT row")
        section, sub = str(row.get("Section", "")), str(row.get("Subsection", ""))
        if section and sub:
            import intake_classify
            valid = intake_classify.valid_subs(section)
            if sub not in valid:
                errors.append(
                    f"{qid}: subsection {sub!r} does not exist in section {section}; "
                    f"valid names are {valid}")
    return errors


def apply_row(row, data):
    """Insert one accepted row into `data` and return the id it was given."""
    new_id = entries.next_id(data)
    item = {
        "id": new_id,
        "item": str(row["Item"]).strip(),
        "age": str(row.get("Age", "")).strip(),
        "link": str(row["Link"]).strip(),
        "price": str(row.get("Approx. price", "")).strip(),
        "desc": str(row["Description"]).strip(),
        "by": str(row.get("Suggested by", "")).strip(),
        "ngo": str(row.get("NGO / proceeds to conservation?", "")).strip(),
    }
    for section in data["sections"]:
        if section["number"] != str(row["Section"]):
            continue
        for sub in section["subsections"]:
            if sub["name"] == str(row["Subsection"]):
                sub["items"].append(item)
                return new_id
    raise SystemExit(f"section {row['Section']} subsection {row['Subsection']} not found")


def _picked_specs(row, queue_row):
    """Turn "0,3" plus the row's candidates into picks.json specs."""
    raw = str(row.get("Image pick", "")).strip()
    if not raw or not queue_row:
        return []
    specs = []
    for part in raw.split(","):
        part = part.strip()
        if not part.isdigit():
            continue
        index = int(part)
        cands = queue_row.get("candidates") or []
        if index < len(cands):
            specs.append("U:" + cands[index]["url"])
    return specs


def main(path=None, rebuild=True):
    path = Path(path) if path else newest_workbook()
    rows = read_workbook(path)
    errors = validate(rows)
    if errors:
        print(f"{len(errors)} problem(s); nothing was applied:")
        for e in errors:
            print("   ", e)
        raise SystemExit(1)

    data = entries.load_items()
    queue = {r["queue_id"]: r for r in intake_queue.load_queue()}
    all_picks = picks_mod.load_picks()

    accepted, rejected, held = [], [], []
    for row in rows:
        qid = row.get("Queue id") or ""
        if row["Status"] == "ACCEPT":
            entry_id = apply_row(row, data)
            specs = _picked_specs(row, queue.get(qid))
            all_picks[entry_id] = dict(specs=specs, note=f"from intake {qid}")
            accepted.append((qid, entry_id))
        elif row["Status"] == "REJECT":
            queue_row = queue.get(qid, {})
            if queue_row.get("url_norm"):
                intake_queue.reject(queue_row["url_norm"], "rejected in review")
            rejected.append(qid)
        else:
            held.append(qid)

    entries.save_items(data)
    picks_mod.save_picks(all_picks)
    intake_queue.save_queue([r for r in intake_queue.load_queue()
                             if r["queue_id"] in held])

    for _qid, entry_id in accepted:
        written, failures = picks_mod.render(entry_id, all_picks[entry_id]["specs"])
        for f in failures:
            print("   image failed:", f)

    print(f"{len(accepted)} accepted, {len(rejected)} rejected, {len(held)} held")
    for qid, entry_id in accepted:
        print(f"   {qid} -> {entry_id}")

    if rebuild and accepted:
        subprocess.run([VENV_PYTHON, str(ROOT / "build_docx.py")], check=True)
        subprocess.run([VENV_PYTHON, str(ROOT / "add_images.py")], check=True)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/.venvs/scrape/bin/python -m pytest tests/test_intake_apply.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 5: Run the whole suite**

Run: `~/.venvs/scrape/bin/python -m pytest tests/ -v`
Expected: PASS, every test from Tasks 1 to 11.

- [ ] **Step 6: Commit**

```bash
git add intake_apply.py tests/test_intake_apply.py
git commit -m "Apply the reviewed workbook into items.json, picks, and the docx

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Install the service and document the workflow

**Files:**
- Create: `shark-swag-intake.service`, `~/.config/systemd/user/shark-swag-intake.service` (symlink or copy)
- Modify: `README.md`

**Interfaces:**
- Consumes: `intake_watch.watch`.
- Produces: a running user service, and a documented end-to-end workflow.

- [ ] **Step 1: Create the Gmail filter by hand**

In the Gmail web UI: Settings, Filters and blocked addresses, Create a new filter. `To` is `simondedman+sharkswag@gmail.com`. Create filter, then tick **Skip the Inbox** and **Apply the label**, choosing a new label named exactly `sharkswag`.

Verify the folder exists over IMAP before writing the unit:

Run: `~/.venvs/scrape/bin/python -c "
import ssl
from imapclient import IMAPClient
from intake_watch import credentials, FOLDER
address, password = credentials()
with IMAPClient('imap.gmail.com', ssl_context=ssl.create_default_context()) as c:
    c.login(address, password)
    folders = [f[2] for f in c.list_folders()]
    assert FOLDER in folders, f'{FOLDER!r} not found; folders are {folders}'
    print(FOLDER, 'exists,', c.select_folder(FOLDER)[b'EXISTS'], 'message(s)')
"`
Expected: `sharkswag exists, N message(s)`

If the label does not appear, send one test email to the alias first: Gmail creates the label lazily.

- [ ] **Step 2: Dry-run the watcher against the real folder**

This reads the mailbox and writes nothing.

Run: `timeout 60 ~/.venvs/scrape/bin/python intake_watch.py --dry-run`
Expected: `connected, watching sharkswag` and a catch-up line. `intake/queue.json` must not appear.

Run: `ls intake/`
Expected: no `queue.json` and no `ledger.json`.

- [ ] **Step 3: Write the unit file**

Create `shark-swag-intake.service` in the project:

```ini
[Unit]
Description=Shark swag email intake (IMAP IDLE watcher)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/media/simon/data/Projects/shark-swag
ExecStart=/home/simon/.venvs/scrape/bin/python /media/simon/data/Projects/shark-swag/intake_watch.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

- [ ] **Step 4: Install and start it**

```bash
mkdir -p ~/.config/systemd/user
cp shark-swag-intake.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now shark-swag-intake.service
systemctl --user status shark-swag-intake.service --no-pager
```
Expected: `Active: active (running)`.

- [ ] **Step 5: Prove push works end to end**

Send an email to `simondedman+sharkswag@gmail.com` with one product URL in the body. Within about a minute:

Run: `journalctl --user -u shark-swag-intake.service -n 20 --no-pager`
Expected: a `push staged 1 row(s)` line.

Run: `~/.venvs/scrape/bin/python -c "
import json
from paths import QUEUE, HEARTBEAT
rows = json.loads(QUEUE.read_text())
print(len(rows), 'row(s) queued; last poll', HEARTBEAT.read_text().strip())
print(rows[-1]['url'], rows[-1]['fetch_status'], rows[-1]['title'][:60])
"`
Expected: one row with its URL, a fetch status, and a title.

- [ ] **Step 6: Build and apply a workbook for that submission**

Run: `~/.venvs/scrape/bin/python intake_sheet.py`
Expected: `1 rows -> /media/simon/data/Projects/shark-swag/intake/review_2026-08-28.xlsx`

Open the workbook, read the Info tab, fill in the Description, set Status to ACCEPT, save, then:

Run: `~/.venvs/scrape/bin/python intake_apply.py`
Expected: `1 accepted, 0 rejected, 0 held`, then the two rebuild commands, then `NN image rows inserted`.

Run: `~/.venvs/scrape/bin/python -c "
from entries import iter_entries
e = iter_entries()[-5:]
for x in e:
    print(x.id, x.section, x.sub, x.item[:50])
"`
Expected: the new entry with id `e89` in the section chosen in the sheet.

- [ ] **Step 7: Document the workflow in `README.md`**

Add a section after the pipeline table:

```markdown
## Adding a suggestion

Email a product link to `simondedman+sharkswag@gmail.com`, with any notes in
the body. A systemd user service (`shark-swag-intake.service`) watches the
`sharkswag` Gmail label over IMAP IDLE and stages the submission within
seconds: it fetches the page, reads off the title, price, and any sentence
about donations, guesses a section and age band from keywords, and downloads
candidate product images.

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
```

- [ ] **Step 8: Commit**

```bash
git add shark-swag-intake.service README.md
git commit -m "Install the intake watcher as a systemd user service

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
git push
```

---

## Done when

- `~/.venvs/scrape/bin/python -m pytest tests/ -v` is green.
- A link emailed to the alias appears in `intake/queue.json` within a minute, without a timer.
- `intake/review_<date>.xlsx` opens on an Info tab, with a frozen, bold, autofiltered header on every tab.
- An accepted row lands in `items.json` with a fresh id, and rebuilding the document leaves every earlier entry's images exactly where they were.
- Killing the service and sending mail while it is down, then starting it, stages the missed message on catch-up.
