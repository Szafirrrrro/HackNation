FROM tm-base:latest
RUN pip install imagehash==4.3.1
COPY common/dl.py /app/common/dl.py
COPY containers/image_embedding/download.py /app/uc/download.py
RUN python /app/uc/download.py
# kontrola kompletności wag (osobna warstwa - nie unieważnia pobranych wag)
COPY common/ensure_weights.py /app/common/ensure_weights.py
RUN python /app/common/ensure_weights.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/image_embedding /app/uc
CMD ["python", "/app/common/main.py", "extract"]
