FROM python:3.12-slim

WORKDIR /opt/easyread

# The base includes CA certificates; PDF/image wheels bundle their native libs.
# The repository includes the built editor assets; Node/Electron is not needed.
COPY pyproject.toml README.md LICENSE ./
COPY easyread ./easyread
RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 easyread \
    && mkdir -p /data/EasyRead \
    && chown -R easyread:easyread /data

ENV PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    EASYREAD_HOME=/data/EasyRead \
    EASYREAD_HOST=0.0.0.0 \
    EASYREAD_PORT=8765

USER easyread
VOLUME ["/data/EasyRead"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('EASYREAD_PORT', '8765') + '/api/version', timeout=3).close()"

CMD ["python", "-m", "easyread", "serve"]
