// Repasse restrito do navegador para a API (ADR-0012). O backend não é exposto: o navegador
// só fala com esta origem, e aqui passa apenas o que a API espera.
import express from 'express';

// Rotas da API que o navegador pode chamar (sem query string: nenhuma rota usa).
const ROTAS = [
  /^\/auth\/(login|sessao|logout|senha)$/,
  /^\/auth\/mfa\/(cadastro|ativar|verificar|recuperar|codigos)$/,
  /^\/pacientes(\/busca)?$/,
  /^\/pacientes\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(\/reativar)?$/,
];
const METODOS = new Set(['GET', 'POST', 'PATCH', 'DELETE']);
const HEADERS_RESPOSTA = ['content-type', 'cache-control', 'x-request-id'];

function erro(res, status, detail) {
  res.status(status).set('Cache-Control', 'no-store').json({ detail });
}

function ipDoCliente(req) {
  // Sempre o IP da conexão TCP: um X-Forwarded-For enviado pelo cliente é descartado.
  return (req.socket.remoteAddress ?? '').replace(/^::ffff:/, '');
}

// O backend define o cookie de pré-autenticação em /auth/mfa; aqui a API mora em /api.
export function reescreverCookie(valor) {
  return valor.replace(/;\s*Path=\/auth\/mfa(?=;|$)/i, '; Path=/api/auth/mfa');
}

export function createApiProxy({ apiUrl, timeoutMs = 10_000, maxBodyBytes = 64 * 1024 }) {
  const router = express.Router();
  const base = new URL(apiUrl);

  router.use((req, res, next) => {
    if (!METODOS.has(req.method) || !ROTAS.some((rota) => rota.test(req.path))) {
      erro(res, 404, 'Não encontrado.');
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
    const headers = { accept: 'application/json', 'x-forwarded-for': ipDoCliente(req) };
    if (req.headers.cookie) headers.cookie = req.headers.cookie;
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
