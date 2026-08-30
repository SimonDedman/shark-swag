#!/usr/bin/env python3
"""Draft the Description field from a product page's own words, via the
local Claude Code CLI.

Grounded or empty: every claim in the draft must trace to the page text
handed to the model. Nothing is inferred, embellished, or brought in from
outside knowledge, and an empty string is the correct answer when the page
text is too thin to say anything specific - that leaves intake_apply's
existing "an ACCEPT row must have a Description" gate doing its job. An
invented sentence would be far worse than an empty cell, because these
entries go into a document the owner's colleagues read.

Drafting runs through the `claude` CLI rather than the Anthropic API, so it
draws on the owner's Claude Max subscription rather than a metered API key
that carries no credit. The systemd service's environment does not put
~/.local/bin on PATH, so the binary is invoked by its absolute path.

Never blocks the pipeline: a missing binary, a timeout, a non-zero exit, an
unparsable reply, or an outright refusal all leave the row staged with an
empty description and an explanatory note, never an exception that stops
process_message from staging the submission at all.
"""
import json
import subprocess

CLAUDE_BIN = "/home/simon/.local/bin/claude"
TIMEOUT_S = 180

# Statuses with nothing on the page worth grounding a draft in: a blocked or
# dead fetch's blank fields say nothing about the product, and a message with
# no URL has no page to draft from at all.
UNDRAFTABLE_STATUSES = {"BLOCKED", "DEAD", "NO_URL"}

INSTRUCTIONS = """\
You draft the Description field for a shark-themed gift guide entry, from \
the seller's own product page text supplied below. The guide's owner reads \
and edits every draft before it is ever seen by anyone else.

Ground rules, in order of importance:

1. Every claim you write must be directly supported by the supplied page \
text. Do not infer, embellish, or bring in anything from outside knowledge, \
even if it seems obviously true or you recognise the brand. If the page \
text is too thin to say anything specific and grounded, set grounded to \
false and description to an empty string - that is the correct answer, not \
a failure. An invented sentence is far worse than an empty one.
2. When you can write a grounded sentence, use the house voice: one or two \
sentences, British English, Oxford commas, concrete and specific about why \
the item is worth giving. Say what makes the thing good - a material, a \
named collaboration or charity, who made it and how, what makes the design \
or artwork accurate or unusual - never that it is good. No marketing \
adjectives, no exclamation marks, and never just restate the item's name.

House style, verbatim examples of the tone, length, and level of specificity \
wanted:
- "Made in New York from organic cotton, and the lemon shark print is a \
direct Sharks4Kids collaboration — rare to find species accuracy on a \
babygro."
- "\\"Sharks are jawesome\\" print on 100% organic cotton; the obvious gift \
for diver parents."
- "Combed organic cotton from an accredited public aquarium's own store; \
stock rotates, so the search link is the durable one."
- "Organic cotton, printed to order in a renewable-energy UK factory, so \
nothing is made until it's bought — and the species artwork is \
actually correct."
"""

REPLY_INSTRUCTION = (
    'Reply with exactly one JSON object and nothing else, in this exact '
    'shape: {"description": "...", "grounded": true or false}. No code '
    'fence, no explanation before or after it.'
)


def _page_text(row):
    """Everything already known about the page, laid out for the model. Only
    facts the extractor itself read off the page - nothing guessed."""
    parts = [f"Product title: {row.get('title') or '(none read)'}"]
    parts.append(f"Page text: {row.get('blurb') or ''}")
    ngo_text = str(row.get("ngo_text") or "").strip()
    if ngo_text:
        parts.append(f"Sentence about donations/proceeds from the page: {ngo_text}")
    return "\n\n".join(parts)


def _build_prompt(row):
    return (
        INSTRUCTIONS
        + "\nPage text to draft from:\n\n"
        + _page_text(row)
        + "\n\n"
        + REPLY_INSTRUCTION
    )


def _call_claude(prompt):
    """Run the local claude CLI once, headlessly.

    Returns (result_text, note). result_text is the model's raw reply text
    (the JSON payload's "result" key) on success, or None on any failure;
    note is None on success and an owner-safe explanation otherwise.
    """
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--output-format", "json",
             "--no-session-persistence"],
            capture_output=True, text=True, timeout=TIMEOUT_S)
    except FileNotFoundError:
        return None, "drafting skipped: claude CLI not found"
    except subprocess.TimeoutExpired:
        return None, f"drafting skipped: claude CLI timed out after {TIMEOUT_S}s"

    if proc.returncode != 0:
        return None, f"drafting skipped: claude CLI exited {proc.returncode}"

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, TypeError):
        return None, "drafting skipped: claude CLI produced no parsable output"

    if not isinstance(payload, dict):
        return None, "drafting skipped: claude CLI produced no parsable output"

    if payload.get("is_error"):
        subtype = payload.get("subtype") or "unknown error"
        return None, f"drafting skipped: claude CLI reported an error ({subtype})"

    result = payload.get("result")
    if not isinstance(result, str) or not result.strip():
        return None, "drafting skipped: claude CLI returned no result text"

    return result, None


def _extract_json_object(text):
    """The first balanced top-level {...} substring in text, or None.

    A brace counter rather than a greedy regex, so a reply with a sentence
    wrapped around a fenced code block ("Sure, here you go:\\n```json\\n{...}\\n```")
    still yields exactly the object and nothing past its closing brace.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _looks_like_plain_sentence(text):
    """True only for something that reads like a bare one- or two-sentence
    draft, never for structured text we simply failed to parse as JSON."""
    if not text or len(text) > 400:
        return False
    if "{" in text or "}" in text or "```" in text:
        return False
    enders = text.count(".") + text.count("!") + text.count("?")
    return 1 <= enders <= 3


def _parse_reply(text):
    """(parsed, note) from the model's raw reply text.

    parsed is a dict with "description" and "grounded" keys on success, or
    None if nothing usable could be recovered; note is None on a clean JSON
    parse, and an explanation otherwise (including the "used verbatim"
    fallback, which is still success - parsed is not None - but worth
    recording).
    """
    stripped = text.strip()
    json_text = _extract_json_object(stripped)
    if json_text is not None:
        try:
            data = json.loads(json_text)
        except (json.JSONDecodeError, TypeError):
            data = None
        if isinstance(data, dict) and "description" in data and "grounded" in data:
            return data, None

    if _looks_like_plain_sentence(stripped):
        return {"description": stripped, "grounded": True}, "reply was not JSON; used verbatim"

    return None, "drafting skipped: could not parse the reply"


def draft_description(row):
    """(description, note) for this queue row.

    description is empty whenever the model judged the page text too thin to
    ground a sentence in, or whenever drafting could not be attempted or
    completed at all; note explains which, and is safe to show the owner.
    """
    blurb = str(row.get("blurb") or "").strip()
    if not blurb:
        return "", "no page blurb to draft from"

    result_text, note = _call_claude(_build_prompt(row))
    if result_text is None:
        return "", note

    parsed, parse_note = _parse_reply(result_text)
    if parsed is None:
        return "", parse_note

    if not parsed.get("grounded"):
        return "", "page text too thin to draft a grounded sentence from"

    description = str(parsed.get("description") or "").strip()
    if not description:
        return "", "model reported grounded but returned no text"

    source = row.get("blurb_source") or "the page text"
    note = f"drafted from {source}"
    if parse_note:
        note += f" ({parse_note})"
    return description, note
