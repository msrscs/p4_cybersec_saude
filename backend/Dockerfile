# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app
# Só as rotinas do container `tarefas`; os scripts administrativos não entram na imagem.
COPY scripts/__init__.py scripts/tarefas.py scripts/verificar_log.py ./scripts/

FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && install -d -m 755 /etc/ssl/rds
WORKDIR /app
COPY --from=build --chown=root:root /app /app
# CA do Amazon RDS/Aurora para DB_SSLMODE=verify-full (ADR-0029). Hash fixo: se a AWS publicar
# um bundle novo, o build falha e o hash é revisado aqui, sem confiar no download às cegas.
ADD --checksum=sha256:90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b --chmod=644 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/rds/global-bundle.pem
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# HTTP dentro da VPC: só a task do frontend alcança a porta 8000 (security group, ADR-0029).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--proxy-headers"]
