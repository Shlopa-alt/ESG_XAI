# Исполнитель запусков (очередь cpu): Celery + скрипты runner/ в зафиксированном окружении.
# Код runner/ не копируется в образ — он смонтирован из репозитория (/repo), чтобы коммит
# запуска был коммитом рабочей копии сервера (правило 3).
FROM python:3.12.10-slim

RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*' \
    && git config --system core.autocrlf true \
    && git config --system core.filemode false

# Окружение расчётов — ровно requirements.lock (его sha256 пишется в каждый запуск)
COPY hsu2025/requirements.lock /opt/requirements.lock
RUN python -m venv /opt/run \
    && /opt/run/bin/pip install --no-cache-dir --no-deps --timeout 300 --retries 10 \
       --extra-index-url https://download.pytorch.org/whl/cpu -r /opt/requirements.lock

# Окружение исполнителя
COPY worker/requirements.txt /opt/worker-requirements.txt
RUN python -m venv /opt/worker && /opt/worker/bin/pip install --no-cache-dir --timeout 300 --retries 10 -r /opt/worker-requirements.txt

COPY worker /app/worker
WORKDIR /app
ENV RUN_PYTHON=/opt/run/bin/python \
    GIT_OPTIONAL_LOCKS=0 \
    PYTHONUNBUFFERED=1
CMD ["/opt/worker/bin/celery", "-A", "worker.tasks", "worker", "-Q", "cpu", "-c", "2", \
     "-n", "cpu@%h", "--loglevel", "INFO"]
