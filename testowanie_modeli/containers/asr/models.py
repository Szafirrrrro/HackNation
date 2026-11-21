"""Transkrypcja ścieżki audio reklam wideo (PL). asr.text trafia do kontenera text."""
from extractor import Extractor, Out, Unavailable


class Whisper(Extractor):
    use_case = "asr"
    family = "text"
    modality = "audio"
    primary_field = "asr.text"
    license = "MIT"

    def __init__(self, size, notes):
        self.size, self.notes = size, notes
        self.name = f"faster-whisper-{size}-int8"
        self.version = f"faster-whisper-1.1.0/Systran/faster-whisper-{size}/int8/beam1/vad"

    def load(self, threads):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(f"Systran/faster-whisper-{self.size}", device="cpu",
                              compute_type="int8", cpu_threads=threads)

    def extract(self, item):
        try:
            segs, info = self.m.transcribe(item.path, language=None, beam_size=1, vad_filter=True)
            segs = list(segs)
        except Exception as e:  # noqa: BLE001 - uszkodzony / nieobsługiwany plik
            raise Unavailable(f"unreadable_audio: {e}")
        return [Out("asr.text", " ".join(s.text.strip() for s in segs)),
                Out("asr.language", {"lang": info.language,
                                     "p": round(info.language_probability, 4)}),
                Out("asr.duration_s", round(info.duration, 2)),
                Out("asr.segments", [{"start": round(s.start, 2), "end": round(s.end, 2),
                                      "text": s.text.strip()} for s in segs])]


EXTRACTORS = [Whisper("base", "74M param"),
              Whisper("small", "244M param, wyraźnie lepszy WER dla PL")]
