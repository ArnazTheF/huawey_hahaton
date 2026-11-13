FROM python:3.11.14-slim-bookworm@sha256:65a93d69fa75478d554f4ad27c85c1e69fa184956261b4301ebaf6dbb0a3543d
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 HOME=/tmp
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
COPY requirements.txt /app/requirements.txt
COPY requirements.lock /app/requirements.lock
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --disable-pip-version-check --index-url "$PIP_INDEX_URL" --timeout 60 --retries 1 -r requirements.lock
COPY baseline /app/baseline
COPY run_agent.py run_solution.py /app/
COPY scripts /app/scripts
COPY models /app/models
COPY configs /app/configs
ENTRYPOINT ["python", "/app/run_solution.py"]
