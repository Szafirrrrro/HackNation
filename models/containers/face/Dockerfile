FROM tm-base:latest
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install onnxruntime==1.20.1 insightface==0.7.3 \
    && apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY common/dl.py /app/common/dl.py
COPY containers/face/download.py /app/uc/download.py
RUN python /app/uc/download.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/face /app/uc
CMD ["python", "/app/common/main.py", "extract"]
