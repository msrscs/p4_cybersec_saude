// Escolha de unidade, serviço, dia e horário com vaga (ADR-0026). Só aparecem as unidades que
// atendem o CID; o dia mostra as vagas, e o horário só é pedido depois de escolher o dia. A vaga é
// conferida de novo no backend ao gravar, porque outra pessoa pode ter marcado nesse intervalo.
import { definirStatus, el, limpar } from './lib/dom.js';
import { rotuloDeDia, rotuloDeHorario } from './lib/ocis.js';

export function criarAgendador(chamarApi, { id, rotuloUnidade, rotuloServico, permitir }) {
  const unidade = el('select', { id: `${id}-unidade` });
  const servico = el('select', { id: `${id}-servico` });
  const dias = el('div', { class: 'vagas', role: 'group', 'aria-label': 'Dias com vaga' });
  const horarios = el('div', { class: 'vagas', role: 'group', 'aria-label': 'Horários vagos' });
  const status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  let unidades = [];
  let escolhido = null;

  const elemento = el(
    'div',
    { class: 'agendador', id },
    el(
      'div',
      { class: 'filtros' },
      el('div', { class: 'field' }, el('label', { for: unidade.id }, rotuloUnidade), unidade),
      el('div', { class: 'field' }, el('label', { for: servico.id }, rotuloServico), servico),
    ),
    el('p', { class: 'seletor__titulo' }, 'Dias com vaga'),
    dias,
    el('p', { class: 'seletor__titulo' }, 'Horários vagos'),
    horarios,
    status,
  );

  function limparEscolha() {
    escolhido = null;
    limpar(horarios);
  }

  function marcarSelecionado(grupo, botao) {
    for (const outro of grupo.querySelectorAll('button')) {
      outro.setAttribute('aria-pressed', String(outro === botao));
    }
  }

  async function carregarHorarios(data) {
    limparEscolha();
    const url =
      `/ocis/opcoes/unidades/${encodeURIComponent(unidade.value)}` +
      `/servicos/${encodeURIComponent(servico.value)}/dias/${encodeURIComponent(data)}/horarios`;
    try {
      const resposta = await chamarApi('GET', url);
      horarios.replaceChildren(
        ...resposta.horarios.map((horario) => {
          const botao = el(
            'button',
            { type: 'button', class: 'vaga vaga--horario', 'aria-pressed': 'false' },
            rotuloDeHorario(horario),
          );
          botao.addEventListener('click', () => {
            escolhido = horario.data_hora;
            marcarSelecionado(horarios, botao);
            definirStatus(status, '');
          });
          return botao;
        }),
      );
      definirStatus(status, resposta.horarios.length === 0 ? 'Este dia acabou de lotar.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  async function carregarDias() {
    limparEscolha();
    limpar(dias);
    if (!unidade.value || !servico.value) return;
    const url =
      `/ocis/opcoes/unidades/${encodeURIComponent(unidade.value)}` +
      `/servicos/${encodeURIComponent(servico.value)}/dias`;
    try {
      const resposta = await chamarApi('GET', url);
      dias.replaceChildren(
        ...resposta.dias.map((dia) => {
          const botao = el(
            'button',
            { type: 'button', class: 'vaga vaga--dia', 'aria-pressed': 'false' },
            rotuloDeDia(dia),
          );
          botao.addEventListener('click', () => {
            marcarSelecionado(dias, botao);
            carregarHorarios(dia.data);
          });
          return botao;
        }),
      );
      definirStatus(status, resposta.dias.length === 0 ? 'Sem vagas nos próximos 60 dias.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  function preencherServicos() {
    const atual = unidades.find(({ id: idUnidade }) => String(idUnidade) === unidade.value);
    servico.replaceChildren(
      el('option', { value: '' }, 'Selecione'),
      ...(atual?.servicos ?? []).map(({ id: idServico, nome }) =>
        el('option', { value: String(idServico) }, nome),
      ),
    );
    carregarDias();
  }

  unidade.addEventListener('change', preencherServicos);
  servico.addEventListener('change', carregarDias);

  return {
    elemento,
    /** Busca as unidades que atendem este CID. Sem CID, deixa tudo vazio. */
    async carregar(idCid) {
      limpar(unidade);
      limpar(servico);
      limpar(dias);
      limparEscolha();
      definirStatus(status, '');
      if (!idCid) return;
      try {
        const resposta = await chamarApi(
          'GET',
          `/ocis/opcoes/cids/${encodeURIComponent(idCid)}/unidades`,
        );
        unidades = resposta.unidades.filter(({ id: idUnidade }) => permitir(idUnidade));
        unidade.replaceChildren(
          el('option', { value: '' }, 'Selecione'),
          ...unidades.map(({ id: idUnidade, nome }) =>
            el('option', { value: String(idUnidade) }, nome),
          ),
        );
        if (unidades.length === 0) {
          definirStatus(status, 'Nenhuma unidade com agenda atende este CID.', 'error');
        }
      } catch (erro) {
        definirStatus(status, erro.message, 'error');
      }
    },
    /** A escolha completa, ou null enquanto faltar o horário. */
    valor() {
      if (!escolhido) return null;
      return {
        id_unidade: Number(unidade.value),
        id_servico: Number(servico.value),
        data_hora: escolhido,
      };
    },
  };
}
