"""intake_draft.draft_description never touches the real claude CLI in these
tests: every subprocess.run call is stubbed. The one real call this feature
makes is a manual, once-off end-to-end check reported by hand (see
.superpowers/cli-drafting-report.md), never run by the suite.
"""
import json
import subprocess

import pytest

import intake_draft

ROW = dict(queue_id="q9001", title="Shark socks",
           blurb="Bamboo and cotton crew socks with a hammerhead silhouette "
                 "knitted into the sole.",
           blurb_source="shopify", ngo_text="")


def _cli_result(result_text, is_error=False, subtype="success"):
    """The JSON stdout the real `claude -p ... --output-format json` prints,
    trimmed to the keys draft_description actually reads."""
    return json.dumps({"result": result_text, "is_error": is_error, "subtype": subtype})


def _completed(stdout, returncode=0):
    return subprocess.CompletedProcess(args=["claude"], returncode=returncode,
                                        stdout=stdout, stderr="")


def _stub_run(monkeypatch, fn):
    """Replace subprocess.run as intake_draft calls it, so draft_description
    never spawns a real process."""
    monkeypatch.setattr(intake_draft.subprocess, "run", fn)


# --- Grounded or empty ---

def test_a_row_with_no_blurb_never_touches_the_cli(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("should not run the CLI without a blurb")
    monkeypatch.setattr(intake_draft.subprocess, "run", boom)
    description, note = intake_draft.draft_description(dict(ROW, blurb=""))
    assert description == ""
    assert "no page blurb" in note


def test_a_grounded_response_is_returned_verbatim(monkeypatch):
    payload = _cli_result(_reply_json(
        "Bamboo and cotton socks with a hammerhead silhouette knitted into "
        "the sole.", True))
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ("Bamboo and cotton socks with a hammerhead "
                            "silhouette knitted into the sole.")
    assert "drafted from shopify" in note


def test_an_ungrounded_response_returns_an_empty_description(monkeypatch):
    payload = _cli_result(_reply_json("", False))
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "too thin" in note


def test_a_grounded_true_but_empty_description_is_still_empty(monkeypatch):
    payload = _cli_result(_reply_json("", True))
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "no text" in note


# --- Tolerant parsing of the model's reply ---

def _reply_json(description, grounded):
    return json.dumps({"description": description, "grounded": grounded})


def test_a_bare_json_object_reply_parses(monkeypatch):
    payload = _cli_result(_reply_json("A grounded sentence about socks.", True))
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == "A grounded sentence about socks."
    assert "drafted from shopify" in note


def test_a_fenced_json_reply_parses(monkeypatch):
    fenced = "```json\n" + _reply_json("A grounded sentence about socks.", True) + "\n```"
    payload = _cli_result(fenced)
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == "A grounded sentence about socks."


def test_a_json_reply_wrapped_in_a_sentence_parses(monkeypatch):
    wrapped = ("Sure, here is the object you asked for: "
               + _reply_json("A grounded sentence about socks.", True)
               + " Let me know if you need anything else.")
    payload = _cli_result(wrapped)
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == "A grounded sentence about socks."


def test_a_bare_plausible_sentence_reply_is_used_verbatim(monkeypatch):
    """No JSON at all, but the reply reads like a real one-sentence draft -
    used, but flagged in the note rather than silently trusted."""
    payload = _cli_result("Bamboo and cotton socks with a hammerhead motif "
                           "knitted into the sole.")
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ("Bamboo and cotton socks with a hammerhead motif "
                            "knitted into the sole.")
    assert "not JSON" in note


def test_a_reply_that_parses_to_nothing_is_never_used_as_a_description(monkeypatch):
    """Garbled, non-JSON, non-sentence-shaped output must never leak through
    as a description - it must come back empty with an explanatory note."""
    payload = _cli_result("{unterminated: true, description")
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "could not parse" in note


# --- Never block the pipeline: CLI/transport failures ---

def test_a_missing_binary_leaves_the_row_staged(monkeypatch):
    def boom(*a, **kw):
        raise FileNotFoundError("no such file")
    _stub_run(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "not found" in note


def test_a_timeout_leaves_the_row_staged(monkeypatch):
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=intake_draft.TIMEOUT_S)
    _stub_run(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "timed out" in note


def test_a_nonzero_exit_leaves_the_row_staged(monkeypatch):
    _stub_run(monkeypatch, lambda *a, **kw: _completed("", returncode=1))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "exited 1" in note


def test_an_error_reported_by_the_cli_leaves_the_row_staged(monkeypatch):
    payload = json.dumps({"result": "", "is_error": True, "subtype": "error_during_execution"})
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "error_during_execution" in note


def test_unparsable_cli_stdout_leaves_the_row_staged(monkeypatch):
    _stub_run(monkeypatch, lambda *a, **kw: _completed("not json at all"))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "no parsable output" in note


def test_a_missing_result_key_leaves_the_row_staged(monkeypatch):
    payload = json.dumps({"is_error": False, "subtype": "success"})
    _stub_run(monkeypatch, lambda *a, **kw: _completed(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "no result text" in note


# --- Request shape: absolute binary path, no session persistence, no
# --system-prompt flags, prompt carries the grounding rules and the page
# text, timeout enforced ---

def test_the_cli_is_invoked_with_the_documented_flags(monkeypatch):
    captured = {}

    def capture(cmd, **kw):
        captured["cmd"] = cmd
        captured["kwargs"] = kw
        return _completed(_cli_result(_reply_json("x", True)))

    _stub_run(monkeypatch, capture)
    intake_draft.draft_description(ROW)

    cmd = captured["cmd"]
    assert cmd[0] == "/home/simon/.local/bin/claude"
    assert cmd[0] == intake_draft.CLAUDE_BIN
    assert "-p" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--no-session-persistence" in cmd
    assert "--system-prompt" not in cmd
    assert "--exclude-dynamic-system-prompt-sections" not in cmd
    assert captured["kwargs"]["timeout"] == 180

    prompt = cmd[cmd.index("-p") + 1]
    assert "Bamboo and cotton crew socks" in prompt
    assert "British English" in prompt
    assert "grounded" in prompt
