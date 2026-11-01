import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { after, before, describe, it } from 'node:test';

import { createApp } from '../src/app.js';

describe('frontend', () => {
  let server;
  let baseUrl;

  before(async () => {
    server = createApp().listen(0, '127.0.0.1');
    await new Promise((resolve) => server.once('listening', resolve));
    baseUrl = `http://127.0.0.1:${server.address().port}`;
  });

  after(() => new Promise((resolve) => server.close(resolve)));

  it('formulários usam POST: sem o JavaScript, CPF e senha não vão para a URL', () => {
    for (const pagina of ['index.html', 'painel.html']) {
      const html = readFileSync(new URL(`../public/${pagina}`, import.meta.url), 'utf8');
      const formularios = html.match(/<form\b[^>]*>/g);
      assert.ok(formularios.length > 0, pagina);
      for (const formulario of formularios) assert.match(formulario, /method="post"/);
    }
  });

  it('formulários montados pelo JavaScript também usam POST', () => {
    for (const script of ['cadastros.js', 'dashboard.js', 'ocis.js']) {
      const codigo = readFileSync(new URL(`../public/js/${script}`, import.meta.url), 'utf8');
      const formularios = codigo.match(/el\(\s*'form',\s*\{[^}]*\}/g);
      assert.ok(formularios.length > 0, script);
      for (const formulario of formularios) assert.match(formulario, /method: 'post'/);
    }
  });

  it('GET /health retorna ok', async () => {
    const res = await fetch(`${baseUrl}/health`);
    assert.equal(res.status, 200);
    assert.deepEqual(await res.json(), { status: 'ok' });
  });

  it('serve a página inicial com headers de segurança', async () => {
    const res = await fetch(`${baseUrl}/`);
    assert.equal(res.status, 200);
    const csp = res.headers.get('content-security-policy');
    assert.match(csp, /default-src 'self'/);
    assert.match(csp, /script-src 'self'/);
    assert.match(csp, /frame-ancestors 'none'/);
    assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval/);
    assert.match(res.headers.get('strict-transport-security'), /max-age=\d+/);
    assert.equal(res.headers.get('x-content-type-options'), 'nosniff');
    assert.equal(res.headers.get('referrer-policy'), 'no-referrer');
    assert.equal(res.headers.get('x-powered-by'), null);
    assert.equal(res.headers.get('x-frame-options'), 'DENY');
    assert.equal(res.headers.get('cross-origin-opener-policy'), 'same-origin');
    assert.equal(res.headers.get('cross-origin-embedder-policy'), 'require-corp');
    assert.equal(res.headers.get('cross-origin-resource-policy'), 'same-origin');
    assert.equal(res.headers.get('origin-agent-cluster'), '?1');
    assert.match(res.headers.get('permissions-policy'), /camera=\(\).*payment=\(\).*usb=\(\)/);
  });

  it('upgrade-insecure-requests só com HTTPS', async () => {
    assert.doesNotMatch(
      (await fetch(`${baseUrl}/`)).headers.get('content-security-policy'),
      /upgrade-insecure-requests/,
    );
    const seguro = createApp({ https: true }).listen(0, '127.0.0.1');
    await new Promise((resolve) => seguro.once('listening', resolve));
    try {
      const res = await fetch(`http://127.0.0.1:${seguro.address().port}/`);
      assert.match(res.headers.get('content-security-policy'), /upgrade-insecure-requests/);
    } finally {
      await new Promise((resolve) => seguro.close(resolve));
    }
  });

  for (const pagina of ['/', '/painel', '/recuperar']) {
    it(`${pagina} não usa scripts ou estilos inline e não é guardada em cache`, async () => {
      const res = await fetch(`${baseUrl}${pagina}`);
      assert.equal(res.status, 200);
      assert.equal(res.headers.get('cache-control'), 'no-store');
      assert.match(res.headers.get('content-security-policy'), /default-src 'self'/);
      const html = await res.text();
      assert.doesNotMatch(html, /<script(?![^>]*\ssrc=)[^>]*>/);
      assert.doesNotMatch(html, /<style/);
      assert.doesNotMatch(html, /\sstyle=/);
      assert.doesNotMatch(html, /\son[a-z]+=/i);
    });
  }

  it('CSP exige Trusted Types e não permite criar políticas', async () => {
    const csp = (await fetch(`${baseUrl}/`)).headers.get('content-security-policy');
    assert.match(csp, /require-trusted-types-for 'script'/);
    assert.match(csp, /trusted-types 'none'/);
  });

  it('serve o logo otimizado referenciado na página', async () => {
    const html = await (await fetch(`${baseUrl}/`)).text();
    assert.match(html, /\/img\/cybersecsaude-720\.webp/);
    const res = await fetch(`${baseUrl}/img/cybersecsaude-720.webp`);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('content-type'), 'image/webp');
  });

  it('rota inexistente retorna 404 genérico', async () => {
    const res = await fetch(`${baseUrl}/nao-existe`);
    assert.equal(res.status, 404);
    assert.deepEqual(await res.json(), { detail: 'Não encontrado.' });
  });

  it('não serve dotfiles', async () => {
    const res = await fetch(`${baseUrl}/.env`);
    assert.notEqual(res.status, 200);
  });
});
