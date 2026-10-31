// Funções puras dos módulos do navegador (sem DOM).
import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { cabecalhos, MENSAGENS, mensagemDeErro } from '../public/js/lib/api.js';
import { corpoDaLista, erroDaBusca } from '../public/js/lib/usuarios.js';
import {
  comEncerradas,
  corpoDoDashboard,
  formatarDias,
  formatarPercentual,
  indicadoresDe,
  indiceMaisProximo,
  marcasDoEixo,
  posicoesComRotulo,
  rotuloDoPeriodo,
  segmentosDeEtapas,
  segmentosDePrazo,
  SERIES_DE_ETAPA,
  temDados,
  tituloDoPeriodo,
  totalDaLinha,
} from '../public/js/lib/dashboard.js';
import {
  corpoDaListaDeOcis,
  indicadorDePrazo,
  instanteDe,
  ROTULO_ETAPA,
  ROTULO_OCI,
  rotuloDeDia,
  rotuloDeHorario,
  seloDaSituacao,
  valorDeDataLocal,
} from '../public/js/lib/ocis.js';
import {
  corpoDoFormulario,
  erroDoFormulario,
  formatarTelefone,
  opcoesAtivas,
  opcoesDeUnidade,
  opcoesMultiplas,
  PADRAO_CID,
  resumoDeCodigos,
  rotuloDeCid,
} from '../public/js/lib/cadastros.js';
import { cpfValido, formatarCpf, somenteDigitos } from '../public/js/lib/cpf.js';
import {
  corpoDaConsulta,
  detalhesDoRegistro,
  periodoValido,
  rotuloDaAcao,
} from '../public/js/lib/logs.js';

describe('Dashboard de OCIs', () => {
  const etapas = { agendado: 2, realizado: 6, faltou: 2, cancelado: 1, remarcado: 3 };
  const dados = {
    abertas: { em_aberto: 10, atrasadas: 2, vencem_em_breve: 3 },
    conclusoes: { concluidas: 4, no_prazo: 3, mediana_dias: 12.25 },
    etapas,
    abertas_no_periodo: 1,
    proximas_etapas: 5,
  };

  it('filtro vazio não vai no corpo, e números vão como número', () => {
    assert.deepEqual(corpoDoDashboard({ dias: '90', tipo: '', unidade: '' }), { dias: 90 });
    assert.deepEqual(corpoDoDashboard({ dias: '30', tipo: '2', unidade: '3' }), {
      dias: 30,
      id_tipo_oci: 2,
      id_unidade: 3,
    });
  });

  it('sem base de cálculo mostra traço, nunca 0%', () => {
    assert.equal(formatarPercentual(0, 0), '—');
    assert.equal(formatarPercentual(0, 5), '0%');
    assert.equal(formatarPercentual(2, 3), '67%');
    assert.equal(formatarDias(null), '—');
    assert.equal(formatarDias(1), '1 dia');
    assert.equal(formatarDias(12.25), '12,3 dias');
  });

  it('indicadores calculam as taxas e só atrasada dá alerta', () => {
    const [aberto, atrasadas, noPrazo, mediana, faltas, proximas] = indicadoresDe(dados);
    assert.equal(aberto.valor, '10');
    assert.match(aberto.detalhe, /^1 aberta no período$/);
    assert.equal(atrasadas.valor, '2');
    assert.equal(atrasadas.alerta, true);
    assert.equal(noPrazo.valor, '75%');
    assert.equal(mediana.valor, '12,3 dias');
    assert.equal(faltas.valor, '25%');
    assert.match(faltas.detalhe, /^2 de 8 etapas encerradas$/);
    assert.equal(proximas.valor, '5');
    const semAtraso = indicadoresDe({
      ...dados,
      abertas: { em_aberto: 1, atrasadas: 0, vencem_em_breve: 0 },
    });
    assert.equal(semAtraso[1].alerta, false);
  });

  it('prazo soma o total e usa o mesmo ícone da lista para atrasada', () => {
    const partes = segmentosDePrazo(dados.abertas);
    assert.deepEqual(
      partes.map((p) => p.valor),
      [5, 3, 2],
    );
    assert.equal(partes.at(-1).icone, '▲');
  });

  it('cancelada e remarcada viram uma parte só, sem perder contagem', () => {
    const partes = segmentosDeEtapas(etapas);
    assert.equal(
      partes.reduce((soma, p) => soma + p.valor, 0),
      14,
    );
    assert.equal(partes.at(-1).valor, 4);
    assert.equal(totalDaLinha(comEncerradas(etapas), SERIES_DE_ETAPA), 14);
  });

  it('eixo usa números redondos, inteiros, e cobre o máximo', () => {
    assert.deepEqual(marcasDoEixo(0), [0, 1]);
    assert.deepEqual(marcasDoEixo(1), [0, 1]);
    assert.deepEqual(marcasDoEixo(3), [0, 1, 2, 3]);
    assert.deepEqual(marcasDoEixo(37), [0, 10, 20, 30, 40]);
    for (const maximo of [2, 7, 99, 1234]) {
      const marcas = marcasDoEixo(maximo);
      assert.ok(marcas.at(-1) >= maximo);
      assert.ok(marcas.every(Number.isInteger));
    }
  });

  it('período: semana pelo dia, mês abreviado', () => {
    assert.equal(rotuloDoPeriodo('2026-10-05', 'week'), '05/10');
    assert.equal(tituloDoPeriodo('2026-10-05', 'week'), 'Semana de 05/10');
    assert.equal(rotuloDoPeriodo('2026-01-01', 'month'), 'jan/26');
    assert.equal(tituloDoPeriodo('2026-12-01', 'month'), 'dez/26');
  });

  it('cursor encontra o ponto mais próximo e fica dentro do gráfico', () => {
    assert.equal(indiceMaisProximo(50, 1, 0, 100), 0);
    assert.equal(indiceMaisProximo(49, 3, 0, 100), 1);
    assert.equal(indiceMaisProximo(-20, 3, 0, 100), 0);
    assert.equal(indiceMaisProximo(500, 3, 0, 100), 2);
  });

  it('rótulos do eixo não passam do máximo e mantêm o último período', () => {
    assert.deepEqual(posicoesComRotulo(3, 6), [0, 1, 2]);
    const posicoes = posicoesComRotulo(14, 4);
    assert.ok(posicoes.length <= 4);
    assert.equal(posicoes.at(-1), 13);
  });

  it('tem dados só quando há OCI ou etapa', () => {
    const zerado = {
      abertas: { em_aberto: 0 },
      abertas_no_periodo: 0,
      conclusoes: { concluidas: 0 },
      etapas: { agendado: 0, realizado: 0, faltou: 0, cancelado: 0, remarcado: 0 },
    };
    assert.equal(temDados(zerado), false);
    assert.equal(temDados({ ...zerado, etapas: { ...zerado.etapas, remarcado: 1 } }), true);
    assert.equal(temDados({ ...zerado, abertas: { em_aberto: 1 } }), true);
  });
});

describe('OCIs', () => {
  it('filtro vazio não vai na lista; CPF só com dígitos', () => {
    assert.deepEqual(corpoDaListaDeOcis({}, null), { depois: null });
    assert.deepEqual(
      corpoDaListaDeOcis(
        { status: 'aberta', tipo: '2', unidade: '3', cpf: '529.982.247-25', atrasadas: true },
        'x',
      ),
      {
        depois: 'x',
        status: 'aberta',
        id_tipo_oci: 2,
        id_unidade: 3,
        cpf: '52998224725',
        atrasadas: true,
      },
    );
  });

  it('data local vira instante com fuso', () => {
    assert.equal(instanteDe('2026-11-05T14:30'), new Date(2026, 10, 5, 14, 30).toISOString());
    assert.equal(instanteDe(''), null);
    assert.equal(instanteDe('qualquer'), null);
  });

  it('valor do campo de data é local, sem segundos', () => {
    const instante = new Date(2026, 10, 5, 14, 30, 45).toISOString();
    assert.equal(valorDeDataLocal(instante), '2026-11-05T14:30');
  });

  it('indicador de prazo: cor, ícone e texto', () => {
    const aberta = (dias, atrasada = false) => ({
      status: 'aberta',
      dias_restantes: dias,
      atrasada,
    });
    assert.deepEqual(indicadorDePrazo(aberta(30)), {
      nivel: 'no-prazo',
      icone: '●',
      texto: 'Faltam 30 dias',
    });
    assert.equal(indicadorDePrazo(aberta(8)).nivel, 'no-prazo');
    assert.equal(indicadorDePrazo(aberta(7)).nivel, 'alerta');
    assert.equal(indicadorDePrazo(aberta(1)).texto, 'Falta 1 dia');
    assert.deepEqual(indicadorDePrazo(aberta(0)), {
      nivel: 'alerta',
      icone: '●',
      texto: 'Vence hoje',
    });
    assert.deepEqual(indicadorDePrazo(aberta(-3, true)), {
      nivel: 'atrasada',
      icone: '▲',
      texto: 'Atrasada há 3 dias',
    });
    assert.equal(indicadorDePrazo(aberta(-1, true)).texto, 'Atrasada há 1 dia');
    assert.equal(indicadorDePrazo(aberta(0, true)).texto, 'Atrasada hoje');
    assert.equal(
      indicadorDePrazo({ status: 'concluida', dias_restantes: null, atrasada: false }).nivel,
      'encerrada',
    );
  });

  it('rótulos de dia e horário com vagas', () => {
    assert.equal(rotuloDeDia({ data: '2026-11-05', vagas: 3 }), 'qui 05/11 · 3 vagas');
    assert.equal(rotuloDeDia({ data: '2026-11-08', vagas: 1 }), 'dom 08/11 · 1 vaga');
    assert.equal(rotuloDeHorario({ hora: '09:30', vagas: 2 }), '09:30 · 2 vagas');
  });

  it('rótulos de situação, inclusive valor desconhecido', () => {
    assert.equal(ROTULO_OCI.concluida, 'Concluída');
    assert.equal(ROTULO_ETAPA.faltou, 'Faltou');
    assert.equal(seloDaSituacao('aberta'), 'ativo');
    assert.equal(seloDaSituacao('concluida'), 'pendente');
    assert.equal(seloDaSituacao('cancelada'), 'inativo');
    assert.equal(seloDaSituacao('faltou'), 'inativo');
  });
});

describe('filtros de usuários', () => {
  it('filtro vazio não vai na consulta e a unidade vira número', () => {
    assert.deepEqual(corpoDaLista({}, null), { depois: null });
    assert.deepEqual(corpoDaLista({ busca: '', grupo: '', unidade: '' }, 'x'), { depois: 'x' });
    assert.deepEqual(corpoDaLista({ busca: 'Ana', grupo: 'Gestor', unidade: '3' }, null), {
      depois: null,
      busca: 'Ana',
      grupo: 'Gestor',
      id_unidade: 3,
    });
  });

  it('avisa quando a busca não pode dar certo', () => {
    assert.equal(erroDaBusca(''), null);
    assert.equal(erroDaBusca('Ana'), null);
    assert.equal(erroDaBusca('529.982.247-25'), null);
    assert.equal(erroDaBusca('52998224725'), null);
    assert.equal(erroDaBusca('A'), 'Digite ao menos 2 letras do nome.');
    assert.equal(erroDaBusca('529.982'), 'Para buscar por CPF, informe os 11 dígitos.');
  });
});

describe('cadastros', () => {
  const campos = [
    { nome: 'cid', rotulo: 'Código', soNaCriacao: true, padrao: PADRAO_CID, mensagem: 'inválido' },
    { nome: 'descricao', rotulo: 'Descrição' },
    { nome: 'telefone', rotulo: 'Telefone', opcional: true, vazio: null },
  ];

  it('campo imutável só vai na criação e opcional vazio vira o valor próprio', () => {
    const valores = { cid: 'C50.9', descricao: ' Mama ', telefone: ' ' };
    assert.deepEqual(corpoDoFormulario(campos, valores, false), {
      cid: 'C50.9',
      descricao: 'Mama',
      telefone: null,
    });
    assert.deepEqual(corpoDoFormulario(campos, valores, true), {
      descricao: 'Mama',
      telefone: null,
    });
  });

  it('campo numérico vai como número', () => {
    const numerico = [{ nome: 'id_tipo_unidade', rotulo: 'Tipo', numerico: true }];
    assert.deepEqual(corpoDoFormulario(numerico, { id_tipo_unidade: '3' }, false), {
      id_tipo_unidade: 3,
    });
    assert.equal(erroDoFormulario(numerico, { id_tipo_unidade: '' }, false), 'Preencha: Tipo.');
  });

  it('combobox de tipo mantém visível o tipo atual inativo', () => {
    assert.deepEqual(opcoesAtivas([{ id: 1, nome: 'Hospital' }], 1, 'Hospital', '(inativo)'), [
      { valor: '1', rotulo: 'Hospital' },
    ]);
    assert.deepEqual(opcoesAtivas([], 7, 'Antigo', '(inativo)'), [
      { valor: '7', rotulo: 'Antigo (inativo)' },
    ]);
  });

  it('campo múltiplo vai como lista de números e não é obrigatório', () => {
    const multipla = [{ nome: 'servicos', rotulo: 'Serviços', multipla: true }];
    assert.deepEqual(corpoDoFormulario(multipla, { servicos: ['2', '5'] }, true), {
      servicos: [2, 5],
    });
    assert.deepEqual(corpoDoFormulario(multipla, { servicos: [] }, false), { servicos: [] });
    assert.equal(erroDoFormulario(multipla, { servicos: [] }, false), null);
  });

  it('caixas marcam os vinculados e mantêm o vinculado inativo', () => {
    assert.deepEqual(
      opcoesMultiplas(
        [
          { id: 1, nome: 'A' },
          { id: 2, nome: 'B' },
        ],
        [
          { id: 2, nome: 'B' },
          { id: 9, nome: 'Antigo' },
        ],
        '(inativo)',
      ),
      [
        { valor: '1', rotulo: 'A', marcado: false },
        { valor: '2', rotulo: 'B', marcado: true },
        { valor: '9', rotulo: 'Antigo (inativo)', marcado: true },
      ],
    );
  });

  it('seleção por busca vai como veio e não é obrigatória', () => {
    const campo = [{ nome: 'cids', rotulo: 'CIDs', selecaoPorBusca: true }];
    assert.deepEqual(corpoDoFormulario(campo, { cids: ['abc'] }, true), { cids: ['abc'] });
    assert.equal(erroDoFormulario(campo, { cids: [] }, false), null);
  });

  it('resume códigos longos na coluna da lista', () => {
    assert.equal(resumoDeCodigos([]), '—');
    assert.equal(resumoDeCodigos(['A00', 'A01']), 'A00, A01');
    assert.equal(resumoDeCodigos(['A', 'B', 'C'], 2), 'A, B e mais 1');
  });

  it('rótulo de CID marca o inativo', () => {
    assert.equal(rotuloDeCid({ cid: 'C50', descricao: 'Mama', status: 'ativo' }), 'C50 — Mama');
    assert.equal(
      rotuloDeCid({ cid: 'C50', descricao: 'Mama', status: 'inativo' }),
      'C50 — Mama (inativo)',
    );
  });

  it('confere preenchimento e formato', () => {
    assert.equal(erroDoFormulario(campos, { cid: '', descricao: 'x' }, false), 'Preencha: Código.');
    assert.equal(erroDoFormulario(campos, { cid: 'C5', descricao: 'x' }, false), 'inválido');
    assert.equal(erroDoFormulario(campos, { cid: 'c50.9', descricao: 'x' }, false), null);
    assert.equal(erroDoFormulario(campos, { descricao: 'x' }, true), null);
  });

  it('formata telefone fixo e celular', () => {
    assert.equal(formatarTelefone('8133550000'), '(81) 3355-0000');
    assert.equal(formatarTelefone('81999990000'), '(81) 99999-0000');
    assert.equal(formatarTelefone(null), '—');
  });

  it('combobox mantém visível a unidade atual, mesmo inativa', () => {
    const ativas = [{ id: 1, nome: 'UBS Norte' }];
    assert.deepEqual(opcoesDeUnidade(ativas), [
      { valor: '', rotulo: 'Sem unidade' },
      { valor: '1', rotulo: 'UBS Norte' },
    ]);
    assert.equal(opcoesDeUnidade(ativas, 1, 'UBS Norte').length, 2);
    assert.deepEqual(opcoesDeUnidade(ativas, 9, 'UBS Sul').at(-1), {
      valor: '9',
      rotulo: 'UBS Sul (inativa)',
    });
  });
});

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

  it('detalhes de evento de lista trazem os pacientes exibidos', () => {
    const texto = detalhesDoRegistro({
      seq: 1,
      hash: 'a',
      resumo: { origem: 'lista' },
      pacientes_lista: ['123.456.789-09', 'abc123abc123'],
    });
    assert.deepEqual(JSON.parse(texto).pacientes_exibidos, ['123.456.789-09', 'abc123abc123']);
    assert.equal(
      'pacientes_exibidos' in JSON.parse(detalhesDoRegistro({ pacientes_lista: [] })),
      false,
    );
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
