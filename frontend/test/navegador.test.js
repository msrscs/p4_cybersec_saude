// Funções puras dos módulos do navegador (sem DOM).
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { cabecalhos, MENSAGENS, mensagemDeErro } from '../public/js/lib/api.js';
import { cpfValido, formatarCpf, somenteDigitos } from '../public/js/lib/cpf.js';
import {
  corpoDaConsulta,
  detalhesDoRegistro,
  periodoValido,
  rotuloDaAcao,
} from '../public/js/lib/logs.js';

describe('auditoria', () => {
  it('filtros vazios não vão na consulta', () => {
    assert.deepEqual(corpoDaConsulta({ de: '', ate: '', acao: '', cpf: '' }), {});
    assert.deepEqual(corpoDaConsulta({}, 42), { antes: 42 });
  });

  it('datas viram o início e o fim do dia local, com fuso', () => {
    const corpo = corpoDaConsulta({ de: '2026-10-01', ate: '2026-10-02' });
    assert.equal(corpo.de, new Date(2026, 9, 1, 0, 0, 0, 0).toISOString());
    assert.equal(corpo.ate, new Date(2026, 9, 2, 23, 59, 59, 999).toISOString());
  });

  it('confere o período', () => {
    assert.equal(periodoValido({ de: '2026-10-02', ate: '2026-10-01' }), false);
    assert.equal(periodoValido({ de: '2026-10-01', ate: '2026-10-01' }), true);
    assert.equal(periodoValido({ de: '2026-10-01', ate: '' }), true);
  });

  it('evento sem rótulo mostra o nome técnico', () => {
    assert.equal(rotuloDaAcao('login_failure'), 'Falha de login');
    assert.equal(rotuloDaAcao('evento_novo'), 'evento_novo');
  });

  it('detalhes juntam metadados e resumo', () => {
    const texto = detalhesDoRegistro({
      seq: 7,
      hash: 'abc',
      request_id: null,
      resumo: { grupo: 'login:60' },
    });
    assert.deepEqual(JSON.parse(texto), {
      seq: 7,
      hash: 'abc',
      request_id: null,
      grupo: 'login:60',
    });
  });
});

describe('cabeçalhos da chamada à API', () => {
  it('envia o token CSRF só em métodos que alteram dados', () => {
    assert.deepEqual(cabecalhos('GET', false, 'tok'), {});
    assert.deepEqual(cabecalhos('POST', false, 'tok'), { 'X-CSRF-Token': 'tok' });
    assert.deepEqual(cabecalhos('PATCH', true, 'tok'), {
      'Content-Type': 'application/json',
      'X-CSRF-Token': 'tok',
    });
  });

  it('antes da sessão completa não há token a enviar', () => {
    assert.deepEqual(cabecalhos('POST', true, null), { 'Content-Type': 'application/json' });
  });
});

describe('cpf', () => {
  it('formata enquanto digita', () => {
    assert.equal(formatarCpf('529'), '529');
    assert.equal(formatarCpf('5299'), '529.9');
    assert.equal(formatarCpf('5299822'), '529.982.2');
    assert.equal(formatarCpf('52998224725'), '529.982.247-25');
    assert.equal(formatarCpf('529.982.247-2599'), '529.982.247-25');
  });

  it('confere os dígitos verificadores', () => {
    assert.equal(cpfValido('529.982.247-25'), true);
    assert.equal(cpfValido('52998224724'), false);
    assert.equal(cpfValido('111.111.111-11'), false);
    assert.equal(cpfValido('123'), false);
  });

  it('extrai só os dígitos', () => {
    assert.equal(somenteDigitos(' 529.982-247 25 '), '52998224725');
  });
});

describe('mensagens de erro', () => {
  it('são genéricas para falhas de rede, validação e servidor', () => {
    assert.equal(mensagemDeErro(0, null), MENSAGENS.rede);
    assert.equal(
      mensagemDeErro(422, { detail: 'Dados inválidos.', campos: ['cpf'] }),
      MENSAGENS.invalido,
    );
    assert.equal(mensagemDeErro(500, { detail: 'Traceback...' }), MENSAGENS.indisponivel);
    assert.equal(mensagemDeErro(403, null), MENSAGENS.negado);
  });

  it('usam o detail genérico que o backend já envia', () => {
    assert.equal(
      mensagemDeErro(401, { detail: 'CPF ou senha inválidos.' }),
      'CPF ou senha inválidos.',
    );
    assert.equal(mensagemDeErro(404, { detail: 1 }), MENSAGENS.generico);
  });
});
