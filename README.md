# CyberSec Saúde

Sistema de apoio à Oferta de Cuidados Integrados (OCI) da SESAU Recife. Projeto acadêmico de Segurança da Informação.

Documentação: [`docs/SPEC.md`](docs/SPEC.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md), [`docs/adr/`](docs/adr/).

## Pré-requisitos
Docker, [uv](https://docs.astral.sh/uv/) e Node.js 26.

## Primeira configuração do banco
```bash
cp .env.example .env                      # preencha os valores (POSTGRES_USER != app_user/migrator)
docker compose up -d db
cd backend && uv run --env-file ../.env python -m scripts.bootstrap_db   # cria roles e schema
cd .. && uv run --project backend --env-file .env alembic upgrade head   # aplica migrations
```

## Subir o ambiente
```bash
docker compose up --build
```
Frontend em http://127.0.0.1:3000. A API não fica exposta fora da rede interna do Docker.

## API e Swagger (desenvolvimento)
```bash
cd backend && uv run --env-file ../.env uvicorn app.main:create_app --factory --reload
```
Swagger em http://127.0.0.1:8000/docs (desabilitado quando `ENVIRONMENT=prod`).

## Desenvolvimento
```bash
# Backend (com --env-file os testes de integração usam um banco temporário, criado e removido)
cd backend && uv sync
uv run --env-file ../.env pytest && uv run ruff check . && uv run mypy . && uv run bandit -r app && uv run pip-audit

# Frontend
cd frontend && npm ci
npm test && npm run lint && npm audit

# Migrations (na raiz)
uv run --project backend --env-file .env alembic upgrade head
```
