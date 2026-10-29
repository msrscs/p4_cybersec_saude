# SPEC: [CyberSec Saúde]

Versão: 0.1 | Autor(es): [André Luis Freire de Andrade Sieczko, Artur Torres Lima Cavalcanti, Eduardo Henrique Ferreira Fonseca Barbosa, Gabriel de Medeiros Almeida, Mauro Sérgio Rezende da Silva, Silvio Barros Tenório] | Data: [29/10/2026]

## 1. Visão geral
**Problema:** [Integração de Dados na SESAU Recife. A Secretaria Executiva da Rede de Média e Alta Complexidade (SERMAC) está implementando o modelo de Oferta de Cuidados Integrados (OCI). O objetivo é criar jornadas de cuidado contínuas entre a Atenção Primária, Especializada e outras redes. Para que a transformação digital avance, a gestão exige uma governança sólida, baseada em dados integrados e em tempo real.]
**Público/usuários:** [Pessoal de saúde da prefeitura do Recife]
**Fora de escopo:** [A integração com sistemas existentes]

## 2. Perfis de usuário
| Perfil | Descrição | Permissões principais |
|---|---|---|
| Navegador | Acesso local. Visão restrita à sua própria unidade de saúde, acompanhando o passo a passo dos pacientes locais na linha de cuidado. | |
| Administrador | Acesso total ao sistema | |
| Auditor | Somente leitura dos logs | |
| Gestor do Cuidado | Acesso regional/específico. Visualiza a gestão da OCI apenas na rede própria (gestão direta). | |
| Gestor | Acesso global. Visualiza a execução da OCI em toda a rede de saúde. | |

## 3. Requisitos funcionais
Formato: RF-XX | user story | critérios de aceite.

**RF-01 Cadastro Usuários**
Como usuário, quero fazer o login, mudar a senha e recuperar o acesso ao sistema.
- [ ] Senha com no mínimo 12 caracteres, pelo menos 1 maiúscula, pelo menos 1 minúscula, pelo menos número, pelo menos um caracter especial, validada no backend
- [ ] Senha armazenada com dbcrypt com salt
- [ ] Ativação do MFA obrigatória no primeiro acesso
- [ ] Criptografar dados sensíveis
- [ ] Tabela: [usuario] Campos: [cpf_hash, cpf_cripto, nome_cripto, email_cripto, unidade, senha_hash_salt, status]
- [ ] CRUD, mudança status
- [ ] Conferir digitos verificador do CPF
- [ ] Sanitizar entradas de dados

**RF-02 Login com MFA**
Como usuário, quero entrar com senha + código TOTP.
- [ ] Login pelo CPF
- [ ] Login só conclui após senha e TOTP válidos
- [ ] 5 falhas seguidas bloqueiam a conta temporariamente
- [ ] Códigos de recuperação de uso único (armazenados com hash)
- [ ] Possibilidade de utilizar Google ou Microsoft Authentication ou via email

**RF-03 Cadastro Pacientes**
Dados do paciente.
- [ ] Criptografar dados sensíveis
- [ ] Tabela: [paciente] Campos: [cpf_hash, cpf_cripto, nome_cripto, data_nascimento_cripto, email_cripto]
- [ ] CRUD
- [ ] Conferir digitos verificador do CPF

**RF-04 Consulta de logs de auditoria (auditor)**
Log WORM do Sistema. Logar tudo.
- [ ] Somente leitura, com filtros por data/usuário/acao
- [ ] Verificação de integridade da cadeia de hashes
- [ ] Dados sensíveis devem está criptografados ou hash.
- [ ] Tabela: [log] Campos: [id_log, acao, resumo_acessado, ip_origem, request_id, geolocaliacao, data_hora, hash_assinatura_worm, cpf_paciente_hash, cpf_usuario_hash, id_oci]

**RF-05 Cadastro Papel RBAC**
Papel RBAC.
- [ ] Tabela: [papel] Campos: [id_papel, papel, descricao, status]
- [ ] CRUD

**RF-06 Cadastro Permissão RBAC**
Permissão RBAC.
- [ ] Tabela: [papel] Campos: [id_permissao, permissao, descricao, status]
- [ ] CRUD

**RF-07 Cadastro Grupo de Usuários**
Grupos de Usuários.
- [ ] Tabela: [grupo] Campos: [id_grupo, grupo, status]
- [ ] CRUD

**RF-08 Cadastro Tipo de OCI**
Tipo de OCI.
- [ ] Tabela: [tipo_oci] Campos: [id_tipo_oci, tipo_oci, prazo_dignostico]
- [ ] CRUD

**RF-09 Cadastro CID**
CID de doenças.
- [ ] Tabela: [cid] Campos: [cid_hash, cid, descricao]
- [ ] CRUD

**RF-10 Cadastro Unidade de Saúde**
Unidade de Sáude (Posto de Sáude, Clínica, Hospital, Laboratório).
- [ ] Tabela: [unidade_saude] Campos: [id_unidade, tipo_unidade, nome, endereco, telefone]
- [ ] CRUD

**RF-11 Cadastro Serviços de Saúde**
Serviços (Consulta Ortopédia, Consulta Oncologista, Exame Sangue, Exame Mamografia).
- [ ] Tabela: [servico_saude] Campos: [id_servico, nome, descricao]
- [ ] CRUD

**RF-12 Cadastro OCI e Navegação**
OCI, Navegação (Marcação dos serviçso de saúde).
- [ ] Tabela: [oci] Campos: [id_oci, id_tipo_oci, cpf_paciente_hash, data_criacao, cid_hash, fk_tipo_oci_id_tipo_oci, resultado, resultado_cid_hash, status]
- [ ] Tabela: [oci_navegacao] Campos: [id_oci_navegacao, id_oci, id_unidade, id_servico, data_hora, status]
- [ ] CRUD

**RF-13 Relacionamentos das Tabelas**
Relacionamentos.
- [ ] Tabela: [papel_permissao] Campos: [fk_papel_id_papel, fk_permissao_id_permissao]
- [ ] Tabela: [grupo_papel] Campos: [fk_grupo_id_grupo, fk_papel_id_papel]
- [ ] Tabela: [usuario_grupo] Campos: [fk_usuario_cpf_hash, fk_grupo_id_grupo]
- [ ] Tabela: [log_oci] Campos: [fk_log_id_log, fk_oci_id_oci]
- [ ] Tabela: [tipo_oci_cid] Campos: [fk_tipo_oci_tipo_oci_id, fk_cid_cid_hash]
- [ ] Tabela: [unidade_saude_servico_saude] Campos: [fk_unidade_saude_id_unidade, fk_servico_saude_id_servico]
- [ ] Tabela: [cid_servico_saude] Campos: [fk_cid_cid_hash, fk_servico_saude_id_servico]

## 4. Requisitos não funcionais / segurança
| ID | Requisito | Verificação |
|---|---|---|
| RNF-01 | MFA (TOTP) para todos os usuários | Teste automatizado |
| RNF-02 | Dados sensíveis cifrados com AES-256-GCM (campo a campo) | Inspeção no banco + teste |
| RNF-03 | Chaves fora do banco (KEK em env/secret manager) | Revisão de arquitetura |
| RNF-04 | Logs WORM: sem UPDATE/DELETE, com encadeamento de hash | Teste tentando alterar |
| RNF-05 | TLS em toda comunicação | Configuração |
| RNF-06 | Proteção contra OWASP Top 10 | Checklist ASVS |
| RNF-07 | Rate limiting em login/MFA | Teste |

## 5. Dados e classificação
| Campo | Tabela | Classificação | Proteção |
|---|---|---|---|
| email | users | Pessoal | Hash para busca + cifrado |
| senha | users | Crítico | dbcrypt com salt |
| segredo TOTP | users | Crítico | AES-256-GCM |
| [dado sensível do domínio] | | Sensível | AES-256-GCM |

Tabelas previstas: `usuario`, `mfa_recovery_codes`, `sessions`, `log`, [outras].

## 6. Eventos de auditoria
login_success, login_failure, mfa_success, mfa_failure, password_change, sensitive_data_access, role_change, [outros].
Campos: id, timestamp, user_id, evento, ip, detalhes (sem dados sensíveis), prev_hash, hash.

## 7. Arquitetura (resumo)
Navegador -> Frontend Node.js -> API Python (FastAPI) -> PostgreSQL.
Detalhes em `ARCHITECTURE.md`. Decisões em `/docs/adr`.

## 8. Ameaças principais
Resumo; análise completa (STRIDE) em `THREAT_MODEL.md`.
| Ameaça | Mitigação | Requisito |
|---|---|---|
| Roubo de senha | bcrypt com salt + MFA | RF-02 |
| Vazamento do banco | Criptografia de campo | RNF-02 |
| Adulteração de logs | WORM + hash encadeado | RNF-04 |
| Força bruta | Rate limit + bloqueio | RNF-07 |
| SQL injection | Queries parametrizadas | RNF-06 |

## 9. Plano de tarefas
Cada tarefa deve ser pequena, testável e entregar valor.
- [x] T01 Estrutura do repo, docker-compose, CI com lint/testes
- [x] T02 Migrations iniciais (usuario, log com triggers WORM)
- [x] T03 Módulo de criptografia (AES-GCM + envelope) com testes
- [x] T04 Cadastro e login (bcrypt, etapa CPF + senha)
- [ ] T05 MFA TOTP + códigos de recuperação
- [ ] T06 Auditoria com hash encadeado + verificação
- [ ] T07 Funcionalidade principal (RF-03)
- [ ] T08 Frontend: telas de login/MFA/principal
- [ ] T09 Hardening (headers, rate limit, CSRF)
- [ ] T10 Revisão de segurança + relatório final

## 10. Critérios de pronto
- Testes passando, lint e `bandit`/`npm audit` sem críticos
- Requisitos relacionados atendidos e documentados
- ADR criado quando houve decisão relevante

## 11. Questões em aberto
- [ ] ...
