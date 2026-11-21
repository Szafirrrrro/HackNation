FROM tm-base:latest
COPY containers/object_detection /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
