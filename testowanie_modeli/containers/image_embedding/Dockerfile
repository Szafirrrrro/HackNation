FROM tm-base:latest
RUN pip install imagehash==4.3.1
COPY containers/image_embedding /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
