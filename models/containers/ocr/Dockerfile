FROM tm-base:latest
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr tesseract-ocr-pol tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/* \
    && pip install pytesseract==0.3.13
COPY common /app/common
COPY containers/ocr /app/uc
CMD ["python", "/app/common/main.py", "extract"]
