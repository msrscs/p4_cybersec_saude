import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import globals from 'globals';

export default [
  { ignores: ['node_modules/', 'coverage/', 'test-results/', 'playwright-report/'] },
  js.configs.recommended,
  {
    files: ['src/**/*.js', 'test/**/*.js', '*.js'],
    languageOptions: { globals: globals.node },
  },
  {
    files: ['public/js/**/*.js'],
    languageOptions: { globals: globals.browser },
    rules: {
      // XSS (I6): a tela é montada só com createElement/textContent.
      'no-restricted-properties': [
        'error',
        { property: 'innerHTML', message: 'Use textContent/createElement.' },
        { property: 'outerHTML', message: 'Use textContent/createElement.' },
        { property: 'insertAdjacentHTML', message: 'Use createElement.' },
        { object: 'document', property: 'write', message: 'Proibido.' },
        { object: 'document', property: 'writeln', message: 'Proibido.' },
        { object: 'localStorage', message: 'Nenhum dado no navegador (ADR-0012).' },
        { object: 'sessionStorage', message: 'Nenhum dado no navegador (ADR-0012).' },
      ],
    },
  },
  {
    files: ['e2e/**/*.js', 'playwright.config.js'],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
  {
    rules: {
      'no-eval': 'error',
      'no-implied-eval': 'error',
      'no-new-func': 'error',
    },
  },
  prettier,
];
