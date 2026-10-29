// Login em duas etapas: CPF + senha e depois TOTP (ou cadastro do MFA no 1º acesso).
// Toda validação definitiva acontece no backend; aqui só orientamos o usuário.
import { chamar, ErroApi } from './lib/api.js';
import { cpfValido, formatarCpf, somenteDigitos } from './lib/cpf.js';
import { definirStatus, el, limpar, mostrarSomente } from './lib/dom.js';

const PRE_AUTH_INVALIDA = 'Sessão de login inválida ou expirada. Entre novamente.';
const $ = (id) => document.getElementById(id);
const etapas = [...document.querySelectorAll('.etapa')];

function irPara(id) {
  mostrarSomente(etapas, $(id));
  $(id).querySelector('input, button')?.focus();
}

function voltarAoLogin(mensagem) {
  $('senha').value = '';
  irPara('etapa-login');
  definirStatus($('status-login'), mensagem, 'error');
}

function entrarNoPainel(restantes = null) {
  // Só a contagem vai na URL (não é dado sensível); o painel mostra o aviso.
  window.location.assign(restantes === null ? '/painel' : `/painel?codigos=${restantes}`);
}

// --- Etapa 1: CPF + senha ----------------------------------------------------------------

const cpfInput = $('cpf');
const senhaInput = $('senha');

cpfInput.addEventListener('input', () => {
  cpfInput.value = formatarCpf(cpfInput.value);
  cpfInput.removeAttribute('aria-invalid');
});

$('toggle-senha').addEventListener('click', (evento) => {
  const mostrar = senhaInput.type === 'password';
  senhaInput.type = mostrar ? 'text' : 'password';
  evento.currentTarget.textContent = mostrar ? 'Ocultar' : 'Mostrar';
  evento.currentTarget.setAttribute('aria-pressed', String(mostrar));
});

$('form-login').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const status = $('status-login');
  if (!cpfValido(cpfInput.value)) {
    cpfInput.setAttribute('aria-invalid', 'true');
    definirStatus(status, 'Informe um CPF válido.', 'error');
    cpfInput.focus();
    return;
  }
  if (senhaInput.value.length === 0) {
    definirStatus(status, 'Informe sua senha.', 'error');
    senhaInput.focus();
    return;
  }
  definirStatus(status, 'Verificando…');
  try {
    const { etapa } = await chamar('POST', '/auth/login', {
      cpf: somenteDigitos(cpfInput.value),
      senha: senhaInput.value,
    });
    senhaInput.value = '';
    definirStatus(status, '');
    if (etapa === 'mfa_cadastro') await iniciarCadastro();
    else prepararVerificacao(false);
  } catch (erro) {
    senhaInput.value = '';
    definirStatus(status, erro instanceof ErroApi ? erro.message : 'Erro inesperado.', 'error');
  }
});

// --- Etapa 2a: cadastro do autenticador --------------------------------------------------

async function iniciarCadastro() {
  try {
    const prov = await chamar('POST', '/auth/mfa/cadastro');
    // O SVG vira imagem (data: URL): scripts dentro dele não executam e nada entra no DOM.
    $('qr-imagem').src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(prov.qr_svg)}`;
    $('qr-chave').textContent = prov.chave.replace(/(.{4})/g, '$1 ').trim();
    irPara('etapa-cadastro');
  } catch (erro) {
    voltarAoLogin(erro.status === 401 ? PRE_AUTH_INVALIDA : erro.message);
  }
}

$('form-ativar').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const campo = $('codigo-ativar');
  const status = $('status-ativar');
  if (!/^\d{6}$/.test(campo.value.trim())) {
    definirStatus(status, 'O código tem 6 dígitos.', 'error');
    return;
  }
  try {
    const { codigos_recuperacao: codigos } = await chamar('POST', '/auth/mfa/ativar', {
      codigo: campo.value.trim(),
    });
    campo.value = '';
    $('qr-imagem').removeAttribute('src');
    $('qr-chave').textContent = '';
    mostrarCodigos(codigos);
  } catch (erro) {
    campo.value = '';
    if (erro.dados?.detail === PRE_AUTH_INVALIDA) voltarAoLogin(PRE_AUTH_INVALIDA);
    else definirStatus(status, erro.message, 'error');
  }
});

// --- Etapa 2b: códigos de recuperação ----------------------------------------------------

let codigosAtuais = [];

function mostrarCodigos(codigos) {
  codigosAtuais = codigos;
  const lista = $('lista-codigos');
  limpar(lista);
  lista.append(...codigos.map((codigo) => el('li', {}, el('code', {}, codigo))));
  irPara('etapa-codigos');
}

$('copiar-codigos').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(codigosAtuais.join('\n'));
    definirStatus($('status-codigos'), 'Códigos copiados.');
  } catch {
    definirStatus($('status-codigos'), 'Não foi possível copiar; anote os códigos.', 'error');
  }
});

$('baixar-codigos').addEventListener('click', () => {
  const texto = `CyberSec Saúde - códigos de recuperação (uso único)\n\n${codigosAtuais.join('\n')}\n`;
  const url = URL.createObjectURL(new Blob([texto], { type: 'text/plain;charset=utf-8' }));
  const link = el('a', { href: url, download: 'cybersec-saude-codigos.txt' });
  link.click();
  URL.revokeObjectURL(url);
});

$('guardei-codigos').addEventListener('change', (evento) => {
  $('continuar-codigos').disabled = !evento.currentTarget.checked;
});

$('continuar-codigos').addEventListener('click', () => {
  codigosAtuais = [];
  limpar($('lista-codigos'));
  entrarNoPainel();
});

// --- Etapa 2c: verificação (TOTP ou código de recuperação) -------------------------------

let modoRecuperacao = false;

function prepararVerificacao(recuperacao) {
  modoRecuperacao = recuperacao;
  const campo = $('codigo-verificar');
  campo.value = '';
  campo.maxLength = recuperacao ? 11 : 6;
  campo.inputMode = recuperacao ? 'text' : 'numeric';
  campo.autocomplete = recuperacao ? 'off' : 'one-time-code';
  $('rotulo-verificar').textContent = recuperacao
    ? 'Código de recuperação'
    : 'Código do aplicativo';
  $('texto-verificar').textContent = recuperacao
    ? 'Informe um dos seus códigos de recuperação (ex.: ABCDE-FGHJK). Ele deixará de valer.'
    : 'Informe o código de 6 dígitos do aplicativo autenticador.';
  $('alternar-recuperacao').textContent = recuperacao
    ? 'Usar o código do aplicativo'
    : 'Usar um código de recuperação';
  definirStatus($('status-verificar'), '');
  irPara('etapa-verificar');
}

$('alternar-recuperacao').addEventListener('click', () => prepararVerificacao(!modoRecuperacao));

$('form-verificar').addEventListener('submit', async (evento) => {
  evento.preventDefault();
  const campo = $('codigo-verificar');
  const status = $('status-verificar');
  const codigo = campo.value.trim();
  const formato = modoRecuperacao ? /^[A-Za-z0-9]{5}-?[A-Za-z0-9]{5}$/ : /^\d{6}$/;
  if (!formato.test(codigo)) {
    definirStatus(status, 'Formato de código inválido.', 'error');
    return;
  }
  try {
    const rota = modoRecuperacao ? '/auth/mfa/recuperar' : '/auth/mfa/verificar';
    const resposta = await chamar('POST', rota, { codigo });
    campo.value = '';
    entrarNoPainel(modoRecuperacao ? Number(resposta.codigos_restantes ?? 0) : null);
  } catch (erro) {
    campo.value = '';
    if (erro.dados?.detail === PRE_AUTH_INVALIDA) voltarAoLogin(PRE_AUTH_INVALIDA);
    else definirStatus(status, erro.message, 'error');
  }
});

// --- Início ------------------------------------------------------------------------------

async function iniciar() {
  const motivo = new URLSearchParams(window.location.search).get('motivo');
  if (motivo === 'expirada') {
    definirStatus($('status-login'), 'Sua sessão expirou. Entre novamente.', 'error');
  } else if (motivo === 'saiu') {
    definirStatus($('status-login'), 'Você saiu do sistema.');
  }
  try {
    await chamar('GET', '/auth/sessao');
    entrarNoPainel(); // já autenticado
  } catch {
    // sem sessão: permanece no login
  }
}

iniciar();
