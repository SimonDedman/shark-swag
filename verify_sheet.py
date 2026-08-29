#!/usr/bin/env python3
"""Contact sheet of the FINAL picks, laid out as the docx will show them."""
import json, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path("/media/simon/data/Projects/shark-swag")
FIN = ROOT / "images" / "final"
POOL = json.loads((ROOT / "images" / "pool.json").read_text())

font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 19)
ROW_H, HDR, W = 150, 28, 2200
rows = []
for i in range(1, 89):
    imgs = sorted(FIN.glob(f"e{i:02d}_*.jpg"))
    rows.append((i, POOL[str(i)]["item"], imgs))

per = 7
for s in range(0, len(rows), per):
    chunk = rows[s:s + per]
    H = len(chunk) * (ROW_H + HDR + 12) + 16
    sheet = Image.new("RGB", (W, H), (252, 252, 252))
    dr = ImageDraw.Draw(sheet)
    y = 8
    for i, name, imgs in chunk:
        dr.text((10, y), f"[{i}] {name[:110]}" + ("   << NO IMAGE >>" if not imgs else ""),
                fill=(0, 0, 0) if imgs else (190, 0, 0), font=font)
        y += HDR
        x = 12
        for p in imgs:
            im = Image.open(p)
            im.thumbnail((900, ROW_H))
            sheet.paste(im, (x, y))
            x += im.size[0] + 10
        dr.line([(0, y + ROW_H + 6), (W, y + ROW_H + 6)], fill=(225, 225, 225))
        y += ROW_H + 12
    sheet.save(ROOT / "images" / f"verify{s//per:02d}.jpg", "JPEG", quality=88)
print("verification sheets written")
