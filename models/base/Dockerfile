# Obraz bazowy: Python + PyTorch CPU + transformers + harness benchmarku.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/models/hf \
    TORCH_HOME=/models/torch \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONPATH=/app/common

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 ca-certificates git curl fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --index-url https://download.pytorch.org/whl/cpu \
        torch==2.5.1 torchvision==0.20.1 \
    && pip install \
        "transformers==4.46.3" "huggingface_hub>=0.26,<0.30" \
        "numpy<2.1" pillow psutil sentencepiece protobuf \
        opencv-python-headless==4.10.0.84 safetensors

WORKDIR /app
COPY common /app/common
