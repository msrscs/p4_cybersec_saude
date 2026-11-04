// Fluxo completo no navegador real, com a CSP estrita e Trusted Types ativos.
// Qualquer violação de CSP, erro de JavaScript ou alert inesperado reprova o teste.
import { expect, test } from '@playwright/test';

import { passoAtual, totp } from './totp.js';

const CPF = process.env.E2E_CPF;
const SENHA = process.env.E2E_SENHA;

function gerarCpf() {
  const base = Array.from({ length: 9 }, () => Math.floor(Math.random() * 10));
  for (let n = 0; n < 2; n += 1) {
    const soma = base.reduce((acc, d, i) => acc + d * (base.length + 1 - i), 0);
    base.push(soma % 11 < 2 ? 0 : 11 - (soma % 11));
  }
  return base.join('');
}

test.describe.configure({ mode: 'serial' });

let page;
let chave;
let ultimoPasso = -1;
let cpfPaciente;
const problemas = [];

// O backend recusa reusar o mesmo passo TOTP (anti-replay): espera o próximo quando preciso.
async function codigoNovo() {
  while (passoAtual() <= ultimoPasso) await new Promise((r) => setTimeout(r, 500));
  ultimoPasso = passoAtual();
  return totp(chave, ultimoPasso);
}

test.beforeAll(async ({ browser }) => {
  const contexto = await browser.newContext();
  page = await contexto.newPage();
  page.on('pageerror', (erro) => problemas.push(`pageerror: ${erro.message}`));
  page.on('dialog', async (dialogo) => {
    problemas.push(`dialog inesperado: ${dialogo.message()}`);
    await dialogo.dismiss();
  });
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    // Respostas 401/403/404/409 da API são esperadas em alguns passos; o resto é problema.
    if (/Failed to load resource: .*status of (401|403|404|409)/.test(msg.text())) return;
    problemas.push(`console: ${msg.text()}`);
  });
});

test.afterAll(async () => {
  await page?.context().close();
});

test.afterEach(() => {
  expect(problemas, 'sem violações de CSP, erros de JS ou alerts').toEqual([]);
});

test('senha errada mostra erro genérico', async () => {
  await page.goto('/');
  await page.getByLabel('CPF').fill(CPF);
  await page.getByLabel('Senha', { exact: true }).fill('Senha#Errada123');
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.locator('#status-login')).toHaveText('CPF ou senha inválidos.');
  await expect(page.getByLabel('Senha', { exact: true })).toHaveValue('');
});

test('primeiro acesso: cadastro do MFA e códigos de recuperação', async () => {
  await page.getByLabel('CPF').fill(CPF);
  await page.getByLabel('Senha', { exact: true }).fill(SENHA);
  await page.getByRole('button', { name: 'Entrar' }).click();

  await expect(page.getByRole('heading', { name: 'Configure o autenticador' })).toBeVisible();
  const qr = page.locator('#qr-imagem');
  await expect(qr).toHaveAttribute('src', /^data:image\/svg\+xml/);
  // A imagem precisa ter sido decodificada de fato, não só ter o atributo src.
  await expect.poll(() => qr.evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
  chave = (await page.locator('#qr-chave').textContent()).replace(/\s/g, '');

  const cadastro = page.locator('#etapa-cadastro');
  await cadastro.getByLabel('Código do aplicativo').fill('000000');
  await page.getByRole('button', { name: 'Ativar' }).click();
  await expect(page.locator('#status-ativar')).toHaveText('Código inválido.');

  await cadastro.getByLabel('Código do aplicativo').fill(await codigoNovo());
  await page.getByRole('button', { name: 'Ativar' }).click();
  await expect(page.getByRole('heading', { name: /códigos de recuperação/ })).toBeVisible();
  await expect(page.locator('#lista-codigos li')).toHaveCount(10);

  const continuar = page.getByRole('button', { name: 'Continuar' });
  await expect(continuar).toBeDisabled();
  await page.getByLabel('Guardei meus códigos em local seguro.').check();
  await continuar.click();
  await expect(page).toHaveURL(/\/painel$/);
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
  await expect(page.locator('#tempo-sessao')).toHaveText(/Sessão: 1[45]:\d\d/);
});

test('dashboard: é o primeiro item do menu e abre vazio, sem erro', async () => {
  await expect(page.locator('#menu .menu__item').first()).toHaveText('Dashboard');
  await expect(page.locator('#menu-dashboard')).toHaveAttribute('aria-current', 'page');
  await expect(page.locator('#secao-dashboard .form__status')).toHaveText(
    'Nenhuma OCI encontrada com esses filtros.',
  );
  await expect(page.locator('#secao-dashboard .indicador')).toHaveCount(0);
  await page.getByRole('button', { name: 'Pacientes', exact: true }).click();
});

test('paciente: cadastrar, buscar, editar, inativar e reativar', async () => {
  const cpf = gerarCpf();
  cpfPaciente = cpf;
  await page.getByRole('button', { name: 'Novo paciente' }).click();
  await page.locator('#paciente-cpf').fill(cpf);
  await page.getByLabel('Nome completo').fill('Maria das Dores');
  await page.getByLabel('Data de nascimento').fill('1975-03-09');
  await page.getByLabel('E-mail (opcional)').fill('maria@exemplo.com.br');
  await page.getByRole('button', { name: 'Salvar' }).click();

  const ficha = page.locator('#ficha');
  await expect(ficha.getByRole('heading', { name: 'Maria das Dores' })).toBeVisible();
  await expect(page.locator('#status-ficha')).toHaveText('Paciente cadastrado.');
  await expect(page.locator('#ficha-status')).toHaveText('Ativo');
  await page.getByRole('button', { name: 'Fechar' }).click();

  await page.getByLabel('Buscar por CPF').fill(cpf);
  await page.getByRole('button', { name: 'Buscar' }).click();
  await expect(page.locator('#ficha-cpf')).toHaveText(
    `${cpf.slice(0, 3)}.${cpf.slice(3, 6)}.${cpf.slice(6, 9)}-${cpf.slice(9)}`,
  );
  await expect(page.locator('#ficha-nascimento')).toHaveText('09/03/1975');

  await page.getByRole('button', { name: 'Editar' }).click();
  await expect(page.locator('#paciente-cpf')).toBeHidden(); // CPF é imutável
  await page.getByLabel('Nome completo').fill('Maria das Dores Silva');
  await page.getByLabel('E-mail (opcional)').fill('');
  await page.getByRole('button', { name: 'Salvar' }).click();
  await expect(ficha.getByRole('heading', { name: 'Maria das Dores Silva' })).toBeVisible();
  await expect(page.locator('#ficha-email')).toHaveText('—');

  await page.getByRole('button', { name: 'Inativar' }).click();
  await expect(page.locator('#ficha-status')).toHaveText('Inativo');
  await expect(page.getByRole('button', { name: 'Editar' })).toBeHidden();
  await page.getByRole('button', { name: 'Reativar' }).click();
  await expect(page.locator('#ficha-status')).toHaveText('Ativo');

  await page.getByLabel('Buscar por CPF').fill(gerarCpf());
  await page.getByRole('button', { name: 'Buscar' }).click();
  await expect(page.locator('#status-busca')).toHaveText('Paciente não encontrado.');
});

test('lista: mostra o paciente com CPF mascarado e abre a ficha', async () => {
  const linha = page.locator('#corpo-lista tr', { hasText: 'Maria das Dores Silva' });
  await expect(linha).toBeVisible();
  await expect(linha.locator('code')).toHaveText(/^\*\*\*\.\d{3}\.\d{3}-\*\*$/);
  await linha.getByRole('button', { name: /Abrir ficha/ }).click();
  await expect(page.locator('#ficha-nome')).toHaveText('Maria das Dores Silva');
  await expect(page.locator('#ficha-cpf')).toHaveText(/^\d{3}\.\d{3}\.\d{3}-\d{2}$/);
  await page.getByRole('button', { name: 'Fechar' }).click();
});

test('nome com HTML aparece como texto (sem XSS)', async () => {
  const malicioso = '<img src=x onerror=alert(1)>Zé';
  await page.getByRole('button', { name: 'Novo paciente' }).click();
  await page.locator('#paciente-cpf').fill(gerarCpf());
  await page.getByLabel('Nome completo').fill(malicioso);
  await page.getByLabel('Data de nascimento').fill('1990-01-01');
  await page.getByRole('button', { name: 'Salvar' }).click();
  await expect(page.locator('#ficha-nome')).toHaveText(malicioso);
  await expect(page.locator('#ficha img')).toHaveCount(0);
  await expect(page.locator('#corpo-lista tr').first().locator('td').first()).toHaveText(malicioso);
  await expect(page.locator('#corpo-lista img')).toHaveCount(0);
});

test('códigos de recuperação: TOTP errado não derruba a sessão', async () => {
  await page.getByRole('button', { name: 'Minha conta' }).click();
  await page.locator('#codigos-totp').fill('000000');
  await page.getByRole('button', { name: 'Gerar novos códigos' }).click();
  await expect(page.locator('#status-codigos')).toHaveText('Código inválido.');
  await expect(page).toHaveURL(/\/painel$/);
});

test('menu lateral segue a ordem definida', async () => {
  const itens = await page.locator('#menu .menu__item').allTextContents();
  expect(itens.map((item) => item.trim())).toEqual([
    'Dashboard',
    'OCIs',
    'Tipos de OCI',
    'Pacientes',
    'Unidades',
    'Tipos de unidade',
    'Serviços',
    'CID',
    'Agendas',
    'Usuários',
    'Auditoria',
    'Minha conta',
  ]);
});

test('nenhum formulário envia por GET, nem os montados pelo JavaScript', async () => {
  await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  await expect(page.locator('#secao-unidades')).toBeVisible();
  await expect(page.locator('form:not([method="post"])')).toHaveCount(0);
});

test('menu lateral fica à esquerda do conteúdo', async () => {
  const menu = await page.locator('.lateral').boundingBox();
  const conteudo = await page.locator('#conteudo').boundingBox();
  expect(menu.x + menu.width).toBeLessThanOrEqual(conteudo.x);
  await expect(page.locator('.lateral img')).toBeVisible();
  expect(await page.locator('.lateral img').evaluate((img) => img.naturalWidth)).toBeGreaterThan(0);
  await expect(page.locator('#usuario-logado')).toHaveText('Admin E2E');
});

test('auditoria: lista, filtra por evento e por CPF, e mostra detalhes', async () => {
  await page.getByRole('button', { name: 'Auditoria' }).click();
  await expect(page.getByRole('heading', { name: 'Auditoria' })).toBeVisible();
  await expect(page.locator('#integridade-selo')).toHaveText('Sem verificação');
  const linhas = page.locator('#corpo-logs tr.log__linha');
  await expect(linhas.first()).toBeVisible();

  await page.getByLabel('Evento').selectOption({ label: 'Paciente cadastrado' });
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(linhas.first().locator('td').nth(1)).toHaveText('Paciente cadastrado');
  await expect(linhas.filter({ hasNotText: 'Paciente cadastrado' })).toHaveCount(0);

  // CPFs decifrados do cadastro (ADR-0016); o nome do paciente continua fora do log.
  const cpfFormatado = `${CPF.slice(0, 3)}.${CPF.slice(3, 6)}.${CPF.slice(6, 9)}-${CPF.slice(9)}`;
  await expect(linhas.first().locator('td').nth(2)).toHaveText(cpfFormatado);
  await expect(linhas.first().locator('td').nth(3)).toHaveText(/^\d{3}\.\d{3}\.\d{3}-\d{2}$/);
  await expect(page.locator('#corpo-logs')).not.toContainText('Maria das Dores');
  const detalhe = page.locator('#corpo-logs tr.log__linha-detalhe').first();
  await expect(detalhe).toBeHidden();
  await linhas.first().getByRole('button', { name: 'Ver' }).click();
  await expect(detalhe.locator('pre')).toContainText('"seq"');
  const larguraDetalhe = (await detalhe.locator('pre').boundingBox()).width;
  expect(larguraDetalhe).toBeGreaterThan((await linhas.first().boundingBox()).width / 2);
  await linhas.first().getByRole('button', { name: 'Ocultar' }).click();
  await expect(detalhe).toBeHidden();

  // Evento de lista: os pacientes exibidos aparecem, embora o evento não tenha um único paciente.
  await page.getByLabel('Evento').selectOption({ label: 'Acesso a dado sensível' });
  await page.getByRole('button', { name: 'Filtrar' }).click();
  const deLista = linhas.filter({ hasText: /\d+ pacientes \(ver detalhes\)/ }).first();
  await expect(deLista).toBeVisible();
  await deLista.getByRole('button', { name: 'Ver' }).click();
  await expect(deLista.locator('xpath=following-sibling::tr[1]').locator('pre')).toContainText(
    'pacientes_exibidos',
  );
  await page.getByRole('button', { name: 'Limpar filtros' }).click();

  await page.getByLabel('CPF do usuário').fill('111.111.111-11');
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(page.locator('#status-logs')).toHaveText('Informe um CPF válido.');

  await page.getByRole('button', { name: 'Limpar filtros' }).click();
  await page.getByLabel('CPF do usuário').fill(CPF);
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(linhas.first()).toBeVisible();
  await expect(linhas.first().locator('td').nth(1)).toHaveText('Consulta ao log');
  await page.getByRole('button', { name: 'Limpar filtros' }).click();
});

test('cadastros: unidade, serviço e CID, com busca, edição, duplicado e inativação', async () => {
  // Tipo novo pela tela, escolhido depois na combobox da unidade.
  await page.getByRole('button', { name: 'Tipos de unidade' }).click();
  await expect(page.getByRole('heading', { name: 'Tipos de unidade' })).toBeVisible();
  await expect(
    page.locator('#secao-tipos-unidade tbody tr', { hasText: 'Hospital' }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Novo tipo' }).click();
  await page.getByLabel('Nome do tipo').fill('Policlínica');
  await page.getByRole('button', { name: 'Salvar tipo' }).click();
  const tipo = page.locator('#secao-tipos-unidade tbody tr', { hasText: 'Policlínica' });
  await expect(tipo.locator('.selo')).toHaveText('Ativo');

  await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  await page.getByRole('button', { name: 'Nova unidade' }).click();
  await page.getByLabel('Nome da unidade').fill('Poli E2E');
  await page.getByLabel('Tipo da unidade').selectOption({ label: 'Policlínica' });
  await page.getByLabel('Endereço da unidade').fill('Rua Poli, 1');
  await page.getByRole('button', { name: 'Salvar unidade' }).click();
  const poli = page.locator('#secao-unidades tbody tr', { hasText: 'Poli E2E' });
  await expect(poli).toContainText('Policlínica');

  // Tipo em uso não pode ser inativado.
  await page.getByRole('button', { name: 'Tipos de unidade' }).click();
  await tipo.getByRole('button', { name: /^Inativar/ }).click();
  await expect(page.locator('#secao-tipos-unidade > .form__status')).toHaveText(
    'Há unidades ativas deste tipo: mude o tipo delas antes de inativar.',
  );
  await expect(tipo.locator('.selo')).toHaveText('Ativo');

  // Editar: a combobox abre no tipo atual e deixa trocar.
  await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  await poli.getByRole('button', { name: /^Editar/ }).click();
  await expect(page.getByLabel('Tipo da unidade').locator('option:checked')).toHaveText(
    'Policlínica',
  );
  await page.getByLabel('Tipo da unidade').selectOption({ label: 'Clínica' });
  await page.getByRole('button', { name: 'Salvar unidade' }).click();
  await expect(poli).toContainText('Clínica');

  await expect(page.getByRole('heading', { name: 'Unidades de saúde' })).toBeVisible();
  await page.getByRole('button', { name: 'Nova unidade' }).click();
  await page.getByLabel('Nome da unidade').fill('UBS E2E');
  await page.getByLabel('Tipo da unidade').selectOption({ label: 'Hospital' });
  await page.getByLabel('Endereço da unidade').fill('Av. Norte, 100');
  await page.getByLabel('Telefone com DDD (opcional)').fill('(81) 3355-0000');
  await page.getByRole('button', { name: 'Salvar unidade' }).click();
  const unidade = page.locator('#secao-unidades tbody tr', { hasText: 'UBS E2E' });
  await expect(unidade).toContainText('(81) 3355-0000');
  await expect(unidade).toContainText('Hospital');

  // Nome repetido: mensagem do backend, sem fechar o formulário.
  await page.getByRole('button', { name: 'Nova unidade' }).click();
  await page.getByLabel('Nome da unidade').fill('ubs e2e');
  await page.getByLabel('Endereço da unidade').fill('Rua Sul, 1');
  await page.getByRole('button', { name: 'Salvar unidade' }).click();
  await expect(page.locator('#secao-unidades form.ficha .form__status')).toHaveText(
    'Já existe um cadastro com esses dados.',
  );
  await page
    .locator('#secao-unidades form.ficha')
    .getByRole('button', { name: 'Cancelar' })
    .click();

  await page.getByRole('button', { name: 'Serviços', exact: true }).click();
  await page.getByRole('button', { name: 'Novo serviço' }).click();
  await page.getByLabel('Nome do serviço').fill('<b>Consulta</b> Ortopedia');
  await page.getByRole('button', { name: 'Salvar serviço' }).click();
  const servico = page.locator('#secao-servicos tbody tr', { hasText: 'Consulta' });
  await expect(servico.locator('td').first()).toHaveText('<b>Consulta</b> Ortopedia');
  await expect(page.locator('#secao-servicos tbody b')).toHaveCount(0);
  await servico.getByRole('button', { name: /^Inativar/ }).click();
  await expect(servico.locator('.selo')).toHaveText('Inativo');
  await servico.getByRole('button', { name: /^Reativar/ }).click();
  await expect(servico.locator('.selo')).toHaveText('Ativo');

  // Serviços da unidade: marcados na edição, mostrados na lista e protegidos ao inativar.
  await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  await unidade.getByRole('button', { name: /^Editar/ }).click();
  const caixa = page.locator('#secao-unidades').getByLabel('<b>Consulta</b> Ortopedia');
  await expect(caixa).not.toBeChecked();
  await caixa.check();
  await page.getByRole('button', { name: 'Salvar unidade' }).click();
  await expect(unidade).toContainText('<b>Consulta</b> Ortopedia');
  await expect(page.locator('#secao-unidades tbody b')).toHaveCount(0);
  await unidade.getByRole('button', { name: /^Editar/ }).click();
  await expect(caixa).toBeChecked();
  await page
    .locator('#secao-unidades form.ficha')
    .getByRole('button', { name: 'Cancelar' })
    .click();

  await page.getByRole('button', { name: 'Serviços', exact: true }).click();
  await servico.getByRole('button', { name: /^Inativar/ }).click();
  await expect(page.locator('#secao-servicos > .form__status')).toHaveText(
    'Há unidades ativas com este serviço: remova-o delas antes de inativar.',
  );
  await expect(servico.locator('.selo')).toHaveText('Ativo');

  await page.getByRole('button', { name: 'CID', exact: true }).click();
  await page.getByRole('button', { name: 'Novo CID' }).click();
  await page.getByLabel('Código CID').fill('errado');
  await page.getByLabel('Descrição do CID').fill('Neoplasia');
  await page.getByRole('button', { name: 'Salvar CID' }).click();
  await expect(page.locator('#secao-cids form.ficha .form__status')).toHaveText(
    'Código CID inválido. Exemplo: C50.9.',
  );
  await page.getByLabel('Código CID').fill('c50.9');
  await page.getByRole('button', { name: 'Salvar CID' }).click();
  const cid = page.locator('#secao-cids tbody tr', { hasText: 'C50.9' });
  await expect(cid).toContainText('Neoplasia');

  await cid.getByRole('button', { name: /^Editar/ }).click();
  await expect(page.getByLabel('Código CID')).toBeDisabled();
  await page.getByLabel('Descrição do CID').fill('Neoplasia maligna da mama');
  await page.getByRole('button', { name: 'Salvar CID' }).click();
  await expect(cid).toContainText('Neoplasia maligna da mama');

  // Tipo de OCI: o CID é escolhido por busca, e o CID em uso não pode ser inativado.
  await page.getByRole('button', { name: 'Tipos de OCI' }).click();
  await expect(page.getByRole('heading', { name: 'Tipos de OCI' })).toBeVisible();
  await page.getByRole('button', { name: 'Novo tipo de OCI' }).click();
  await page.getByLabel('Nome da OCI').fill('OCI Oncologia');
  await page.getByLabel('Prazo para diagnóstico (dias)').fill('trinta');
  await page.getByRole('button', { name: 'Salvar tipo de OCI' }).click();
  await expect(page.locator('#secao-tipos-oci form.ficha > .form__status')).toHaveText(
    'Informe o prazo em dias, de 1 a 3650.',
  );
  await page.getByLabel('Prazo para diagnóstico (dias)').fill('30');
  await page.getByLabel('Buscar CID por código ou descrição').fill('mama');
  await page.locator('#secao-tipos-oci').getByRole('button', { name: 'Procurar' }).click();
  await page.getByRole('button', { name: 'Incluir C50.9' }).click();
  await expect(page.getByRole('button', { name: 'Remover C50.9' })).toBeVisible();
  await page.getByRole('button', { name: 'Salvar tipo de OCI' }).click();
  const oci = page.locator('#secao-tipos-oci tbody tr', { hasText: 'OCI Oncologia' });
  await expect(oci).toContainText('C50.9');
  await expect(oci).toContainText('30');

  await oci.getByRole('button', { name: /^Editar/ }).click();
  await expect(page.getByRole('button', { name: 'Remover C50.9' })).toBeVisible();
  await page
    .locator('#secao-tipos-oci form.ficha')
    .getByRole('button', { name: 'Cancelar' })
    .click();

  await page.getByRole('button', { name: 'CID', exact: true }).click();
  await cid.getByRole('button', { name: /^Inativar/ }).click();
  await expect(page.locator('#secao-cids > .form__status')).toHaveText(
    'Há tipos de OCI ativos com este CID: remova-o deles antes de inativar.',
  );
  await expect(cid.locator('.selo')).toHaveText('Ativo');

  await page.getByLabel('Buscar em CID').fill('nada-disso');
  await page.locator('#secao-cids').getByRole('button', { name: 'Buscar' }).click();
  await expect(page.locator('#secao-cids tbody tr')).toHaveCount(0);
  await page.getByLabel('Buscar em CID').fill('mama');
  await page.locator('#secao-cids').getByRole('button', { name: 'Buscar' }).click();
  await expect(cid).toBeVisible();
});

test('usuários: cadastrar com senha temporária, grupos, inativar, reativar e resetar', async () => {
  const ficha = page.locator('#ficha-usuario');
  const cpf = gerarCpf();
  await page.getByRole('button', { name: 'Usuários' }).click();
  await expect(page.getByRole('heading', { name: 'Usuários', exact: true })).toBeVisible();
  await expect(page.locator('#corpo-usuarios tr', { hasText: 'Admin E2E' })).toBeVisible();

  // A própria conta não pode ser inativada nem resetada.
  await page.locator('#corpo-usuarios tr', { hasText: 'Admin E2E' }).getByRole('button').click();
  await expect(page.locator('#usuario-nome')).toHaveText('Admin E2E');
  await expect(page.getByRole('button', { name: 'Inativar usuário' })).toBeHidden();
  await expect(page.getByRole('button', { name: 'Resetar acesso' })).toBeHidden();

  await page.getByRole('button', { name: 'Novo usuário' }).click();
  await page.getByLabel('CPF do novo usuário').fill(cpf);
  await page.getByLabel('Nome do usuário').fill('<b>Rita</b> Navegadora');
  await page.getByLabel('E-mail do usuário').fill(`u${cpf}@recife.pe.gov.br`);
  await page.getByLabel('Unidade do usuário').selectOption({ label: 'UBS E2E' });
  await page.locator('#form-usuario-grupos').getByLabel('Navegador').check();
  await page.getByRole('button', { name: 'Salvar usuário' }).click();

  const senha = page.locator('#usuario-senha-valor');
  await expect(senha).toHaveText(/^.{16}$/);
  const temporaria = await senha.textContent();
  await expect(page.locator('#usuario-nome')).toHaveText('<b>Rita</b> Navegadora');
  await expect(page.locator('#usuario-unidade')).toHaveText('UBS E2E');
  await expect(page.locator('#corpo-usuarios b')).toHaveCount(0);
  await page.getByRole('button', { name: 'Já entreguei a senha' }).click();
  await expect(page.locator('#usuario-senha')).toBeHidden();
  await expect(senha).toHaveText('');

  await page.locator('#usuario-grupos').getByLabel('Auditor').check();
  await page.getByRole('button', { name: 'Salvar grupos' }).click();
  await expect(page.locator('#status-usuario')).toHaveText('Grupos atualizados.');
  const linha = page.locator('#corpo-usuarios tr').first();
  await expect(linha.locator('td').nth(2)).toHaveText('UBS E2E');
  await expect(linha.locator('td').nth(3)).toHaveText('Navegador, Auditor');
  await expect(linha.locator('code')).toHaveText(/^\*\*\*\.\d{3}\.\d{3}-\*\*$/);

  await page.getByRole('button', { name: 'Editar usuário' }).click();
  // A combobox abre na unidade atual da pessoa.
  await expect(page.getByLabel('Unidade do usuário').locator('option:checked')).toHaveText(
    'UBS E2E',
  );
  await page.getByLabel('Nome do usuário').fill('Rita Navegadora');
  await page.getByRole('button', { name: 'Salvar usuário' }).click();
  await expect(page.locator('#status-usuario')).toHaveText('Dados atualizados.');

  await page.getByRole('button', { name: 'Inativar usuário' }).click();
  await expect(page.locator('#usuario-status')).toHaveText('Inativo');
  await page.getByRole('button', { name: 'Reativar usuário' }).click();
  await expect(page.locator('#usuario-status')).toHaveText('Ativo');

  await page.getByRole('button', { name: 'Resetar acesso' }).click();
  await page.getByRole('button', { name: 'Desistir' }).click();
  await page.getByRole('button', { name: 'Resetar acesso' }).click();
  await page.getByRole('button', { name: 'Confirmar reset' }).click();
  await expect(senha).toHaveText(/^.{16}$/);
  expect(await senha.textContent()).not.toBe(temporaria);
  await page.getByRole('button', { name: 'Já entreguei a senha' }).click();
  await expect(ficha).toBeVisible();
  await page.getByRole('button', { name: 'Fechar ficha' }).click();

  // Filtros da lista: nome (sem acento nem maiúscula), CPF, grupo e unidade.
  const lista = page.locator('#corpo-usuarios tr');
  const filtrar = () =>
    page.locator('#filtros-usuarios').getByRole('button', { name: 'Filtrar' }).click();
  await page.getByLabel('Buscar por nome ou CPF').fill('rita navegadora');
  await filtrar();
  await expect(lista).toHaveCount(1);
  await expect(lista.first()).toContainText('Rita Navegadora');

  await page.getByLabel('Buscar por nome ou CPF').fill(cpf);
  await filtrar();
  await expect(lista).toHaveCount(1);
  await expect(lista.first()).toContainText('Rita Navegadora');

  await page.getByLabel('Buscar por nome ou CPF').fill('123');
  await filtrar();
  await expect(page.locator('#status-lista-usuarios')).toHaveText(
    'Para buscar por CPF, informe os 11 dígitos.',
  );

  await page.getByLabel('Buscar por nome ou CPF').fill('');
  await page.getByLabel('Filtrar por grupo').selectOption('Auditor');
  await page.getByLabel('Filtrar por unidade').selectOption({ label: 'UBS E2E' });
  await filtrar();
  await expect(lista).toHaveCount(1);
  await page.getByLabel('Filtrar por grupo').selectOption('Gestor');
  await filtrar();
  await expect(lista).toHaveCount(0);
  await expect(page.locator('#status-lista-usuarios')).toHaveText('Nenhum usuário encontrado.');
  await page.locator('#secao-usuarios').getByRole('button', { name: 'Limpar filtros' }).click();
  await expect(page.locator('#corpo-usuarios tr', { hasText: 'Admin E2E' })).toBeVisible();

  // Unidade com usuário ativo não pode ser inativada.
  await page.getByRole('button', { name: 'Unidades', exact: true }).click();
  const unidade = page.locator('#secao-unidades tbody tr', { hasText: 'UBS E2E' });
  await unidade.getByRole('button', { name: /^Inativar/ }).click();
  await expect(page.locator('#secao-unidades > .form__status')).toHaveText(
    'Há usuários ativos nesta unidade: mova-os antes de inativar.',
  );
  await expect(unidade.locator('.selo')).toHaveText('Ativo');
});

test('no celular a página não tem rolagem lateral, em nenhuma seção', async () => {
  const original = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 800 });
  for (const secao of [
    'Dashboard',
    'OCIs',
    'Usuários',
    'Tipos de unidade',
    'Unidades',
    'Serviços',
    'CID',
    'Agendas',
    'Tipos de OCI',
    'Auditoria',
    'Pacientes',
    'Minha conta',
  ]) {
    await page.getByRole('button', { name: secao, exact: true }).click();
    await expect(page.getByRole('button', { name: secao, exact: true })).toHaveAttribute(
      'aria-current',
      'page',
    );
    const largura = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(largura, secao).toBeLessThanOrEqual(390);
  }
  await page.setViewportSize(original);
  await page.getByRole('button', { name: 'Pacientes', exact: true }).click();
});

test('OCI: agenda, marcar por dia e horário, remarcar, prazo, duplicada e concluir', async () => {
  // Preparação: o serviço atende o CID, e a unidade tem agenda amanhã, com 1 vaga por horário.
  await page.getByRole('button', { name: 'Serviços', exact: true }).click();
  const servico = page.locator('#secao-servicos tbody tr', { hasText: 'Consulta' });
  await servico.getByRole('button', { name: /^Editar/ }).click();
  await page.getByLabel('Buscar CID do serviço').fill('C50.9');
  await page.locator('#secao-servicos').getByRole('button', { name: 'Procurar' }).click();
  await page.locator('#secao-servicos').getByRole('button', { name: 'Incluir C50.9' }).click();
  await page.getByRole('button', { name: 'Salvar serviço' }).click();
  await expect(servico).toContainText('C50.9');

  const amanha = (new Date(Date.now() + 86_400_000 - 3 * 3_600_000).getUTCDay() + 6) % 7;
  await page.getByRole('button', { name: 'Agendas', exact: true }).click();
  await page.getByRole('button', { name: 'Nova agenda' }).click();
  await page.getByLabel('Unidade da agenda').selectOption({ label: 'UBS E2E' });
  await page.getByLabel('Serviço da agenda').selectOption({ label: '<b>Consulta</b> Ortopedia' });
  await page.getByLabel('Dia da semana').selectOption(String(amanha));
  await page.getByLabel('Hora inicial').fill('08:00');
  await page.getByLabel('Hora final').fill('09:30');
  await page.getByLabel('Duração do atendimento (minutos)').fill('30');
  await page.getByLabel('Vagas por horário').fill('1');
  await page.getByRole('button', { name: 'Salvar agenda' }).click();
  await expect(page.locator('#secao-agendas tbody tr').first()).toContainText('08:00 às 09:30');

  const secao = page.locator('#secao-ocis');
  await page.getByRole('button', { name: 'OCIs', exact: true }).click();
  await expect(secao.getByRole('heading', { name: 'OCIs', exact: true })).toBeVisible();

  // Só a unidade que atende aparece; o dia mostra as vagas; os horários vêm depois do dia.
  const agendaNova = secao.locator('#agenda-nova');
  async function preencherNova() {
    await secao.getByRole('button', { name: 'Nova OCI' }).click();
    await secao.getByLabel('CPF do paciente da OCI').fill(cpfPaciente);
    await secao.getByLabel('Tipo da nova OCI').selectOption({ label: 'OCI Oncologia' });
    await expect(secao.getByLabel('Unidade da primeira etapa').locator('option')).toHaveCount(2);
  }
  await preencherNova();
  await secao.getByLabel('Unidade da primeira etapa').selectOption({ label: 'UBS E2E' });
  await secao.getByLabel('Serviço da primeira etapa').selectOption({ index: 1 });
  await expect(agendaNova.locator('.vaga--dia').first()).toContainText('3 vagas');
  await expect(agendaNova.locator('.vaga--horario')).toHaveCount(0);
  await agendaNova.locator('.vaga--dia').first().click();
  await expect(agendaNova.locator('.vaga--horario')).toHaveCount(3);
  await expect(agendaNova.locator('.vaga--horario').first()).toHaveText('08:00 · 1 vaga');
  await agendaNova.locator('.vaga--horario').first().click();
  await secao.locator('#form-oci').getByRole('button', { name: 'Abrir OCI' }).click();

  const ficha = page.locator('#ficha-oci');
  await expect(ficha.locator('#oci-paciente')).toHaveText('Maria das Dores Silva');
  await expect(ficha.locator('#oci-situacao')).toHaveText('Aberta');
  await expect(ficha.locator('#oci-cid')).toContainText('C50.9');
  await expect(ficha.locator('#oci-cpf')).toHaveText(/^\*\*\*\.\d{3}\.\d{3}-\*\*$/);

  // A lista mostra quantos dias faltam, com o indicador de prazo.
  const linha = secao.locator('#corpo-ocis tr', { hasText: 'Maria das Dores Silva' });
  await expect(linha).toContainText('OCI Oncologia');
  await expect(linha.locator('code')).toHaveText(/^\*\*\*\.\d{3}\.\d{3}-\*\*$/);
  await expect(linha.locator('.prazo--no-prazo')).toContainText('Faltam 30 dias');

  // A vaga marcada some; encaminhar usa o mesmo caminho.
  const agendaEtapa = ficha.locator('#agenda-etapa');
  await ficha.getByLabel('Unidade do encaminhamento').selectOption({ label: 'UBS E2E' });
  await ficha.getByLabel('Serviço do encaminhamento').selectOption({ index: 1 });
  await expect(agendaEtapa.locator('.vaga--dia').first()).toContainText('2 vagas');
  await agendaEtapa.locator('.vaga--dia').first().click();
  await expect(agendaEtapa.locator('.vaga--horario').first()).toHaveText('08:30 · 1 vaga');
  await agendaEtapa.locator('.vaga--horario').first().click();
  await ficha.getByRole('button', { name: 'Incluir etapa' }).click();
  const etapas = ficha.locator('#oci-etapas tr');
  await expect(etapas).toHaveCount(2);

  // Remarcar: a etapa antiga fica no histórico, e a vaga dela volta a ficar livre.
  await etapas.first().getByRole('button', { name: 'Remarcar' }).click();
  const remarcar = ficha.locator('#agenda-remarcar');
  await ficha.getByLabel('Nova unidade').selectOption({ label: 'UBS E2E' });
  await ficha.getByLabel('Novo serviço').selectOption({ index: 1 });
  await expect(remarcar.locator('.vaga--dia').first()).toContainText('1 vaga');
  await remarcar.locator('.vaga--dia').first().click();
  await expect(remarcar.locator('.vaga--horario').first()).toHaveText('09:00 · 1 vaga');
  await remarcar.locator('.vaga--horario').first().click();
  await ficha.getByRole('button', { name: 'Confirmar remarcação' }).click();
  await expect(etapas).toHaveCount(3);
  await expect(ficha.locator('#oci-etapas')).toContainText('Remarcado');

  const agendada = etapas.filter({ hasText: 'Agendado' }).first();
  await agendada.getByRole('button', { name: 'Realizado' }).click();
  await expect(ficha.locator('#oci-etapas')).toContainText('Realizado');

  // Mesmo paciente e tipo: recusa enquanto houver OCI aberta.
  await preencherNova();
  await secao.getByLabel('Unidade da primeira etapa').selectOption({ label: 'UBS E2E' });
  await secao.getByLabel('Serviço da primeira etapa').selectOption({ index: 1 });
  await agendaNova.locator('.vaga--dia').first().click();
  await agendaNova.locator('.vaga--horario').first().click();
  await secao.locator('#form-oci').getByRole('button', { name: 'Abrir OCI' }).click();
  await expect(secao.locator('#status-form-oci')).toHaveText(
    'Este paciente já tem uma OCI aberta deste tipo.',
  );
  await secao.locator('#form-oci').getByRole('button', { name: 'Cancelar' }).click();

  // Concluir: resultado exibido como texto, sem interpretar HTML; a ficha fica encerrada.
  await expect(ficha).toBeVisible();
  await ficha.getByLabel('Resultado da OCI').fill('<b>Laudo</b> de teste');
  await ficha.getByRole('button', { name: 'Concluir OCI' }).click();
  await expect(ficha.locator('#oci-situacao')).toHaveText('Concluída');
  await expect(ficha.locator('#oci-resultado')).toHaveText('<b>Laudo</b> de teste');
  await expect(ficha.locator('#oci-resultado b')).toHaveCount(0);
  await expect(ficha.getByRole('button', { name: 'Concluir OCI' })).toBeHidden();
  await expect(ficha.getByRole('button', { name: 'Incluir etapa' })).toBeHidden();
  await expect(linha.locator('.prazo--encerrada')).toHaveText(/Encerrada/);

  // Filtro por situação e por CPF.
  await secao.getByLabel('Situação da OCI').selectOption('cancelada');
  await secao.locator('#filtros-ocis').getByRole('button', { name: 'Filtrar' }).click();
  await expect(secao.locator('#corpo-ocis tr')).toHaveCount(0);
  await secao.getByLabel('Situação da OCI').selectOption('concluida');
  await secao.getByLabel('CPF do paciente (filtro)').fill(cpfPaciente);
  await secao.locator('#filtros-ocis').getByRole('button', { name: 'Filtrar' }).click();
  await expect(secao.locator('#corpo-ocis tr')).toHaveCount(1);
  await secao.locator('#filtros-ocis').getByRole('button', { name: 'Limpar filtros' }).click();
  await ficha.getByRole('button', { name: 'Fechar OCI' }).click();
});

test('dashboard: indicadores, gráficos, filtros e dados em tabela, no celular também', async () => {
  await page.getByRole('button', { name: 'Dashboard', exact: true }).click();
  const secao = page.locator('#secao-dashboard');
  await expect(secao.locator('.indicador').first()).toBeVisible();
  await expect(secao.locator('.indicador', { hasText: 'Concluídas no prazo' })).toContainText(
    '100%',
  );
  await expect(secao.locator('.linhas svg .traco')).toHaveCount(2);

  // O tipo tem HTML no nome em outros testes: aqui nada de nome da API vira marcação.
  await expect(secao.locator('.cartao-grafico b')).toHaveCount(0);
  const tipos = secao.locator('.cartao-grafico', { hasText: 'OCIs por tipo' });
  const barra = tipos.locator('.barra').first();
  await barra.focus();
  await expect(secao.locator('.dica-grafico')).toBeVisible();
  await expect(secao.locator('.dica-grafico')).toContainText('Concluída');
  await barra.blur();
  await expect(secao.locator('.dica-grafico')).toBeHidden();

  // Teclado no gráfico de linhas: as setas percorrem os períodos.
  await secao.locator('.linhas').focus();
  await expect(secao.locator('.dica-grafico')).toBeVisible();
  await page.keyboard.press('ArrowLeft');
  await expect(secao.locator('.dica-grafico')).toContainText('Abertas');
  await secao.locator('.linhas').blur();

  await tipos.getByText('Ver dados').click();
  await expect(tipos.locator('table tbody tr').first()).toBeVisible();

  // Só o cabeçalho, sobre o verde, é branco: o nome de cada linha usa a cor do texto, nos dois temas.
  for (const colorScheme of ['light', 'dark']) {
    await page.emulateMedia({ colorScheme });
    const dadoDaLinha = tipos.locator('table tbody td').first();
    const corDoDado = await dadoDaLinha.evaluate((td) => getComputedStyle(td).color);
    await expect(tipos.locator('table tbody th').first()).toHaveCSS('color', corDoDado);
    await expect(tipos.locator('table thead th').first()).toHaveCSS('color', 'rgb(255, 255, 255)');
  }
  await page.emulateMedia({ colorScheme: 'light' });

  // Filtro de unidade tira o gráfico por unidade, que teria uma barra só.
  await expect(secao.locator('.cartao-grafico', { hasText: 'Etapas por unidade' })).toBeVisible();
  await secao.getByLabel('Unidade', { exact: true }).selectOption({ index: 1 });
  await expect(secao.locator('.cartao-grafico', { hasText: 'Etapas por unidade' })).toBeHidden();
  await secao.getByLabel('Unidade', { exact: true }).selectOption({ index: 0 });
  await secao.getByLabel('Período').selectOption('365');
  await expect(secao.locator('.cartao-grafico', { hasText: 'Por mês' })).toBeVisible();

  const original = page.viewportSize();
  await page.setViewportSize({ width: 390, height: 800 });
  await expect(secao.locator('.linhas svg')).toHaveAttribute('width', /^(2|3)\d\d$/);
  const largura = await page.evaluate(() => document.documentElement.scrollWidth);
  expect(largura).toBeLessThanOrEqual(390);
  await page.setViewportSize(original);
});

// O HTTPS do navegador é verificado na borda (CloudFront/ALB, ADR-0029), fora deste ambiente.
test('cookie de sessão protegido e CSRF: sem token a API recusa', async () => {
  const cookies = await page.context().cookies();
  const sessao = cookies.find((c) => c.name === '__Host-sessao');
  expect(sessao).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Strict' });
  const status = await page.evaluate(async () => {
    const r = await fetch('/api/auth/logout', { method: 'POST' });
    return r.status;
  });
  expect(status).toBe(403);
});

test('sair encerra a sessão no servidor', async () => {
  await page.getByRole('button', { name: 'Sair' }).click();
  await expect(page).toHaveURL(/\/\?motivo=saiu$/);
  await expect(page.locator('#status-login')).toHaveText('Você saiu do sistema.');
  await page.goto('/painel');
  await expect(page).toHaveURL(/\/\?motivo=expirada$/);
});

test('novo login pede o código do aplicativo', async () => {
  await page.getByLabel('CPF').fill(CPF);
  await page.getByLabel('Senha', { exact: true }).fill(SENHA);
  await page.getByRole('button', { name: 'Entrar' }).click();
  await expect(page.getByRole('heading', { name: 'Confirme seu acesso' })).toBeVisible();
  await page
    .locator('#etapa-verificar')
    .getByLabel('Código do aplicativo')
    .fill(await codigoNovo());
  await page.getByRole('button', { name: 'Confirmar' }).click();
  await expect(page).toHaveURL(/\/painel$/);
  await expect(page.getByRole('heading', { name: 'Dashboard', exact: true })).toBeVisible();
});
