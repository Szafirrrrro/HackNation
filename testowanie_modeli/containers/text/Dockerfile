FROM tm-base:latest
RUN pip install "sentence-transformers==3.3.1"
COPY common/dl.py /app/common/dl.py
COPY containers/text/download.py /app/uc/download.py
RUN python /app/uc/download.py
# kod po pobraniu modeli -> zmiany kodu nie unieważniają warstwy z wagami
COPY common /app/common
COPY containers/text /app/uc
CMD ["python", "/app/common/main.py", "extract"]
