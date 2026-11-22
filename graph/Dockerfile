FROM python:3.13-slim-bookworm
WORKDIR /opt/scamgraph
ENV PYTHONUNBUFFERED=1 STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
COPY requirements-capture.txt ./
COPY graph/requirements*.txt graph/
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 tesseract-ocr-pol tesseract-ocr-eng \
    && python -m pip install --no-cache-dir -r graph/requirements-app.txt \
    && python -m playwright install --with-deps chrome \
    && rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr \
    && tesseract --list-langs | grep -qx pol \
    && tesseract --list-langs | grep -qx eng \
    && rm -rf /var/lib/apt/lists/*
COPY graph/app.py graph/
COPY graph/ftf_graph/*.py graph/ftf_graph/
COPY graph/data/sample_cards.jsonl graph/data/tranco_46YVX.csv graph/data/trusted_manual.txt graph/data/
COPY graph/eval/reference.jsonl graph/eval/queries.jsonl graph/eval/labels.json graph/eval/
COPY scamgraph/*.py scamgraph/
COPY scamgraph/discovery/*.py scamgraph/discovery/snapshot.js scamgraph/discovery/
COPY scamgraph/discovery/data/top-100k.csv scamgraph/discovery/data/
COPY models/common/*.py models/common/
COPY db/schema.sql db/schema.sql
COPY scripts/evaluate_campaigns.py scripts/evaluate_campaigns.py
RUN useradd --create-home analyst && mkdir .private-discovery && chown analyst .private-discovery
USER analyst
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "graph/app.py", "--server.address=0.0.0.0", "--server.port=8501"]
