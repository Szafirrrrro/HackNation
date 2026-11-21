FROM tm-base:latest
# Effort (ICML 2025, YZY-stack/Effort-AIGI-Detection) - licencja CC BY-NC 4.0.
# Kod przypięty do commita; wagi .pth NIE są w obrazie - montowane z models/weights/effort/.
ARG EFFORT_COMMIT=96f5dea2b534d400cfd7003f053c7e93c8e16461
RUN apt-get update && apt-get install -y --no-install-recommends build-essential cmake \
    && pip install dlib==19.24.6 \
    && apt-get purge -y build-essential cmake && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
RUN pip install imutils==0.5.4 scikit-image==0.24.0 scikit-learn==1.5.2 scipy==1.14.1 pyyaml tqdm \
        tensorboard==2.18.0 loralib==0.1.2 efficientnet_pytorch==0.7.1 \
    && git init /opt/effort && cd /opt/effort \
    && git remote add origin https://github.com/YZY-stack/Effort-AIGI-Detection.git \
    && git fetch --depth 1 origin ${EFFORT_COMMIT} && git checkout FETCH_HEAD && rm -rf .git figs \
    # demo.py używa sys.stderr bez importu sys (ścieżka ostrzeżenia o nieczytelnym pliku)
    && sed -i '1i import sys' DeepfakeBench/training/demo.py
# Backbone: effort_detector ładuje CLIPModel z "../models--openai--clip-vit-large-patch14"
# względem DeepfakeBench/ -> /opt/effort/models--openai--clip-vit-large-patch14 (katalog HF)
COPY common/dl.py /app/common/dl.py
COPY containers/aigi_effort/download.py /app/uc/download.py
RUN python /app/uc/download.py
COPY common /app/common
COPY containers/aigi_effort /app/uc
WORKDIR /opt/effort/DeepfakeBench
CMD ["python", "/app/common/main.py", "extract"]
