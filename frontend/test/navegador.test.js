// Funções puras dos módulos do navegador (sem DOM).
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { MENSAGENS, mensagemDeErro } from '../public/js/lib/api.js';
import { cpfValido, formatarCpf, somenteDigitos } from '../public/js/lib/cpf.js';

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
