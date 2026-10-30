// Cliente da API (mesma origem, via /api). Nada é guardado em localStorage/sessionStorage.

export const MENSAGENS = {
  rede: 'Não foi possível falar com o servidor. Verifique sua conexão.',
  indisponivel: 'Serviço indisponível. Tente novamente em instantes.',
  invalido: 'Verifique os dados informados.',
  negado: 'Você não tem permissão para esta ação.',
  generico: 'Não foi possível concluir. Tente novamente.',
};

export function mensagemDeErro(status, dados) {
  const detalhe = typeof dados?.detail === 'string' ? dados.detail : null;
  if (status === 0) return MENSAGENS.rede;
  if (status === 403 && !detalhe) return MENSAGENS.negado;
  if (status === 422) return MENSAGENS.invalido;
  if (status >= 500) return MENSAGENS.indisponivel;
  return detalhe ?? MENSAGENS.generico;
}

export class ErroApi extends Error {
  constructor(status, dados) {
    super(mensagemDeErro(status, dados));
    this.status = status;
    this.dados = dados;
  }
}

let aoExpirar = null;
// Token CSRF da sessão (ADR-0013): só em memória, vem de GET /auth/sessao.
let tokenCsrf = null;

export function cabecalhos(metodo, temCorpo, csrf) {
  const headers = temCorpo ? { 'Content-Type': 'application/json' } : {};
  if (metodo !== 'GET' && csrf) headers['X-CSRF-Token'] = csrf;
  return headers;
}

/** Define o que fazer quando a sessão cai (401 em rota protegida). */
export function quandoSessaoExpirar(callback) {
  aoExpirar = callback;
}

/**
 * Chama a API. Lança ErroApi em qualquer status >= 400.
 * `sessao: true` (padrão em rotas protegidas) aciona quandoSessaoExpirar num 401.
 */
export async function chamar(metodo, caminho, corpo, { sessao = false } = {}) {
  let resposta;
  try {
    resposta = await fetch(`/api${caminho}`, {
      method: metodo,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: cabecalhos(metodo, corpo !== undefined, tokenCsrf),
      body: corpo === undefined ? undefined : JSON.stringify(corpo),
    });
  } catch {
    throw new ErroApi(0, null);
  }
  const tipo = resposta.headers.get('content-type') ?? '';
  const dados = tipo.includes('application/json') ? await resposta.json() : null;
  if (resposta.status === 401 && sessao && aoExpirar) aoExpirar();
  if (!resposta.ok) throw new ErroApi(resposta.status, dados);
  if (typeof dados?.csrf_token === 'string') tokenCsrf = dados.csrf_token;
  return dados;
}
