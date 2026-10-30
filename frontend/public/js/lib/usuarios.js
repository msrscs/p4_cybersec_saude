// Funções puras da tela de usuários (sem DOM).

/** Corpo da consulta: filtro vazio não vai; nome e CPF ficam no corpo, nunca na URL. */
export function corpoDaLista({ busca, grupo, unidade }, depois) {
  const corpo = { depois };
  if (busca) corpo.busca = busca;
  if (grupo) corpo.grupo = grupo;
  if (unidade) corpo.id_unidade = Number(unidade);
  return corpo;
}

/** Mensagem para uma busca que não pode dar certo, ou null. Só dígitos é tratado como CPF. */
export function erroDaBusca(busca) {
  if (busca === '') return null;
  if (/^[\d.\-\s]+$/.test(busca)) {
    return busca.replace(/\D/g, '').length === 11
      ? null
      : 'Para buscar por CPF, informe os 11 dígitos.';
  }
  return busca.length < 2 ? 'Digite ao menos 2 letras do nome.' : null;
}
