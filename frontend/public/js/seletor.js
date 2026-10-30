// Seleção múltipla por busca, para listas grandes como a de CID (ADR-0024): procura ao clicar,
// inclui o resultado e mostra os escolhidos. Montagem só com createElement (CSP com Trusted Types).
import { definirStatus, el } from './lib/dom.js';

export function criarSeletor(chamarApi, campo, idBase) {
  const selecionados = new Map();
  const termo = el('input', { id: `${idBase}-busca`, type: 'search', maxlength: 100 });
  const status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  const resultados = el('ul', { class: 'seletor__lista' });
  const escolhidos = el('ul', { class: 'seletor__lista' });

  function desenharEscolhidos() {
    if (selecionados.size === 0) {
      escolhidos.replaceChildren(el('li', { class: 'dica' }, campo.vazioSelecao));
      return;
    }
    escolhidos.replaceChildren(
      ...[...selecionados.values()]
        .sort((a, b) => campo.rotuloItem(a).localeCompare(campo.rotuloItem(b), 'pt-BR'))
        .map((item) =>
          el(
            'li',
            { class: 'seletor__item' },
            el('span', {}, campo.rotuloItem(item)),
            el(
              'button',
              {
                type: 'button',
                class: 'link link--botao',
                'aria-label': `Remover ${campo.codigoItem(item)}`,
                onclick: () => {
                  selecionados.delete(item.id);
                  desenharEscolhidos();
                },
              },
              'Remover',
            ),
          ),
        ),
    );
  }

  function desenharResultados(itens) {
    resultados.replaceChildren(
      ...itens.map((item) =>
        el(
          'li',
          { class: 'seletor__item' },
          el('span', {}, campo.rotuloItem(item)),
          el(
            'button',
            {
              type: 'button',
              class: 'link link--botao',
              'aria-label': `Incluir ${campo.codigoItem(item)}`,
              onclick: () => {
                selecionados.set(item.id, item);
                desenharEscolhidos();
              },
            },
            'Incluir',
          ),
        ),
      ),
    );
  }

  async function procurar() {
    const busca = termo.value.trim();
    if (busca.length < 2) {
      definirStatus(status, 'Digite ao menos 2 caracteres.', 'error');
      return;
    }
    try {
      const { opcoes } = await chamarApi('POST', campo.buscaEm, { busca });
      desenharResultados(opcoes);
      definirStatus(status, opcoes.length === 0 ? 'Nada encontrado.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  // Enter procura, em vez de enviar o formulário inteiro.
  termo.addEventListener('keydown', (evento) => {
    if (evento.key !== 'Enter') return;
    evento.preventDefault();
    procurar();
  });

  const elemento = el(
    'fieldset',
    { class: 'grupos' },
    el('legend', {}, campo.rotulo),
    el('label', { for: termo.id }, campo.rotuloBusca),
    el(
      'div',
      { class: 'busca__linha' },
      termo,
      el(
        'button',
        {
          type: 'button',
          class: 'button button--secundario button--pequeno',
          onclick: procurar,
        },
        'Procurar',
      ),
    ),
    status,
    resultados,
    el('p', { class: 'seletor__titulo' }, 'Selecionados'),
    escolhidos,
  );

  return {
    elemento,
    definir(itens) {
      selecionados.clear();
      for (const item of itens) selecionados.set(item.id, item);
      termo.value = '';
      resultados.replaceChildren();
      definirStatus(status, '');
      desenharEscolhidos();
    },
    valores: () => [...selecionados.keys()],
  };
}
