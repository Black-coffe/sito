FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SITO_HOST=0.0.0.0 \
    SITO_PORT=8765 \
    SITO_DATA_DIR=/data

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install . && useradd --create-home --uid 1000 sito && mkdir -p /data && chown sito /data

USER sito
VOLUME ["/data"]
EXPOSE 8765
CMD ["sito", "serve"]
