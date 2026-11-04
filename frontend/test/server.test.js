import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { describe, it } from 'node:test';

const SERVIDOR = new URL('../src/server.js', import.meta.url).pathname;

// Só os casos em que o processo não sobe: assim o teste termina sem precisar derrubá-lo.
function iniciar(env) {
  return spawnSync(process.execPath, [SERVIDOR], {
    env: { PATH: process.env.PATH, PORT: '0', ...env },
    encoding: 'utf8',
    timeout: 10_000,
  });
}

describe('inicialização do servidor (ADR-0029)', () => {
  it('em produção, recusa subir sem TLS_NA_BORDA', () => {
    const r = iniciar({ NODE_ENV: 'production' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /TLS_NA_BORDA=true/);
  });

  it('em produção, recusa ORIGEM_PUBLICA sem HTTPS', () => {
    const r = iniciar({
      NODE_ENV: 'production',
      TLS_NA_BORDA: 'true',
      ORIGEM_PUBLICA: 'http://saude.exemplo.gov.br',
    });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /ORIGEM_PUBLICA deve usar https/);
  });

  it('recusa PROXIES_CONFIAVEIS inválido sem ecoar o valor', () => {
    const r = iniciar({ PROXIES_CONFIAVEIS: '0.0.0.0/0' });
    assert.equal(r.status, 1);
    assert.match(r.stderr, /PROXIES_CONFIAVEIS inválido/);
    assert.doesNotMatch(r.stderr, /0\.0\.0\.0/);
  });
});
