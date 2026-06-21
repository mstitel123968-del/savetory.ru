FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=100 \
    PIP_RETRIES=10

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates fonts-dejavu-core \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/
RUN set -eux; \
    pip_flags="--no-cache-dir --retries 10 --timeout 100 --prefer-binary --index-url ${PIP_INDEX_URL}"; \
    if [ -n "${PIP_TRUSTED_HOST}" ]; then pip_flags="${pip_flags} --trusted-host ${PIP_TRUSTED_HOST}"; fi; \
    python -m pip install ${pip_flags} --upgrade pip setuptools wheel; \
    python -m pip install ${pip_flags} -r requirements.txt

COPY . /app/

# Normalize potential Windows line endings before marking the entrypoint executable
RUN sed -i 's/\r$//' docker/entrypoint.sh \
    && chmod +x docker/entrypoint.sh

RUN SECRET_KEY=build-only-dummy-key python manage.py collectstatic --noinput

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "trezo_site.wsgi:application", "--bind", "0.0.0.0:8000"]
