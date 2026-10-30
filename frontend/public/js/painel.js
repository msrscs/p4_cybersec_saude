// Área logada. A interface mostra só o que as permissões da sessão permitem, mas quem
// autoriza de fato é o backend, a cada requisição (ADR-0011).
import { criarAuditoria } from './auditoria.js';
import { chamar, ErroApi, quandoSessaoExpirar } from './lib/api.js';
import { cpfValido, formatarCpf, somenteDigitos } from './lib/cpf.js';
import { definirStatus, el, limpar, mostrarSomente } from './lib/dom.js';
import { criarUsuarios } from './usuarios.js';

const $ = (id) => document.getElementById(id);
const INATIVIDADE_MS = 15 * 60 * 1000;
const AVISO_ANTES_MS = 60 * 1000;
const secoes = [...document.querySelectorAll('.painel')];
let permissoes = new Set();
let pacienteAtual = null;

const pode = (permissao) => permissoes.has(`paciente:${permissao}`);
const api = (metodo, caminho, corpo) => chamar(metodo, caminho, corpo, { sessao: true });

// --- Sessão: expiração por inatividade ---------------------------------------------------

let expiraEm = 0;
let cronometro = null;

function sairPara(motivo) {
  limparDados();
  window.location.replace(`/?motivo=${motivo}`);
}

quandoSessaoExpirar(() => sairPara('expirada'));

function renovarPrazo(expira) {
  expiraEm = expira ? new Date(expira).getTime() : Date.now() + INATIVIDADE_MS;
}

function tick() {
  const restante = expiraEm - Date.now();
  if (restante <= 0) {
    clearInterval(cronometro);
    sairPara('expirada');
    return;
  }
  const minutos = Math.floor(restante / 60000);
  const segundos = String(Math.floor((restante % 60000) / 1000)).padStart(2, '0');
  $('tempo-sessao').textContent = `Sessão: ${minutos}:${segundos}`;
  const dialogo = $('dialogo-sessao');
  if (restante <= AVISO_ANTES_MS && !dialogo.open) dialogo.showModal();
}

$('continuar-sessao').addEventListener('click', async () => {
  try {
    const sessao = await api('GET', '/auth/sessao');
    renovarPrazo(sessao.expira_em);
    $('dialogo-sessao').close();
  } catch {
    // 401 já redireciona
  }
});

async function sair() {
  limparDados();
  try {
    await chamar('POST', '/auth/logout');
  } finally {
    window.location.replace('/?motivo=saiu');
  }
}

$('sair').addEventListener('click', sair);
$('sair-dialogo').addEventListener('click', sair);

// Qualquer chamada bem-sucedida renova o prazo no servidor; espelhamos aqui.
async function chamarApi(metodo, caminho, corpo) {
  const dados = await api(metodo, caminho, corpo);
  renovarPrazo();
  return dados;
}

// --- Navegação ---------------------------------------------------------------------------

const aoAbrir = {};

function abrir(idSecao) {
  mostrarSomente(secoes, $(idSecao));
  for (const item of document.querySelectorAll('.menu__item')) {
    item.setAttribute('aria-current', item.dataset.secao === idSecao ? 'page' : 'false');
  }
  aoAbrir[idSecao]?.();
}

for (const item of document.querySelectorAll('.menu__item')) {
  item.addEventListener('click', () => abrir(item.dataset.secao));
}

function limparDados() {
  pacienteAtual = null;
  for (const form of document.querySelectorAll('form')) form.reset();
  for (const id of [
    'ficha-nome',
    'ficha-cpf',
    'ficha-nascimento',
    'ficha-email',
    'ficha-atualizado',
  ]) {
    $(id).textContent = '';
  }
  limpar($('lista-codigos'));
  limpar($('corpo-lista'));
  limpar($('corpo-logs'));
  limpar($('corpo-usuarios'));
  for (const id of ['usuario-senha-valor', 'usuario-nome', 'usuario-cpf', 'usuario-email']) {
    $(id).textContent = '';
  }
}

// --- Troca de senha (formulário reutilizado em dois lugares) -----------------------------

function campoSenha(id, rotulo, autocomplete) {
  return el(
    'div',
    { class: 'field' },
    el('label', { for: id }, rotulo),
    el('input', { id, type: 'password', autocomplete, required: true }),
  );
}

function montarFormSenha(form, indice, aoConcluir) {
  const ids = ['atual', 'nova', 'confirma'].map((n) => `senha-${n}-${indice}`);
  const status = el('p', { class: 'form__status', role: 'status', 'aria-live': 'polite' });
  form.append(
    campoSenha(ids[0], 'Senha atual', 'current-password'),
    campoSenha(ids[1], 'Nova senha', 'new-password'),
    campoSenha(ids[2], 'Confirme a nova senha', 'new-password'),
    el(
      'p',
      { class: 'dica' },
      'Mínimo de 12 caracteres, com maiúscula, minúscula, número e caractere especial.',
    ),
    status,
    el('button', { class: 'button button--pequeno', type: 'submit' }, 'Salvar nova senha'),
  );
  form.addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const [atual, nova, confirma] = ids.map((id) => $(id));
    if (nova.value !== confirma.value) {
      definirStatus(status, 'A confirmação não confere com a nova senha.', 'error');
      return;
    }
    try {
      await chamarApi('POST', '/auth/senha', { senha_atual: atual.value, nova_senha: nova.value });
      form.reset();
      definirStatus(status, 'Senha alterada.');
      aoConcluir?.();
    } catch (erro) {
      for (const campo of [atual, nova, confirma]) campo.value = '';
      definirStatus(status, erro.message, 'error');
    }
  });
}

// --- Pacientes ---------------------------------------------------------------------------

const formatarData = (iso) => new Date(`${iso}T00:00:00`).toLocaleDateString('pt-BR');

function mostrarFicha(paciente) {
  pacienteAtual = paciente;
  $('form-paciente').hidden = true;
  $('ficha-nome').textContent = paciente.nome;
  $('ficha-cpf').textContent = paciente.cpf;
  $('ficha-nascimento').textContent = formatarData(paciente.data_nascimento);
  $('ficha-email').textContent = paciente.email ?? '—';
  $('ficha-atualizado').textContent = new Date(paciente.atualizado_em).toLocaleString('pt-BR');
  const ativo = paciente.status === 'ativo';
  $('ficha-status').textContent = ativo ? 'Ativo' : 'Inativo';
  $('ficha-status').dataset.status = paciente.status;
  $('editar').hidden = !(pode('editar') && ativo);
  $('inativar').hidden = !(pode('inativar') && ativo);
  $('reativar').hidden = !(pode('inativar') && !ativo);
  definirStatus($('status-ficha'), '');
  $('ficha').hidden = false;
}

function fecharFicha() {
  pacienteAtual = null;
  $('ficha').hidden = true;
}

$('fechar-ficha').addEventListener('click', fecharFicha);

const buscaCpf = $('busca-cpf');
buscaCpf.addEventListener('input', () => (buscaCpf.value = formatarCpf(buscaCpf.value)));
$('paciente-cpf').addEventListener('input', (e) => (e.target.value = formatarCpf(e.target.value)));

$('form-busca').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const status = $('status-busca');
  fecharFicha();
  if (!cpfValido(buscaCpf.value)) {
    definirStatus(status, 'Informe um CPF válido.', 'error');
    return;
  }
  definirStatus(status, 'Buscando…');
  try {
    // CPF no corpo, nunca na URL (ADR-0011).
    const paciente = await chamarApi('POST', '/pacientes/busca', {
      cpf: somenteDigitos(buscaCpf.value),
    });
    definirStatus(status, '');
    mostrarFicha(paciente);
  } catch (erro) {
    definirStatus(status, erro.message, erro.status === 404 ? 'info' : 'error');
  }
});

// --- Lista de pacientes (ADR-0014) ---------------------------------------------------------

let cursorAtual = null;
let cursorProximo = null;
const cursoresAnteriores = [];

async function abrirDaLista(id) {
  const status = $('status-lista');
  definirStatus(status, '');
  $('form-paciente').hidden = true;
  try {
    mostrarFicha(await chamarApi('GET', `/pacientes/${encodeURIComponent(id)}`));
    $('ficha').scrollIntoView();
  } catch (erro) {
    definirStatus(status, erro.message, 'error');
  }
}

function linhaDaLista(paciente) {
  return el(
    'tr',
    {},
    el('td', {}, paciente.nome),
    el('td', {}, el('code', {}, paciente.cpf_mascarado)),
    el(
      'td',
      {},
      el(
        'span',
        { class: 'selo', dataset: { status: paciente.status } },
        paciente.status === 'ativo' ? 'Ativo' : 'Inativo',
      ),
    ),
    el(
      'td',
      {},
      el(
        'button',
        {
          type: 'button',
          class: 'link link--botao',
          'aria-label': `Abrir ficha de ${paciente.nome}`,
          onclick: () => abrirDaLista(paciente.id),
        },
        'Abrir',
      ),
    ),
  );
}

async function carregarLista() {
  if (!pode('listar')) return;
  const status = $('status-lista');
  try {
    const { itens, proximo } = await chamarApi('POST', '/pacientes/lista', { depois: cursorAtual });
    cursorProximo = proximo;
    $('corpo-lista').replaceChildren(...itens.map(linhaDaLista));
    $('lista-anterior').disabled = cursoresAnteriores.length === 0;
    $('lista-proxima').disabled = proximo === null;
    definirStatus(status, itens.length === 0 ? 'Nenhum paciente cadastrado.' : '');
  } catch (erro) {
    definirStatus(status, erro.message, 'error');
  }
}

$('lista-proxima').addEventListener('click', () => {
  cursoresAnteriores.push(cursorAtual);
  cursorAtual = cursorProximo;
  carregarLista();
});

$('lista-anterior').addEventListener('click', () => {
  cursorAtual = cursoresAnteriores.pop() ?? null;
  carregarLista();
});

function abrirFormPaciente(paciente = null) {
  fecharFicha();
  const form = $('form-paciente');
  form.reset();
  form.dataset.id = paciente?.id ?? '';
  $('titulo-form-paciente').textContent = paciente ? 'Editar paciente' : 'Novo paciente';
  $('campo-cpf-paciente').hidden = Boolean(paciente); // CPF é imutável
  if (paciente) {
    $('paciente-nome').value = paciente.nome;
    $('paciente-nascimento').value = paciente.data_nascimento;
    $('paciente-email').value = paciente.email ?? '';
  }
  $('paciente-nascimento').max = new Date().toISOString().slice(0, 10);
  definirStatus($('status-paciente'), '');
  form.hidden = false;
  form.querySelector('input:not([hidden])')?.focus();
}

$('novo-paciente').addEventListener('click', () => abrirFormPaciente());
$('editar').addEventListener('click', () => abrirFormPaciente(pacienteAtual));
$('cancelar-paciente').addEventListener('click', () => {
  $('form-paciente').hidden = true;
});

$('form-paciente').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const form = evento.currentTarget;
  const status = $('status-paciente');
  const id = form.dataset.id;
  const dados = {
    nome: $('paciente-nome').value.trim(),
    data_nascimento: $('paciente-nascimento').value,
    email: $('paciente-email').value.trim() || null,
  };
  if (!id && !cpfValido($('paciente-cpf').value)) {
    definirStatus(status, 'Informe um CPF válido.', 'error');
    return;
  }
  if (dados.nome.length < 2 || !dados.data_nascimento) {
    definirStatus(status, 'Preencha nome e data de nascimento.', 'error');
    return;
  }
  try {
    const salvo = id
      ? await chamarApi('PATCH', `/pacientes/${encodeURIComponent(id)}`, dados)
      : await chamarApi('POST', '/pacientes', {
          ...dados,
          cpf: somenteDigitos($('paciente-cpf').value),
        });
    form.reset();
    mostrarFicha(salvo);
    definirStatus($('status-ficha'), id ? 'Dados atualizados.' : 'Paciente cadastrado.');
    carregarLista();
  } catch (erro) {
    definirStatus(status, erro.message, 'error');
  }
});

async function alterarStatus(ativar) {
  if (!pacienteAtual) return;
  const id = encodeURIComponent(pacienteAtual.id);
  try {
    if (ativar) await chamarApi('POST', `/pacientes/${id}/reativar`);
    else await chamarApi('DELETE', `/pacientes/${id}`);
    mostrarFicha(await chamarApi('GET', `/pacientes/${id}`));
    definirStatus($('status-ficha'), ativar ? 'Paciente reativado.' : 'Paciente inativado.');
    carregarLista();
  } catch (erro) {
    definirStatus($('status-ficha'), erro.message, 'error');
  }
}

$('inativar').addEventListener('click', () => alterarStatus(false));
$('reativar').addEventListener('click', () => alterarStatus(true));

// --- Códigos de recuperação --------------------------------------------------------------

$('form-codigos').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const campo = $('codigos-totp');
  const status = $('status-codigos');
  const lista = $('lista-codigos');
  if (!/^\d{6}$/.test(campo.value.trim())) {
    definirStatus(status, 'O código tem 6 dígitos.', 'error');
    return;
  }
  try {
    // 401 aqui é código errado, não sessão expirada: sem redirecionar.
    const { codigos_recuperacao: codigos } = await chamar('POST', '/auth/mfa/codigos', {
      codigo: campo.value.trim(),
    });
    renovarPrazo();
    limpar(lista);
    lista.append(...codigos.map((codigo) => el('li', {}, el('code', {}, codigo))));
    lista.hidden = false;
    definirStatus(status, 'Novos códigos gerados. Guarde-os agora: não serão mostrados de novo.');
  } catch (erro) {
    definirStatus(status, erro instanceof ErroApi ? erro.message : 'Erro inesperado.', 'error');
  } finally {
    campo.value = '';
  }
});

// --- Início ------------------------------------------------------------------------------

function avisoDeCodigos() {
  const restantes = new URLSearchParams(window.location.search).get('codigos');
  window.history.replaceState(null, '', '/painel');
  if (restantes === null || !/^\d+$/.test(restantes)) return;
  const aviso = $('aviso');
  aviso.textContent =
    `Você entrou com um código de recuperação. Restam ${restantes}. ` +
    'Gere novos códigos em "Minha conta".';
  aviso.hidden = false;
}

async function iniciar() {
  let sessao;
  try {
    sessao = await api('GET', '/auth/sessao');
  } catch {
    return; // 401 já redirecionou
  }
  renovarPrazo(sessao.expira_em);
  cronometro = setInterval(tick, 1000);
  tick();
  $('usuario-logado').textContent = sessao.nome ?? '';

  if (sessao.troca_senha_obrigatoria) {
    montarFormSenha(document.querySelector('#secao-troca [data-form="senha"]'), 1, () =>
      window.location.reload(),
    );
    abrir('secao-troca');
    return;
  }

  permissoes = new Set(sessao.permissoes);
  montarFormSenha(document.querySelector('#secao-conta [data-form="senha"]'), 2);
  $('menu').hidden = false;
  $('form-busca').hidden = !pode('ler');
  $('novo-paciente').hidden = !pode('criar');
  const temPacientes = pode('ler') || pode('criar');
  const temLogs = permissoes.has('log:ler');
  const temUsuarios = permissoes.has('usuario:ler');
  $('sem-permissao').hidden = temPacientes;
  $('lista-pacientes').hidden = !pode('listar');
  $('menu-pacientes').hidden = !temPacientes && temLogs;
  $('menu-auditoria').hidden = !temLogs;
  $('menu-usuarios').hidden = !temUsuarios;
  if (temUsuarios) {
    aoAbrir['secao-usuarios'] = criarUsuarios(chamarApi, permissoes).abrir;
  }
  if (temLogs) aoAbrir['secao-auditoria'] = criarAuditoria(chamarApi).abrir;
  avisoDeCodigos();
  carregarLista();
  abrir(temPacientes || !temLogs ? 'secao-pacientes' : 'secao-auditoria');
}

iniciar();
