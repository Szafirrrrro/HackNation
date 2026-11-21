FROM tm-base:latest
RUN pip install "sentence-transformers==3.3.1"
COPY containers/text /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
