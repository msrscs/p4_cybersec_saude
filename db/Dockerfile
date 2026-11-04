# syntax=docker/dockerfile:1
# Imagem do módulo de banco (ADR-0029): migrations (Alembic, role migrator), bootstrap das roles e
# importação do CID. Roda como task avulsa no ECS (ou `docker compose run --rm migrar`), nunca
# como serviço. Build a partir da raiz do repositório:
#
#   docker build -f db/Dockerfile -t cybersec-saude-db .
#
#   alembic upgrade head                 (padrão; MIGRATOR_DB_PASSWORD)
#   python -m scripts.bootstrap_db       (1x; usuário mestre do Aurora: POSTGRES_USER/PASSWORD)
#   python -m scripts.importar_cid       (catálogo CID; usa as chaves da aplicação)

FROM ghcr.io/astral-sh/uv:0.13.7 AS uv

FROM python:3.14-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /srv/backend
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
RUN uv sync --locked --no-dev --no-install-project
COPY backend/app ./app
COPY backend/scripts/__init__.py backend/scripts/bootstrap_db.py backend/scripts/importar_cid.py ./scripts/

FROM python:3.14-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PATH="/srv/backend/.venv/bin:$PATH" PYTHONPATH=/srv/backend
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && install -d -m 755 /etc/ssl/rds
WORKDIR /srv
COPY --from=build --chown=root:root /srv/backend /srv/backend
COPY --chown=root:root alembic.ini ./
COPY --chown=root:root db/migrations ./db/migrations
COPY --chown=root:root db/seeds ./db/seeds
# Mesma CA do RDS/Aurora da imagem do backend (ADR-0029), com o mesmo hash fixo.
ADD --checksum=sha256:90a6f1a7978a1b1b096dca6c57511ca48d3b8cf052f8e704baf358f34ea2f21b --chmod=644 \
    https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /etc/ssl/rds/global-bundle.pem
USER app
CMD ["alembic", "-c", "/srv/alembic.ini", "upgrade", "head"]
