FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        fontconfig \
        fonts-dejavu \
        libfreetype6 \
        libjpeg62-turbo \
        libopenjp2-7 \
        libpng16-16 \
        libraqm0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

RUN pip install \
    --no-cache-dir \
    --disable-pip-version-check \
    -r /app/requirements.txt

COPY . /app

RUN mkdir -p \
    /app/data \
    /app/widget_cache \
    /app/covers \
    /app/collages

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "4", "--timeout", "120", "server:app"]