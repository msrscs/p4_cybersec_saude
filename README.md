# CyberSec Saúde

Sistema de apoio à Oferta de Cuidados Integrados (OCI) da SESAU Recife. Projeto acadêmico de Segurança da Informação.

Documentação: [`docs/SPEC.md`](docs/SPEC.md), [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Os ADRs e o modelo de ameaças são mantidos fora do repositório.

## Módulos
| Pasta | Imagem | Na AWS |
|---|---|---|
| `frontend/` | `docker build frontend` | ECS Fargate atrás de CloudFront + ALB (TLS na borda) |
| `backend/` | `docker build backend` | ECS Fargate, alcançado só pelo frontend; rotinas pelo EventBridge Scheduler |
| `db/` | `docker build -f db/Dockerfile .` | Task avulsa de migrations/bootstrap contra o Aurora Serverless v2 |

Variáveis por task e requisitos da infraestrutura (security groups, cabeçalho secreto de origem, `rds.force_ssl`) estão no ADR-0029.

## Pré-requisitos
Docker, [uv](https://docs.astral.sh/uv/) e Node.js 26.

## Primeira configuração do banco
```bash
cp .env.example .env                      # preencha os valores (POSTGRES_USER != app_user/migrator)
cd backend && uv run python -m scripts.gerar_chaves && cd ..   # KEK, HMAC_KEY e LOG_CHECKPOINT_KEY no .env (sem exibir)
docker compose up -d db
cd backend && uv run --env-file ../.env python -m scripts.bootstrap_db   # cria roles e schema
cd .. && uv run --project backend --env-file .env alembic upgrade head   # aplica migrations
cd backend && uv run --env-file ../.env python -m scripts.importar_cid && cd ..  # catálogo de CID (ADR-0020)
cd backend && uv run --env-file ../.env python -m scripts.criar_usuario \
  --cpf 000.000.000-00 --nome "Seu Nome" --email voce@recife.pe.gov.br   # senha pedida sem eco
```

## Acesso e recuperação
- **1º acesso:** CPF + senha → cadastro do MFA (QR code no Google/Microsoft Authenticator) → guarde os 10 códigos de recuperação.
- **Novos usuários, grupos e reset de acesso:** pela tela **Usuários**, com perfil Administrador (ADR-0017). Os scripts abaixo ficam para o primeiro administrador e para emergências.
- **Esqueceu a senha ou perdeu o celular e os códigos, sem administrador disponível:** quem tem acesso ao servidor roda
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
Sobe um banco temporário, a API e o frontend em portas próprias (HTTP em `localhost`, como atrás da borda na AWS), roda o fluxo completo no Chromium (login, MFA, pacientes, logout) e remove tudo no fim (ADR-0012, ADR-0029).

## Subir o ambiente
```bash
docker compose up --build
```
Acesso em **http://localhost:3000**. Só o frontend publica porta; a API não (ADR-0029). O banco usa TLS obrigatório com um certificado efêmero gerado pelo próprio container, então não há certificado para criar, instalar ou renovar. Na AWS, o HTTPS fica no CloudFront/ALB.

Migrations pela imagem do módulo `db` (a mesma usada na AWS):
```bash
docker compose run --rm migrar                                  # alembic upgrade head
docker compose run --rm migrar python -m scripts.bootstrap_db   # roles (1x)
```

As rotinas periódicas rodam no container `tarefas` (limpeza a cada 15 min, verificação do log a cada hora). Acompanhe com `docker logs cybersec_saude-tarefas`.

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
