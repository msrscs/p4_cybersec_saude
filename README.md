# CyberSec Saúde

Sistema de apoio à Oferta de Cuidados Integrados (OCI) da SESAU Recife. Projeto acadêmico de Segurança da Informação.

Documentação: [`docs/SPEC.md`](docs/SPEC.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md), [`docs/adr/`](docs/adr/).

## Pré-requisitos
Docker, [uv](https://docs.astral.sh/uv/) e Node.js 26.

## Subir o ambiente
```bash
cp .env.example .env   # preencha os valores
docker compose up --build
```
Frontend em http://127.0.0.1:3000. A API não fica exposta fora da rede interna do Docker.

## Desenvolvimento
```bash
# Backend
cd backend && uv sync
uv run pytest && uv run ruff check . && uv run mypy . && uv run bandit -r app && uv run pip-audit

# Frontend
cd frontend && npm ci
npm test && npm run lint && npm audit

# Migrations (na raiz, requer MIGRATION_DATABASE_URL)
uv run --project backend alembic upgrade head
```
