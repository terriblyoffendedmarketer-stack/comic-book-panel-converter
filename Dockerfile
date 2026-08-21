# Dockerfile — Comic Book Converter
# Deploys the Flask web app with all conversion dependencies.
# Usage: docker build -t comic-converter . && docker run -p 8080:8080 comic-converter
#
# Gotchas:
# - Uses python:3.12-slim, not alpine (OpenCV needs glibc).
# - unar for CBR extraction, p7zip-full for CB7 and KCC.
# - 7zz symlink needed for KCC (it calls 7zz, not 7z).
# - DATA_DIR env var points to persistent volume for input/output.

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    p7zip-full \
    unar \
    libgl1 \
    libglib2.0-0 \
    git \
    gcc \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/7z /usr/bin/7zz

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

ENV PORT=8080
ENV DATA_DIR=/data

RUN mkdir -p /data/input /data/output
RUN gcc -O2 -shared -fPIC -o src/dither_native.so src/dither_native.c

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--timeout", "600", "--workers", "1", "--threads", "8", "wsgi:app"]
