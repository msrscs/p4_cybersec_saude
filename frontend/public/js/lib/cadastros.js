// Funções puras dos cadastros de catálogo (sem DOM).

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
    if (campo.multipla) {
      corpo[campo.nome] = (valores[campo.nome] ?? []).map(Number);
      continue;
    }
    const valor = (valores[campo.nome] ?? '').trim();
    if (valor === '' && campo.opcional) corpo[campo.nome] = campo.vazio;
    else corpo[campo.nome] = campo.numerico ? Number(valor) : valor;
  }
  return corpo;
}

/** Primeira mensagem de erro de preenchimento, ou null se está tudo certo. */
export function erroDoFormulario(campos, valores, editando) {
  for (const campo of campos) {
    if ((editando && campo.soNaCriacao) || campo.multipla) continue;
    const valor = (valores[campo.nome] ?? '').trim();
    if (valor === '' && !campo.opcional) return `Preencha: ${campo.rotulo}.`;
    if (valor !== '' && campo.padrao && !campo.padrao.test(valor)) return campo.mensagem;
  }
  return null;
}

/** Opções de combobox: os ativos, mais o valor atual se estiver inativo, para ele não sumir. */
export function opcoesAtivas(ativas, atualId, atualNome, sufixoInativo) {
  const opcoes = ativas.map(({ id, nome }) => ({ valor: String(id), rotulo: nome }));
  if (atualId !== null && atualId !== undefined && !ativas.some(({ id }) => id === atualId)) {
    opcoes.push({ valor: String(atualId), rotulo: `${atualNome ?? atualId} ${sufixoInativo}` });
  }
  return opcoes;
}

/** Caixas de seleção: os ativos e os já vinculados, marcados, mesmo que estejam inativos. */
export function opcoesMultiplas(ativas, atuais, sufixoInativo) {
  const marcados = new Set(atuais.map(({ id }) => id));
  const idsAtivos = new Set(ativas.map(({ id }) => id));
  return [
    ...ativas.map(({ id, nome }) => ({
      valor: String(id),
      rotulo: nome,
      marcado: marcados.has(id),
    })),
    ...atuais
      .filter(({ id }) => !idsAtivos.has(id))
      .map(({ id, nome }) => ({
        valor: String(id),
        rotulo: `${nome} ${sufixoInativo}`,
        marcado: true,
      })),
  ];
}

export function opcoesDeUnidade(ativas, atualId, atualNome) {
  return [
    { valor: '', rotulo: 'Sem unidade' },
    ...opcoesAtivas(ativas, atualId, atualNome, '(inativa)'),
  ];
}
