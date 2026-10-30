// Funções puras da tela de auditoria (sem DOM).

const ROTULOS = {
  access_denied: 'Acesso negado',
  access_reset: 'Reset de acesso',
  account_locked: 'Conta bloqueada',
  csrf_rejected: 'CSRF recusado',
  log_chain_broken: 'Cadeia do log quebrada',
  log_chain_verified: 'Cadeia do log verificada',
  log_checkpoint_created: 'Checkpoint do log criado',
  log_read: 'Consulta ao log',
  login_failure: 'Falha de login',
  login_success: 'Login: senha correta',
  logout: 'Saída do sistema',
  mfa_enrolled: 'MFA cadastrado',
  mfa_failure: 'Falha de MFA',
  mfa_recovery_used: 'Código de recuperação usado',
  mfa_success: 'MFA confirmado',
  password_change: 'Troca de senha',
  patient_created: 'Paciente cadastrado',
  patient_deactivated: 'Paciente inativado',
  patient_reactivated: 'Paciente reativado',
  patient_search: 'Busca de paciente',
  patient_updated: 'Paciente alterado',
  rate_limited: 'Limite de requisições atingido',
  recovery_codes_generated: 'Códigos de recuperação gerados',
  role_change: 'Mudança de permissão',
  sensitive_data_access: 'Acesso a dado sensível',
  session_created: 'Sessão criada',
  user_created: 'Usuário cadastrado',
  user_deactivated: 'Usuário inativado',
  user_reactivated: 'Usuário reativado',
  user_updated: 'Usuário alterado',
};

// Evento novo no backend, ainda sem rótulo: mostra o nome técnico em vez de sumir da tela.
export const rotuloDaAcao = (acao) => ROTULOS[acao] ?? acao;

/** Monta o corpo da consulta: datas do dia local viram instantes com fuso; vazio não vai. */
export function corpoDaConsulta({ de, ate, acao, cpf }, antes = null) {
  const corpo = {};
  if (de) corpo.de = new Date(`${de}T00:00:00`).toISOString();
  if (ate) corpo.ate = new Date(`${ate}T23:59:59.999`).toISOString();
  if (acao) corpo.acao = acao;
  if (cpf) corpo.cpf = cpf;
  if (antes !== null) corpo.antes = antes;
  return corpo;
}

export function periodoValido({ de, ate }) {
  return !de || !ate || de <= ate;
}

/** Texto expandido de um registro: metadados técnicos e o resumo gravado no log. */
export function detalhesDoRegistro(item) {
  return JSON.stringify(
    {
      seq: item.seq,
      hash: item.hash,
      usuario_hash: item.usuario,
      paciente_hash: item.paciente,
      request_id: item.request_id,
      ...item.resumo,
    },
    null,
    2,
  );
}
