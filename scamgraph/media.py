"""Local-only image OCR and optional speech transcription."""
import csv
import io
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path

from .sources import clean, evidence, fact

IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
AUDIO = {".wav", ".mp3", ".m4a"}
VIDEO = {".mp4", ".webm"}


def ocr(path, artifact):
    from PIL import Image
    try:
        with Image.open(path) as im:
            width, height = im.size
            if width * height > 32_000_000:
                raise ValueError("Obraz przekracza limit pikseli")
            im.verify()
    except Image.DecompressionBombError as exc:
        raise ValueError("Obraz przekracza limit pikseli") from exc
    if os.name == "nt" and shutil.which("powershell.exe"):
        command = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File",
                   str(Path(__file__).with_name("windows_ocr.ps1")), str(path.resolve())]
        response = subprocess.run(command, check=True, capture_output=True, timeout=60)
        data = json.loads(response.stdout.decode("utf-8-sig"))
        lines = data["lines"]
        method = "Windows.Media.Ocr/" + str(os.sys.getwindowsversion().build) + "/" + data["language"]
    elif shutil.which("tesseract"):
        langs = subprocess.check_output(["tesseract", "--list-langs"], timeout=10).decode().splitlines()
        lang = "+".join(x for x in ("pol", "eng") if x in langs)
        if not lang:
            raise ValueError("Brak języka polskiego lub angielskiego OCR")
        response = subprocess.run(["tesseract", str(path), "stdout", "-l", lang, "tsv"],
                                  check=True, capture_output=True, timeout=60)
        groups = defaultdict(list)
        for word in csv.DictReader(io.StringIO(response.stdout.decode()), delimiter="\t"):
            if word["text"].strip():
                groups[tuple(word[k] for k in ("page_num", "block_num", "par_num", "line_num"))].append(word)
        lines = []
        for words in groups.values():
            boxes = [(int(w["left"]), int(w["top"]), int(w["width"]), int(w["height"])) for w in words]
            lines.append({"text": " ".join(w["text"] for w in words),
                          "bbox": [min(x for x,y,w,h in boxes), min(y for x,y,w,h in boxes),
                                   max(x+w for x,y,w,h in boxes), max(y+h for x,y,w,h in boxes)]})
        version = subprocess.check_output(["tesseract", "--version"], timeout=10).decode().splitlines()[0]
        method = version + "/" + lang
    else:
        raise ValueError("Brak lokalnego silnika OCR")
    return [{**fact(clean(line["text"]), evidence(artifact, bbox=line["bbox"])), "method": method} for line in lines]


def screen_fields(lines):
    fields = []
    for index, line in enumerate(lines):
        value = line["value"]
        key = None
        if re.search(r"^(sponsorowane|sponsored)$", value, re.I) and index:
            fields.append({"field": "page_name", **lines[index-1]})
        if re.search(r"(się więcej|learn more|kup teraz|shop now|sign up|zarejestruj się)", value, re.I):
            key = "cta"
        elif re.search(r"wycofan|usunięt|removed|withdrawn|narusza", value, re.I):
            key = "removal_notice"
        elif re.fullmatch(r"(?:www\.)?[\w.-]+\.[a-z]{2,}", value, re.I):
            key = "visible_domain"
        elif re.fullmatch(r"aktywna|nieaktywna|active|inactive", value, re.I):
            key = "status"
        elif re.search(r"(?:library id|identyfikator biblioteki|id biblioteki)\s*:\s*\d+", value, re.I):
            fields.append({**line, "field": "ad_ref", "value": re.search(r"\d+", value)[0]})
        elif re.search(r"(?:page id|identyfikator strony|id reklamodawcy)\s*:\s*\d+", value, re.I):
            fields.append({**line, "field": "advertiser_ref", "value": re.search(r"\d+", value)[0]})
        elif re.search(r"rozpoczęcie emisji|rozpoczęto wyświetlanie|started running|data rozpoczęcia", value, re.I):
            key = "start_date"
        elif re.search(r"zakończenie emisji|zakończono wyświetlanie|stopped running|data zakończenia", value, re.I):
            key = "end_date"
        elif re.match(r"^(platforms?|platformy)\s*:", value, re.I):
            key = "platforms"
        if key:
            fields.append({"field": key, **line})
    return fields


def transcribe(path, artifact, model_dir):
    if not model_dir:
        raise ValueError("Brak skonfigurowanego lokalnego modelu ASR")
    if path.stat().st_size > 50 * 1024**2:
        raise ValueError("Nagranie przekracza 50 MiB")
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    from .sources import digest

    samples, count = [], 0
    formats = {".wav": "wav", ".mp3": "mp3", ".m4a": "mov", ".mp4": "mov", ".webm": "matroska"}
    with av.open(io.BytesIO(path.read_bytes()), format=formats[path.suffix.lower()],
                 options={"protocol_whitelist": ""}) as container:
        if not container.streams.audio:
            raise ValueError("Brak ścieżki dźwiękowej")
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        def append(frames):
            nonlocal count
            for frame in frames:
                count += frame.samples
                if count > 180 * 16000:
                    raise ValueError("Nagranie przekracza 180 sekund")
                samples.append(frame.to_ndarray().ravel())
        for frame in container.decode(audio=0):
            append(resampler.resample(frame))
        append(resampler.resample(None))
    if not count:
        raise ValueError("Brak próbek audio")
    model = WhisperModel(str(model_dir.resolve(strict=True)), device="cpu", compute_type="int8", local_files_only=True)
    segments, info = model.transcribe(np.concatenate(samples), beam_size=1, vad_filter=True)
    duration = count / 16000
    rows = []
    for s in segments:
        start, end = max(0, min(s.start, duration)), max(0, min(s.end, duration))
        if s.text.strip() and start <= end:
            rows.append({"start": start, "end": end, "text": clean(s.text), "evidence": evidence(artifact, start=start, end=end)})
    if not rows:
        raise ValueError("Nie wykryto mowy")
    return {"method": "faster-whisper/cpu-int8/beam1/vad", "model_sha256": digest(model_dir / "model.bin"),
            "text": " ".join(row["text"] for row in rows), "language": info.language, "duration_s": duration,
            "segments": rows, "evidence": evidence(artifact, start=0, end=duration)}
