import { createApp } from './app.js';
import { cabecalhoIp, normalizarOrigem, redesConfiaveis } from './proxy.js';

const env = process.env;
const producao = env.NODE_ENV === 'production';
const port = Number.parseInt(env.PORT ?? '3000', 10);
const host = env.HOST ?? '127.0.0.1';
const apiUrl = env.API_URL ?? 'http://127.0.0.1:8000';
// TLS termina na borda (CloudFront + ALB com certificado ACM); entre o ALB e as tasks o tráfego
// fica na VPC, restrito por security groups (RNF-05, ADR-0029). Em produção, essa condição tem
// de ser declarada: sem ela, o processo não sobe, para nunca servir HTTP direto ao navegador.
const tlsNaBorda = env.TLS_NA_BORDA === 'true';

function iniciar() {
  if (producao && !tlsNaBorda) {
    throw new Error('Em produção, defina TLS_NA_BORDA=true (TLS no CloudFront/ALB, ADR-0029).');
  }
  return createApp({
    apiUrl,
    https: tlsNaBorda,
    origemPublica: normalizarOrigem(env.ORIGEM_PUBLICA, { exigirHttps: producao }),
    confianca: {
      redes: redesConfiaveis(env.PROXIES_CONFIAVEIS),
      cabecalho: cabecalhoIp(env.IP_CLIENTE_HEADER),
    },
  });
}

let app;
try {
  app = iniciar();
} catch (err) {
  // Só a mensagem de configuração, escrita por nós: nenhum valor de variável é ecoado.
  console.error(err.message);
  process.exit(1);
}

app.listen(port, host, () => {
  console.log(`Frontend ouvindo em http://${host}:${port}`);
});
