FROM tm-base:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pytesseract==0.3.13 easyocr==1.7.2
COPY containers/ocr /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
