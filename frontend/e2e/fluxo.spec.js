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
  await expect(page.getByRole('heading', { name: 'Pacientes', exact: true })).toBeVisible();
  await expect(page.locator('#tempo-sessao')).toHaveText(/Sessão: 1[45]:\d\d/);
});

test('paciente: cadastrar, buscar, editar, inativar e reativar', async () => {
  const cpf = gerarCpf();
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

test('menu lateral fica à esquerda do conteúdo', async () => {
  const menu = await page.locator('#menu').boundingBox();
  const conteudo = await page.locator('#conteudo').boundingBox();
  expect(menu.x + menu.width).toBeLessThanOrEqual(conteudo.x);
  expect(menu.height).toBeGreaterThan(conteudo.y);
});

test('auditoria: lista, filtra por evento e por CPF, e mostra detalhes', async () => {
  await page.getByRole('button', { name: 'Auditoria' }).click();
  await expect(page.getByRole('heading', { name: 'Auditoria' })).toBeVisible();
  await expect(page.locator('#integridade-selo')).toHaveText('Sem verificação');
  const linhas = page.locator('#corpo-logs tr');
  await expect(linhas.first()).toBeVisible();

  await page.getByLabel('Evento').selectOption({ label: 'Paciente cadastrado' });
  await page.getByRole('button', { name: 'Filtrar' }).click();
  await expect(linhas.first().locator('td').nth(1)).toHaveText('Paciente cadastrado');
  await expect(linhas.filter({ hasNotText: 'Paciente cadastrado' })).toHaveCount(0);

  // Hash truncado na tela: nunca o CPF nem o nome do paciente.
  await expect(linhas.first().locator('code').first()).toHaveText(/^[0-9a-f]{12}$/);
  await expect(page.locator('#corpo-logs')).not.toContainText('Maria das Dores');
  await expect(page.locator('#corpo-logs')).not.toContainText(CPF);
  await linhas.first().getByText('Ver').click();
  await expect(linhas.first().locator('pre')).toContainText('"seq"');

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

test('HTTPS, cookie de sessão protegido e CSRF: sem token a API recusa', async () => {
  expect(new URL(page.url()).protocol).toBe('https:');
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
  await expect(page.getByRole('heading', { name: 'Pacientes', exact: true })).toBeVisible();
});
