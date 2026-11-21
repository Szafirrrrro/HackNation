FROM tm-base:latest
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && pip install onnxruntime==1.20.1 insightface==0.7.3 \
    && apt-get purge -y build-essential && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY containers/face /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
