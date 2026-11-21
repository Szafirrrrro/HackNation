FROM tm-base:latest
RUN pip install faster-whisper==1.1.0
COPY common/dl.py /app/common/dl.py
COPY containers/asr/download.py /app/uc/download.py
RUN python /app/uc/download.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/asr /app/uc
CMD ["python", "/app/common/main.py", "extract"]
