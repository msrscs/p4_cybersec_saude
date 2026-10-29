# CyberSec Saúde

Sistema de apoio à Oferta de Cuidados Integrados (OCI) da SESAU Recife. Projeto acadêmico de Segurança da Informação.

Documentação: [`docs/SPEC.md`](docs/SPEC.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md), [`docs/adr/`](docs/adr/).

## Pré-requisitos
Docker, [uv](https://docs.astral.sh/uv/) e Node.js 26.

## Primeira configuração do banco
```bash
cp .env.example .env                      # preencha os valores (POSTGRES_USER != app_user/migrator)
cd backend && uv run python -m scripts.gerar_chaves && cd ..   # KEK, HMAC_KEY e LOG_CHECKPOINT_KEY no .env (sem exibir)
docker compose up -d db
cd backend && uv run --env-file ../.env python -m scripts.bootstrap_db   # cria roles e schema
cd .. && uv run --project backend --env-file .env alembic upgrade head   # aplica migrations
cd backend && uv run --env-file ../.env python -m scripts.criar_usuario \
  --cpf 000.000.000-00 --nome "Seu Nome" --email voce@recife.pe.gov.br   # senha pedida sem eco
```

## Acesso e recuperação
- **1º acesso:** CPF + senha → cadastro do MFA (QR code no Google/Microsoft Authenticator) → guarde os 10 códigos de recuperação.
- **Esqueceu a senha ou perdeu o celular e os códigos:** um administrador roda
  `cd backend && uv run --env-file ../.env python -m scripts.resetar_acesso --cpf ...`,
  que gera uma senha temporária (mostrada uma vez); o usuário recadastra o MFA e troca a senha.

## Perfis de acesso (RBAC)
```bash
cd backend && uv run --env-file ../.env python -m scripts.atribuir_grupo --cpf 000.000.000-00 --grupo Administrador
```
Grupos: Administrador, Gestor, Gestor do Cuidado, Navegador, Auditor (`--remover` desfaz). Sem grupo, o usuário entra mas não acessa pacientes (ADR-0011).

## Integridade do log de auditoria
```bash
cd backend && uv run --env-file ../.env python -m scripts.verificar_log --checkpoint
```
Recalcula a cadeia de hashes inteira, grava um checkpoint assinado e imprime a **âncora** (`seq:hash`): guarde-a fora do sistema e confira depois com `--ancora seq:hash`. Sai com código 1 se detectar adulteração (ADR-0010).

## Teste ponta a ponta (navegador)
```bash
cd frontend && npx playwright install chromium && sudo npx playwright install-deps chromium  # 1x
cd backend && uv run --env-file ../.env python -m tests.e2e_ambiente
```
Sobe um banco temporário, a API e o frontend em portas próprias, roda o fluxo completo no Chromium (login, MFA, pacientes, logout) e remove tudo no fim (ADR-0012).

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
