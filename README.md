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

A second run of `intake_sheet.py` on the same day writes a time-suffixed
workbook beside the first rather than overwriting it, and `intake_apply.py`
refuses a workbook it has already applied: an accepted row leaves the queue,
and a row that is ACCEPT but no longer queued is the signature of a second run.

### Setting the intake up, once

1. **Create the Gmail filter by hand.** Settings, Filters and blocked
   addresses, Create a new filter. `To` is `simondedman+sharkswag@gmail.com`.
   Create filter, then tick Skip the Inbox and Apply the label, choosing a new
   label named exactly `sharkswag`. Gmail creates the label lazily, so if it
   does not appear, send one test email to the alias first.

2. **Check the folder is visible over IMAP**, which also checks the credentials
   in `~/Documents/obsidian-pkm/.env` (`GMAIL_ADDRESS` and
   `GMAIL_APP_PASSWORD`, an app password, never the account password):

        ~/.venvs/scrape/bin/python -c "
        import ssl
        from imapclient import IMAPClient
        from intake_watch import credentials, FOLDER
        address, password = credentials()
        with IMAPClient('imap.gmail.com', ssl_context=ssl.create_default_context()) as c:
            c.login(address, password)
            assert FOLDER in [f[2] for f in c.list_folders()]
            print(FOLDER, 'exists,', c.select_folder(FOLDER)[b'EXISTS'], 'message(s)')
        "

   Expect `sharkswag exists, N message(s)`.

3. **Dry-run it against the real folder first.** This reads the mailbox and
   writes nothing at all: no queue, no ledger, no heartbeat, no log line.

        timeout 60 ~/.venvs/scrape/bin/python intake_watch.py --dry-run
        ls intake/          # no queue.json, no ledger.json

   Expect `connected, watching sharkswag` and a catch-up line.

4. **Install and start the service.**

        mkdir -p ~/.config/systemd/user
        cp shark-swag-intake.service ~/.config/systemd/user/
        systemctl --user daemon-reload
        systemctl --user enable --now shark-swag-intake.service
        systemctl --user status shark-swag-intake.service --no-pager

   Expect `Active: active (running)`.

5. **Prove push works end to end.** Send an email to the alias with one product
   URL in the body, then within about a minute expect a `push staged 1 row(s)`
   line from `journalctl --user -u shark-swag-intake.service -n 20 --no-pager`.

Service state:

    systemctl --user status shark-swag-intake.service
    journalctl --user -u shark-swag-intake.service -f
    cat intake/heartbeat        # last successful poll

The heartbeat is the one to read: it is written after every successful poll, so
a timestamp older than about six hours means the daemon is running but not
reaching Gmail, which `systemctl status` alone will not tell you. Liveness is
systemd's business and nothing here checks for a running process; a `pgrep -f`
pattern matches the searching command itself in this harness and always says
yes.

The unit sets `RestartPreventExitStatus=78`. A missing credential or an
unreadable file under `intake/` cannot be fixed by trying again in thirty
seconds, so the daemon logs why once and stays down instead of looping with the
reason buried in the journal. `systemctl --user status` shows the exit code;
`intake/intake.log` holds the reason.

## Design notes

`docs/superpowers/specs/` carries the design documents, including the planned
email intake system for onboarding new suggestions.

## Caches

`images/raw`, `images/htmlcache`, `images/pool`, and `images/sheets` are
gitignored and regenerable, at the cost of re-fetching every source. Some
sources have since gone dead, so `images/final/` is the durable copy of the
chosen images.
