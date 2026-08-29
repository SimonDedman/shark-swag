#!/usr/bin/env python3
"""Edit shark-swag-suggestions.docx in place:

  * every entry's "> <item>" line becomes Heading 3, so it appears in the
    navigation tree under its age-band Heading 2;
  * a row of product images is inserted after each entry's NGO line.

Edited in place rather than rebuilt from build_docx.py so the manual wording
changes already made in the Gaps section survive.

Entries are matched to their ids by item name AND the section and subsection
headings they sit under. Name alone was enough only while ids were positional:
the document and the id list then happened to agree, so taking the lowest
unused id for each name in document order was right by accident. Ids are now
stable data, so a resubmitted item that already exists elsewhere in the guide
would take a later id, meet the document's first occurrence of its name first,
and shift every occurrence of that name onto the wrong pictures, while
`missing` reported nothing because each name still resolved.
"""
import copy, re, sys

import docx
from docx.shared import Pt, Inches, Emu
from PIL import Image

from entries import iter_entries
from paths import FINAL, DOCX

ROW_H_IN = 1.34          # 8 lines of 10.5pt Calibri at 1.15 line spacing
MAX_ROW_W_IN = 6.4       # usable width inside the default 1in margins
GAP_IN = 0.08

FLAG = re.compile(r"\s*\[(already in doc|splurge)\]\s*$")


def entry_index():
    """(item name, section number, subsection name) to the ids that carry it.

    build_docx.py writes a Heading 1 per section and a Heading 2 per
    subsection, so the walk below always knows both while reading an entry.
    Ids stay in id order within a key, and a key with more than one id is a
    genuine ambiguity rather than an ordering to exploit.
    """
    mapping = {}
    for e in sorted(iter_entries(), key=lambda e: int(e.id[1:])):
        mapping.setdefault((e.item, e.section, e.sub), []).append(e.id)
    return mapping


def images_for(entry_id):
    return sorted(FINAL.glob(f"{entry_id}_*.jpg"))


def insert_after(paragraph, doc):
    new_p = copy.deepcopy(paragraph._p)
    for child in list(new_p):
        new_p.remove(child)
    paragraph._p.addnext(new_p)
    return docx.text.paragraph.Paragraph(new_p, paragraph._parent)


def walk(paras):
    """Every entry in the document as (head paragraph, NGO paragraph, section
    number, subsection name). The NGO paragraph is None if the entry has none."""
    found = []
    section = sub = ""
    for p in paras:
        style = p.style.name if p.style is not None else ""
        text = p.text
        if style == "Heading 1":
            section = text.split(".", 1)[0].strip()
            sub = ""
        elif style == "Heading 2":
            sub = text.strip()
        elif text.startswith("▸ "):
            found.append([p, None, section, sub])
        elif (text.startswith("NGO / proceeds to conservation?")
              and found and found[-1][1] is None):
            found[-1][1] = p
    return found


def main(path=None, index=None):
    path = path or DOCX
    index = entry_index() if index is None else index
    doc = docx.Document(path)
    found = walk(doc.paragraphs)
    print(f"{len(found)} entries found in the docx")

    used, placed, missing, ambiguous, headings = set(), 0, [], {}, 0
    for head, ngo, section, sub in found:
        name = FLAG.sub("", head.text[2:]).strip()

        head.style = doc.styles["Heading 3"]
        head.paragraph_format.space_before = Pt(10)
        head.paragraph_format.space_after = Pt(2)
        headings += 1

        key = (name, section, sub)
        cands = [i for i in index.get(key, []) if i not in used]
        if not cands:
            missing.append(key)
            continue
        if len(cands) > 1:
            # Two entries with the same name in the same subsection. Guessing
            # here is how the wrong pictures got attached last time, so the run
            # says so instead and leaves both without images.
            ambiguous.setdefault(key, list(index[key]))
            missing.append(key)
            continue
        entry_id = cands[0]
        used.add(entry_id)

        files = images_for(entry_id)
        if not files or ngo is None:
            continue

        sizes = [Image.open(f).size for f in files]
        widths = [ROW_H_IN * w / h for w, h in sizes]
        total = sum(widths) + GAP_IN * (len(files) - 1)
        scale = min(1.0, MAX_ROW_W_IN / total)

        p = insert_after(ngo, doc)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(2)
        for n, (f, w) in enumerate(zip(files, widths)):
            if n:
                p.add_run("  ")
            p.add_run().add_picture(str(f), width=Inches(w * scale),
                                    height=Inches(ROW_H_IN * scale))
        placed += 1

    doc.save(path)
    print(f"{headings} entry headings promoted to Heading 3")
    print(f"{placed} image rows inserted")
    for key, ids in sorted(ambiguous.items()):
        print(f"AMBIGUOUS: {key[0]!r} appears twice in section {key[1]} "
              f"{key[2]!r} as {ids}; no images were placed for either. "
              f"Rename one, or move it, so the pairing is decidable.")
    if missing:
        print("unmatched entries (name, section, subsection):", missing)
    return dict(headings=headings, placed=placed, missing=missing,
                ambiguous=ambiguous)


if __name__ == "__main__":
    main()
