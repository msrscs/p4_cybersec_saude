// Dashboard de OCIs (ADR-0027): só números agregados. A interface esconde o filtro de unidade de
// quem não tem alcance global, mas quem aplica o alcance, a cada requisição, é o backend.
import {
  barraSegmentada,
  barrasEmpilhadas,
  criarDica,
  legenda,
  linhasNoTempo,
  tabelaDeDados,
} from './graficos.js';
import { definirStatus, el } from './lib/dom.js';
import {
  comEncerradas,
  corpoDoDashboard,
  descricaoDoAlcance,
  formatarNumero,
  indicadoresDe,
  PERIODO_PADRAO,
  PERIODOS,
  segmentosDeEtapas,
  segmentosDePrazo,
  SERIES_DA_TENDENCIA,
  SERIES_DE_ETAPA,
  SERIES_DE_OCI,
  temDados,
  tituloDoPeriodo,
  totalDaLinha,
} from './lib/dashboard.js';

const SERIE_DO_CID = [{ chave: 'total', rotulo: 'OCIs', cor: 'andamento' }];

function cartao(titulo, subtitulo, ...conteudo) {
  return el(
    'section',
    { class: 'cartao-grafico' },
    el('h2', {}, titulo),
    subtitulo ? el('p', { class: 'dica' }, subtitulo) : null,
    ...conteudo,
  );
}

function indicador({ rotulo, valor, detalhe, alerta }) {
  return el(
    'div',
    { class: 'indicador' },
    el('p', { class: 'indicador__rotulo' }, rotulo),
    el(
      'p',
      { class: 'indicador__valor' },
      alerta ? el('span', { class: 'indicador__alerta', 'aria-hidden': 'true' }, '▲') : null,
      valor,
    ),
    el('p', { class: 'indicador__detalhe' }, detalhe),
  );
}

function tabelaEmpilhada(titulo, coluna, linhas, series) {
  return tabelaDeDados(
    titulo,
    [coluna, ...series.map(({ rotulo }) => rotulo), 'Total'],
    linhas.map((linha) => [
      linha.nome,
      ...series.map(({ chave }) => formatarNumero(linha[chave])),
      formatarNumero(totalDaLinha(linha, series)),
    ]),
  );
}

function cartaoEmpilhado(titulo, subtitulo, coluna, linhas, series, dica) {
  if (linhas.length === 0) return cartao(titulo, subtitulo, semDados());
  return cartao(
    titulo,
    subtitulo,
    legenda(series),
    barrasEmpilhadas(linhas, series, dica),
    tabelaEmpilhada(titulo, coluna, linhas, series),
  );
}

const semDados = () => el('p', { class: 'painel__texto' }, 'Sem dados no período.');

function cartaoDeSegmentos(titulo, subtitulo, partes, dica) {
  if (partes.every(({ valor }) => valor === 0)) return cartao(titulo, subtitulo, semDados());
  return cartao(
    titulo,
    subtitulo,
    barraSegmentada(titulo, partes, dica),
    legenda(partes),
    tabelaDeDados(
      titulo,
      ['Situação', 'Quantidade'],
      partes.map(({ rotulo, valor }) => [rotulo, formatarNumero(valor)]),
    ),
  );
}

function cartaoDaTendencia(dados, dica, aoDesmontar) {
  const titulo = 'OCIs abertas e concluídas';
  const subtitulo = dados.granularidade === 'month' ? 'Por mês' : 'Por semana';
  const { area, encerrar } = linhasNoTempo(
    titulo,
    dados.serie,
    SERIES_DA_TENDENCIA,
    dados.granularidade,
    dica,
  );
  aoDesmontar(encerrar);
  const cartaoPronto = cartao(
    titulo,
    subtitulo,
    legenda(SERIES_DA_TENDENCIA),
    area,
    tabelaDeDados(
      titulo,
      ['Período', ...SERIES_DA_TENDENCIA.map(({ rotulo }) => rotulo)],
      dados.serie.map((ponto) => [
        tituloDoPeriodo(ponto.inicio, dados.granularidade),
        formatarNumero(ponto.abertas),
        formatarNumero(ponto.concluidas),
      ]),
    ),
  );
  cartaoPronto.classList.add('cartao-grafico--largo');
  return cartaoPronto;
}

function montarGraficos(dados, filtroDeUnidade, dica, aoDesmontar) {
  const cids = dados.por_cid.map((cid) => ({
    nome: `${cid.codigo} — ${cid.descricao}`,
    total: cid.total,
  }));
  const comoEtapas = (grupos) => grupos.map(comEncerradas);
  return [
    cartaoDaTendencia(dados, dica, aoDesmontar),
    cartaoDeSegmentos(
      'Prazo das OCIs em aberto',
      'Situação agora, sem depender do período',
      segmentosDePrazo(dados.abertas),
      dica,
    ),
    cartaoDeSegmentos(
      'Etapas por situação',
      'Etapas marcadas para o período',
      segmentosDeEtapas(dados.etapas),
      dica,
    ),
    cartaoEmpilhado(
      'OCIs por tipo',
      'Abertas no período, pela situação atual',
      'Tipo de OCI',
      dados.por_tipo,
      SERIES_DE_OCI,
      dica,
    ),
    cartaoEmpilhado(
      'CIDs mais frequentes',
      'Os 8 mais comuns nas OCIs abertas no período',
      'CID',
      cids,
      SERIE_DO_CID,
      dica,
    ),
    // Com uma unidade só, este gráfico teria uma única barra: os números já estão no resto da tela.
    dados.alcance === 'todas' && !filtroDeUnidade
      ? cartaoEmpilhado(
          'Etapas por unidade',
          'Etapas marcadas para o período',
          'Unidade',
          comoEtapas(dados.por_unidade),
          SERIES_DE_ETAPA,
          dica,
        )
      : null,
    cartaoEmpilhado(
      'Etapas por serviço',
      'Etapas marcadas para o período',
      'Serviço',
      comoEtapas(dados.por_servico),
      SERIES_DE_ETAPA,
      dica,
    ),
  ].filter(Boolean);
}

function preencher(campo, rotuloDeTodos, opcoes) {
  const escolhido = campo.value;
  campo.replaceChildren(
    el('option', { value: '' }, rotuloDeTodos),
    ...opcoes.map(({ id, nome }) => el('option', { value: id }, nome)),
  );
  // Opção que saiu da lista (inativada) volta para "todos".
  campo.value = opcoes.some(({ id }) => String(id) === escolhido) ? escolhido : '';
}

export function criarDashboard(chamarApi, permissoes) {
  const secao = document.getElementById('secao-dashboard');
  const todasAsUnidades = permissoes.has('oci:todas_unidades');
  const dica = criarDica();
  const periodo = el(
    'select',
    { id: 'dashboard-periodo' },
    PERIODOS.map(({ dias, rotulo }) =>
      el('option', { value: dias, selected: dias === PERIODO_PADRAO }, rotulo),
    ),
  );
  const tipo = el(
    'select',
    { id: 'dashboard-tipo' },
    el('option', { value: '' }, 'Todos os tipos'),
  );
  const unidade = el(
    'select',
    { id: 'dashboard-unidade' },
    el('option', { value: '' }, 'Todas as unidades'),
  );
  const alcance = el('p', { class: 'painel__texto', id: 'dashboard-alcance' });
  const status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  const indicadores = el('div', { class: 'indicadores' });
  const graficos = el('div', { class: 'graficos' });
  const conteudo = el(
    'div',
    { class: 'dashboard', id: 'dashboard-conteudo' },
    indicadores,
    graficos,
  );
  const campo = (id, rotulo, controle) =>
    el('div', { class: 'field' }, el('label', { for: id }, rotulo), controle);
  const filtros = el(
    'form',
    { class: 'filtros', id: 'filtros-dashboard', novalidate: true, autocomplete: 'off' },
    campo('dashboard-periodo', 'Período', periodo),
    campo('dashboard-tipo', 'Tipo de OCI', tipo),
    todasAsUnidades ? campo('dashboard-unidade', 'Unidade', unidade) : null,
  );
  secao.append(
    el('h1', { id: 'titulo-dashboard' }, 'Dashboard'),
    alcance,
    filtros,
    status,
    conteudo,
    dica.caixa,
  );

  let requisicao = 0;
  let desmontar = [];

  function desenhar(dados) {
    for (const encerrar of desmontar) encerrar();
    desmontar = [];
    dica.esconder();
    alcance.textContent = descricaoDoAlcance(dados.alcance);
    const vazio = !temDados(dados);
    indicadores.replaceChildren(...(vazio ? [] : indicadoresDe(dados).map(indicador)));
    graficos.replaceChildren(
      ...(vazio ? [] : montarGraficos(dados, unidade.value, dica, (f) => desmontar.push(f))),
    );
    definirStatus(status, vazio ? 'Nenhuma OCI encontrada com esses filtros.' : '');
  }

  async function carregar() {
    requisicao += 1;
    const atual = requisicao;
    conteudo.setAttribute('aria-busy', 'true');
    try {
      const corpo = corpoDoDashboard({
        dias: periodo.value,
        tipo: tipo.value,
        unidade: unidade.value,
      });
      const dados = await chamarApi('POST', '/ocis/dashboard', corpo);
      if (atual === requisicao) desenhar(dados); // resposta antiga não sobrescreve a mais nova
    } catch (erro) {
      if (atual === requisicao) definirStatus(status, erro.message, 'error');
    } finally {
      if (atual === requisicao) conteudo.removeAttribute('aria-busy');
    }
  }

  // A cada abertura: um tipo ou unidade criado depois precisa aparecer, sem perder a escolha atual.
  async function carregarOpcoes() {
    const { tipos, unidades } = await chamarApi('GET', '/ocis/opcoes');
    preencher(tipo, 'Todos os tipos', tipos);
    preencher(unidade, 'Todas as unidades', unidades);
  }

  filtros.addEventListener('change', carregar);
  filtros.addEventListener('submit', (evento) => evento.preventDefault());

  return {
    async abrir() {
      try {
        await carregarOpcoes();
      } catch (erro) {
        // Sem as opções, o dashboard ainda funciona com os filtros padrão.
        definirStatus(status, erro.message, 'error');
      }
      await carregar();
    },
  };
}
