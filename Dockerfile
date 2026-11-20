FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HOME=/tmp/revalue YOLO_CONFIG_DIR=/tmp/revalue/yolo MPLCONFIGDIR=/tmp/revalue/matplotlib \
    YOLO_AUTOINSTALL=false OMP_NUM_THREADS=2 MKL_NUM_THREADS=2
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/revalue
COPY fyp/requirements-linux-cpu.txt /tmp/revalue-requirements.txt
RUN python -m pip install --no-deps --only-binary=:all: --index-url https://download.pytorch.org/whl/cpu \
        torch==2.15.0+cpu torchvision==0.29.2+cpu \
    && python -m pip install --only-binary=:all: -r /tmp/revalue-requirements.txt \
    && python -m pip check

COPY app/ ./app/
COPY backend/src/ ./backend/src/
COPY backend/data/phone_catalogue.json ./backend/data/phone_catalogue.json
COPY backend/models/revalue_exterior_yolo11n_v0.2.pt ./backend/models/revalue_exterior_yolo11n_v0.2.pt
RUN chmod -R a+rX /srv/revalue \
    && mkdir -p "$YOLO_CONFIG_DIR" "$MPLCONFIGDIR" \
    && chown -R 10001:10001 "$HOME"

USER 10001:10001
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import os, urllib.request; u = urllib.request.build_opener(urllib.request.ProxyHandler({})); u.open('http://127.0.0.1:' + os.getenv('PORT', '7860') + '/healthz', timeout=3).close()"
CMD ["python", "-m", "backend.src.supervisor"]
