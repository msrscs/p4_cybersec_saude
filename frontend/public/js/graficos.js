// Gráficos do dashboard, sem biblioteca externa: a CSP e os Trusted Types só permitem scripts
// próprios (ADR-0027). Nomes vêm da API e entram sempre como texto, nunca como HTML. Todo valor
// mostrado no hover também está na tabela "Ver dados".
import { el } from './lib/dom.js';
import {
  formatarNumero,
  formatarPercentual,
  indiceMaisProximo,
  marcasDoEixo,
  posicoesComRotulo,
  rotuloDoPeriodo,
  tituloDoPeriodo,
  totalDaLinha,
} from './lib/dashboard.js';

const SVG = 'http://www.w3.org/2000/svg';
const ALTURA_DA_LINHA = 240;
const MARGEM = { topo: 14, direita: 36, base: 28, esquerda: 40 };
const MINIMO_ENTRE_ROTULOS_FINAIS = 14;
const LARGURA_POR_ROTULO = 64;
const FATIA_MINIMA_COM_ROTULO = 0.08;
const AFASTAMENTO_DA_DICA = 14;

function svg(tag, atributos = {}, ...filhos) {
  const elemento = document.createElementNS(SVG, tag);
  for (const [nome, valor] of Object.entries(atributos)) elemento.setAttribute(nome, String(valor));
  elemento.append(...filhos);
  return elemento;
}

/** Uma só caixa de dica por tela, posicionada pelo CSSOM (a CSP não aceita style em atributo). */
export function criarDica() {
  const caixa = el('div', { class: 'dica-grafico', role: 'tooltip', hidden: true });
  return {
    caixa,
    mostrar(titulo, linhas, x, y) {
      caixa.replaceChildren(
        el('p', { class: 'dica-grafico__titulo' }, titulo),
        ...linhas.map(({ valor, rotulo, cor }) =>
          el(
            'p',
            { class: 'dica-grafico__linha' },
            cor ? el('span', { class: 'dica-grafico__chave', dataset: { cor } }) : null,
            el('b', {}, valor),
            ` ${rotulo}`,
          ),
        ),
      );
      caixa.hidden = false;
      const { width, height } = caixa.getBoundingClientRect();
      const esquerda = Math.min(x + AFASTAMENTO_DA_DICA, window.innerWidth - width - 8);
      caixa.style.left = `${Math.max(esquerda, 8)}px`;
      caixa.style.top = `${Math.max(y - height - AFASTAMENTO_DA_DICA, 8)}px`;
    },
    esconder() {
      caixa.hidden = true;
    },
  };
}

export function legenda(itens) {
  return el(
    'ul',
    { class: 'legenda', 'aria-hidden': 'true' },
    itens.map(({ rotulo, cor, icone }) =>
      el(
        'li',
        {},
        icone
          ? el('span', { class: 'legenda__icone', dataset: { cor } }, icone)
          : el('span', { class: 'legenda__chave', dataset: { cor } }),
        rotulo,
      ),
    ),
  );
}

/** Tabela recolhida: alternativa sem cor e sem mouse aos gráficos. */
export function tabelaDeDados(titulo, colunas, linhas) {
  return el(
    'details',
    { class: 'dados-grafico' },
    el('summary', {}, 'Ver dados'),
    el(
      'div',
      { class: 'tabela' },
      el(
        'table',
        {},
        el('caption', { class: 'sr-only' }, titulo),
        el(
          'thead',
          {},
          el(
            'tr',
            {},
            colunas.map((coluna) => el('th', { scope: 'col' }, coluna)),
          ),
        ),
        el(
          'tbody',
          {},
          linhas.map((linha) =>
            el(
              'tr',
              {},
              linha.map((celula, i) =>
                el(i === 0 ? 'th' : 'td', i === 0 ? { scope: 'row' } : {}, String(celula)),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

function ligarDica(alvo, dica, conteudo) {
  const abrirEm = (x, y) => {
    const { titulo, linhas } = conteudo();
    dica.mostrar(titulo, linhas, x, y);
  };
  alvo.addEventListener('pointermove', (e) => abrirEm(e.clientX, e.clientY));
  alvo.addEventListener('pointerleave', () => dica.esconder());
  alvo.addEventListener('blur', () => dica.esconder());
  alvo.addEventListener('focus', () => {
    const { left, top } = alvo.getBoundingClientRect();
    abrirEm(left, top);
  });
}

/** Parte de um todo: blocos proporcionais, com o valor dentro só quando cabe. */
export function barraSegmentada(titulo, partes, dica) {
  const total = partes.reduce((soma, { valor }) => soma + valor, 0);
  const visiveis = partes.filter(({ valor }) => valor > 0);
  const descricao = partes
    .map(({ rotulo, valor }) => `${rotulo}: ${formatarNumero(valor)}`)
    .join('; ');
  const linhasDaDica = partes.map(({ rotulo, valor, cor }) => ({
    valor: `${formatarNumero(valor)} (${formatarPercentual(valor, total)})`,
    rotulo,
    cor,
  }));
  const barra = el(
    'div',
    { class: 'segmentos', role: 'img', tabindex: 0, 'aria-label': `${titulo}. ${descricao}` },
    visiveis.map(({ valor, cor }) => {
      const bloco = el(
        'span',
        { class: 'segmentos__bloco', dataset: { cor } },
        valor / total >= FATIA_MINIMA_COM_ROTULO ? formatarNumero(valor) : null,
      );
      bloco.style.flexGrow = String(valor);
      return bloco;
    }),
  );
  ligarDica(barra, dica, () => ({ titulo, linhas: linhasDaDica }));
  return barra;
}

/** Comparação entre categorias: barras horizontais empilhadas, com o total na ponta. */
export function barrasEmpilhadas(linhas, series, dica) {
  const maximo = Math.max(1, ...linhas.map((linha) => totalDaLinha(linha, series)));
  return el(
    'div',
    { class: 'barras' },
    linhas.map((linha) => {
      const total = totalDaLinha(linha, series);
      const partes = series.filter(({ chave }) => linha[chave] > 0);
      const preenchido = el(
        'span',
        { class: 'barra__preenchido' },
        partes.map(({ chave, cor }) => {
          const parte = el('span', { class: 'barra__parte', dataset: { cor } });
          parte.style.flexGrow = String(linha[chave]);
          return parte;
        }),
      );
      preenchido.style.width = `${(total / maximo) * 100}%`;
      const descricao = series
        .map(({ chave, rotulo }) => `${rotulo}: ${formatarNumero(linha[chave])}`)
        .join('; ');
      const barra = el(
        'div',
        {
          class: 'barra',
          tabindex: 0,
          role: 'img',
          'aria-label': `${linha.nome}. Total ${formatarNumero(total)}. ${descricao}`,
        },
        el('span', { class: 'barra__nome', title: linha.nome }, linha.nome),
        el('span', { class: 'barra__trilho' }, preenchido),
        el('span', { class: 'barra__valor' }, formatarNumero(total)),
      );
      ligarDica(barra, dica, () => ({
        titulo: linha.nome,
        linhas: series.map(({ chave, rotulo, cor }) => ({
          valor: formatarNumero(linha[chave]),
          rotulo,
          cor,
        })),
      }));
      return barra;
    }),
  );
}

function desenharLinhas(area, pontos, series, granularidade, largura, dica) {
  const fim = largura - MARGEM.direita;
  const piso = ALTURA_DA_LINHA - MARGEM.base;
  const maximo = Math.max(0, ...pontos.flatMap((ponto) => series.map(({ chave }) => ponto[chave])));
  const marcas = marcasDoEixo(maximo);
  const teto = marcas.at(-1);
  const x = (i) =>
    pontos.length === 1
      ? (MARGEM.esquerda + fim) / 2
      : MARGEM.esquerda + (i / (pontos.length - 1)) * (fim - MARGEM.esquerda);
  const y = (valor) => piso - (valor / teto) * (piso - MARGEM.topo);

  const grade = marcas.flatMap((marca) => [
    svg('line', {
      class: marca === 0 ? 'eixo' : 'grade',
      x1: MARGEM.esquerda,
      x2: fim,
      y1: y(marca),
      y2: y(marca),
    }),
    svg(
      'text',
      { class: 'marca', x: MARGEM.esquerda - 8, y: y(marca) + 4, 'text-anchor': 'end' },
      formatarNumero(marca),
    ),
  ]);
  const quantos = Math.max(2, Math.floor((fim - MARGEM.esquerda) / LARGURA_POR_ROTULO));
  const eixoX = posicoesComRotulo(pontos.length, quantos).map((i) =>
    svg(
      'text',
      { class: 'marca', x: x(i), y: piso + 18, 'text-anchor': 'middle' },
      rotuloDoPeriodo(pontos[i].inicio, granularidade),
    ),
  );

  const ultimo = pontos.at(-1);
  const finais = [];
  const tracos = series.flatMap(({ chave, cor }) => {
    const caminho = pontos
      .map((ponto, i) => `${i === 0 ? 'M' : 'L'}${x(i)} ${y(ponto[chave])}`)
      .join(' ');
    const alturaFinal = y(ultimo[chave]);
    const separado = finais.every(
      (outra) => Math.abs(outra - alturaFinal) >= MINIMO_ENTRE_ROTULOS_FINAIS,
    );
    if (separado) finais.push(alturaFinal);
    return [
      svg('path', { class: 'traco', d: caminho, 'data-cor': cor }),
      svg('circle', {
        class: 'ponto',
        cx: x(pontos.length - 1),
        cy: alturaFinal,
        r: 4,
        'data-cor': cor,
      }),
      separado
        ? svg(
            'text',
            { class: 'valor-final', x: x(pontos.length - 1) + 9, y: alturaFinal + 4 },
            formatarNumero(ultimo[chave]),
          )
        : null,
    ].filter(Boolean);
  });

  const cursor = svg('line', { class: 'cursor', y1: MARGEM.topo, y2: piso, visibility: 'hidden' });
  const realces = series.map(({ cor }) =>
    svg('circle', { class: 'ponto', r: 4, 'data-cor': cor, visibility: 'hidden' }),
  );
  const figura = svg('svg', {
    viewBox: `0 0 ${largura} ${ALTURA_DA_LINHA}`,
    width: largura,
    height: ALTURA_DA_LINHA,
    'aria-hidden': 'true',
  });
  figura.append(...grade, ...eixoX, cursor, ...tracos, ...realces);
  area.replaceChildren(figura);

  let atual = pontos.length - 1;
  const marcar = (indice, xTela, yTela) => {
    atual = indice;
    const ponto = pontos[indice];
    cursor.setAttribute('x1', x(indice));
    cursor.setAttribute('x2', x(indice));
    cursor.setAttribute('visibility', 'visible');
    series.forEach(({ chave }, s) => {
      realces[s].setAttribute('cx', x(indice));
      realces[s].setAttribute('cy', y(ponto[chave]));
      realces[s].setAttribute('visibility', 'visible');
    });
    dica.mostrar(
      tituloDoPeriodo(ponto.inicio, granularidade),
      series.map(({ chave, rotulo, cor }) => ({
        valor: formatarNumero(ponto[chave]),
        rotulo,
        cor,
      })),
      xTela,
      yTela,
    );
  };
  const limpar = () => {
    cursor.setAttribute('visibility', 'hidden');
    for (const realce of realces) realce.setAttribute('visibility', 'hidden');
    dica.esconder();
  };
  const noTeclado = () => {
    const caixa = figura.getBoundingClientRect();
    marcar(atual, caixa.left + x(atual), caixa.top + MARGEM.topo);
  };
  area.onpointermove = (evento) => {
    const caixa = figura.getBoundingClientRect();
    const indice = indiceMaisProximo(
      evento.clientX - caixa.left,
      pontos.length,
      MARGEM.esquerda,
      fim,
    );
    marcar(indice, evento.clientX, evento.clientY);
  };
  area.onpointerleave = limpar;
  area.onblur = limpar;
  area.onfocus = noTeclado;
  area.onkeydown = (evento) => {
    const passo = { ArrowLeft: -1, ArrowRight: 1 }[evento.key];
    if (!passo) return;
    evento.preventDefault();
    atual = Math.min(Math.max(atual + passo, 0), pontos.length - 1);
    noTeclado();
  };
}

/** Evolução no tempo: linhas com uma escala só, redesenhadas quando a largura muda. */
export function linhasNoTempo(titulo, pontos, series, granularidade, dica) {
  const totais = series
    .map(
      ({ chave, rotulo }) =>
        `${rotulo}: ${formatarNumero(pontos.reduce((s, p) => s + p[chave], 0))}`,
    )
    .join('; ');
  const area = el('div', {
    class: 'linhas',
    role: 'img',
    tabindex: 0,
    'aria-label': `${titulo}. ${totais}. Use as setas para percorrer os períodos.`,
  });
  let larguraAtual = 0;
  const observador = new ResizeObserver(([{ contentRect }]) => {
    const largura = Math.round(contentRect.width);
    if (largura === 0 || largura === larguraAtual) return;
    larguraAtual = largura;
    desenharLinhas(area, pontos, series, granularidade, largura, dica);
  });
  observador.observe(area);
  return { area, encerrar: () => observador.disconnect() };
}
