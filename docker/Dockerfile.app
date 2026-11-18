# Fast code-only update from an existing complete EasyRead runtime.
# First installation / changed runtime dependencies: use the root Dockerfile.
ARG BASE_IMAGE=easyread:local
FROM ${BASE_IMAGE} AS full
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_DEFAULT_TIMEOUT=60
ARG PIP_RETRIES=3
USER root
WORKDIR /opt/easyread
RUN rm -rf /opt/easyread/easyread
COPY pyproject.toml README.md LICENSE ./
COPY easyread ./easyread
RUN python -m pip install --no-cache-dir --no-deps --force-reinstall . \
    && python -m pip check
COPY docker/runtime.py /usr/local/bin/easyread-runtime
COPY docker/cli.py /usr/local/bin/easyread-cli
COPY docker/terminal-session.sh /usr/local/bin/easyread-terminal-session
RUN chmod 755 /usr/local/bin/easyread-runtime /usr/local/bin/easyread-cli /usr/local/bin/easyread-terminal-session
USER easyread
ENTRYPOINT ["python", "/usr/local/bin/easyread-runtime"]
CMD ["python", "-m", "easyread", "serve"]
