"""Ścieżka audio reklam (nagrania i wideo).

- Whisper: transkrypcja (PL); asr.text trafia do kontenera text (rodzina text).
- Chromaprint: odcisk akustyczny nagrania (rodzina audio), odpowiednik pHash dla dźwięku.
- ECAPA: odcisk głosu mówcy (rodzina audio).
Wszystkie cechy jednego nagrania mają wspólny origin_id (<ad_id>#audio_path), więc liczą się
jako jedno źródło (kontrakt, „Pochodzenie”).
"""
import json
import subprocess

import numpy as np

from extractor import Extractor, Out, Unavailable, l2


SAMPLE_RATE = 16000
# Decyzja zespołu 2026-11-21: ścieżka o szczycie poniżej ok. -80 dBFS to cisza. Nagrania ekranu
# bez dźwięku mają ścieżkę z samymi zerami; odcisk i głos z ciszy pasowałyby do siebie nawzajem.
SILENCE_PEAK = 1e-4


def _has_audio_stream(path):
    import av
    try:
        with av.open(path) as c:
            return bool(c.streams.audio)
    except Exception as e:  # noqa: BLE001 - uszkodzony / nieobsługiwany plik
        raise Unavailable(f"unreadable_audio: {e}")


def is_silent(wav, peak=SILENCE_PEAK):
    return wav.size == 0 or float(np.abs(wav).max()) < peak


def load_audio(path, max_seconds=None):
    """Mono 16 kHz float32. Przyczyny braku wspólne dla Whisper, Chromaprint i ECAPA.

    max_seconds: cisza sprawdzana na tym samym fragmencie, z którego model liczy cechę.
    Plik jest nadal dekodowany w całości (limit przed dekodowaniem: zaległość w CONTEXT.md)."""
    from faster_whisper import decode_audio
    if not _has_audio_stream(path):
        raise Unavailable("no_audio_stream")
    try:
        wav = decode_audio(path, sampling_rate=SAMPLE_RATE)
    except Exception as e:  # noqa: BLE001 - uszkodzony / nieobsługiwany plik
        raise Unavailable(f"unreadable_audio: {e}")
    if max_seconds is not None:
        wav = wav[: int(max_seconds * SAMPLE_RATE)]
    if wav.size == 0:
        raise Unavailable("audio_too_short")
    if is_silent(wav):
        raise Unavailable("silent_audio")
    return wav


class Whisper(Extractor):
    use_case = "asr"
    family = "text"
    modality = "audio"
    primary_field = "asr.text"
    license = "MIT"

    def __init__(self, size, notes, stage, decision):
        self.size, self.notes, self.stage, self.decision = size, notes, stage, decision
        self.name = f"faster-whisper-{size}-int8"
        self.version = f"faster-whisper-1.1.0/Systran/faster-whisper-{size}"
        self.hf_repo = f"Systran/faster-whisper-{size}"
        # język PL jak w ustaleniach zespołu (reklamy kierowane do Polski)
        self.params = {"language": "pl", "beam_size": 1, "vad_filter": True, "compute_type": "int8",
                       "silence_peak": SILENCE_PEAK}

    def load(self, threads):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(f"Systran/faster-whisper-{self.size}", device="cpu",
                              compute_type=self.params["compute_type"], cpu_threads=threads)

    def extract(self, item):
        wav = load_audio(item.path)   # spójne przyczyny braku z Chromaprint/ECAPA
        try:
            segs, info = self.m.transcribe(wav, language=self.params["language"],
                                           beam_size=self.params["beam_size"],
                                           vad_filter=self.params["vad_filter"])
            segs = list(segs)
        except Exception as e:  # noqa: BLE001 - uszkodzony / nieobsługiwany plik
            raise Unavailable(f"unreadable_audio: {e}")
        text = " ".join(s.text.strip() for s in segs).strip()
        # sama muzyka / szum: VAD nie znalazł mowy -> brak transkrypcji, a nie pusty tekst ze statusem ok
        return [Out("asr.text", text) if text else Out("asr.text", reason="no_speech_detected"),
                Out("asr.duration_s", round(info.duration, 2)),
                Out("asr.segments", [{"start": round(s.start, 2), "end": round(s.end, 2),
                                      "text": s.text.strip()} for s in segs])]


class Chromaprint(Extractor):
    name = "chromaprint-fpcalc"
    use_case = "audio_fingerprint"
    family = "audio"
    modality = "audio"
    primary_field = "audio.fingerprint"
    stage = "default"
    decision = ("Domyślne (decyzja zespołu 2026-11-21): deterministyczny odcisk bez wag, jak pHash dla "
                "obrazu; wykrywa to samo nagranie po rekompresji i przycięciu. Jakość na prawdziwych "
                "reklamach czeka na nagrania.")
    license = "LGPL-2.1 (Chromaprint)"
    notes = ("fpcalc -raw: tablica int32, ok. 8 subodcisków/s; porównanie: features_lib."
             "chromaprint_similarity (zgodność bitów przy najlepszym przesunięciu)")
    params = {"max_seconds": 600, "silence_peak": SILENCE_PEAK}

    @property
    def version(self):
        try:
            out = subprocess.run(["fpcalc", "-version"], capture_output=True, text=True).stdout
            return "fpcalc-" + out.strip().split()[2]
        except Exception:  # noqa: BLE001
            return "fpcalc-unknown"

    def load(self, threads):
        subprocess.run(["fpcalc", "-version"], capture_output=True, check=True)

    def extract(self, item):
        # cisza daje odcisk wspólny dla wszystkich niemych nagrań; ten sam zakres co -length fpcalc
        load_audio(item.path, self.params["max_seconds"])
        p = subprocess.run(["fpcalc", "-raw", "-json", "-length", str(self.params["max_seconds"]),
                            item.path], capture_output=True, text=True)
        if p.returncode != 0:
            msg = (p.stderr or p.stdout).strip().splitlines()
            msg = msg[-1] if msg else f"exit {p.returncode}"
            if "audio stream" in msg.lower():
                raise Unavailable("no_audio_stream")
            if "empty fingerprint" in msg.lower():   # fpcalc 1.5: nagranie zbyt krótkie na odcisk
                raise Unavailable("audio_too_short")
            raise Unavailable(f"unreadable_audio: {msg}")
        r = json.loads(p.stdout)
        fp = np.asarray(r.get("fingerprint") or [], dtype=np.int64).astype(np.uint32).view(np.int32)
        duration = round(float(r.get("duration", 0.0)), 2)
        if fp.size == 0:
            return [Out("audio.fingerprint", reason="audio_too_short"),
                    Out("audio.duration_s", duration)]
        return [Out("audio.fingerprint", {"array": fp, "n_frames": int(fp.size)}),
                Out("audio.duration_s", duration)]


class ECAPA(Extractor):
    name = "speechbrain-ecapa-voxceleb"
    use_case = "speaker_embedding"
    family = "audio"
    modality = "audio"
    primary_field = "audio.speaker_embedding"
    stage = "on_demand"
    decision = ("Na żądanie (decyzja zespołu 2026-11-21): ten sam lektor w różnych reklamach także przy "
                "innym tekście. Do profilu domyślnego po pomiarze na prawdziwych głosach "
                "(ten sam vs różny mówca, muzyka w tle).")
    hf_repo = "speechbrain/spkrec-ecapa-voxceleb"
    license = "Apache-2.0"
    notes = "192d, L2; trenowany na VoxCeleb (głównie angielski); porównanie: kosinus"
    params = {"sample_rate": SAMPLE_RATE, "max_seconds": 60, "min_seconds": 0.5,
              "silence_peak": SILENCE_PEAK}

    @property
    def version(self):
        try:
            from importlib.metadata import version
            return f"speechbrain-{version('speechbrain')}/spkrec-ecapa-voxceleb"
        except Exception:  # noqa: BLE001
            return "speechbrain-unknown/spkrec-ecapa-voxceleb"

    def load(self, threads):
        import torch
        from huggingface_hub import snapshot_download
        from speechbrain.inference.speaker import EncoderClassifier
        torch.set_num_threads(threads)
        local = snapshot_download(self.hf_repo, local_files_only=True)
        # hyperparams.yaml wskazuje wagi przez pretrained_path=<repo HF>; podmieniamy na kopię lokalną
        self.m = EncoderClassifier.from_hparams(source=local, savedir="/tmp/ecapa",
                                                overrides={"pretrained_path": local},
                                                run_opts={"device": "cpu"})
        self.m.eval()

    def extract(self, item):
        import torch
        sr = self.params["sample_rate"]
        wav = load_audio(item.path, self.params["max_seconds"])   # głos tylko z początku nagrania
        if wav.size < self.params["min_seconds"] * sr:
            raise Unavailable("audio_too_short")
        with torch.no_grad():
            emb = self.m.encode_batch(torch.from_numpy(wav).unsqueeze(0)).reshape(-1).numpy()
        return [Out("audio.speaker_embedding", l2(emb))]


EXTRACTORS = [Whisper("base", "74M param", "on_demand",
                      "Na żądanie (decyzja użytkownika 2026-11-21): wybrano small. Oczekiwanie, nie pomiar: "
                      "base gorzej radzi sobie z polskimi nazwami produktów i liczbami. Base nie był "
                      "uruchamiany na nagraniach reklam."),
              Whisper("small", "244M param", "default",
                      "Domyślne (decyzja użytkownika 2026-11-21, wybór na oko, bez pomiaru WER): "
                      "transkrypcja PL do rodziny text. Do potwierdzenia na transkrypcjach "
                      "referencyjnych (WER, nazwy produktów, liczby, czas na minutę)."),
              Chromaprint(),
              ECAPA()]
