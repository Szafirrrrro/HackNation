FROM tm-base:latest
COPY common/dl.py /app/common/dl.py
COPY containers/object_detection/download.py /app/uc/download.py
RUN python /app/uc/download.py
# Owlv2ImageProcessor wymaga scipy (po warstwie z wagami, żeby nie pobierać ich ponownie)
RUN pip install "scipy<1.15"
# kontrola kompletności wag (osobna warstwa - nie unieważnia pobranych wag)
COPY common/ensure_weights.py /app/common/ensure_weights.py
RUN python /app/common/ensure_weights.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/object_detection /app/uc
CMD ["python", "/app/common/main.py", "extract"]
