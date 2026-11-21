FROM tm-base:latest
RUN pip install faster-whisper==1.1.0
COPY containers/asr /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
