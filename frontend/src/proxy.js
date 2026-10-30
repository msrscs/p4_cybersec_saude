// Repasse restrito do navegador para a API (ADR-0012). O backend não é exposto: o navegador
// só fala com esta origem, e aqui passa apenas o que a API espera.
import { isIP } from 'node:net';

import express from 'express';

// Rotas da API que o navegador pode chamar (sem query string: nenhuma rota usa).
const ROTAS = [
  /^\/auth\/(login|sessao|logout|senha)$/,
  /^\/auth\/mfa\/(cadastro|ativar|verificar|recuperar|codigos)$/,
  /^\/logs\/(consulta|acoes|integridade)$/,
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

// IP da conexão TCP, salvo se ela vier do proxy de borda configurado (ADR-0013): ele substitui
// o X-Forwarded-For enviado pelo navegador. De qualquer outro, o header é descartado.
export function ipDoCliente(req, proxyConfiavel) {
  const conexao = (req.socket.remoteAddress ?? '').replace(/^::ffff:/, '');
  if (!proxyConfiavel || conexao !== proxyConfiavel) return conexao;
  const informado = String(req.headers['x-forwarded-for'] ?? '').trim();
  return isIP(informado) ? informado : conexao;
}

// CSRF, 1ª camada (ADR-0013): só a própria origem altera dados. Vale também para login e MFA,
// que ainda não têm o token CSRF da sessão. Sem nenhum dos dois headers, não veio de navegador
// atual: recusa, porque o repasse só atende as telas.
export function mesmaOrigem(req) {
  const site = req.headers['sec-fetch-site'];
  const origem = req.headers.origin;
  if (site === undefined && origem === undefined) return false;
  if (site !== undefined && site !== 'same-origin') return false;
  if (origem === undefined) return true;
  try {
    return new URL(origem).host === req.headers.host;
  } catch {
    return false;
  }
}

// O backend define o cookie de pré-autenticação em /auth/mfa; aqui a API mora em /api.
export function reescreverCookie(valor) {
  return valor.replace(/;\s*Path=\/auth\/mfa(?=;|$)/i, '; Path=/api/auth/mfa');
}

export function createApiProxy({
  apiUrl,
  timeoutMs = 10_000,
  maxBodyBytes = 64 * 1024,
  proxyConfiavel = null,
}) {
  const router = express.Router();
  const base = new URL(apiUrl);

  router.use((req, res, next) => {
    if (!METODOS.has(req.method) || !ROTAS.some((rota) => rota.test(req.path))) {
      erro(res, 404, 'Não encontrado.');
      return;
    }
    if (req.method !== 'GET' && !mesmaOrigem(req)) {
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
      'x-forwarded-for': ipDoCliente(req, proxyConfiavel),
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
