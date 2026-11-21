FROM tm-base:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pytesseract==0.3.13 easyocr==1.7.2
COPY common/dl.py /app/common/dl.py
COPY containers/ocr/download.py /app/uc/download.py
RUN python /app/uc/download.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/ocr /app/uc
CMD ["python", "/app/common/main.py", "extract"]
