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
