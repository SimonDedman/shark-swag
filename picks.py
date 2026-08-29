#!/usr/bin/env python3
"""Chosen image per entry, rendered to the size the docx embeds.

Specs: "P:<pool_key>" reuses a pool candidate; "U:<url>" is a source the pool
missed; an optional "|crop=l,t,r,b" gives fractional crop bounds applied before
the automatic padding trim.
"""
import json, sys
from pathlib import Path
from PIL import Image

sys.path.insert(0, "/media/simon/data/Projects/shark-swag")
from imgproc import download, load, autocrop, to_height, TARGET_H

ROOT = Path("/media/simon/data/Projects/shark-swag")
POOL = json.loads((ROOT / "images" / "pool.json").read_text())
OUT = ROOT / "images" / "final"
OUT.mkdir(parents=True, exist_ok=True)

S4K_BOOKS = "https://static.wixstatic.com/media/7ab14d_be479428acc64ade8e1d3f7a76cbc4d3~mv2.jpg"
MISS_TEE = ("https://ih1.redbubble.net/image.6013215274.7262/ssrco,classic_tee,mens_02,"
            "101010:01c5ca27c6,front,product_square,x600.u2.jpg")
CDN = "https://cdn.shopify.com/s/files/1"
# Shark Trust's Oceanic 31 art prints live in their own collection, not the
# shop root that /collections returned.
O31 = "https://cdn.shopify.com/s/files/1/1141/5276/products"

PICKS = {
 1:  ["P:1_00"],
 2:  [],                                     # PADI Gear storefront is JS-only
 3:  ["P:3_00"],   # first hit on the shop search; it is the octopus bodysuit, not a shark print
 4:  [f"U:https://images.podos.io/t2olir70sekgiwrvh0dwztxvl1ho54rw4oehiobenm7e0nre.jpeg.jpg?w=1110", "P:4_00", "P:4_02", "P:4_11"],
 5:  ["P:5_00", "P:5_01", "P:5_03", "P:5_05"],
 6:  ["P:6_00"],
 7:  [f"U:{MISS_TEE}", "P:7_01", "P:7_05", "P:7_08"],
 8:  ["P:8_10", "P:8_09", "P:8_11", "P:8_05"],
 9:  [f"U:{CDN}/0025/9027/7685/files/Sharkflatlaysq-PhotoRoom.jpg"],
 10: ["P:10_00"],
 11: ["P:11_00"],
 12: ["P:12_01"],
 13: ["P:13_02", "P:13_04", "P:13_05", "P:13_09"],
 14: [],                                     # Wix storefront is JS-only
 15: ["P:15_08", "P:15_05", "P:15_09", "P:15_10"],
 16: ["P:16_00|crop=0,0.44,1,1"],
 17: ["P:17_00|crop=0,0.44,1,1"],
 18: ["P:18_00", "P:18_02", "P:18_03", "P:18_08"],
 19: ["P:19_00"],
 20: ["P:20_00"],
 21: ["P:21_00"],
 22: ["P:22_00"],
 23: ["P:23_00"],
 24: ["P:24_00"],
 25: [f"U:https://www.lego.com/cdn/cs/set/assets/blt360959af12fb5bfc/31381_Prod_en-gb.png?fit=bounds&width=800&height=800",
      f"U:https://www.lego.com/cdn/cs/set/assets/blt563c6451b3962ef5/5006627.jpg?fit=bounds&width=800&height=800",
      f"U:https://www.lego.com/cdn/cs/set/assets/bltf51319e5e0f94542/21350.png?fit=bounds&width=800&height=800"],
 26: ["P:26_00"],
 27: ["P:27_00"],
 28: ["P:28_00"],
 29: ["P:29_00"],
 30: [f"U:https://m.media-amazon.com/images/P/B001YIT1YI.01._SCLZZZZZZZ_.jpg"],
 31: ["P:31_00"],
 32: ["P:32_00"],
 33: ["P:33_00"],
 34: ["P:34_01"],
 35: ["U:https://www.abramsbooks.com/cover_images/2/9781419719202_s3.jpg"],
 36: ["P:36_00"],
 37: ["P:37_00"],
 38: ["P:38_00"],
 39: [f"U:{S4K_BOOKS}"],
 40: [f"U:https://m.media-amazon.com/images/P/0593685253.01._SCLZZZZZZZ_.jpg"],
 41: ["P:41_00"],
 42: ["P:42_02"],   # Amazon /images/P/<isbn> returns the wrong title for this one
 43: ["P:43_01"],
 44: ["P:44_00"],
 45: ["P:45_00"],
 46: ["P:46_00"],
 47: ["P:47_00"],
 48: ["P:48_00"],
 49: ["P:49_01"],
 50: ["P:50_09"],
 51: ["P:51_02", "P:51_03", "P:51_09", "P:51_11"],
 52: [f"U:{CDN}/0490/8007/4397/files/15539137955485119819.png",
      f"U:{CDN}/0490/8007/4397/files/womens-shark-print-bikini-2PC-c.png",
      f"U:{CDN}/0490/8007/4397/files/shark_print_bikini_bottoms.png"],
 53: ["P:53_00"],
 54: [f"U:{CDN}/0468/6004/2395/products/53103_florida_sharks_side1_b85d7d68-d0fd-4e35-86d9-5b398c0db587.jpg",
      f"U:{CDN}/0468/6004/2395/products/Hawaiian_Sharks_and_rays_side_1_fd5c4eea-5050-410f-adc5-090dfb2cf3bf.jpg",
      f"U:{CDN}/0468/6004/2395/products/California_sharks_inshore_v2_45ae9ce3-2d2d-4ff2-8706-b42e763e78e0.jpg",
      f"U:{CDN}/0468/6004/2395/files/BahamasSharks_RaysSide1.jpg"],
 55: [f"U:https://m.media-amazon.com/images/P/B001YIT1YI.01._SCLZZZZZZZ_.jpg"],
 56: ["P:56_00"],
 57: ["P:57_00"],
 58: [f"U:{S4K_BOOKS}"],
 59: ["P:59_00"],
 60: [f"U:{O31}/9e948dea1ac14b3897e112796233f078_de14ea44-29a8-4bfa-a757-c9c6ee0003af.jpg",
      f"U:{O31}/5bd6fb2735134dfaa5189e8a552f7824_aa9eb593-4a97-4fdb-a284-6802fdbfda5e.jpg",
      f"U:{O31}/d5de0eba0e7f49b48a3bce86a51caa5f.jpg",
      f"U:{O31}/9543ef91de1947f7a05e74d9ebb61ce5.jpg"],
 61: ["P:61_01", "P:61_06", "P:61_08", "P:61_10"],
 62: ["P:62_01", "P:15_01", "P:32_00",
      f"U:{O31}/5bd6fb2735134dfaa5189e8a552f7824_aa9eb593-4a97-4fdb-a284-6802fdbfda5e.jpg"],
 63: ["P:63_00", "P:63_01", "P:63_02", "P:63_08"],
 64: [f"U:{S4K_BOOKS}", "P:64_01", "P:64_03", "P:64_05"],
 65: [f"U:{MISS_TEE}", "P:65_01", "P:65_08", "P:65_11"],
 66: [],                                     # Wix storefront is JS-only
 67: ["P:67_09", "P:67_10"],
 68: [f"U:{CDN}/0500/4820/4965/files/TR25-0869.jpg",
      f"U:{CDN}/0500/4820/4965/products/c43ad12666d5ea6e52a67f3dc1a4f366.jpg",
      f"U:{CDN}/0500/4820/4965/products/54e743e3996a4d694dfee960e4ca9e19.jpg",
      f"U:{CDN}/0500/4820/4965/products/ff999cbd4cf7968cc1560a20fb1ba1ce.jpg"],
 69: ["P:69_01", "P:69_05", "P:69_09", "P:69_10"],
 70: ["P:70_01", "P:70_04",
      "U:https://sharkstewards.org/wp-content/uploads/2020/03/Mens-Front.png",
      "P:70_08"],
 71: ["P:71_00"],
 72: ["P:72_00", "P:72_02", "P:72_07", "P:72_10"],
 73: ["P:73_04", "P:73_05", "P:73_07"],
 74: ["P:74_00"],
 75: ["P:75_02"],
 76: ["P:76_01"],
 77: ["P:77_00"],
 78: ["U:https://www.aquariumofpacific.org/images/exhibits/Blacktip-Reef-Shark_LRG.jpg",
      "U:https://www.aquariumofpacific.org/images/exhibits/Zebra-shark-swimming_LRG.jpg"],
 79: ["P:79_02"],
 80: ["P:80_00"],
 81: ["P:81_01"],
 82: ["P:82_00"],
 83: ["U:https://codeblackfossils.com/wp-content/uploads/2023/12/1000011960.jpg"],
 84: ["P:84_00"],
 85: ["P:85_00", "P:85_04", "P:85_05", "P:85_08"],
 86: ["P:86_00"],
 87: ["P:87_04", "P:87_06", "P:87_10"],
 88: ["P:88_06"],
}


def resolve(spec):
    body, _, opts = spec.partition("|")
    crop = None
    for o in opts.split("|"):
        if o.startswith("crop="):
            crop = [float(x) for x in o[5:].split(",")]
    kind, _, val = body.partition(":")
    if kind == "P":
        k, j = val.rsplit("_", 1)
        return POOL[k]["cands"][int(j)]["url"], POOL[k]["link"], crop
    return val, None, crop


def main():
    log = []
    for idx, specs in sorted(PICKS.items()):
        for n, spec in enumerate(specs):
            url, ref, crop = resolve(spec)
            p, note = download(url, referer=ref)
            if p is None:
                log.append((idx, n, "FAIL " + note, url))
                continue
            im = load(p)
            if crop:
                w, h = im.size
                im = im.crop((int(crop[0] * w), int(crop[1] * h),
                              int(crop[2] * w), int(crop[3] * h)))
            im, tnote = autocrop(im)
            im = to_height(im, TARGET_H)
            im.save(OUT / f"e{idx:02d}_{n}.jpg", "JPEG", quality=92, subsampling=0)
            log.append((idx, n, f"ok {im.size[0]}x{im.size[1]}", url))
    fails = [l for l in log if l[2].startswith("FAIL")]
    print(f"{len(log)-len(fails)} images written, {len(fails)} failed")
    for f in fails:
        print("   ", f)
    empty = [i for i, s in PICKS.items() if not s]
    print("entries deliberately without an image:", empty)


if __name__ == "__main__":
    main()
