// Montagem de tela sem innerHTML: só createElement e textContent (CSP com Trusted Types).

export function el(tag, atributos = {}, ...filhos) {
  const elemento = document.createElement(tag);
  for (const [nome, valor] of Object.entries(atributos)) {
    if (valor === false || valor === null || valor === undefined) continue;
    if (nome === 'dataset') Object.assign(elemento.dataset, valor);
    else if (nome.startsWith('on')) elemento.addEventListener(nome.slice(2), valor);
    else elemento.setAttribute(nome, valor === true ? '' : String(valor));
  }
  elemento.append(...filhos.flat().filter((f) => f !== null && f !== undefined && f !== false));
  return elemento;
}

export function limpar(no) {
  no.replaceChildren();
}

export function mostrarSomente(secoes, ativa) {
  for (const secao of secoes) secao.hidden = secao !== ativa;
}

export function definirStatus(no, mensagem, tipo = 'info') {
  no.textContent = mensagem;
  no.dataset.kind = tipo;
}
