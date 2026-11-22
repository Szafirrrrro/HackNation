#!/usr/bin/env python3
"""Generuje syntetyczne karty reklam (JSONL) do testowania silnika grafu.

Scenariusz testowy (wszystkie domeny w zarezerwowanej strefie .test):
  * Kampania A "Inwestycja"  - rózne domeny frontowe, wspólny pośrednik w przekierowaniach,
                               wspólny piksel Meta i endpoint formularza, prezenter_A.
  * Kampania B "Ten sam uśmiech" - ZERO wspólnej infrastruktury, ale ta sama osoba
                               (prezenter_B, dobra jakość), podobny tekst i szablon grafiki.
  * Kampania C "Krypto-bot"  - wspólny certyfikat (SAN), favicon, szablon DOM, domeny
                               kupione hurtem w ciągu godziny; TEŻ prezenter_A.
  * Szum                     - losowe reklamy z Cloudflare, popularnymi słowami i rozmytą
                               twarzą prezenter_A.
Szablon (MinHash DOM): A — ten sam zestaw stron z wariacjami (Jaccard ≈ 0.8), C — prawie identyczny
(≈ 0.94), B i szum — różne strony.
Audio: reklamy wideo z A mają ten sam plik lektora (odcisk z drobnymi zmianami) i ten sam skrypt;
B ma sklonowany głos prezenter_B (ten sam głos, inne nagrania); C to statyczne banery bez audio;
część szumu ma losowe audio.

Oczekiwany wynik: 3 kampanie, szum osobno, A i C NIE sklejone mimo wspólnej twarzy.
Wektory mają tu 32 wymiary; prawdziwe embeddingi (384/512/768) działają tak samo.
"""
import json
import random
from datetime import datetime, timedelta, timezone

DIM = 32
rng = random.Random(7)


def unit(v):
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def rand_vec():
    return unit([rng.gauss(0, 1) for _ in range(DIM)])


def near(center, sigma):
    return [round(x, 4) for x in unit([c + rng.gauss(0, sigma) for c in center])]


def phash_near(base, flips):
    v = int(base, 16)
    for b in rng.sample(range(64), flips):
        v ^= 1 << b
    return f"{v:016x}"


def rand_phash():
    return f"{rng.getrandbits(64):016x}"


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


PERSON = {"prezenter_A": rand_vec(), "prezenter_B": rand_vec()}
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
cards = []


VOICE = {"lektor_A": rand_vec(), "glos_B": rand_vec()}


def rand_fp(n=60):
    return [rng.getrandbits(32) - 2**31 for _ in range(n)]


def fp_variant(base, shift, flips):
    """Ten sam plik audio: przesunięty o kilka ramek, z kilkoma przekłamanymi bitami (kompresja)."""
    arr = [rng.getrandbits(32) - 2**31 for _ in range(shift)] + list(base)
    for _ in range(flips):
        k = rng.randrange(len(arr))
        u = (arr[k] & 0xFFFFFFFF) ^ (1 << rng.randrange(32))
        arr[k] = u - 2**32 if u >= 2**31 else u
    return arr


def audio(transcript, voice, voice_sigma, fp, text_emb):
    return {"transcript": transcript,
            "segments": [{"start": 0.0, "end": 3.0, "text": transcript}],
            "asr_duration_s": 30.0, "duration_s": 30.0,
            "fingerprint": {"array": fp, "key": "r0", "shape": [len(fp)], "dtype": "int32", "n_frames": len(fp)},
            "speaker_embedding": near(VOICE[voice], voice_sigma) if voice else None,
            "text_embedding": text_emb}


def rand_sig(n=128):
    return [rng.getrandbits(32) for _ in range(n)]


def minhash(sig, p_changed):
    """Sygnatura MinHash wariantu szablonu: ułamek p_changed pozycji zmieniony (Jaccard dwóch
    wariantów ≈ (1 - p_changed)²)."""
    out = [rng.getrandbits(32) if rng.random() < p_changed else x for x in sig]
    return {"method": "dom-shingle-minhash-v1", "k": 8, "num_perm": len(out),
            "tokens": rng.randint(60, 400), "shingles": rng.randint(50, 380), "signature": out}


def face(person, quality, deepfake):
    sigma = 0.03 + (1 - quality) * 0.16  # gorsza jakość -> bardziej zaszumiony wektor
    return {
        "person": person,
        "similarity": None,  # uzupełnia moduł twarzy po porównaniu z bazą referencyjną
        "quality": round(quality, 2),
        "deepfake_score": round(deepfake, 2),
        "embedding": near(PERSON[person], sigma),
    }


def card(ad_id, source, first_seen, status, chain, ip, asn, registrar, ns, registered,
         cert_id, san, favicon, pixel, ga, scripts, form, contacts, template, hidden,
         ad_text, keywords, text_emb, phash, clip, faces, audio_block=None, template_mh=None):
    for i, f in enumerate(faces):
        sim = sum(a * b for a, b in zip(f["embedding"], PERSON[f["person"]]))
        f["similarity"] = round(sim, 3)
    return {
        "ad_id": ad_id,
        "provenance": {
            "source": source,
            "url": f"https://{chain[0]}/?utm_campaign={rng.getrandbits(32):x}",
            "fetched_at": iso(first_seen + timedelta(hours=1)),
            "snapshot": f"snapshots/{ad_id}/",
        },
        "first_seen": iso(first_seen),
        "last_seen": iso(first_seen + timedelta(days=rng.randint(1, 6))),
        "status": status,
        "infra": {
            "redirect_chain": chain,
            "final_domain": chain[-1],
            "rdap": {"registered": iso(registered), "registrar": registrar, "nameservers": ns},
            "dns": {"ip": ip, "asn": asn},
            "cert": {"id": cert_id, "san": san},
            "favicon": {"mmh3": favicon, "phash": None},
        },
        "page": {
            "tracking_ids": {"meta_pixel": pixel, "ga": ga},
            "script_hashes": scripts,
            "form_endpoint": form,
            "contacts": contacts,
            "dom_template_hash": template,
            "dom_template_minhash": template_mh,
            "hidden_text_hash": hidden,
        },
        "text": {"ad_text": ad_text, "ocr_text": "", "keywords": keywords, "embedding": text_emb},
        "visual": {"phash": phash, "clip_embedding": clip},
        "faces": faces,
        "audio": audio_block,
    }


# ---------------- Kampania A ----------------
txtA, visA = rand_vec(), rand_vec()
fpA = rand_fp()
sigA = rand_sig()
finalsA = ["inwestuj-teraz.test", "zysk-orlen.test", "pasywny-dochod.test"]
for i in range(8):
    fs = T0 + timedelta(days=i * 1.5)
    chain = [f"okazja-{i}.test", "track-hub.test", finalsA[i % 3]]
    cards.append(card(
        f"A{i:02d}", "meta_ad_library", fs, "dead" if i < 4 else "alive", chain,
        "104.16.1.1", "AS13335", "Registrar-Alfa", ["ns1.cloudflare.test"],
        fs - timedelta(days=rng.randint(1, 3)), f"crtA-{i}", [chain[-1]], rng.randint(-2**31, 2**31),
        "PX-771001", None, [f"sha:{rng.getrandbits(48):x}", "sha:countdown-A"],
        "api.leadbox-a.test/submit", {"phones": ["+48500100200"], "telegram": [], "crypto": []},
        f"dom:{rng.getrandbits(40):x}", None,
        f"Prezes zdradza sekret inwestycji #{i}", ["inwestycja", "orlen", "pasywny dochód"],
        near(txtA, 0.06), rand_phash(), near(visA, 0.12),
        [face("prezenter_A", rng.uniform(0.6, 0.9), rng.uniform(0.5, 0.9))] if i % 2 == 0 else [],
        audio("Prezes Orlenu zdradza sekret pasywnego dochodu. Zarejestruj się dziś!", "lektor_A", 0.04,
              fp_variant(fpA, rng.randint(0, 4), rng.randint(5, 30)), near(txtA, 0.06))
        if i % 2 == 0 else None,
        minhash(sigA, 0.10)))

# ---------------- Kampania B ----------------
txtB, visB, phB = rand_vec(), rand_vec(), rand_phash()
for i in range(7):
    fs = T0 + timedelta(days=3 + i)
    d = f"sekret-{rng.getrandbits(24):x}.test"
    cards.append(card(
        f"B{i:02d}", "meta_ad_library" if i % 2 else "cert_pl_list", fs, "dead", [d],
        f"45.{rng.randint(1,250)}.{rng.randint(1,250)}.{rng.randint(1,250)}", f"AS{rng.randint(20000, 60000)}",
        rng.choice(["Registrar-Beta", "Registrar-Gamma", "Registrar-Delta"]), [f"ns.{d}"],
        fs - timedelta(days=rng.randint(1, 20)), f"crtB-{i}", [d], rng.randint(-2**31, 2**31),
        None, None, [f"sha:{rng.getrandbits(48):x}"], f"{d}/form.php",
        {"phones": [], "telegram": [], "crypto": []}, f"dom:{rng.getrandbits(40):x}", None,
        f"Znany prezenter: ten trik zmienił moje życie (wariant {i})", ["sekret", "bogactwo", "prezenter"],
        near(txtB, 0.07), phash_near(phB, rng.randint(2, 6)), near(visB, 0.06),
        [face("prezenter_B", rng.uniform(0.75, 0.95), rng.uniform(0.6, 0.95))],
        audio(f"Ten jeden trik zmienił moje życie, wariant {i}", "glos_B", 0.05, rand_fp(), near(txtB, 0.07)),
        minhash(rand_sig(), 0)))

# ---------------- Kampania C ----------------
txtC, visC, phC = rand_vec(), rand_vec(), rand_phash()
sigC = rand_sig()
domsC = [f"krypto-bot-{i}.test" for i in range(6)]
bulk = T0 + timedelta(days=10, hours=14)
for i in range(6):
    fs = T0 + timedelta(days=11 + i * 0.5)
    cards.append(card(
        f"C{i:02d}", "urlscan", fs, "alive" if i > 2 else "dead", [domsC[i]],
        f"91.200.{i}.{rng.randint(1,250)}", "AS48666", "Registrar-Omega", ["ns1.omega.test", "ns2.omega.test"],
        bulk + timedelta(minutes=7 * i), "crtC-shared", domsC, 1337421337,
        None, "G-CRYPTO9", ["sha:bot-widget-C"], f"{domsC[i]}/api/lead",
        {"phones": [], "telegram": ["@krypto_wsparcie"], "crypto": []}, "dom:template-C", "hid:seo-C",
        f"Bot AI zarabia za Ciebie {500 + i * 100} zł dziennie", ["inwestycja", "bitcoin", "bot ai"],
        near(txtC, 0.06), phash_near(phC, rng.randint(3, 8)), near(visC, 0.08),
        [face("prezenter_A", rng.uniform(0.7, 0.9), rng.uniform(0.3, 0.7))],
        None, minhash(sigC, 0.03)))

# ---------------- Szum ----------------
for i in range(6):
    fs = T0 + timedelta(days=rng.uniform(0, 18))
    d = f"losowa-{rng.getrandbits(24):x}.test"
    cards.append(card(
        f"N{i:02d}", rng.choice(["meta_ad_library", "cert_pl_list", "urlscan"]), fs,
        rng.choice(["dead", "alive"]), [d], "104.16.1.1", "AS13335",
        rng.choice(["Registrar-Alfa", "Registrar-Beta"]), ["ns1.cloudflare.test"],
        fs - timedelta(days=rng.randint(30, 400)), f"crtN-{i}", [d], rng.randint(-2**31, 2**31),
        None, None, [f"sha:{rng.getrandbits(48):x}"], f"{d}/kontakt",
        {"phones": [], "telegram": [], "crypto": []}, f"dom:{rng.getrandbits(40):x}", None,
        f"Promocja dnia {i}", ["inwestycja", "promocja"], rand_vec(), rand_phash(), rand_vec(),
        [face("prezenter_A", rng.uniform(0.15, 0.35), rng.uniform(0.0, 0.4))] if i % 2 else [],
        audio(f"Promocja dnia {i}, tylko teraz", None, 0, rand_fp(), rand_vec()) if i % 3 == 0 else None,
        minhash(rand_sig(), 0) if i % 2 == 0 else None))

with open("data/sample_cards.jsonl", "w", encoding="utf-8") as f:
    for c in cards:
        f.write(json.dumps(c, ensure_ascii=False) + "\n")

# Jedna "ładna" karta do podglądu (wektory skrócone)
ex = json.loads(json.dumps(cards[0]))
ex["text"]["embedding"] = ex["text"]["embedding"][:4] + ["..."]
ex["visual"]["clip_embedding"] = ex["visual"]["clip_embedding"][:4] + ["..."]
if ex["page"].get("dom_template_minhash"):
    ex["page"]["dom_template_minhash"]["signature"] = ex["page"]["dom_template_minhash"]["signature"][:4] + ["..."]
for fc in ex["faces"]:
    fc["embedding"] = fc["embedding"][:4] + ["..."]
with open("data/example_card.json", "w", encoding="utf-8") as f:
    json.dump(ex, f, ensure_ascii=False, indent=2)

print(f"Zapisano {len(cards)} kart do data/sample_cards.jsonl")
