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
    // HTTP em localhost: o Chromium trata localhost como contexto seguro, então os cookies
    // Secure/__Host- funcionam como em produção (onde o TLS termina na borda, ADR-0029).
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
