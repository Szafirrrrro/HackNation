FROM tm-base:latest
# reverse-SynthID (Research License, tylko niekomercyjnie, wymagana atrybucja):
# przypięty commit; używamy WYŁĄCZNIE ścieżek detekcji, nie bypassu.
ARG RSID_COMMIT=b11083676fd3ee3ff97ce9d03c0e409e46905902
RUN pip install scipy PyWavelets scikit-learn \
    && git init /opt/rsid && cd /opt/rsid \
    && git remote add origin https://github.com/aloshdenny/reverse-SynthID.git \
    && git fetch --depth 1 origin ${RSID_COMMIT} && git checkout FETCH_HEAD \
    && rm -rf .git watermark_investigation assets artifacts/visualizations runs gui
COPY containers/ai_generated /app/uc
RUN python /app/uc/download.py
CMD ["python", "/app/uc/run.py"]
