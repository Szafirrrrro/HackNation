#!/usr/bin/env python3
"""Tworzy przykładowe "nowe reklamy" do testowania demonstratora (data/new_ad_*.json).

  new_ad_krypto.json   — nowa domena, ale ta sama favicona, szablon i Telegram co kampania "Krypto-bot"
  new_ad_usmiech.json  — zero wspólnej infrastruktury, ta sama twarz i podobny tekst co "Ten sam uśmiech"
  new_ad_nieznana.json — losowa reklama bez związku z korpusem (powinna zostać bez kampanii)

Uruchom po tools/gen_sample_cards.py:   python tools/make_new_ad_examples.py
"""
import copy
import json
import random

rng = random.Random(42)


def jitter(vec, sigma=0.03):
    v = [x + rng.gauss(0, sigma) for x in vec]
    n = sum(x * x for x in v) ** 0.5
    return [round(x / n, 4) for x in v]


cards = {c["ad_id"]: c for c in map(json.loads, open("data/sample_cards.jsonl", encoding="utf-8"))}

# 1) dołącza do kampanii C przez wspólne artefakty
k = copy.deepcopy(cards["C03"])
k["ad_id"] = "NEW-KRYPTO"
dom = "krypto-bot-nowy.test"
k["provenance"].update(source="upload", url=f"https://{dom}/?ref=fb", fetched_at="2026-11-21T10:00:00Z")
k["first_seen"], k["last_seen"], k["status"] = "2026-11-20T08:00:00Z", "2026-11-21T10:00:00Z", "alive"
k["infra"].update(redirect_chain=[dom], final_domain=dom)
k["infra"]["dns"]["ip"] = "91.200.9.9"
k["infra"]["cert"] = {"id": "crtC-nowy", "san": [dom]}
k["infra"]["rdap"]["registered"] = "2026-11-19T22:00:00Z"
k["page"]["form_endpoint"] = f"{dom}/api/lead"
k["text"]["ad_text"] = "Nowy bot AI: 1200 zł dziennie bez wychodzenia z domu"
k["text"]["embedding"] = jitter(k["text"]["embedding"])
k["visual"]["clip_embedding"] = jitter(k["visual"]["clip_embedding"])
for f in k["faces"]:
    f["embedding"] = jitter(f["embedding"], 0.02)

# 2) dołącza do kampanii B tylko przez twarz, tekst i wygląd
u = copy.deepcopy(cards["B02"])
u["ad_id"] = "NEW-USMIECH"
dom = "sekret-nowy.test"
u["provenance"].update(source="upload", url=f"https://{dom}/", fetched_at="2026-11-21T10:00:00Z")
u["first_seen"], u["last_seen"], u["status"] = "2026-11-18T12:00:00Z", "2026-11-21T10:00:00Z", "alive"
u["infra"].update(redirect_chain=[dom], final_domain=dom)
u["infra"]["dns"] = {"ip": "45.99.99.99", "asn": "AS59999"}
u["infra"]["rdap"] = {"registered": "2026-11-17T09:00:00Z", "registrar": "Registrar-Nowy", "nameservers": [f"ns.{dom}"]}
u["infra"]["cert"] = {"id": "crt-usmiech-nowy", "san": [dom]}
u["infra"]["favicon"]["mmh3"] = 99887766
u["page"].update(form_endpoint=f"{dom}/form.php", dom_template_hash="dom:nowy", script_hashes=["sha:nowy"])
u["text"]["ad_text"] = "Prezenter wyznaje: ten sekret dał mi niezależność"
u["text"]["embedding"] = jitter(u["text"]["embedding"])
u["visual"]["clip_embedding"] = jitter(u["visual"]["clip_embedding"])
for f in u["faces"]:
    f["embedding"] = jitter(f["embedding"], 0.02)
if u.get("audio"):  # nowe nagranie, ale ten sam (sklonowany) głos
    u["audio"]["fingerprint"]["array"] = [rng.getrandbits(32) - 2**31 for _ in range(60)]
    u["audio"]["transcript"] = "Prezenter wyznaje: ten sekret dał mi niezależność"
    u["audio"]["speaker_embedding"] = jitter(u["audio"]["speaker_embedding"], 0.02)
    if u["audio"].get("text_embedding"):
        u["audio"]["text_embedding"] = jitter(u["audio"]["text_embedding"])

# 3) losowa, niezwiązana
n = copy.deepcopy(cards["N01"])
n["ad_id"] = "NEW-NIEZNANA"
dom = "zupelnie-inna.test"
n["provenance"].update(source="upload", url=f"https://{dom}/", fetched_at="2026-11-21T10:00:00Z")
n["first_seen"], n["last_seen"], n["status"] = "2026-11-21T07:00:00Z", "2026-11-21T10:00:00Z", "alive"
n["infra"].update(redirect_chain=[dom], final_domain=dom)
n["infra"]["dns"] = {"ip": "203.0.113.7", "asn": "AS64500"}
n["infra"]["cert"] = {"id": "crt-inna", "san": [dom]}
n["page"]["form_endpoint"] = f"{dom}/kontakt"
n["text"]["ad_text"] = "Wyprzedaż rowerów"
n["text"]["embedding"] = jitter([rng.gauss(0, 1) for _ in n["text"]["embedding"]], 0)
n["visual"]["clip_embedding"] = jitter([rng.gauss(0, 1) for _ in n["visual"]["clip_embedding"]], 0)
n["visual"]["phash"] = f"{rng.getrandbits(64):016x}"
n["faces"] = []
n["audio"] = None

for name, card in (("krypto", k), ("usmiech", u), ("nieznana", n)):
    with open(f"data/new_ad_{name}.json", "w", encoding="utf-8") as fh:
        json.dump(card, fh, ensure_ascii=False, indent=2)
print("Zapisano data/new_ad_krypto.json, data/new_ad_usmiech.json, data/new_ad_nieznana.json")
