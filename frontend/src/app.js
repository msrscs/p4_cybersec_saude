import path from 'node:path';
import { fileURLToPath } from 'node:url';

import express from 'express';
import helmet from 'helmet';

import { createApiProxy } from './proxy.js';

const publicDir = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');

export function createApp({
  apiUrl = 'http://127.0.0.1:8000',
  apiTimeoutMs,
  proxyConfiavel,
  https = false,
} = {}) {
  const app = express();
  app.disable('x-powered-by');

  app.use(
    helmet({
      contentSecurityPolicy: {
        useDefaults: false,
        directives: {
          defaultSrc: ["'self'"],
          scriptSrc: ["'self'"],
          styleSrc: ["'self'"],
          imgSrc: ["'self'", 'data:'],
          fontSrc: ["'self'"],
          connectSrc: ["'self'"],
          objectSrc: ["'none'"],
          baseUri: ["'self'"],
          formAction: ["'self'"],
          frameAncestors: ["'none'"],
          // Trusted Types: o navegador recusa atribuir texto a innerHTML e afins (I6).
          requireTrustedTypesFor: ["'script'"],
          trustedTypes: ["'none'"],
          // Só com TLS: em http://localhost (dev) quebraria as chamadas da própria página.
          ...(https ? { upgradeInsecureRequests: [] } : {}),
        },
      },
      strictTransportSecurity: { maxAge: 63072000, includeSubDomains: true, preload: true },
      referrerPolicy: { policy: 'no-referrer' },
      xFrameOptions: { action: 'deny' },
      crossOriginOpenerPolicy: { policy: 'same-origin' },
      crossOriginResourcePolicy: { policy: 'same-origin' },
    }),
  );
  app.use((_req, res, next) => {
    res.setHeader(
      'Permissions-Policy',
      'camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=()',
    );
    next();
  });

  app.get('/health', (_req, res) => {
    res.json({ status: 'ok' });
  });

  app.use('/api', createApiProxy({ apiUrl, timeoutMs: apiTimeoutMs, proxyConfiavel }));

  app.use(
    express.static(publicDir, {
      dotfiles: 'deny',
      index: 'index.html',
      extensions: ['html'], // /painel -> painel.html
      setHeaders: (res, arquivo) => {
        if (arquivo.endsWith('.html')) res.setHeader('Cache-Control', 'no-store');
      },
    }),
  );

  app.use((_req, res) => {
    res.status(404).json({ detail: 'Não encontrado.' });
  });

  // Erro genérico: nunca devolve stack trace nem a mensagem original ao cliente.
  // eslint-disable-next-line no-unused-vars
  app.use((err, _req, res, _next) => {
    console.error('Erro não tratado:', err?.name ?? 'Error');
    res.status(500).json({ detail: 'Erro interno.' });
  });

  return app;
}
