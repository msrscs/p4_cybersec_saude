import assert from 'node:assert/strict';
import http from 'node:http';
import { after, before, beforeEach, describe, it } from 'node:test';

import { createApp } from '../src/app.js';
import { ipDoCliente, reescreverCookie } from '../src/proxy.js';

const UUID = '6f1c2a8e-1f0b-4c55-9d1e-2b4b9b6b7c11';

function ouvir(servidor) {
  return new Promise((resolve) => {
    servidor.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${servidor.address().port}`));
  });
}

describe('repasse /api para o backend', () => {
  let backend;
  let frontend;
  let baseUrl;
  let recebido;
  let resposta;

  before(async () => {
    // Backend falso: registra o que chegou e devolve a resposta configurada no teste.
    backend = http.createServer((req, res) => {
      const partes = [];
      req.on('data', (p) => partes.push(p));
      req.on('end', () => {
        recebido = {
          metodo: req.method,
          url: req.url,
          headers: req.headers,
          corpo: Buffer.concat(partes).toString(),
        };
        if (resposta.atraso) return setTimeout(() => res.end('{}'), resposta.atraso);
        res.writeHead(resposta.status, resposta.headers);
        res.end(resposta.corpo);
      });
    });
    const apiUrl = await ouvir(backend);
    frontend = createApp({ apiUrl, apiTimeoutMs: 300 }).listen(0, '127.0.0.1');
    await new Promise((resolve) => frontend.once('listening', resolve));
    baseUrl = `http://127.0.0.1:${frontend.address().port}`;
  });

  after(async () => {
    await new Promise((resolve) => frontend.close(resolve));
    backend.closeAllConnections();
    await new Promise((resolve) => backend.close(resolve));
  });

  beforeEach(() => {
    recebido = null;
    resposta = {
      status: 200,
      headers: { 'content-type': 'application/json', 'x-request-id': 'abc', server: 'uvicorn' },
      corpo: '{"ok":true}',
    };
  });

  it('repassa método, caminho, corpo JSON e cookies', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', cookie: '__Host-sessao=abc', origin: baseUrl },
      body: '{"cpf":"1"}',
    });
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { ok: true });
    assert.equal(recebido.metodo, 'POST');
    assert.equal(recebido.url, '/auth/login');
    assert.equal(recebido.corpo, '{"cpf":"1"}');
    assert.equal(recebido.headers.cookie, '__Host-sessao=abc');
    assert.equal(res.headers.get('x-request-id'), 'abc');
    assert.equal(res.headers.get('server'), null); // headers do backend não vazam
  });

  it('descarta headers do cliente e sobrescreve X-Forwarded-For com o IP real', async () => {
    await fetch(`${baseUrl}/api/auth/sessao`, {
      headers: { 'x-forwarded-for': '1.2.3.4', authorization: 'Bearer x', 'x-extra': 'y' },
    });
    assert.equal(recebido.headers['x-forwarded-for'], '127.0.0.1');
    assert.equal(recebido.headers.authorization, undefined);
    assert.equal(recebido.headers['x-extra'], undefined);
  });

  it('descarta a query string', async () => {
    await fetch(`${baseUrl}/api/auth/sessao?cpf=12345678909`);
    assert.equal(recebido.url, '/auth/sessao');
  });

  for (const [metodo, caminho] of [
    ['GET', `/pacientes/${UUID}`],
    ['PATCH', `/pacientes/${UUID}`],
    ['DELETE', `/pacientes/${UUID}`],
    ['POST', `/pacientes/${UUID}/reativar`],
    ['POST', '/pacientes/busca'],
    ['POST', '/pacientes/lista'],
    ['POST', '/logs/consulta'],
    ['GET', '/logs/acoes'],
    ['GET', '/logs/integridade'],
    ['POST', '/tipos-unidade/lista'],
    ['POST', '/tipos-unidade'],
    ['GET', '/tipos-unidade/opcoes'],
    ['PATCH', '/tipos-unidade/4'],
    ['DELETE', '/tipos-unidade/4'],
    ['POST', '/tipos-unidade/4/reativar'],
    ['GET', '/servicos/opcoes'],
    ['POST', '/ocis'],
    ['POST', '/ocis/lista'],
    ['GET', '/ocis/opcoes'],
    ['GET', '/ocis/opcoes/tipos/3/cids'],
    ['GET', `/ocis/opcoes/cids/${'a'.repeat(64)}/unidades`],
    ['GET', '/ocis/opcoes/unidades/3/servicos/4/dias'],
    ['GET', '/ocis/opcoes/unidades/3/servicos/4/dias/2026-11-05/horarios'],
    ['POST', `/ocis/${UUID}/navegacoes/12/remarcar`],
    ['POST', '/agendas/lista'],
    ['POST', '/agendas'],
    ['PATCH', '/agendas/2'],
    ['DELETE', '/agendas/2'],
    ['POST', '/agendas/2/reativar'],
    ['GET', `/ocis/${UUID}`],
    ['PATCH', `/ocis/${UUID}`],
    ['POST', `/ocis/${UUID}/concluir`],
    ['POST', `/ocis/${UUID}/cancelar`],
    ['POST', `/ocis/${UUID}/navegacoes`],
    ['PATCH', `/ocis/${UUID}/navegacoes/12`],
    ['POST', '/cids/opcoes'],
    ['POST', '/tipos-oci/lista'],
    ['POST', '/tipos-oci'],
    ['PATCH', '/tipos-oci/2'],
    ['DELETE', '/tipos-oci/2'],
    ['POST', '/tipos-oci/2/reativar'],
    ['POST', '/unidades/lista'],
    ['POST', '/unidades'],
    ['GET', '/unidades/opcoes'],
    ['PATCH', '/unidades/12'],
    ['DELETE', '/servicos/3'],
    ['POST', '/servicos/3/reativar'],
    ['POST', '/cids/lista'],
    ['PATCH', `/cids/${'a'.repeat(64)}`],
    ['POST', `/cids/${'a'.repeat(64)}/reativar`],
    ['POST', '/usuarios/lista'],
    ['GET', '/usuarios/grupos'],
    ['POST', '/usuarios'],
    ['GET', `/usuarios/${UUID}`],
    ['PATCH', `/usuarios/${UUID}`],
    ['DELETE', `/usuarios/${UUID}`],
    ['POST', `/usuarios/${UUID}/reativar`],
    ['POST', `/usuarios/${UUID}/resetar`],
    ['POST', `/usuarios/${UUID}/grupos`],
    ['POST', '/auth/mfa/verificar'],
  ]) {
    it(`permite ${metodo} ${caminho}`, async () => {
      const res = await fetch(`${baseUrl}/api${caminho}`, {
        method: metodo,
        headers: { origin: baseUrl },
      });
      assert.equal(res.status, 200);
      assert.equal(recebido.url, caminho);
    });
  }

  for (const caminho of [
    '/docs',
    '/openapi.json',
    '/health',
    '/pacientes/1',
    '/pacientes/..%2fauth%2flogin',
    '/pacientes/%2e%2e/docs',
    '/auth/mfa/qualquer',
    '/logs',
    '/logs/qualquer',
    '/usuarios/1',
    '/usuarios/qualquer',
    '/tipos-unidade/0',
    '/ocis/1',
    `/ocis/${UUID}/qualquer`,
    `/ocis/${UUID}/navegacoes/abc`,
    '/ocis/opcoes/tipos/abc/cids',
    '/ocis/opcoes/unidades/3/servicos',
    '/ocis/opcoes/unidades/3/servicos/4/dias/ontem/horarios',
    '/ocis/opcoes/cids/abc/unidades',
    '/agendas/0',
    '/tipos-oci/0',
    '/tipos-oci/abc',
    '/tipos-unidade/abc',
    '/unidades/0',
    '/unidades/abc',
    '/unidades/1/resetar',
    '/cids/abc',
    `/cids/${'A'.repeat(64)}`,
    `/pacientes/${UUID.toUpperCase()}`,
  ]) {
    it(`recusa rota fora da lista: ${caminho}`, async () => {
      const res = await fetch(`${baseUrl}/api${caminho}`);
      assert.equal(res.status, 404);
      assert.equal(recebido, null);
    });
  }

  it('recusa métodos não previstos', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, { method: 'PUT' });
    assert.equal(res.status, 404);
    assert.equal(recebido, null);
  });

  it('recusa corpo que não é JSON', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded', origin: baseUrl },
      body: 'cpf=1',
    });
    assert.equal(res.status, 415);
    assert.equal(recebido, null);
  });

  it('recusa corpo acima do limite', async () => {
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json', origin: baseUrl },
      body: JSON.stringify({ x: 'a'.repeat(70 * 1024) }),
    });
    assert.equal(res.status, 413);
    assert.deepEqual(await res.json(), { detail: 'Requisição grande demais.' });
    assert.equal(recebido, null);
  });

  it('reescreve o Path do cookie de pré-autenticação e mantém o de sessão', async () => {
    resposta.headers['set-cookie'] = [
      'pre_auth=t; HttpOnly; Max-Age=300; Path=/auth/mfa; SameSite=strict; Secure',
      '__Host-sessao=s; HttpOnly; Path=/; SameSite=strict; Secure',
    ];
    const res = await fetch(`${baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { origin: baseUrl },
    });
    assert.deepEqual(res.headers.getSetCookie(), [
      'pre_auth=t; HttpOnly; Max-Age=300; Path=/api/auth/mfa; SameSite=strict; Secure',
      '__Host-sessao=s; HttpOnly; Path=/; SameSite=strict; Secure',
    ]);
  });

  for (const [nome, headers] of [
    ['sem Origin nem Sec-Fetch-Site', {}],
    ['Origin de outro site', { origin: 'https://evil.example' }],
    ['Origin malformado', { origin: 'null' }],
    ['Sec-Fetch-Site cross-site', { 'sec-fetch-site': 'cross-site' }],
    ['Sec-Fetch-Site same-site', { 'sec-fetch-site': 'same-site' }],
  ]) {
    it(`CSRF: recusa POST com ${nome} sem chegar ao backend`, async () => {
      const res = await fetch(`${baseUrl}/api/auth/login`, { method: 'POST', headers });
      assert.equal(res.status, 403);
      assert.deepEqual(await res.json(), { detail: 'Requisição recusada.' });
      assert.equal(recebido, null);
    });
  }

  it('CSRF: aceita Sec-Fetch-Site same-origin sem Origin', async () => {
    const res = await fetch(`${baseUrl}/api/auth/logout`, {
      method: 'POST',
      headers: { 'sec-fetch-site': 'same-origin' },
    });
    assert.equal(res.status, 200);
  });

  it('CSRF: Sec-Fetch-Site same-origin não salva Origin de outro site', async () => {
    const res = await fetch(`${baseUrl}/api/auth/logout`, {
      method: 'POST',
      headers: { 'sec-fetch-site': 'same-origin', origin: 'https://evil.example' },
    });
    assert.equal(res.status, 403);
  });

  it('repassa X-CSRF-Token ao backend e Retry-After ao navegador', async () => {
    resposta = {
      status: 429,
      headers: { 'content-type': 'application/json', 'retry-after': '42' },
      corpo: '{"detail":"x"}',
    };
    const res = await fetch(`${baseUrl}/api/pacientes`, {
      method: 'POST',
      headers: { origin: baseUrl, 'x-csrf-token': 'tok' },
    });
    assert.equal(recebido.headers['x-csrf-token'], 'tok');
    assert.equal(res.status, 429);
    assert.equal(res.headers.get('retry-after'), '42');
  });

  it('respostas sem Cache-Control ganham no-store', async () => {
    const res = await fetch(`${baseUrl}/api/auth/sessao`);
    assert.equal(res.headers.get('cache-control'), 'no-store');
  });

  it('repassa status de erro do backend sem alterar', async () => {
    resposta = {
      status: 401,
      headers: { 'content-type': 'application/json' },
      corpo: '{"detail":"x"}',
    };
    const res = await fetch(`${baseUrl}/api/auth/sessao`);
    assert.equal(res.status, 401);
    assert.deepEqual(await res.json(), { detail: 'x' });
  });

  it('não segue redirecionamentos do backend', async () => {
    resposta = { status: 302, headers: { location: 'http://evil.example/' }, corpo: '' };
    const res = await fetch(`${baseUrl}/api/auth/sessao`, { redirect: 'manual' });
    assert.equal(res.status, 302);
    assert.equal(res.headers.get('location'), null);
  });

  it('backend lento: 504 genérico', async () => {
    resposta.atraso = 1000;
    const res = await fetch(`${baseUrl}/api/auth/sessao`);
    assert.equal(res.status, 504);
    assert.deepEqual(await res.json(), { detail: 'Serviço indisponível. Tente novamente.' });
  });
});

describe('repasse com backend fora do ar', () => {
  it('responde 502 genérico', async () => {
    const app = createApp({ apiUrl: 'http://127.0.0.1:9' }).listen(0, '127.0.0.1');
    await new Promise((resolve) => app.once('listening', resolve));
    try {
      const res = await fetch(`http://127.0.0.1:${app.address().port}/api/auth/sessao`);
      assert.equal(res.status, 502);
      assert.deepEqual(await res.json(), { detail: 'Serviço indisponível. Tente novamente.' });
    } finally {
      await new Promise((resolve) => app.close(resolve));
    }
  });
});

describe('ipDoCliente', () => {
  const req = (ip, xff) => ({
    socket: { remoteAddress: ip },
    headers: xff === undefined ? {} : { 'x-forwarded-for': xff },
  });

  it('sem proxy configurado, vale a conexão', () => {
    assert.equal(ipDoCliente(req('::ffff:10.0.0.9', '1.2.3.4')), '10.0.0.9');
  });

  it('só aceita X-Forwarded-For vindo do proxy configurado', () => {
    assert.equal(ipDoCliente(req('10.0.0.1', '1.2.3.4'), '10.0.0.1'), '1.2.3.4');
    assert.equal(ipDoCliente(req('::ffff:10.0.0.1', '2001:db8::1'), '10.0.0.1'), '2001:db8::1');
    assert.equal(ipDoCliente(req('10.0.0.9', '1.2.3.4'), '10.0.0.1'), '10.0.0.9');
  });

  it('valor inválido do proxy cai no IP da conexão', () => {
    assert.equal(ipDoCliente(req('10.0.0.1', '1.2.3.4, 5.6.7.8'), '10.0.0.1'), '10.0.0.1');
    assert.equal(ipDoCliente(req('10.0.0.1', 'lixo'), '10.0.0.1'), '10.0.0.1');
    assert.equal(ipDoCliente(req('10.0.0.1'), '10.0.0.1'), '10.0.0.1');
  });
});

describe('reescreverCookie', () => {
  it('só altera o Path exato /auth/mfa', () => {
    assert.equal(reescreverCookie('a=1; Path=/auth/mfa'), 'a=1; Path=/api/auth/mfa');
    assert.equal(reescreverCookie('a=1; Path=/auth/mfa/x'), 'a=1; Path=/auth/mfa/x');
    assert.equal(reescreverCookie('a=1; Path=/'), 'a=1; Path=/');
  });
});
