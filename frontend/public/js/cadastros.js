// Telas de catálogo (ADR-0019, ADR-0021): um só componente para todos os cadastros.
// A interface esconde o que o perfil não pode fazer; quem autoriza é o backend.
import {
  corpoDoFormulario,
  erroDoFormulario,
  formatarTelefone,
  opcoesAtivas,
  opcoesMultiplas,
  PADRAO_CID,
} from './lib/cadastros.js';
import { definirStatus, el } from './lib/dom.js';

const $ = (id) => document.getElementById(id);
const ROTULO_STATUS = { ativo: 'Ativo', inativo: 'Inativo' };

export const CATALOGOS = {
  tiposUnidade: {
    secao: 'secao-tipos-unidade',
    rota: '/tipos-unidade',
    titulo: 'Tipos de unidade',
    singular: 'tipo',
    novo: 'Novo tipo',
    identificacao: (item) => item.nome,
    campos: [
      { nome: 'nome', rotulo: 'Nome do tipo', max: 150 },
      {
        nome: 'descricao',
        rotulo: 'Descrição do tipo (opcional)',
        max: 500,
        opcional: true,
        vazio: '',
      },
    ],
    colunas: [
      { titulo: 'Nome', valor: (item) => item.nome },
      { titulo: 'Descrição', valor: (item) => item.descricao || '—' },
    ],
  },
  unidades: {
    secao: 'secao-unidades',
    rota: '/unidades',
    titulo: 'Unidades de saúde',
    singular: 'unidade',
    novo: 'Nova unidade',
    identificacao: (item) => item.nome,
    campos: [
      { nome: 'nome', rotulo: 'Nome da unidade', max: 150 },
      {
        nome: 'id_tipo_unidade',
        rotulo: 'Tipo da unidade',
        numerico: true,
        opcoesDe: '/tipos-unidade/opcoes',
        nomeAtual: (item) => item.tipo_unidade,
        sufixoInativo: '(inativo)',
      },
      { nome: 'endereco', rotulo: 'Endereço da unidade', max: 300 },
      {
        nome: 'telefone',
        rotulo: 'Telefone com DDD (opcional)',
        max: 20,
        opcional: true,
        vazio: null,
      },
      {
        nome: 'servicos',
        rotulo: 'Serviços oferecidos',
        multipla: true,
        opcoesDe: '/servicos/opcoes',
        sufixoInativo: '(inativo)',
      },
    ],
    colunas: [
      { titulo: 'Nome', valor: (item) => item.nome },
      { titulo: 'Tipo', valor: (item) => item.tipo_unidade },
      { titulo: 'Endereço', valor: (item) => item.endereco },
      { titulo: 'Telefone', valor: (item) => formatarTelefone(item.telefone), semQuebra: true },
      {
        titulo: 'Serviços',
        valor: (item) => item.servicos.map(({ nome }) => nome).join(', ') || '—',
      },
    ],
  },
  servicos: {
    secao: 'secao-servicos',
    rota: '/servicos',
    titulo: 'Serviços de saúde',
    singular: 'serviço',
    novo: 'Novo serviço',
    identificacao: (item) => item.nome,
    campos: [
      { nome: 'nome', rotulo: 'Nome do serviço', max: 150 },
      {
        nome: 'descricao',
        rotulo: 'Descrição do serviço (opcional)',
        max: 500,
        opcional: true,
        vazio: '',
      },
    ],
    colunas: [
      { titulo: 'Nome', valor: (item) => item.nome },
      { titulo: 'Descrição', valor: (item) => item.descricao || '—' },
    ],
  },
  cids: {
    secao: 'secao-cids',
    rota: '/cids',
    titulo: 'CID',
    singular: 'CID',
    novo: 'Novo CID',
    identificacao: (item) => item.cid,
    campos: [
      {
        nome: 'cid',
        rotulo: 'Código CID',
        max: 10,
        soNaCriacao: true,
        padrao: PADRAO_CID,
        mensagem: 'Código CID inválido. Exemplo: C50.9.',
      },
      { nome: 'descricao', rotulo: 'Descrição do CID', max: 500 },
    ],
    colunas: [
      { titulo: 'Código', valor: (item) => item.cid },
      { titulo: 'Descrição', valor: (item) => item.descricao },
    ],
  },
};

function controleDoCampo(campo, id) {
  if (campo.multipla) return el('div', { id, class: 'grupos__lista' });
  if (campo.opcoesDe) return el('select', { id });
  return el('input', { id, type: 'text', maxlength: campo.max, autocomplete: 'off' });
}

export function criarCadastro(chamarApi, catalogo, podeGerenciar) {
  const prefixo = catalogo.secao;
  const idCampo = (campo) => `${prefixo}-campo-${campo.nome}`;
  const status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  const statusForm = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  const corpo = el('tbody', {});
  const anterior = el(
    'button',
    { type: 'button', class: 'button button--secundario button--pequeno', disabled: true },
    'Anterior',
  );
  const proxima = el(
    'button',
    { type: 'button', class: 'button button--secundario button--pequeno', disabled: true },
    'Próxima',
  );
  const tituloForm = el('h2', {});
  const form = el('form', {
    class: 'form ficha',
    novalidate: true,
    autocomplete: 'off',
    hidden: true,
  });
  const busca = el('input', {
    id: `${prefixo}-busca`,
    type: 'search',
    maxlength: 100,
    autocomplete: 'off',
  });
  let pagina = 1;
  let termo = '';
  let editando = null;

  function valoresDoForm() {
    const valores = {};
    for (const campo of catalogo.campos) {
      const controle = $(idCampo(campo));
      valores[campo.nome] = campo.multipla
        ? [...controle.querySelectorAll('input:checked')].map((caixa) => caixa.value)
        : controle.value;
    }
    return valores;
  }

  function preencherCaixas(campo, lista) {
    const destino = $(idCampo(campo));
    if (lista.length === 0) {
      destino.replaceChildren(el('p', { class: 'dica' }, 'Nenhum serviço ativo cadastrado.'));
      return;
    }
    destino.replaceChildren(
      ...lista.map(({ valor, rotulo, marcado }) => {
        const id = `${idCampo(campo)}-${valor}`;
        return el(
          'label',
          { class: 'grupo', for: id },
          el('input', { id, type: 'checkbox', value: valor, checked: marcado }),
          rotulo,
        );
      }),
    );
  }

  // Combobox vinda da API: sem as opções o formulário não abre, para não gravar valor errado.
  async function carregarOpcoes(item) {
    for (const campo of catalogo.campos.filter((c) => c.opcoesDe)) {
      const { opcoes } = await chamarApi('GET', campo.opcoesDe);
      if (campo.multipla) {
        preencherCaixas(
          campo,
          opcoesMultiplas(opcoes, item?.[campo.nome] ?? [], campo.sufixoInativo),
        );
        continue;
      }
      const lista = opcoesAtivas(
        opcoes,
        item?.[campo.nome],
        item ? campo.nomeAtual(item) : null,
        campo.sufixoInativo,
      );
      $(idCampo(campo)).replaceChildren(
        ...lista.map(({ valor, rotulo }) => el('option', { value: valor }, rotulo)),
      );
    }
  }

  async function abrirForm(item = null) {
    try {
      await carregarOpcoes(item);
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
      return;
    }
    editando = item;
    form.reset();
    tituloForm.textContent = item ? `Editar ${catalogo.singular}` : catalogo.novo;
    for (const campo of catalogo.campos) {
      if (campo.multipla) continue;
      const controle = $(idCampo(campo));
      if (item) controle.value = item[campo.nome] ?? '';
      // Campo imutável aparece na edição, mas não pode ser alterado.
      controle.disabled = Boolean(item && campo.soNaCriacao);
    }
    definirStatus(statusForm, '');
    form.hidden = false;
    form.querySelector('input:not(:disabled)')?.focus();
  }

  form.append(
    tituloForm,
    ...catalogo.campos.map((campo) =>
      campo.multipla
        ? el(
            'fieldset',
            { class: 'grupos' },
            el('legend', {}, campo.rotulo),
            controleDoCampo(campo, idCampo(campo)),
          )
        : el(
            'div',
            { class: 'field' },
            el('label', { for: idCampo(campo) }, campo.rotulo),
            controleDoCampo(campo, idCampo(campo)),
          ),
    ),
    statusForm,
    el(
      'div',
      { class: 'acoes' },
      el(
        'button',
        { class: 'button button--pequeno', type: 'submit' },
        `Salvar ${catalogo.singular}`,
      ),
      el(
        'button',
        {
          class: 'link link--botao',
          type: 'button',
          onclick: () => {
            form.hidden = true;
          },
        },
        'Cancelar',
      ),
    ),
  );

  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const valores = valoresDoForm();
    const problema = erroDoFormulario(catalogo.campos, valores, Boolean(editando));
    if (problema) {
      definirStatus(statusForm, problema, 'error');
      return;
    }
    const dados = corpoDoFormulario(catalogo.campos, valores, Boolean(editando));
    try {
      if (editando) {
        await chamarApi('PATCH', `${catalogo.rota}/${encodeURIComponent(editando.id)}`, dados);
      } else {
        await chamarApi('POST', catalogo.rota, dados);
      }
      const mensagem = editando ? 'Dados atualizados.' : 'Cadastro criado.';
      form.hidden = true;
      await carregar();
      definirStatus(status, mensagem);
    } catch (erro) {
      definirStatus(statusForm, erro.message, 'error');
    }
  });

  async function alterarStatus(item, ativar) {
    const url = `${catalogo.rota}/${encodeURIComponent(item.id)}`;
    try {
      if (ativar) await chamarApi('POST', `${url}/reativar`);
      else await chamarApi('DELETE', url);
      await carregar();
      definirStatus(status, ativar ? 'Cadastro reativado.' : 'Cadastro inativado.');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  function linha(item) {
    const nome = catalogo.identificacao(item);
    const ativo = item.status === 'ativo';
    const acoes = podeGerenciar
      ? el(
          'td',
          { class: 'tabela__acoes' },
          el(
            'button',
            {
              type: 'button',
              class: 'link link--botao',
              'aria-label': `Editar ${nome}`,
              onclick: () => abrirForm(item),
            },
            'Editar',
          ),
          el(
            'button',
            {
              type: 'button',
              class: 'link link--botao',
              'aria-label': `${ativo ? 'Inativar' : 'Reativar'} ${nome}`,
              onclick: () => alterarStatus(item, !ativo),
            },
            ativo ? 'Inativar' : 'Reativar',
          ),
        )
      : null;
    return el(
      'tr',
      {},
      catalogo.colunas.map((coluna) =>
        el('td', { class: coluna.semQuebra ? 'tabela__sem-quebra' : null }, coluna.valor(item)),
      ),
      el(
        'td',
        {},
        el(
          'span',
          { class: 'selo', dataset: { status: item.status } },
          ROTULO_STATUS[item.status] ?? item.status,
        ),
      ),
      acoes,
    );
  }

  async function carregar() {
    try {
      const { itens, tem_mais: temMais } = await chamarApi('POST', `${catalogo.rota}/lista`, {
        pagina,
        busca: termo || null,
      });
      corpo.replaceChildren(...itens.map(linha));
      anterior.disabled = pagina === 1;
      proxima.disabled = !temMais;
      definirStatus(status, itens.length === 0 ? 'Nenhum cadastro encontrado.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  anterior.addEventListener('click', () => {
    pagina -= 1;
    carregar();
  });
  proxima.addEventListener('click', () => {
    pagina += 1;
    carregar();
  });

  const formBusca = el(
    'form',
    { class: 'busca', novalidate: true, autocomplete: 'off' },
    el('label', { for: busca.id }, `Buscar em ${catalogo.titulo}`),
    el(
      'div',
      { class: 'busca__linha' },
      busca,
      el('button', { class: 'button button--pequeno', type: 'submit' }, 'Buscar'),
    ),
  );
  formBusca.addEventListener('submit', (evento) => {
    evento.preventDefault();
    termo = busca.value.trim();
    pagina = 1;
    carregar();
  });

  const novo = el(
    'button',
    {
      type: 'button',
      class: 'button button--pequeno',
      hidden: !podeGerenciar,
      onclick: () => abrirForm(),
    },
    catalogo.novo,
  );

  $(catalogo.secao).append(
    el(
      'div',
      { class: 'painel__cabecalho' },
      el('h1', { id: `titulo-${prefixo}` }, catalogo.titulo),
      novo,
    ),
    formBusca,
    form,
    el(
      'div',
      { class: 'tabela' },
      el(
        'table',
        { class: 'tabela--cadastro' },
        el(
          'thead',
          {},
          el(
            'tr',
            {},
            catalogo.colunas.map((coluna) => el('th', { scope: 'col' }, coluna.titulo)),
            el('th', { scope: 'col' }, 'Situação'),
            podeGerenciar
              ? el('th', { scope: 'col' }, el('span', { class: 'sr-only' }, 'Ações'))
              : null,
          ),
        ),
        corpo,
      ),
    ),
    status,
    el('div', { class: 'acoes' }, anterior, proxima),
  );

  return { abrir: carregar };
}
