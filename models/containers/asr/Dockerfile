FROM tm-base:latest
RUN pip install faster-whisper==1.1.0
COPY common/dl.py /app/common/dl.py
COPY containers/asr/download.py /app/uc/download.py
RUN python /app/uc/download.py
# audio (rodzina audio) w osobnych warstwach po Whisperze -> nie unieważnia pobranych wag Whispera
# fpcalc (Chromaprint) dekoduje audio i wideo przez ffmpeg
RUN apt-get update && apt-get install -y --no-install-recommends libchromaprint-tools \
    && rm -rf /var/lib/apt/lists/*
# torchaudio z indeksu CPU w wersji zgodnej z torch 2.5.1 z tm-base (speechbrain go wymaga)
RUN pip install --index-url https://download.pytorch.org/whl/cpu torchaudio==2.5.1 \
    && pip install speechbrain==1.0.3
COPY containers/asr/download_audio.py /app/uc/download_audio.py
RUN python /app/uc/download_audio.py
# kontrola kompletności wag (osobna warstwa - nie unieważnia pobranych wag)
COPY common/ensure_weights.py /app/common/ensure_weights.py
RUN python /app/common/ensure_weights.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/asr /app/uc
CMD ["python", "/app/common/main.py", "extract"]
