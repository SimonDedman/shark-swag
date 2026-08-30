"""intake_draft.draft_description never touches the network in these tests:
every anthropic call is stubbed. The one real call this feature makes is a
manual, once-off end-to-end check reported by hand (see
.superpowers/draft-description-report.md), never run by the suite.
"""
import anthropic
import httpx2
import pytest

import intake_draft

ROW = dict(queue_id="q9001", title="Shark socks",
           blurb="Bamboo and cotton crew socks with a hammerhead silhouette "
                 "knitted into the sole.",
           blurb_source="shopify", ngo_text="")


class _Block:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _StopDetails:
    def __init__(self, category):
        self.category = category


class _Response:
    def __init__(self, content_text=None, stop_reason="end_turn", stop_details=None):
        self.content = [_Block(content_text)] if content_text is not None else []
        self.stop_reason = stop_reason
        self.stop_details = stop_details


class _FakeMessages:
    def __init__(self, create_fn):
        self.create = create_fn


class _FakeClient:
    def __init__(self, create_fn):
        self.messages = _FakeMessages(create_fn)


def _stub_client(monkeypatch, create_fn):
    """Replace anthropic.Anthropic so draft_description never opens a real
    connection. Patched on the module intake_draft actually calls through
    (`intake_draft.anthropic`), not a copy, so the except clauses in
    draft_description still catch the genuine anthropic exception classes
    raised by create_fn."""
    monkeypatch.setattr(intake_draft.anthropic, "Anthropic",
                         lambda api_key=None: _FakeClient(create_fn))


@pytest.fixture
def real_key_env(tmp_path, monkeypatch):
    """A .env holding a harmless placeholder key, so _api_key() succeeds
    without ever touching the real credential."""
    env = tmp_path / "fake.env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test-not-real\n")
    monkeypatch.setattr(intake_draft, "ENV_FILE", env)
    return env


def _request():
    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


# --- Grounded or empty ---

def test_a_row_with_no_blurb_never_touches_the_client(monkeypatch):
    def boom(api_key=None):
        raise AssertionError("should not construct a client without a blurb")
    monkeypatch.setattr(intake_draft.anthropic, "Anthropic", boom)
    description, note = intake_draft.draft_description(dict(ROW, blurb=""))
    assert description == ""
    assert "no page blurb" in note


def test_a_grounded_response_is_returned_verbatim(real_key_env, monkeypatch):
    payload = ('{"description": "Bamboo and cotton socks with a hammerhead '
               'silhouette knitted into the sole.", "grounded": true, '
               '"reason": "material and design are both stated on the page"}')
    _stub_client(monkeypatch, lambda **kw: _Response(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ("Bamboo and cotton socks with a hammerhead "
                            "silhouette knitted into the sole.")
    assert "drafted from shopify" in note


def test_an_ungrounded_response_returns_an_empty_description_with_the_reason(
        real_key_env, monkeypatch):
    payload = ('{"description": "", "grounded": false, '
               '"reason": "the page text says nothing specific about this item"}')
    _stub_client(monkeypatch, lambda **kw: _Response(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert note == "the page text says nothing specific about this item"


def test_a_grounded_true_but_empty_description_is_still_empty(real_key_env, monkeypatch):
    payload = '{"description": "", "grounded": true, "reason": ""}'
    _stub_client(monkeypatch, lambda **kw: _Response(payload))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "no text" in note


def test_an_unparsable_response_leaves_the_row_staged(real_key_env, monkeypatch):
    _stub_client(monkeypatch, lambda **kw: _Response("not json"))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "unparsable" in note


# --- Refusal: must check stop_reason before reading content ---

def test_a_refusal_returns_empty_and_names_the_category(real_key_env, monkeypatch):
    _stub_client(monkeypatch, lambda **kw: _Response(
        stop_reason="refusal", stop_details=_StopDetails("cyber")))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "refused" in note
    assert "cyber" in note


def test_a_refusal_with_no_content_does_not_crash(real_key_env, monkeypatch):
    """content is empty on a refusal; draft_description must check
    stop_reason before ever indexing into content."""
    _stub_client(monkeypatch, lambda **kw: _Response(
        content_text=None, stop_reason="refusal", stop_details=_StopDetails(None)))
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "refused" in note


# --- Never block the pipeline: specific exceptions, most-specific first ---

def test_a_missing_api_key_leaves_the_row_staged(tmp_path, monkeypatch):
    env = tmp_path / "empty.env"
    env.write_text("# nothing useful here\n")
    monkeypatch.setattr(intake_draft, "ENV_FILE", env)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "ANTHROPIC_API_KEY" in note
    assert "drafting skipped" in note


def test_an_unreadable_env_file_leaves_the_row_staged(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_draft, "ENV_FILE", tmp_path / "does-not-exist.env")
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "drafting skipped" in note


def test_a_rate_limit_error_leaves_the_row_staged(real_key_env, monkeypatch):
    def boom(**kw):
        raise anthropic.RateLimitError(
            "rate limited", response=httpx2.Response(429, request=_request()), body=None)
    _stub_client(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "rate limited" in note


def test_a_server_error_leaves_the_row_staged(real_key_env, monkeypatch):
    def boom(**kw):
        raise anthropic.APIStatusError(
            "server error", response=httpx2.Response(500, request=_request()), body=None)
    _stub_client(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "API error" in note
    assert "500" in note


def test_a_connection_error_leaves_the_row_staged(real_key_env, monkeypatch):
    def boom(**kw):
        raise anthropic.APIConnectionError(request=_request())
    _stub_client(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "network error" in note


def test_a_not_found_model_leaves_the_row_staged(real_key_env, monkeypatch):
    def boom(**kw):
        raise anthropic.NotFoundError(
            "not found", response=httpx2.Response(404, request=_request()), body=None)
    _stub_client(monkeypatch, boom)
    description, note = intake_draft.draft_description(ROW)
    assert description == ""
    assert "model not found" in note


def test_the_api_key_never_reaches_the_note(real_key_env, monkeypatch):
    def boom(**kw):
        raise anthropic.APIConnectionError(request=_request())
    _stub_client(monkeypatch, boom)
    _description, note = intake_draft.draft_description(ROW)
    assert "sk-ant-test-not-real" not in note


# --- Request shape: no budget_tokens, no assistant prefill, low effort ---

def test_the_request_uses_the_documented_model_and_parameters(real_key_env, monkeypatch):
    captured = {}

    def capture(**kw):
        captured.update(kw)
        return _Response('{"description": "x", "grounded": true, "reason": ""}')

    _stub_client(monkeypatch, capture)
    intake_draft.draft_description(ROW)
    assert captured["model"] == "claude-opus-5"
    assert captured["max_tokens"] == 512
    assert captured["output_config"]["effort"] == "low"
    assert "budget_tokens" not in captured
    assert all(m["role"] != "assistant" for m in captured["messages"])
    assert captured["extra_headers"]["Accept-Encoding"] == "gzip"
