import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import paths          # noqa: E402
import intake_apply   # noqa: E402
import intake_queue   # noqa: E402
import intake_sheet   # noqa: E402
import intake_watch   # noqa: E402

# Every module that binds one of these names via `from paths import X`,
# enumerated by grepping every "from paths import" in the repo rather than
# guessed (see .superpowers/test-isolation-report.md for the grep and its
# output) - a name left off this list is a hole this guard cannot see
# through, and `from paths import X` binds X locally in that module, so
# patching paths.X alone leaves that binding pointed at the real file.
#
# Only the writable state a running pipeline can overwrite is redirected.
# Read-only committed project data - items.json, existing.json,
# images/picks.json, images/candidates.json, images/pool.json, the HTML
# cache, the docx, images/final, images/raw, images/pool, images/ itself,
# the project root, and the .env file - is deliberately left alone: several
# existing tests (test_entries.py, test_pool_keys.py, test_picks.py,
# test_add_images.py) legitimately read it by its real path.
WRITABLE_NAMES = ("SHEETS", "LEDGER", "QUEUE", "REJECTED", "HEARTBEAT", "INTAKE_LOG")

# Every module known to hold one of the above as its own `from paths import`
# binding: intake_queue (LEDGER, QUEUE, REJECTED), intake_watch (all six),
# intake_apply (SHEETS), intake_sheet (SHEETS), plus paths itself, the
# common source every one of those bindings was copied from at import time.
_MODULES_HOLDING_A_BINDING = (paths, intake_queue, intake_watch, intake_apply, intake_sheet)


@pytest.fixture(autouse=True)
def isolate_writable_project_state(tmp_path, monkeypatch):
    """Redirect every writable path the intake pipeline can write to -
    contact sheets, the ledger, the queue, the rejected list, the heartbeat,
    and the intake log - into this test's own tmp_path, at every module that
    holds its own binding of the name.

    This exists because the guard used to be opt-in, one
    `monkeypatch.setattr(intake_sheet, "SHEETS", tmp_path)` line at a time in
    every test that built a contact sheet, and a test added later without
    that line wrote a real contact sheet straight into
    images/sheets/pending_q0001.jpg - the id of a real staged submission -
    which was then embedded into the owner's live review workbook in place
    of his actual product photo.

    test_isolation_guard_protects_the_real_sheets_dir (in
    test_intake_sheet.py) is the control that proves this: it deliberately
    does not patch intake_sheet.SHEETS itself, the way every other contact
    sheet test must remember to, and fails if this fixture is ever removed.
    """
    for name in WRITABLE_NAMES:
        target = tmp_path / name.lower()
        for mod in _MODULES_HOLDING_A_BINDING:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, target)
    return tmp_path
