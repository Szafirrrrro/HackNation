"""Generuje syntetyczne dane przykładowe w /out (uruchamiane w kontenerze tm-face).

- texts/*.txt          teksty reklam (scripts/sample_texts.py)
- images/*.png|jpg     kreacje reklamowe: tekst + twarze (zdjęcie testowe insightface t1.jpg)
                        + warianty (crop/resize/JPEG) do testu near-duplicate
- faces/*.jpg          zdjęcia z twarzami
"""
import os
import sys
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from sample_texts import TEXTS

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/out")
for d in ["texts", "images", "faces"]:
    (OUT / d).mkdir(parents=True, exist_ok=True)

for k, t in TEXTS.items():
    (OUT / "texts" / f"{k}.txt").write_text(t + "\n", encoding="utf-8")

import insightface
face_src = Path(insightface.__file__).parent / "data" / "images" / "t1.jpg"
faces = Image.open(face_src).convert("RGB")
faces.save(OUT / "faces" / "group_t1.jpg", quality=92)
w, h = faces.size
faces.crop((0, 0, w // 2, h)).save(OUT / "faces" / "group_t1_left.jpg", quality=85)

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_R = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ""
    for wd in words:
        test = (cur + " " + wd).strip()
        if draw.textlength(test, font=font) > width:
            lines.append(cur)
            cur = wd
        else:
            cur = test
    return lines + [cur]


def ad(name, headline, body, url, bg, with_face):
    W, H = 1080, 1080
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    f1, f2, f3 = ImageFont.truetype(FONT, 58), ImageFont.truetype(FONT_R, 36), ImageFont.truetype(FONT, 30)
    y = 50
    for line in wrap(d, headline, f1, W - 100):
        d.text((50, y), line, font=f1, fill="white")
        y += 70
    if with_face:
        ph = faces.resize((W - 100, int((W - 100) * h / w)))
        im.paste(ph, (50, y + 20))
        y += ph.size[1] + 40
    for line in wrap(d, body, f2, W - 100)[:6]:
        d.text((50, y), line, font=f2, fill="#f0f0f0")
        y += 46
    d.rectangle((50, H - 130, W - 50, H - 50), fill="#ffcc00")
    d.text((80, H - 110), url, font=f3, fill="black")
    im.save(OUT / "images" / f"{name}.png")
    return im


a1 = ad("A1_krypto", "WYWIAD, KTÓRY ZABLOKOWAŁ BANK", TEXTS["A1_krypto"],
        "investpro-ai-pl.online/rejestracja", "#0b3d91", True)
ad("A2_krypto", "SKANDAL NA ANTENIE!", TEXTS["A2_krypto"],
   "investpro-ai-pl.site/start", "#0b3d91", True)
ad("B1_zdrowie", "PROFESOR UJAWNIA SEKRET", TEXTS["B1_zdrowie"],
   "cardio-natura-sklep.shop", "#1d6b2f", False)
ad("C1_doplata", "DOPŁATA 2500 ZŁ", TEXTS["C1_doplata"],
   "gov-zwrot-energii.info/formularz", "#8a1c1c", False)
ad("D1_neutral", "MECZ OTWARCIA SEZONU", TEXTS["D1_neutral"],
   "klub-sportowy.pl/bilety", "#333333", False)

# warianty A1: duplikat po kompresji, crop, zmniejszenie
a1.convert("RGB").save(OUT / "images" / "A1_krypto_dup_q40.jpg", quality=40)
a1.crop((0, 0, 1080, 900)).save(OUT / "images" / "A1_krypto_crop.png")
a1.resize((540, 540)).save(OUT / "images" / "A1_krypto_small.png")
print("ok", sorted(str(p.relative_to(OUT)) for p in OUT.rglob("*") if p.is_file()))
