// Funções puras da tela de OCIs (sem DOM).

export const ROTULO_OCI = { aberta: 'Aberta', concluida: 'Concluída', cancelada: 'Cancelada' };
export const ROTULO_ETAPA = {
  agendado: 'Agendado',
  realizado: 'Realizado',
  faltou: 'Faltou',
  cancelado: 'Cancelado',
};
const SELOS = {
  aberta: 'ativo',
  agendado: 'ativo',
  concluida: 'pendente',
  realizado: 'pendente',
};

/** Cor do selo: encerramento sem sucesso e valores desconhecidos usam o tom de alerta. */
export const seloDaSituacao = (situacao) => SELOS[situacao] ?? 'inativo';

/** Corpo da lista: filtro vazio não vai; CPF e demais filtros ficam no corpo, nunca na URL. */
export function corpoDaListaDeOcis({ status, tipo, unidade, cpf, atrasadas }, depois) {
  const corpo = { depois };
  if (status) corpo.status = status;
  if (tipo) corpo.id_tipo_oci = Number(tipo);
  if (unidade) corpo.id_unidade = Number(unidade);
  if (cpf) corpo.cpf = cpf.replace(/\D/g, '');
  if (atrasadas) corpo.atrasadas = true;
  return corpo;
}

/** Valor de um campo datetime-local (hora local) como instante com fuso; inválido vira null. */
export function instanteDe(valor) {
  const data = new Date(valor);
  return valor && !Number.isNaN(data.getTime()) ? data.toISOString() : null;
}

/** Instante da API como valor de campo datetime-local, na hora local. */
export function valorDeDataLocal(iso) {
  const data = new Date(iso);
  const dois = (n) => String(n).padStart(2, '0');
  return (
    `${data.getFullYear()}-${dois(data.getMonth() + 1)}-${dois(data.getDate())}` +
    `T${dois(data.getHours())}:${dois(data.getMinutes())}`
  );
}
