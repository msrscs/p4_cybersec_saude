// Repasse restrito do navegador para a API (ADR-0012). O backend não é exposto: o navegador
// só fala com esta origem, e aqui passa apenas o que a API espera.
import { BlockList, isIP } from 'node:net';

import express from 'express';

// Rotas da API que o navegador pode chamar (sem query string: nenhuma rota usa).
const ROTAS = [
  /^\/auth\/(login|sessao|logout|senha)$/,
  /^\/auth\/mfa\/(cadastro|ativar|verificar|recuperar|codigos)$/,
  /^\/logs\/(consulta|acoes|integridade)$/,
  /^\/ocis(\/lista|\/opcoes|\/dashboard)?$/,
  /^\/ocis\/opcoes\/tipos\/[1-9][0-9]{0,9}\/cids$/,
  /^\/ocis\/opcoes\/cids\/[0-9a-f]{64}\/unidades$/,
  /^\/ocis\/opcoes\/unidades\/[1-9][0-9]{0,9}\/servicos\/[1-9][0-9]{0,9}\/dias$/,
  /^\/ocis\/opcoes\/unidades\/[1-9][0-9]{0,9}\/servicos\/[1-9][0-9]{0,9}\/dias\/\d{4}-\d{2}-\d{2}\/horarios$/,
  /^\/ocis\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\/concluir|\/cancelar|\/navegacoes)?$/,
  /^\/ocis\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/navegacoes\/[1-9][0-9]{0,18}(\/remarcar)?$/,
  /^\/(tipos-unidade|unidades|servicos|cids|tipos-oci|agendas)(\/lista)?$/,
  /^\/cids\/opcoes$/,
  /^\/(tipos-unidade|unidades|servicos)\/opcoes$/,
  /^\/(tipos-unidade|unidades|servicos|tipos-oci|agendas)\/[1-9][0-9]{0,9}(\/reativar)?$/,
  /^\/cids\/[0-9a-f]{64}(\/reativar)?$/,
  /^\/usuarios(\/lista|\/grupos)?$/,
  /^\/usuarios\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\/reativar|\/resetar|\/grupos)?$/,
  /^\/pacientes(\/busca|\/lista)?$/,
  /^\/pacientes\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\/reativar)?$/,
];
const METODOS = new Set(['GET', 'POST', 'PATCH', 'DELETE']);
const HEADERS_RESPOSTA = ['content-type', 'cache-control', 'x-request-id', 'retry-after'];
const CABECALHO_CSRF = 'x-csrf-token';

function erro(res, status, detail) {
  res.status(status).set('Cache-Control', 'no-store').json({ detail });
}

// Cabeçalhos que um proxy confiável pode usar para informar o IP do usuário (ADR-0029):
// - x-forwarded-for: um único IP (proxy que substitui o valor enviado pelo navegador);
// - cloudfront-viewer-address: "ip:porta", gerado pelo CloudFront (o navegador não o controla).
const CABECALHOS_IP = new Set(['x-forwarded-for', 'cloudfront-viewer-address']);

// Lista "IP ou CIDR" separada por vírgula, ex.: "10.0.0.0/16,10.1.0.0/16". Valor inválido
// interrompe a inicialização: confiar em quem não devia falsificaria o IP da auditoria.
export function redesConfiaveis(texto) {
  const itens = String(texto ?? '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
  if (itens.length === 0) return null;
  const redes = new BlockList();
  for (const item of itens) {
    const [endereco, prefixo, ...resto] = item.split('/');
    const tipo = isIP(endereco);
    const maximo = tipo === 6 ? 128 : 32;
    const prefixoValido = prefixo === undefined || /^\d{1,3}$/.test(prefixo);
    const bits = prefixo === undefined ? maximo : Number(prefixo);
    // /0 confiaria em qualquer origem: o IP da auditoria passaria a ser escolhido pelo cliente.
    if (!tipo || resto.length || !prefixoValido || bits === 0 || bits > maximo) {
      throw new Error('PROXIES_CONFIAVEIS inválido: use IPs ou CIDRs separados por vírgula.');
    }
    redes.addSubnet(endereco, bits, tipo === 6 ? 'ipv6' : 'ipv4');
  }
  return redes;
}

export function cabecalhoIp(nome = 'x-forwarded-for') {
  const valor = String(nome).trim().toLowerCase();
  if (!CABECALHOS_IP.has(valor)) {
    throw new Error(`IP_CLIENTE_HEADER deve ser um de: ${[...CABECALHOS_IP].join(', ')}.`);
  }
  return valor;
}

function ipInformado(valor, cabecalho) {
  const texto = String(valor ?? '').trim();
  if (cabecalho === 'x-forwarded-for') return isIP(texto) ? texto : null;
  // cloudfront-viewer-address: o que vem depois do último ":" é a porta, também em IPv6.
  const separador = texto.lastIndexOf(':');
  if (separador < 1 || !/^\d{1,5}$/.test(texto.slice(separador + 1))) return null;
  const ip = texto.slice(0, separador);
  return isIP(ip) ? ip : null;
}

// IP da conexão TCP, salvo se ela vier de um proxy confiável (ADR-0013, ADR-0029): então vale o
// IP que ele informa no cabeçalho configurado. De qualquer outro, o cabeçalho é ignorado.
export function ipDoCliente(req, { redes = null, cabecalho = 'x-forwarded-for' } = {}) {
  const conexao = (req.socket.remoteAddress ?? '').replace(/^::ffff:/, '');
  const tipo = isIP(conexao);
  if (!redes || !tipo || !redes.check(conexao, tipo === 6 ? 'ipv6' : 'ipv4')) return conexao;
  return ipInformado(req.headers[cabecalho], cabecalho) ?? conexao;
}

// CSRF, 1ª camada (ADR-0013): só a própria origem altera dados. Vale também para login e MFA,
// que ainda não têm o token CSRF da sessão. Sem nenhum dos dois headers, não veio de navegador
// atual: recusa, porque o repasse só atende as telas. Atrás de CDN/balanceador o Host que chega
// aqui pode não ser o do navegador: com ORIGEM_PUBLICA, o Origin é comparado com ela (ADR-0029).
export function mesmaOrigem(req, origemPublica = null) {
  const site = req.headers['sec-fetch-site'];
  const origem = req.headers.origin;
  if (site === undefined && origem === undefined) return false;
  if (site !== undefined && site !== 'same-origin') return false;
  if (origem === undefined) return true;
  try {
    const url = new URL(origem);
    return origemPublica ? url.origin === origemPublica : url.host === req.headers.host;
  } catch {
    return false;
  }
}

// "https://saude.exemplo.gov.br" -> origem normalizada; caminho, query ou HTTP fora de dev: erro.
export function normalizarOrigem(texto, { exigirHttps = true } = {}) {
  if (!texto) return null;
  let url;
  try {
    url = new URL(texto);
  } catch {
    throw new Error('ORIGEM_PUBLICA inválida.');
  }
  const soOrigem = url.pathname === '/' && !url.search && !url.hash && !url.username;
  if (!soOrigem || !['https:', 'http:'].includes(url.protocol)) {
    throw new Error('ORIGEM_PUBLICA deve ser só esquema + host, ex.: https://saude.exemplo.gov.br');
  }
  if (exigirHttps && url.protocol !== 'https:') {
    throw new Error('ORIGEM_PUBLICA deve usar https.');
  }
  return url.origin;
}

// O backend define o cookie de pré-autenticação em /auth/mfa; aqui a API mora em /api.
export function reescreverCookie(valor) {
  return valor.replace(/;\s*Path=\/auth\/mfa(?=;|$)/i, '; Path=/api/auth/mfa');
}

export function createApiProxy({
  apiUrl,
  timeoutMs = 10_000,
  maxBodyBytes = 64 * 1024,
  confianca = {},
  origemPublica = null,
}) {
  const router = express.Router();
  const base = new URL(apiUrl);

  router.use((req, res, next) => {
    if (!METODOS.has(req.method) || !ROTAS.some((rota) => rota.test(req.path))) {
      erro(res, 404, 'Não encontrado.');
      return;
    }
    if (req.method !== 'GET' && !mesmaOrigem(req, origemPublica)) {
      erro(res, 403, 'Requisição recusada.');
      return;
    }
    const temCorpo =
      Number(req.headers['content-length'] ?? 0) > 0 || 'transfer-encoding' in req.headers;
    if (temCorpo && !req.is('application/json')) {
      erro(res, 415, 'Envie JSON.');
      return;
    }
    next();
  });

  router.use(express.raw({ type: 'application/json', limit: maxBodyBytes }));

  router.use(async (req, res) => {
    const headers = {
      accept: 'application/json',
      'x-forwarded-for': ipDoCliente(req, confianca),
    };
    if (req.headers.cookie) headers.cookie = req.headers.cookie;
    if (req.headers[CABECALHO_CSRF]) headers[CABECALHO_CSRF] = req.headers[CABECALHO_CSRF];
    const corpo = Buffer.isBuffer(req.body) && req.body.length > 0 ? req.body : undefined;
    if (corpo) headers['content-type'] = 'application/json';

    let resposta;
    try {
      resposta = await fetch(new URL(req.path, base), {
        method: req.method,
        headers,
        body: corpo,
        redirect: 'manual',
        signal: AbortSignal.timeout(timeoutMs),
      });
    } catch (err) {
      const tempo = err?.name === 'TimeoutError';
      console.error('Falha ao chamar a API:', err?.name ?? 'Error');
      erro(res, tempo ? 504 : 502, 'Serviço indisponível. Tente novamente.');
      return;
    }

    res.status(resposta.status);
    for (const nome of HEADERS_RESPOSTA) {
      const valor = resposta.headers.get(nome);
      if (valor) res.set(nome, valor);
    }
    if (!resposta.headers.get('cache-control')) res.set('Cache-Control', 'no-store');
    const cookies = resposta.headers.getSetCookie().map(reescreverCookie);
    if (cookies.length) res.set('Set-Cookie', cookies);
    res.send(Buffer.from(await resposta.arrayBuffer()));
  });

  // Corpo grande demais ou JSON malformado no parser: resposta genérica.
  // eslint-disable-next-line no-unused-vars
  router.use((err, _req, res, _next) => {
    if (err?.type === 'entity.too.large') {
      erro(res, 413, 'Requisição grande demais.');
      return;
    }
    erro(res, 400, 'Requisição inválida.');
  });

  return router;
}
