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
