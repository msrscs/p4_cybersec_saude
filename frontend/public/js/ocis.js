// Tela de OCIs e navegação (RF-12, ADR-0025). A interface esconde o que o perfil não pode fazer,
// mas quem autoriza e aplica o alcance por unidade, a cada requisição, é o backend.
import { cpfValido, formatarCpf } from './lib/cpf.js';
import { definirStatus, el, limpar } from './lib/dom.js';
import {
  corpoDaListaDeOcis,
  instanteDe,
  ROTULO_ETAPA,
  ROTULO_OCI,
  seloDaSituacao,
} from './lib/ocis.js';

const $ = (id) => document.getElementById(id);
const dataHora = (iso) => new Date(iso).toLocaleString('pt-BR');
const data = (iso) => new Date(iso).toLocaleDateString('pt-BR');
const rotuloCid = (cid) => `${cid.cid} — ${cid.descricao}`;

function selo(situacao, rotulo) {
  return el('span', { class: 'selo', dataset: { status: seloDaSituacao(situacao) } }, rotulo);
}

function status(id) {
  return el('p', { class: 'form__status', id, role: 'status', 'aria-live': 'polite' });
}

function campo(id, rotulo, controle) {
  return el('div', { class: 'field' }, el('label', { for: id }, rotulo), controle);
}

function preencher(select, vazio, opcoes) {
  select.replaceChildren(
    ...(vazio === null ? [] : [el('option', { value: '' }, vazio)]),
    ...opcoes.map(({ id, nome }) => el('option', { value: String(id) }, nome)),
  );
}

export function criarOcis(chamarApi, permissoes) {
  const pode = (acao) => permissoes.has(`oci:${acao}`);
  let opcoes = null;
  let filtros = {};
  let cursorAtual = null;
  let cursorProximo = null;
  const cursoresAnteriores = [];
  let ociAtual = null;

  // --- Controles dependentes: o tipo define os CIDs, e a unidade define os serviços ------

  async function carregarCids(select, idTipo) {
    limpar(select);
    if (!idTipo) return;
    const { cids } = await chamarApi(
      'GET',
      `/ocis/opcoes/tipos/${encodeURIComponent(idTipo)}/cids`,
    );
    preencher(
      select,
      null,
      cids.map((c) => ({ id: c.id, nome: rotuloCid(c) })),
    );
  }

  async function carregarServicos(select, idUnidade) {
    limpar(select);
    if (!idUnidade) return;
    const { servicos } = await chamarApi(
      'GET',
      `/ocis/opcoes/unidades/${encodeURIComponent(idUnidade)}/servicos`,
    );
    preencher(select, null, servicos);
  }

  function aoMudar(origem, destino, carregar, statusEl) {
    origem.addEventListener('change', async () => {
      try {
        await carregar(destino, origem.value);
      } catch (erro) {
        definirStatus(statusEl, erro.message, 'error');
      }
    });
  }

  // --- Estrutura da tela -----------------------------------------------------------------

  const filtroStatus = el(
    'select',
    { id: 'oci-filtro-situacao' },
    el('option', { value: '' }, 'Todas'),
    Object.entries(ROTULO_OCI).map(([valor, rotulo]) => el('option', { value: valor }, rotulo)),
  );
  const filtroTipo = el('select', { id: 'oci-filtro-tipo' });
  const filtroUnidade = el('select', { id: 'oci-filtro-unidade' });
  const filtroCpf = el('input', {
    id: 'oci-filtro-cpf',
    type: 'text',
    inputmode: 'numeric',
    maxlength: 14,
    autocomplete: 'off',
  });
  const filtroAtrasadas = el('input', { id: 'oci-filtro-atrasadas', type: 'checkbox' });
  const statusLista = status('status-lista-ocis');
  const corpoLista = el('tbody', { id: 'corpo-ocis' });
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

  const formFiltros = el(
    'form',
    { class: 'filtros', id: 'filtros-ocis', novalidate: true, autocomplete: 'off' },
    campo(filtroStatus.id, 'Situação da OCI', filtroStatus),
    campo(filtroTipo.id, 'Tipo da OCI', filtroTipo),
    campo(filtroUnidade.id, 'Unidade da OCI', filtroUnidade),
    campo(filtroCpf.id, 'CPF do paciente (filtro)', filtroCpf),
    el('label', { class: 'grupo', for: filtroAtrasadas.id }, filtroAtrasadas, 'Só atrasadas'),
    el(
      'div',
      { class: 'acoes' },
      el('button', { class: 'button button--pequeno', type: 'submit' }, 'Filtrar'),
      el(
        'button',
        {
          class: 'link link--botao',
          type: 'button',
          onclick: () => {
            formFiltros.reset();
            filtros = {};
            recomecar();
          },
        },
        'Limpar filtros',
      ),
    ),
  );

  // --- Nova OCI ---------------------------------------------------------------------------

  const novaCpf = el('input', {
    id: 'oci-nova-cpf',
    type: 'text',
    inputmode: 'numeric',
    maxlength: 14,
    autocomplete: 'off',
  });
  const novaTipo = el('select', { id: 'oci-nova-tipo' });
  const novaCid = el('select', { id: 'oci-nova-cid' });
  const novaUnidade = el('select', { id: 'oci-nova-unidade' });
  const novaServico = el('select', { id: 'oci-nova-servico' });
  const novaData = el('input', { id: 'oci-nova-data', type: 'datetime-local' });
  const statusForm = status('status-form-oci');
  const formNova = el(
    'form',
    { class: 'form ficha', id: 'form-oci', novalidate: true, autocomplete: 'off', hidden: true },
    el('h2', {}, 'Nova OCI'),
    campo(novaCpf.id, 'CPF do paciente da OCI', novaCpf),
    campo(novaTipo.id, 'Tipo da nova OCI', novaTipo),
    campo(novaCid.id, 'CID da nova OCI', novaCid),
    campo(novaUnidade.id, 'Unidade da primeira etapa', novaUnidade),
    campo(novaServico.id, 'Serviço da primeira etapa', novaServico),
    campo(novaData.id, 'Data e hora da primeira etapa', novaData),
    statusForm,
    el(
      'div',
      { class: 'acoes' },
      el('button', { class: 'button button--pequeno', type: 'submit' }, 'Abrir OCI'),
      el(
        'button',
        {
          class: 'link link--botao',
          type: 'button',
          onclick: () => {
            formNova.hidden = true;
          },
        },
        'Cancelar',
      ),
    ),
  );
  novaCpf.addEventListener('input', () => (novaCpf.value = formatarCpf(novaCpf.value)));
  filtroCpf.addEventListener('input', () => (filtroCpf.value = formatarCpf(filtroCpf.value)));
  aoMudar(novaTipo, novaCid, carregarCids, statusForm);
  aoMudar(novaUnidade, novaServico, carregarServicos, statusForm);

  async function abrirFormNova() {
    formNova.reset();
    limpar(novaCid);
    limpar(novaServico);
    preencher(novaTipo, 'Selecione', opcoes.tipos);
    preencher(novaUnidade, 'Selecione', opcoes.unidades_abertura);
    definirStatus(
      statusForm,
      opcoes.unidades_abertura.length === 0 ? 'Seu usuário não tem unidade para abrir OCI.' : '',
    );
    formNova.hidden = false;
    novaCpf.focus();
  }

  formNova.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const instante = instanteDe(novaData.value);
    if (!cpfValido(novaCpf.value)) {
      definirStatus(statusForm, 'Informe um CPF válido.', 'error');
      return;
    }
    if (!novaTipo.value || !novaCid.value || !novaUnidade.value || !novaServico.value) {
      definirStatus(statusForm, 'Escolha tipo, CID, unidade e serviço.', 'error');
      return;
    }
    if (!instante) {
      definirStatus(statusForm, 'Informe a data e a hora da primeira etapa.', 'error');
      return;
    }
    try {
      const oci = await chamarApi('POST', '/ocis', {
        cpf: novaCpf.value.replace(/\D/g, ''),
        id_tipo_oci: Number(novaTipo.value),
        cid: novaCid.value,
        id_unidade: Number(novaUnidade.value),
        id_servico: Number(novaServico.value),
        data_hora: instante,
      });
      formNova.reset();
      formNova.hidden = true;
      mostrarFicha(oci);
      await carregarLista();
    } catch (erro) {
      definirStatus(statusForm, erro.message, 'error');
    }
  });

  // --- Ficha -----------------------------------------------------------------------------

  const etapaUnidade = el('select', { id: 'oci-etapa-unidade' });
  const etapaServico = el('select', { id: 'oci-etapa-servico' });
  const etapaData = el('input', { id: 'oci-etapa-data', type: 'datetime-local' });
  const statusFicha = status('status-oci');
  const formEtapa = el(
    'form',
    { class: 'filtros', id: 'form-etapa', novalidate: true, autocomplete: 'off' },
    campo(etapaUnidade.id, 'Unidade do encaminhamento', etapaUnidade),
    campo(etapaServico.id, 'Serviço do encaminhamento', etapaServico),
    campo(etapaData.id, 'Data e hora do encaminhamento', etapaData),
    el(
      'div',
      { class: 'acoes' },
      el('button', { class: 'button button--pequeno', type: 'submit' }, 'Incluir etapa'),
    ),
  );
  aoMudar(etapaUnidade, etapaServico, carregarServicos, statusFicha);

  const resultado = el('textarea', { id: 'oci-conclusao-resultado', maxlength: 4000, rows: 3 });
  const resultadoCid = el('select', { id: 'oci-conclusao-cid' });
  const formConclusao = el(
    'form',
    { class: 'form', id: 'form-conclusao', novalidate: true, autocomplete: 'off' },
    campo(resultado.id, 'Resultado da OCI', resultado),
    campo(resultadoCid.id, 'CID do resultado (opcional)', resultadoCid),
    el(
      'div',
      { class: 'acoes' },
      el('button', { class: 'button button--pequeno', type: 'submit' }, 'Concluir OCI'),
      el(
        'button',
        {
          class: 'button button--perigo button--pequeno',
          type: 'button',
          id: 'oci-cancelar',
          onclick: () => {
            $('oci-confirmar').hidden = false;
          },
        },
        'Cancelar OCI',
      ),
    ),
    el(
      'div',
      { class: 'aviso', id: 'oci-confirmar', hidden: true },
      el('p', {}, 'Cancelar encerra esta OCI e não pode ser desfeito. Confirma?'),
      el(
        'div',
        { class: 'acoes' },
        el(
          'button',
          {
            class: 'button button--perigo button--pequeno',
            type: 'button',
            onclick: () => executar(`/ocis/${encodeURIComponent(ociAtual.id)}/cancelar`),
          },
          'Confirmar cancelamento',
        ),
        el(
          'button',
          {
            class: 'link link--botao',
            type: 'button',
            onclick: () => {
              $('oci-confirmar').hidden = true;
            },
          },
          'Desistir',
        ),
      ),
    ),
  );

  const dado = (rotulo, id) => el('div', {}, el('dt', {}, rotulo), el('dd', { id }));
  const corpoEtapas = el('tbody', { id: 'oci-etapas' });
  const ficha = el(
    'article',
    { class: 'ficha', id: 'ficha-oci', hidden: true, 'aria-labelledby': 'oci-paciente' },
    el(
      'header',
      { class: 'ficha__cabecalho' },
      el('h2', { id: 'oci-paciente' }),
      el('span', { class: 'selo', id: 'oci-situacao' }),
    ),
    el(
      'dl',
      { class: 'ficha__dados' },
      dado('CPF', 'oci-cpf'),
      dado('Tipo de OCI', 'oci-tipo'),
      dado('CID', 'oci-cid'),
      dado('Aberta em', 'oci-criada'),
      dado('Prazo', 'oci-prazo'),
      dado('Resultado', 'oci-resultado'),
      dado('CID do resultado', 'oci-resultado-cid'),
    ),
    el('h3', {}, 'Navegação'),
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
            ['Data e hora', 'Unidade', 'Serviço', 'Situação'].map((titulo) =>
              el('th', { scope: 'col' }, titulo),
            ),
            el('th', { scope: 'col' }, el('span', { class: 'sr-only' }, 'Ações')),
          ),
        ),
        corpoEtapas,
      ),
    ),
    formEtapa,
    formConclusao,
    statusFicha,
    el(
      'div',
      { class: 'acoes' },
      el(
        'button',
        {
          type: 'button',
          class: 'link link--botao',
          onclick: () => {
            ociAtual = null;
            ficha.hidden = true;
          },
        },
        'Fechar OCI',
      ),
    ),
  );

  function linhaEtapa(oci, etapa) {
    const url = `/ocis/${encodeURIComponent(oci.id)}/navegacoes/${encodeURIComponent(etapa.id)}`;
    const marcar = (situacao, rotulo) =>
      el(
        'button',
        {
          type: 'button',
          class: 'link link--botao',
          onclick: () => executar(url, { status: situacao }, 'PATCH'),
        },
        rotulo,
      );
    return el(
      'tr',
      {},
      el('td', {}, dataHora(etapa.data_hora)),
      el('td', {}, etapa.unidade),
      el('td', {}, etapa.servico),
      el('td', {}, selo(etapa.status, ROTULO_ETAPA[etapa.status] ?? etapa.status)),
      el(
        'td',
        { class: 'tabela__acoes' },
        etapa.pode_marcar && pode('editar')
          ? [
              marcar('realizado', 'Realizado'),
              marcar('faltou', 'Faltou'),
              marcar('cancelado', 'Cancelado'),
            ]
          : null,
      ),
    );
  }

  function mostrarFicha(oci) {
    ociAtual = oci;
    const aberta = oci.status === 'aberta';
    $('oci-paciente').textContent = oci.paciente_nome ?? 'Cadastro ilegível';
    const situacao = $('oci-situacao');
    situacao.textContent = ROTULO_OCI[oci.status] ?? oci.status;
    situacao.dataset.status = seloDaSituacao(oci.status);
    $('oci-cpf').textContent = oci.cpf_mascarado ?? '—';
    $('oci-tipo').textContent = oci.tipo_oci;
    $('oci-cid').textContent = rotuloCid(oci.cid);
    $('oci-criada').textContent = dataHora(oci.data_criacao);
    $('oci-prazo').textContent = `${data(oci.prazo_em)}${oci.atrasada ? ' (atrasada)' : ''}`;
    $('oci-resultado').textContent = oci.resultado ?? '—';
    $('oci-resultado-cid').textContent = oci.resultado_cid ? rotuloCid(oci.resultado_cid) : '—';
    corpoEtapas.replaceChildren(...oci.navegacoes.map((etapa) => linhaEtapa(oci, etapa)));
    formEtapa.hidden = !(aberta && pode('editar'));
    formConclusao.hidden = !(aberta && pode('concluir'));
    formEtapa.reset();
    formConclusao.reset();
    $('oci-confirmar').hidden = true;
    limpar(etapaServico);
    preencher(etapaUnidade, 'Selecione', opcoes.unidades);
    definirStatus(statusFicha, '');
    ficha.hidden = false;
    if (aberta && pode('concluir')) carregarCidsDoResultado(oci);
  }

  async function carregarCidsDoResultado(oci) {
    try {
      const { cids } = await chamarApi(
        'GET',
        `/ocis/opcoes/tipos/${encodeURIComponent(oci.id_tipo_oci)}/cids`,
      );
      preencher(
        resultadoCid,
        'Sem CID',
        cids.map((c) => ({ id: c.id, nome: rotuloCid(c) })),
      );
    } catch (erro) {
      definirStatus(statusFicha, erro.message, 'error');
    }
  }

  async function executar(url, corpo, metodo = 'POST') {
    try {
      mostrarFicha(await chamarApi(metodo, url, corpo));
      await carregarLista();
    } catch (erro) {
      definirStatus(statusFicha, erro.message, 'error');
    }
  }

  formEtapa.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const instante = instanteDe(etapaData.value);
    if (!etapaUnidade.value || !etapaServico.value || !instante) {
      definirStatus(statusFicha, 'Escolha unidade, serviço, data e hora.', 'error');
      return;
    }
    executar(`/ocis/${encodeURIComponent(ociAtual.id)}/navegacoes`, {
      id_unidade: Number(etapaUnidade.value),
      id_servico: Number(etapaServico.value),
      data_hora: instante,
    });
  });

  formConclusao.addEventListener('submit', (evento) => {
    evento.preventDefault();
    const texto = resultado.value.trim();
    if (texto.length < 2) {
      definirStatus(statusFicha, 'Descreva o resultado para concluir.', 'error');
      return;
    }
    executar(`/ocis/${encodeURIComponent(ociAtual.id)}/concluir`, {
      resultado: texto,
      resultado_cid: resultadoCid.value || null,
    });
  });

  // --- Lista -----------------------------------------------------------------------------

  async function abrirFicha(id) {
    definirStatus(statusLista, '');
    formNova.hidden = true;
    try {
      mostrarFicha(await chamarApi('GET', `/ocis/${encodeURIComponent(id)}`));
      ficha.scrollIntoView();
    } catch (erro) {
      definirStatus(statusLista, erro.message, 'error');
    }
  }

  function linha(oci) {
    return el(
      'tr',
      {},
      el('td', {}, oci.paciente_nome ?? 'Cadastro ilegível'),
      el('td', {}, el('code', {}, oci.cpf_mascarado ?? '—')),
      el('td', {}, oci.tipo_oci),
      el('td', { title: oci.cid.descricao }, oci.cid.cid),
      el('td', {}, selo(oci.status, ROTULO_OCI[oci.status] ?? oci.status)),
      el(
        'td',
        { class: 'tabela__sem-quebra' },
        data(oci.prazo_em),
        oci.atrasada ? [' ', selo('atrasada', 'Atrasada')] : null,
      ),
      el(
        'td',
        {},
        el(
          'button',
          {
            type: 'button',
            class: 'link link--botao',
            'aria-label': `Abrir OCI de ${oci.paciente_nome ?? 'cadastro ilegível'}`,
            onclick: () => abrirFicha(oci.id),
          },
          'Abrir',
        ),
      ),
    );
  }

  async function carregarLista() {
    try {
      const { itens, proximo } = await chamarApi(
        'POST',
        '/ocis/lista',
        corpoDaListaDeOcis(filtros, cursorAtual),
      );
      cursorProximo = proximo;
      corpoLista.replaceChildren(...itens.map(linha));
      anterior.disabled = cursoresAnteriores.length === 0;
      proxima.disabled = proximo === null;
      definirStatus(statusLista, itens.length === 0 ? 'Nenhuma OCI encontrada.' : '');
    } catch (erro) {
      definirStatus(statusLista, erro.message, 'error');
    }
  }

  function recomecar() {
    cursorAtual = null;
    cursoresAnteriores.length = 0;
    return carregarLista();
  }

  formFiltros.addEventListener('submit', (evento) => {
    evento.preventDefault();
    if (filtroCpf.value && !cpfValido(filtroCpf.value)) {
      definirStatus(statusLista, 'Informe um CPF válido.', 'error');
      return;
    }
    filtros = {
      status: filtroStatus.value,
      tipo: filtroTipo.value,
      unidade: filtroUnidade.value,
      cpf: filtroCpf.value,
      atrasadas: filtroAtrasadas.checked,
    };
    recomecar();
  });
  anterior.addEventListener('click', () => {
    cursorAtual = cursoresAnteriores.pop() ?? null;
    carregarLista();
  });
  proxima.addEventListener('click', () => {
    cursoresAnteriores.push(cursorAtual);
    cursorAtual = cursorProximo;
    carregarLista();
  });

  $('secao-ocis').append(
    el(
      'div',
      { class: 'painel__cabecalho' },
      el('h1', { id: 'titulo-ocis' }, 'OCIs'),
      el(
        'button',
        {
          type: 'button',
          class: 'button button--pequeno',
          hidden: !pode('criar'),
          onclick: abrirFormNova,
        },
        'Nova OCI',
      ),
    ),
    formNova,
    ficha,
    formFiltros,
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
            ['Paciente', 'CPF', 'Tipo', 'CID', 'Situação', 'Prazo'].map((titulo) =>
              el('th', { scope: 'col' }, titulo),
            ),
            el('th', { scope: 'col' }, el('span', { class: 'sr-only' }, 'Ação')),
          ),
        ),
        corpoLista,
      ),
    ),
    statusLista,
    el('div', { class: 'acoes' }, anterior, proxima),
  );

  return {
    async abrir() {
      try {
        opcoes = await chamarApi('GET', '/ocis/opcoes');
        preencher(filtroTipo, 'Todos', opcoes.tipos);
        preencher(filtroUnidade, 'Todas', opcoes.unidades);
      } catch (erro) {
        definirStatus(statusLista, erro.message, 'error');
        return;
      }
      await recomecar();
    },
  };
}
