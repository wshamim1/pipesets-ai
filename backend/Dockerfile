FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SQLITE_DB_PATH=/data/pipesets.db

WORKDIR /app

# Tesseract: the default OCR engine for scanned PDF pages and images (loaders/_ocr.py, English included).
# Other languages: add tesseract-ocr-<code> packages. OCRmyPDF (+ ghostscript) is optional.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Dependencies first so this layer is cached until the lock changes. Exact versions, hash-checked
# (requirements.lock is generated from requirements.txt — see its header). The lock pins the CPU
# build of torch (torch==…+cpu), which only the PyTorch index serves; the hashes still decide
# which files are accepted.
COPY requirements.lock .
RUN pip install --require-hashes --extra-index-url https://download.pytorch.org/whl/cpu \
    -r requirements.lock

COPY . .

# Non-root user. /data (a single volume) holds the SQLite DB and uploaded documents;
# the app writes uploads to /app/uploads, which is a symlink into /data.
RUN useradd --system --uid 10001 --home-dir /app appuser \
    && mkdir -p /data \
    && ln -s /data/uploads /app/uploads \
    && chown -R appuser:appuser /data /app
USER 10001

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"

CMD ["sh", "-c", "mkdir -p /data/uploads && exec uvicorn main:app --host 0.0.0.0 --port 8000"]
