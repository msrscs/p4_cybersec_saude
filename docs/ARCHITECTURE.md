# ARCHITECTURE: CyberSec Saúde

Versão: 0.1 | Relacionado: `SPEC.md`, `THREAT_MODEL.md`, `/docs/adr`

## 1. Contexto
Sistema web para [descrever: ex. gestão de prontuários/consultas] com dados de saúde (sensíveis pela LGPD, art. 5º, II). Prioridades: confidencialidade, integridade e rastreabilidade.

## 2. Visão geral (C4: containers)

```mermaid
flowchart LR
    U[Usuário no navegador] -->|HTTPS| F[Frontend Node.js]
    F -->|HTTPS + cookie de sessão| B[API Python / FastAPI]
    B -->|SQL parametrizado| D[(PostgreSQL 18)]
    B -->|KEK| K[Gerenciador de chaves: .env no dev, secret manager em produção]
    D --- A[(log WORM)]
```

| Componente | Tecnologia | Responsabilidade |
|---|---|---|
| Frontend | Node.js | Telas, fluxo de login/MFA, headers de segurança (CSP, HSTS) |
| Backend | Python 3.14 + FastAPI | Regras de negócio, autenticação, MFA, criptografia, auditoria |
| Banco | PostgreSQL 18 (Docker) | Persistência, triggers WORM, permissões por role |
| Chaves | Variável de ambiente (dev) | Guarda a KEK que cifra as DEKs |

## 3. Camadas do backend

```
rotas (routers)  ->  serviços  ->  repositórios  ->  banco
      |                 |
   validação        regras de negócio, cripto, auditoria
   (Pydantic)
```
- **Rotas:** só recebem/validam entrada e devolvem resposta. Sem lógica de negócio.
- **Serviços:** autenticação, MFA, criptografia, auditoria, regras do domínio.
- **Repositórios:** único ponto de acesso ao banco (queries parametrizadas/ORM).

Estrutura sugerida:
```
backend/app/
  api/         # routers
  core/        # config, segurança, dependências
  services/    # auth, mfa, crypto, audit
  repositories/
  models/      # tabelas
  schemas/     # Pydantic
  tests/
```

## 4. Fluxo de autenticação com MFA

```mermaid
sequenceDiagram
    participant U as Usuário
    participant F as Frontend
    participant B as API
    participant D as Banco
    U->>F: CPF + senha
    F->>B: POST /auth/login
    B->>D: busca usuário (hash do CPF), verifica bcrypt
    B-->>F: 200 mfa_required (token temporário, curto)
    U->>F: código TOTP
    F->>B: POST /auth/mfa/verify
    B->>D: decifra segredo TOTP, valida código
    B->>D: grava evento em log
    B-->>F: sessão completa (cookie HttpOnly, Secure, SameSite)
```
Regras: token temporário só vale para a etapa MFA; rate limit e bloqueio progressivo nas duas etapas; códigos de recuperação de uso único, armazenados com hash.

## 5. Criptografia de dados sensíveis (envelope encryption)

- **Dado sensível** é cifrado com uma **DEK** (AES-256-GCM, nonce único por registro).
- A **DEK** é cifrada com a **KEK** e guardada junto do registro (`dek_encrypted`).
- A **KEK** nunca fica no banco: vem de variável de ambiente (dev) ou secret manager (produção).
- Para buscar por campo cifrado (ex.: e-mail), usar **hash determinístico com chave (HMAC-SHA256)** em coluna separada.
- Rotação: trocar a KEK exige apenas recifrar as DEKs, não os dados.

| Dado | Proteção |
|---|---|
| Senha | bcrypt com salt, custo >= 12 (hash, não é cifrado) |
| Segredo TOTP | AES-256-GCM |
| Dados de saúde (CPF, diagnóstico, etc.) | AES-256-GCM por campo |
| Códigos de recuperação | Hash |
| Em trânsito | TLS |

## 6. Log de auditoria WORM

- Tabela `log` (schema `app`) **append-only**: triggers bloqueiam `UPDATE`, `DELETE` e `TRUNCATE`.
- Role da aplicação (`app_user`) com **apenas INSERT e SELECT** na tabela. Migrations rodam com outra role.
- **Hash encadeado:** `hash = SHA-256(conteudo + prev_hash)`. Alterar um registro quebra todos os seguintes.
- Endpoint/job de **verificação da cadeia** para detectar adulteração.
- Opcional (nível avançado): exportar periodicamente para armazenamento com *object lock*.
- Nenhum dado sensível dentro do log.

Esquema base:
```
log(id_log, data_hora, acao, resumo_acessado, ip_origem, request_id, geolocalizacao, cpf_usuario_hash, cpf_paciente_hash, id_oci, prev_hash, hash_assinatura_worm)
```

## 7. Controle de acesso
RBAC com perfis (usuário, profissional, administrador, auditor). Verificação **sempre no backend**, a cada requisição. Auditor tem somente leitura dos logs. Administrador não lê dados de saúde sem registro de auditoria.

## 8. Implantação (Docker)
- Desenvolvimento: `db` no Docker (porta 127.0.0.1:5433), backend e frontend rodando no WSL.
- Empacotamento (T01/T09): serviços `backend` e `frontend` com Dockerfile (usuário não-root, imagem enxuta), rede interna entre containers e apenas o frontend exposto.
- Segredos: `.env` fora do git; `.env.example` versionado sem valores.

## 9. Decisões de arquitetura (ADRs a criar em `/docs/adr`)
| ADR | Decisão | Alternativa descartada |
|---|---|---|
| 001 | FastAPI como backend | Django |
| 002 | TOTP como segundo fator | SMS (vulnerável a SIM swap) |
| 003 | bcrypt com salt para senhas | Argon2id/PBKDF2 |
| 004 | Criptografia de campo com envelope | Só pgcrypto / disco cifrado |
| 005 | WORM por trigger + hash encadeado | Tabela comum com permissão |
| 006 | Postgres 18 em Docker | Instalação local |

## 10. Requisitos de qualidade
- Testes automatizados em auth, cripto e auditoria.
- Análise estática: `bandit`, `ruff`, `mypy`; dependências: `pip-audit`, `npm audit`.
- Teste dinâmico com OWASP ZAP na fase final.
