# Operator-owned tool image. Build context contains tools only, never a candidate.
FROM python:3.12-slim-bookworm
LABEL org.oma.sandbox="1"
RUN apt-get update && apt-get install -y --no-install-recommends nodejs git \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /opt/oma/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/oma/requirements.txt
RUN mkdir /workspace && chmod 755 /workspace
ENV PYTHONDONTWRITEBYTECODE=1
USER 65532:65532
WORKDIR /workspace
