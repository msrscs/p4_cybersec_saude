// Teste ponta a ponta no navegador (ADR-0012). O ambiente (banco temporário, API e frontend)
// é montado por: cd backend && uv run --env-file ../.env python -m tests.e2e_ambiente
import { defineConfig, devices } from '@playwright/test';

if (!process.env.E2E_BASE_URL) {
  throw new Error(
    'Rode pelo orquestrador: cd backend && uv run --env-file ../.env python -m tests.e2e_ambiente',
  );
}

export default defineConfig({
  testDir: 'e2e',
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [['list'], ['github']] : 'list',
  timeout: 90_000,
  use: {
    baseURL: process.env.E2E_BASE_URL,
    trace: 'off', // traces guardariam CPF/senha de teste em disco
    screenshot: 'off',
    video: 'off',
    // Confia só no certificado descartável deste teste (pela chave pública). Nunca usar
    // ignoreHTTPSErrors: a verificação de TLS segue valendo para todo o resto.
    launchOptions: { args: [`--ignore-certificate-errors-spki-list=${process.env.E2E_SPKI}`] },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
