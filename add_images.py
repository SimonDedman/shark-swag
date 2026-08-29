#!/usr/bin/env python3
"""Edit shark-swag-suggestions.docx in place:

  * every entry's "> <item>" line becomes Heading 3, so it appears in the
    navigation tree under its age-band Heading 2;
  * a row of product images is inserted after each entry's NGO line.

Edited in place rather than rebuilt from build_docx.py so the manual wording
changes already made in the Gaps section survive.
"""
import copy, json, re, sys
from pathlib import Path

import docx
from docx.shared import Pt, Inches, Emu
from PIL import Image


ROOT = Path("/media/simon/data/Projects/shark-swag")
FIN = ROOT / "images" / "final"
DOC = ROOT / "shark-swag-suggestions.docx"

ROW_H_IN = 1.34          # 8 lines of 10.5pt Calibri at 1.15 line spacing
MAX_ROW_W_IN = 6.4       # usable width inside the default 1in margins
GAP_IN = 0.08


def entry_key(order, existing_names):
    """items.json order, with the four pre-existing doc entries appended -
    the same order picks.py numbers them in."""
    return order


def build_order():
    data = json.loads((ROOT / "items.json").read_text())
    names = []
    for s in data["sections"]:
        for sub in s["subsections"]:
            for it in sub["items"]:
                names.append(it["item"])
    names += ["SPHYRNAS — tees, hoodies, hats, accessories",
              "Sharks Preschool Activity Book",
              "Underwater Photography and Editing Ebooks",
              "Colouring & Facts Book (currently only available as PDF)"]
    return names


def insert_after(paragraph, doc):
    new_p = copy.deepcopy(paragraph._p)
    for child in list(new_p):
        new_p.remove(child)
    paragraph._p.addnext(new_p)
    return docx.text.paragraph.Paragraph(new_p, paragraph._parent)


def main():
    names = build_order()
    doc = docx.Document(DOC)
    paras = doc.paragraphs

    # locate each entry: the "> name" paragraph and its NGO line
    entries, i = [], 0
    while i < len(paras):
        t = paras[i].text
        if t.startswith("▸ "):
            head = paras[i]
            j = i + 1
            ngo = None
            while j < len(paras) and not paras[j].text.startswith("▸ "):
                if paras[j].text.startswith("NGO / proceeds to conservation?"):
                    ngo = paras[j]
                    break
                j += 1
            entries.append((head, ngo))
            i = j
        else:
            i += 1
    print(f"{len(entries)} entries found in the docx")

    # match docx order to picks order by the item name on the heading line
    name_to_idx = {}
    for n, nm in enumerate(names, 1):
        name_to_idx.setdefault(nm, []).append(n)

    used, placed, missing, headings = set(), 0, [], 0
    for head, ngo in entries:
        raw = head.text[2:]
        nm = re.sub(r"\s*\[(already in doc|splurge)\]\s*$", "", raw).strip()

        head.style = doc.styles["Heading 3"]
        head.paragraph_format.space_before = Pt(10)
        head.paragraph_format.space_after = Pt(2)
        headings += 1

        cands = [k for k in name_to_idx.get(nm, []) if k not in used]
        if not cands:
            missing.append(nm)
            continue
        idx = cands[0]
        used.add(idx)

        files = sorted(FIN.glob(f"e{idx:02d}_*.jpg"))
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

    doc.save(DOC)
    print(f"{headings} entry headings promoted to Heading 3")
    print(f"{placed} image rows inserted")
    if missing:
        print("unmatched entry names:", missing)


if __name__ == "__main__":
    main()
