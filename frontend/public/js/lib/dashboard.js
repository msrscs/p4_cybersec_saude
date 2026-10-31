// Funções puras do dashboard de OCIs (sem DOM). ADR-0027.

export const PERIODOS = [
  { dias: 30, rotulo: 'Últimos 30 dias' },
  { dias: 90, rotulo: 'Últimos 90 dias' },
  { dias: 180, rotulo: 'Últimos 180 dias' },
  { dias: 365, rotulo: 'Últimos 12 meses' },
];
export const PERIODO_PADRAO = 90;

// A cor acompanha o que está sendo medido em todos os gráficos: azul é em andamento, verde-água
// é encerrado com sucesso, laranja é falta e cinza é o que saiu da conta.
export const SERIES_DE_OCI = [
  { chave: 'aberta', rotulo: 'Aberta', cor: 'andamento' },
  { chave: 'concluida', rotulo: 'Concluída', cor: 'sucesso' },
  { chave: 'cancelada', rotulo: 'Cancelada', cor: 'neutra' },
];
export const SERIES_DE_ETAPA = [
  { chave: 'realizado', rotulo: 'Realizada', cor: 'sucesso' },
  { chave: 'agendado', rotulo: 'Agendada', cor: 'andamento' },
  { chave: 'faltou', rotulo: 'Faltou', cor: 'falta' },
  { chave: 'encerrada', rotulo: 'Cancelada ou remarcada', cor: 'neutra' },
];
export const SERIES_DA_TENDENCIA = [
  { chave: 'abertas', rotulo: 'Abertas', cor: 'andamento' },
  { chave: 'concluidas', rotulo: 'Concluídas', cor: 'sucesso' },
];

const NUMERO = new Intl.NumberFormat('pt-BR');
const DECIMAL = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 1 });
const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

export const formatarNumero = (valor) => NUMERO.format(valor);

/** Corpo da consulta: filtro vazio não vai; os valores ficam no corpo, nunca na URL. */
export function corpoDoDashboard({ dias, tipo, unidade }) {
  const corpo = { dias: Number(dias) };
  if (tipo) corpo.id_tipo_oci = Number(tipo);
  if (unidade) corpo.id_unidade = Number(unidade);
  return corpo;
}

/** Percentual inteiro; sem base para calcular, mostra um traço em vez de um 0% enganoso. */
export function formatarPercentual(parte, total) {
  return total > 0 ? `${Math.round((parte / total) * 100)}%` : '—';
}

export function formatarDias(dias) {
  if (dias === null || dias === undefined) return '—';
  return `${DECIMAL.format(dias)} ${dias === 1 ? 'dia' : 'dias'}`;
}

const contagem = (n, singular, plural) => `${formatarNumero(n)} ${n === 1 ? singular : plural}`;

/** Cartões de números do topo. `alerta` acompanha um ícone, para não depender só da cor. */
export function indicadoresDe({
  abertas,
  conclusoes,
  etapas,
  abertas_no_periodo,
  proximas_etapas,
}) {
  const comparecimentos = etapas.realizado + etapas.faltou;
  return [
    {
      rotulo: 'Em aberto agora',
      valor: formatarNumero(abertas.em_aberto),
      detalhe: `${contagem(abertas_no_periodo, 'aberta', 'abertas')} no período`,
    },
    {
      rotulo: 'Atrasadas agora',
      valor: formatarNumero(abertas.atrasadas),
      detalhe: `${formatarPercentual(abertas.atrasadas, abertas.em_aberto)} das em aberto`,
      alerta: abertas.atrasadas > 0,
    },
    {
      rotulo: 'Concluídas no prazo',
      valor: formatarPercentual(conclusoes.no_prazo, conclusoes.concluidas),
      detalhe: `${formatarNumero(conclusoes.no_prazo)} de ${contagem(conclusoes.concluidas, 'concluída', 'concluídas')}`,
    },
    {
      rotulo: 'Tempo mediano até concluir',
      valor: formatarDias(conclusoes.mediana_dias),
      detalhe: 'Da abertura à conclusão',
    },
    {
      rotulo: 'Faltas nas etapas',
      valor: formatarPercentual(etapas.faltou, comparecimentos),
      detalhe: `${formatarNumero(etapas.faltou)} de ${contagem(comparecimentos, 'etapa encerrada', 'etapas encerradas')}`,
    },
    {
      rotulo: 'Etapas nos próximos 7 dias',
      valor: formatarNumero(proximas_etapas),
      detalhe: 'Agendadas',
    },
  ];
}

/** Partes do prazo das OCIs em aberto, com os mesmos limites e ícones da lista de OCIs. */
export function segmentosDePrazo({ em_aberto: total, atrasadas, vencem_em_breve: alerta }) {
  return [
    { rotulo: 'No prazo', valor: total - atrasadas - alerta, cor: 'bom', icone: '●' },
    { rotulo: 'Vence em até 7 dias', valor: alerta, cor: 'atencao', icone: '●' },
    { rotulo: 'Atrasada', valor: atrasadas, cor: 'critico', icone: '▲' },
  ];
}

/** Cancelada e remarcada viram uma parte só: nenhuma das duas conta como atendimento. */
export const comEncerradas = (grupo) => ({
  ...grupo,
  encerrada: grupo.cancelado + grupo.remarcado,
});

export function segmentosDeEtapas(etapas) {
  const grupo = comEncerradas(etapas);
  return SERIES_DE_ETAPA.map(({ chave, rotulo, cor }) => ({ rotulo, cor, valor: grupo[chave] }));
}

export const totalDaLinha = (linha, series) =>
  series.reduce((soma, { chave }) => soma + linha[chave], 0);

/** Marcas do eixo em números redondos, de 0 até cobrir o máximo, sem fração em contagens. */
export function marcasDoEixo(maximo, quantidade = 4) {
  if (maximo <= 0) return [0, 1];
  const bruto = maximo / quantidade;
  const potencia = 10 ** Math.floor(Math.log10(bruto));
  const fator = [1, 2, 5, 10].find((f) => f * potencia >= bruto);
  const passo = Math.max(1, fator * potencia);
  const marcas = [];
  for (let valor = 0; valor < maximo + passo; valor += passo) marcas.push(valor);
  return marcas;
}

/** Rótulo do período da série: semana pela segunda-feira, mês abreviado. */
export function rotuloDoPeriodo(inicio, granularidade) {
  const [ano, mes, dia] = inicio.split('-');
  if (granularidade === 'month') return `${MESES[Number(mes) - 1]}/${ano.slice(2)}`;
  return `${dia}/${mes}`;
}

export function tituloDoPeriodo(inicio, granularidade) {
  const rotulo = rotuloDoPeriodo(inicio, granularidade);
  return granularidade === 'month' ? rotulo : `Semana de ${rotulo}`;
}

/** Índice do ponto mais próximo de uma posição horizontal entre `inicio` e `fim`. */
export function indiceMaisProximo(x, quantidade, inicio, fim) {
  if (quantidade <= 1) return 0;
  const indice = Math.round(((x - inicio) / (fim - inicio)) * (quantidade - 1));
  return Math.min(Math.max(indice, 0), quantidade - 1);
}

/** Quais posições do eixo horizontal recebem rótulo, sem se sobrepor; a última sempre aparece. */
export function posicoesComRotulo(quantidade, maximo) {
  if (quantidade <= maximo) return Array.from({ length: quantidade }, (_, i) => i);
  const passo = Math.ceil((quantidade - 1) / (maximo - 1));
  const posicoes = [];
  for (let i = quantidade - 1; i >= 0; i -= passo) posicoes.unshift(i);
  return posicoes;
}

export const temDados = ({ abertas, abertas_no_periodo, conclusoes, etapas }) =>
  abertas.em_aberto + abertas_no_periodo + conclusoes.concluidas > 0 ||
  SERIES_DE_ETAPA.some(({ chave }) => comEncerradas(etapas)[chave] > 0);

export function descricaoDoAlcance(alcance) {
  if (alcance === 'todas') return 'Toda a rede.';
  if (alcance === 'unidade') return 'OCIs com etapa na sua unidade.';
  return 'Seu usuário não está vinculado a uma unidade: fale com o administrador.';
}
