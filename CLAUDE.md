# CLAUDE.md

Projeto CyberSec- Sáude
Acadêmico de Segurança da Informação. Segurança vem antes de funcionalidade.

## Stack
- Frontend: Node.js 26 + Express + helmet (/frontend)
- Backend: Python 3.14 + FastAPI, dependências com uv (/backend)
- Banco: PostgreSQL 18 (migrations em /db/migrations, via Alembic)
- Docs: /docs (SPEC.md, ARCHITECTURE.md, THREAT_MODEL.md, /adr)

## Fluxo de trabalho
1. Leia `docs/SPEC.md` e os ADRs relevantes antes de implementar.
2. Para mudanças grandes, proponha um plano e espere aprovação.
3. Implemente UMA tarefa por vez (ver "Plano de tarefas" na SPEC).
4. Escreva testes junto com o código. Rode os testes antes de dizer que terminou.
5. Commits pequenos, mensagens no padrão Conventional Commits (feat:, fix:, docs:).
6. Decisão técnica nova ou que mude algo existente: crie um ADR em `docs/adr/`.

## Comandos
- Backend: `cd backend && uv run --env-file ../.env pytest` | `uv run ruff check .` | `uv run mypy .` | `uv run bandit -r app` | `uv run pip-audit`
- Frontend: `cd frontend && npm test` | `npm run lint` | `npm audit`
- Banco: `cd backend && uv run --env-file ../.env python -m scripts.bootstrap_db` (roles, 1x) | na raiz: `uv run --project backend --env-file .env alembic upgrade head`
- Subir tudo: `docker compose up`

## Regras de segurança (inegociáveis)
- NUNCA hardcodar segredos, chaves ou senhas. Use variáveis de ambiente (.env fora do git).
- NUNCA logar senhas, tokens, códigos MFA, chaves ou dados sensíveis em texto claro.
- Senhas: bcrypt com salt, custo >= 12 (ver ADR-0003; atenção ao limite de 72 bytes). Nunca MD5/SHA simples.
- MFA: TOTP (pyotp) obrigatório no login, com códigos de recuperação de uso único (guardados com hash).
- Dados sensíveis: criptografia em nível de campo com AES-256-GCM (lib `cryptography`), nonce único por registro, envelope encryption (DEK cifrada por KEK). Chaves nunca ficam no banco junto dos dados.
- SQL: apenas queries parametrizadas/ORM. Proibido concatenar strings em SQL.
- Toda entrada é validada no backend (Pydantic), independentemente do frontend.
- Sessões/tokens: expiração curta, cookies HttpOnly + Secure + SameSite, proteção contra CSRF.
- Rate limiting e bloqueio progressivo em login e verificação MFA.
- Mensagens de erro genéricas ao cliente (sem stack trace, sem revelar se o usuário existe).
- TLS obrigatório; headers de segurança no frontend (CSP, HSTS, X-Content-Type-Options).
- Dependências: versões fixas (lockfile), rodar `npm audit` e `pip-audit` periodicamente.

## Log de auditoria WORM
- Tabela `log` (schema `app`) append-only: triggers bloqueiam UPDATE, DELETE e TRUNCATE.
- A role da aplicação só tem INSERT e SELECT nessa tabela.
- Cada registro guarda `prev_hash` e `hash_assinatura_worm` (SHA-256 do conteúdo + prev_hash) para detectar adulteração.
- Deve existir um job/endpoint de verificação da cadeia de hashes.
- Eventos obrigatórios: login (sucesso/falha), MFA, troca de senha, acesso a dado sensível, mudança de permissão.
- Nunca incluir dado sensível no conteúdo do log.

## Convenções de código
- Python: type hints obrigatórios, formatação com ruff/black, funções pequenas.
- Node: ESLint + Prettier.
- Separação: rotas -> serviços -> repositórios (acesso a dados). Nada de lógica de negócio nas rotas.
- Cobertura mínima de testes nos módulos de auth, criptografia e auditoria.

## O que NÃO fazer
- Não inventar bibliotecas de criptografia próprias.
- Não desabilitar verificação TLS/validações "só para testar".
- Não alterar migrations já aplicadas; crie uma nova.
- Não avançar para a próxima tarefa sem os testes da atual passando.

## Ao terminar cada tarefa
Resuma o que mudou, quais riscos da THREAT_MODEL foram mitigados e o que ficou pendente.
 