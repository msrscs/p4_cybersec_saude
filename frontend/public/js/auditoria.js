// Tela de auditoria (RF-04, ADR-0015). Só exibe: quem autoriza e registra a leitura é o backend.
import { cpfValido, formatarCpf, somenteDigitos } from './lib/cpf.js';
import { definirStatus, el } from './lib/dom.js';
import { corpoDaConsulta, detalhesDoRegistro, periodoValido, rotuloDaAcao } from './lib/logs.js';

const $ = (id) => document.getElementById(id);
const dataHora = (iso) => new Date(iso).toLocaleString('pt-BR');
const hashOuTraco = (valor) => (valor ? el('code', {}, valor) : '—');

function linha(item) {
  return el(
    'tr',
    {},
    el('td', {}, dataHora(item.data_hora)),
    el('td', { title: item.acao }, rotuloDaAcao(item.acao)),
    el('td', {}, hashOuTraco(item.usuario)),
    el('td', {}, hashOuTraco(item.paciente)),
    el('td', {}, item.ip_origem ?? '—'),
    el(
      'td',
      {},
      el(
        'details',
        {},
        el('summary', {}, 'Ver'),
        el('pre', { class: 'log__detalhe' }, detalhesDoRegistro(item)),
      ),
    ),
  );
}

function mostrarIntegridade(dados) {
  const selo = $('integridade-selo');
  if (dados.integra === null) {
    selo.textContent = 'Sem verificação';
    selo.dataset.status = 'pendente';
  } else {
    selo.textContent = dados.integra ? 'Íntegra' : 'Adulteração detectada';
    selo.dataset.status = dados.integra ? 'ativo' : 'inativo';
  }
  const partes = [`${dados.total_registros} registros`];
  if (dados.verificada_em) partes.push(`última verificação: ${dataHora(dados.verificada_em)}`);
  if (dados.checkpoint_em) partes.push(`último checkpoint: ${dataHora(dados.checkpoint_em)}`);
  $('integridade-texto').textContent = partes.join(' · ');
}

export function criarAuditoria(chamarApi) {
  let filtros = {};
  let cursorAtual = null;
  let cursorProximo = null;
  let cursoresAnteriores = [];
  let acoesCarregadas = false;

  async function carregarAcoes() {
    if (acoesCarregadas) return;
    const { acoes } = await chamarApi('GET', '/logs/acoes');
    const opcoes = acoes
      .map((acao) => el('option', { value: acao }, rotuloDaAcao(acao)))
      .sort((a, b) => a.textContent.localeCompare(b.textContent, 'pt-BR'));
    $('log-acao').replaceChildren(el('option', { value: '' }, 'Todos'), ...opcoes);
    acoesCarregadas = true;
  }

  async function carregarPagina() {
    const status = $('status-logs');
    try {
      const { itens, proximo } = await chamarApi(
        'POST',
        '/logs/consulta',
        corpoDaConsulta(filtros, cursorAtual),
      );
      cursorProximo = proximo;
      $('corpo-logs').replaceChildren(...itens.map(linha));
      $('logs-anterior').disabled = cursoresAnteriores.length === 0;
      $('logs-proxima').disabled = proximo === null;
      definirStatus(status, itens.length === 0 ? 'Nenhum registro encontrado.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  function recomecar() {
    cursorAtual = null;
    cursoresAnteriores = [];
    return carregarPagina();
  }

  const cpf = $('log-cpf');
  cpf.addEventListener('input', () => (cpf.value = formatarCpf(cpf.value)));

  $('form-logs').addEventListener('submit', (evento) => {
    evento.preventDefault();
    const status = $('status-logs');
    const novos = {
      de: $('log-de').value,
      ate: $('log-ate').value,
      acao: $('log-acao').value,
      cpf: somenteDigitos(cpf.value),
    };
    if (novos.cpf && !cpfValido(novos.cpf)) {
      definirStatus(status, 'Informe um CPF válido.', 'error');
      return;
    }
    if (!periodoValido(novos)) {
      definirStatus(status, 'A data inicial deve ser anterior à final.', 'error');
      return;
    }
    filtros = novos;
    recomecar();
  });

  $('log-limpar').addEventListener('click', () => {
    $('form-logs').reset();
    filtros = {};
    recomecar();
  });

  $('logs-proxima').addEventListener('click', () => {
    cursoresAnteriores.push(cursorAtual);
    cursorAtual = cursorProximo;
    carregarPagina();
  });

  $('logs-anterior').addEventListener('click', () => {
    cursorAtual = cursoresAnteriores.pop() ?? null;
    carregarPagina();
  });

  return {
    async abrir() {
      try {
        await carregarAcoes();
        mostrarIntegridade(await chamarApi('GET', '/logs/integridade'));
      } catch (erro) {
        definirStatus($('status-logs'), erro.message, 'error');
      }
      await recomecar();
    },
  };
}
