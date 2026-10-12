FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
RUN pip install --no-cache-dir pytest==8.4.2 pytest-timeout==2.4.0 pytest-json-report==1.5.0 ruff==0.14.0
COPY opencode /usr/local/bin/opencode
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/workspace/src OPENCODE_DISABLE_AUTOUPDATE=true OPENCODE_DISABLE_SHARE=true
USER 65534:65534
WORKDIR /workspace
