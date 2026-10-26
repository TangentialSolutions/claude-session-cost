"""Render ANSI terminal text to a PNG (dev helper; needs Pillow). Usage: render.py out.png title1 file1 [title2 file2...]"""
import re, sys
from PIL import Image, ImageDraw, ImageFont
R = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"; B = R.replace(".ttf", "-Bold.ttf")
SZ = 16; f, fb = ImageFont.truetype(R, SZ), ImageFont.truetype(B, SZ)
CW = f.getlength("M"); LH = 22
COL = {"31": (240, 98, 98), "33": (240, 200, 90), "36": (90, 200, 220), "2": (130, 136, 150)}
FG, BG = (220, 223, 228), (24, 26, 32)
def parse(line):
    out, st = [], {"c": FG, "b": False}
    for part in re.split(r"(\x1b\[[0-9;]*m)", line):
        m = re.match(r"\x1b\[([0-9;]*)m", part)
        if m:
            for code in (m.group(1) or "0").split(";"):
                if code == "0": st = {"c": FG, "b": False}
                elif code == "1": st["b"] = True
                elif code in COL: st["c"] = COL[code]
        elif part: out.append((part, dict(st)))
    return out
blocks = [(sys.argv[i], open(sys.argv[i + 1]).read().rstrip("\n").split("\n")) for i in range(2, len(sys.argv), 2)]
width = int(max(len(re.sub(r"\x1b\[[0-9;]*m", "", l)) for _, ls in blocks for l in ls) * CW) + 60
height = 50 + sum(LH * (len(ls) + 2) + 10 for _, ls in blocks)
img = Image.new("RGB", (width, height), BG); d = ImageDraw.Draw(img)
d.rectangle([0, 0, width, 30], fill=(40, 43, 52))
for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]): d.ellipse([12 + i * 20, 9, 24 + i * 20, 21], fill=c)
y = 44
for title, lines in blocks:
    d.text((30, y), title, font=fb, fill=(150, 160, 180)); y += LH + 6
    for l in lines:
        x = 30
        for txt, st in parse(l):
            d.text((x, y), txt, font=fb if st["b"] else f, fill=st["c"]); x += f.getlength(txt)
        y += LH
    y += LH
img.save(sys.argv[1])
