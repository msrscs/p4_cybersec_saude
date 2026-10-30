// Funções puras dos cadastros de catálogo (sem DOM).

export const TIPOS_UNIDADE = ['Posto de Saúde', 'Clínica', 'Hospital', 'Laboratório'];
export const PADRAO_CID = /^[A-Za-z][0-9]{2}(\.[0-9A-Za-z]{1,2})?$/;

export function formatarTelefone(digitos) {
  if (!digitos) return '—';
  const meio = digitos.length === 11 ? 7 : 6;
  return `(${digitos.slice(0, 2)}) ${digitos.slice(2, meio)}-${digitos.slice(meio)}`;
}

/** Corpo da gravação: campo imutável só vai na criação; opcional vazio vira `vazio`. */
export function corpoDoFormulario(campos, valores, editando) {
  const corpo = {};
  for (const campo of campos) {
    if (editando && campo.soNaCriacao) continue;
    const valor = (valores[campo.nome] ?? '').trim();
    corpo[campo.nome] = valor === '' && campo.opcional ? campo.vazio : valor;
  }
  return corpo;
}

/** Primeira mensagem de erro de preenchimento, ou null se está tudo certo. */
export function erroDoFormulario(campos, valores, editando) {
  for (const campo of campos) {
    if (editando && campo.soNaCriacao) continue;
    const valor = (valores[campo.nome] ?? '').trim();
    if (valor === '' && !campo.opcional) return `Preencha: ${campo.rotulo}.`;
    if (valor !== '' && campo.padrao && !campo.padrao.test(valor)) return campo.mensagem;
  }
  return null;
}

/** Opções da combobox de unidade; a unidade atual inativa continua visível para não sumir. */
export function opcoesDeUnidade(ativas, atualId, atualNome) {
  const opcoes = ativas.map(({ id, nome }) => ({ valor: String(id), rotulo: nome }));
  if (atualId !== null && atualId !== undefined && !ativas.some(({ id }) => id === atualId)) {
    opcoes.push({ valor: String(atualId), rotulo: `${atualNome ?? atualId} (inativa)` });
  }
  return [{ valor: '', rotulo: 'Sem unidade' }, ...opcoes];
}
