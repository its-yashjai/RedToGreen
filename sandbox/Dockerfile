# The image the repo's tests run in. Kept tiny on purpose: Python + pytest, nothing else.
FROM python:3.12-slim

RUN python -m pip install --no-cache-dir --disable-pip-version-check pytest

# Never run untrusted code as root.
USER 65534:65534
WORKDIR /workspace
