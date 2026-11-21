"""Transkrypcja ścieżki audio reklam wideo (PL) -> tekst do analizy narracji."""
from bench import AUDIO_EXT, ModelSpec, files, run_suite, short_label


def inputs():
    return files("audio", AUDIO_EXT)


def make(size):
    def load(threads):
        from faster_whisper import WhisperModel
        return WhisperModel(f"Systran/faster-whisper-{size}", device="cpu",
                            compute_type="int8", cpu_threads=threads)

    def infer(m, path):
        segs, info = m.transcribe(path, language="pl", beam_size=1, vad_filter=True)
        txt = " ".join(s.text.strip() for s in segs)
        return {"audio_s": round(info.duration, 1), "text": txt[:200]}
    return load, infer


run_suite("asr", [
    ModelSpec("faster-whisper/base (int8)", "asr", "MIT", *make("base"), inputs,
              notes="74M param", item_label=short_label),
    ModelSpec("faster-whisper/small (int8)", "asr", "MIT", *make("small"), inputs,
              notes="244M param, wyraźnie lepszy WER dla PL", item_label=short_label),
])
