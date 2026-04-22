FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt ./requirements-prod.txt

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-prod.txt

COPY . .

CMD ["python", "herramientas/auto_actualizar.py", "--help"]

