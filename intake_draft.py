#!/usr/bin/env python3
"""Draft the Description field from a product page's own words, via Claude.

Grounded or empty: every claim in the draft must trace to the page text
handed to the model. Nothing is inferred, embellished, or brought in from
outside knowledge, and an empty string is the correct answer when the page
text is too thin to say anything specific - that leaves intake_apply's
existing "an ACCEPT row must have a Description" gate doing its job. An
invented sentence would be far worse than an empty cell, because these
entries go into a document the owner's colleagues read.

Never blocks the pipeline: a missing key, a network failure, a rate limit,
or an outright refusal all leave the row staged with an empty description
and an explanatory note, never an exception that stops process_message from
staging the submission at all.
"""
import json

import anthropic

from paths import ENV_FILE

MODEL = "claude-opus-5"
MAX_TOKENS = 512

# Statuses with nothing on the page worth grounding a draft in: a blocked or
# dead fetch's blank fields say nothing about the product, and a message with
# no URL has no page to draft from at all.
UNDRAFTABLE_STATUSES = {"BLOCKED", "DEAD", "NO_URL"}

SYSTEM_PROMPT = """\
You draft the Description field for a shark-themed gift guide entry, from \
the seller's own product page text supplied in the user message. The guide's \
owner reads and edits every draft before it is ever seen by anyone else.

Ground rules, in order of importance:

1. Every claim you write must be directly supported by the supplied page \
text. Do not infer, embellish, or bring in anything from outside knowledge, \
even if it seems obviously true or you recognise the brand. If the page \
text is too thin to say anything specific and grounded, set grounded to \
false, description to an empty string, and give a short reason - that is \
the correct answer, not a failure. An invented sentence is far worse than \
an empty one.
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

DRAFT_SCHEMA = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": "The drafted Description, or an empty string "
                                "when grounded is false.",
            },
            "grounded": {
                "type": "boolean",
                "description": "True only if every claim in description is "
                                "directly supported by the supplied page text.",
            },
            "reason": {
                "type": "string",
                "description": "A short note on the grounding decision - why "
                                "the page text was or was not enough to draft "
                                "from.",
            },
        },
        "required": ["description", "grounded", "reason"],
        "additionalProperties": False,
    },
}


class ConfigError(Exception):
    """No key means no draft, not a program crash."""


def _api_key():
    """Read ANTHROPIC_API_KEY from the shared .env, the same way
    intake_watch.credentials() reads the Gmail values. Never logged."""
    try:
        text = ENV_FILE.read_text()
    except OSError as e:
        raise ConfigError(f"cannot read {ENV_FILE}: {type(e).__name__}: {e}")
    for line in text.splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "ANTHROPIC_API_KEY":
            value = value.strip().strip("'\"")
            if value:
                return value
    raise ConfigError(f"ANTHROPIC_API_KEY missing from {ENV_FILE}")


def _page_text(row):
    """Everything already known about the page, laid out for the model. Only
    facts the extractor itself read off the page - nothing guessed."""
    parts = [f"Product title: {row.get('title') or '(none read)'}"]
    parts.append(f"Page text: {row.get('blurb') or ''}")
    ngo_text = str(row.get("ngo_text") or "").strip()
    if ngo_text:
        parts.append(f"Sentence about donations/proceeds from the page: {ngo_text}")
    return "\n\n".join(parts)


def draft_description(row):
    """(description, note) for this queue row.

    description is empty whenever the model judged the page text too thin to
    ground a sentence in, or whenever drafting could not be attempted or
    completed at all; note explains which, and is safe to show the owner.
    """
    blurb = str(row.get("blurb") or "").strip()
    if not blurb:
        return "", "no page blurb to draft from"

    try:
        api_key = _api_key()
    except ConfigError as e:
        return "", f"drafting skipped: {e}"

    client = anthropic.Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": "low", "format": DRAFT_SCHEMA},
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _page_text(row)}],
            # This machine's ~/.venvs/scrape carries httpx2 2.12.0 alongside
            # the system "Brotli" package (1.1.0): httpx2's brotli decoder
            # calls decompressor.process(data, output_buffer_limit=...), a
            # brotlicffi-only signature, and that combination raises
            # "process() takes no keyword arguments" on every response,
            # surfacing here as an opaque APIConnectionError. Declining
            # brotli avoids the broken decode path entirely; gzip is still
            # negotiated so responses stay compressed on the wire.
            extra_headers={"Accept-Encoding": "gzip"},
        )
    except anthropic.NotFoundError as e:
        return "", f"drafting skipped: model not found ({e})"
    except anthropic.RateLimitError:
        return "", "drafting skipped: rate limited"
    except anthropic.APIStatusError as e:
        return "", f"drafting skipped: API error ({e.status_code})"
    except anthropic.APIConnectionError:
        return "", "drafting skipped: network error"

    if response.stop_reason == "refusal":
        category = getattr(response.stop_details, "category", None)
        return "", f"drafting skipped: refused ({category or 'no category given'})"

    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return "", "drafting skipped: unparsable response"

    reason = str(data.get("reason") or "").strip()
    if not data.get("grounded"):
        return "", reason or "page text too thin to draft a grounded sentence from"

    description = str(data.get("description") or "").strip()
    if not description:
        return "", "model reported grounded but returned no text"
    source = row.get("blurb_source") or "the page text"
    return description, f"drafted from {source}" + (f" ({reason})" if reason else "")
