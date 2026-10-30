import { readFileSync } from 'node:fs';
import https from 'node:https';

import { createApp } from './app.js';

const port = Number.parseInt(process.env.PORT ?? '3000', 10);
const host = process.env.HOST ?? '127.0.0.1';
const apiUrl = process.env.API_URL ?? 'http://127.0.0.1:8000';
const proxyConfiavel = process.env.PROXY_CONFIAVEL;
const { TLS_CERT: certificado, TLS_KEY: chave } = process.env;

// TLS em toda comunicação (RNF-05, ADR-0013): sem certificado, só fora de produção.
if (!(certificado && chave) && process.env.NODE_ENV === 'production') {
  console.error('TLS_CERT e TLS_KEY são obrigatórios em produção.');
  process.exit(1);
}

if (certificado && chave) {
  const app = createApp({ apiUrl, proxyConfiavel, https: true });
  const tls = { cert: readFileSync(certificado), key: readFileSync(chave), minVersion: 'TLSv1.2' };
  https.createServer(tls, app).listen(port, host, () => {
    console.log(`Frontend ouvindo em https://${host}:${port}`);
  });
} else {
  createApp({ apiUrl, proxyConfiavel }).listen(port, host, () => {
    console.log(`Frontend ouvindo em http://${host}:${port}`);
  });
}
