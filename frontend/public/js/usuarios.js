// Tela de usuários (RF-01, ADR-0017). A interface mostra só o que as permissões permitem, mas
// quem autoriza e aplica as proteções (própria conta, último administrador) é o backend.
import { cpfValido, formatarCpf, somenteDigitos } from './lib/cpf.js';
import { definirStatus, el } from './lib/dom.js';

const $ = (id) => document.getElementById(id);
const ROTULO_STATUS = { ativo: 'Ativo', inativo: 'Inativo', bloqueado: 'Bloqueado' };
const simOuNao = (valor) => (valor ? 'Sim' : 'Não');

export function criarUsuarios(chamarApi, permissoes) {
  const pode = (acao) => permissoes.has(`usuario:${acao}`);
  let gruposDisponiveis = null;
  let usuarioAtual = null;
  let cursorAtual = null;
  let cursorProximo = null;
  const cursoresAnteriores = [];

  // --- Grupos (caixas de seleção) --------------------------------------------------------

  function caixasDeGrupo(destino, prefixo, marcados = []) {
    destino.replaceChildren(
      ...gruposDisponiveis.map((grupo, indice) => {
        const id = `${prefixo}-${indice}`;
        return el(
          'label',
          { class: 'grupo', for: id },
          el('input', {
            id,
            type: 'checkbox',
            value: grupo,
            checked: marcados.includes(grupo),
          }),
          grupo,
        );
      }),
    );
  }

  const gruposMarcados = (origem) =>
    [...origem.querySelectorAll('input:checked')].map((caixa) => caixa.value);

  // --- Senha temporária (exibida uma vez) ------------------------------------------------

  function mostrarSenha(senha) {
    $('usuario-senha-valor').textContent = senha;
    definirStatus($('status-senha-usuario'), '');
    $('usuario-senha').hidden = false;
    $('usuario-senha').scrollIntoView();
  }

  function esconderSenha() {
    $('usuario-senha-valor').textContent = '';
    $('usuario-senha').hidden = true;
  }

  $('usuario-senha-copiar').addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText($('usuario-senha-valor').textContent);
      definirStatus($('status-senha-usuario'), 'Senha copiada.');
    } catch {
      definirStatus($('status-senha-usuario'), 'Não foi possível copiar; anote a senha.', 'error');
    }
  });
  $('usuario-senha-fechar').addEventListener('click', esconderSenha);

  // --- Ficha ------------------------------------------------------------------------------

  function mostrarFicha(usuario) {
    usuarioAtual = usuario;
    $('form-usuario').hidden = true;
    $('usuario-confirmar').hidden = true;
    $('usuario-nome').textContent = usuario.nome;
    $('usuario-status').textContent = ROTULO_STATUS[usuario.status] ?? usuario.status;
    $('usuario-status').dataset.status = usuario.status;
    $('usuario-cpf').textContent = usuario.cpf;
    $('usuario-email').textContent = usuario.email;
    $('usuario-unidade').textContent = usuario.id_unidade ?? '—';
    $('usuario-mfa').textContent = simOuNao(usuario.mfa_ativo);
    $('usuario-troca').textContent = simOuNao(usuario.troca_senha_obrigatoria);
    $('usuario-bloqueado').textContent = simOuNao(usuario.bloqueado);
    const ativo = usuario.status === 'ativo';
    $('usuario-editar').hidden = !pode('editar');
    $('usuario-inativar').hidden = !(pode('inativar') && ativo && !usuario.proprio);
    $('usuario-reativar').hidden = !(pode('inativar') && !ativo && !usuario.proprio);
    $('usuario-resetar').hidden = !(pode('resetar') && !usuario.proprio);
    const gerenciaGrupos = pode('grupos');
    caixasDeGrupo($('usuario-grupos'), 'ficha-grupo', usuario.grupos);
    for (const caixa of $('usuario-grupos').querySelectorAll('input')) {
      caixa.disabled = !gerenciaGrupos;
    }
    $('usuario-salvar-grupos').hidden = !gerenciaGrupos;
    definirStatus($('status-usuario'), '');
    $('ficha-usuario').hidden = false;
  }

  function fecharFicha() {
    usuarioAtual = null;
    $('ficha-usuario').hidden = true;
  }

  $('usuario-fechar').addEventListener('click', fecharFicha);

  async function abrirFicha(id) {
    definirStatus($('status-lista-usuarios'), '');
    try {
      mostrarFicha(await chamarApi('GET', `/usuarios/${encodeURIComponent(id)}`));
      $('ficha-usuario').scrollIntoView();
    } catch (erro) {
      definirStatus($('status-lista-usuarios'), erro.message, 'error');
    }
  }

  async function recarregarFicha(mensagem) {
    const id = encodeURIComponent(usuarioAtual.id);
    mostrarFicha(await chamarApi('GET', `/usuarios/${id}`));
    definirStatus($('status-usuario'), mensagem);
    await carregarLista();
  }

  async function alterarStatus(ativar) {
    const id = encodeURIComponent(usuarioAtual.id);
    try {
      if (ativar) await chamarApi('POST', `/usuarios/${id}/reativar`);
      else await chamarApi('DELETE', `/usuarios/${id}`);
      await recarregarFicha(ativar ? 'Usuário reativado.' : 'Usuário inativado.');
    } catch (erro) {
      definirStatus($('status-usuario'), erro.message, 'error');
    }
  }

  $('usuario-inativar').addEventListener('click', () => alterarStatus(false));
  $('usuario-reativar').addEventListener('click', () => alterarStatus(true));

  // O reset derruba as sessões e o MFA do usuário: pede confirmação antes.
  $('usuario-resetar').addEventListener('click', () => {
    $('usuario-confirmar').hidden = false;
  });
  $('usuario-confirmar-nao').addEventListener('click', () => {
    $('usuario-confirmar').hidden = true;
  });
  $('usuario-confirmar-sim').addEventListener('click', async () => {
    const id = encodeURIComponent(usuarioAtual.id);
    try {
      const { senha_temporaria: senha } = await chamarApi('POST', `/usuarios/${id}/resetar`);
      await recarregarFicha('Acesso resetado.');
      mostrarSenha(senha);
    } catch (erro) {
      $('usuario-confirmar').hidden = true;
      definirStatus($('status-usuario'), erro.message, 'error');
    }
  });

  $('usuario-salvar-grupos').addEventListener('click', async () => {
    const id = encodeURIComponent(usuarioAtual.id);
    try {
      mostrarFicha(
        await chamarApi('POST', `/usuarios/${id}/grupos`, {
          grupos: gruposMarcados($('usuario-grupos')),
        }),
      );
      definirStatus($('status-usuario'), 'Grupos atualizados.');
      await carregarLista();
    } catch (erro) {
      caixasDeGrupo($('usuario-grupos'), 'ficha-grupo', usuarioAtual.grupos);
      definirStatus($('status-usuario'), erro.message, 'error');
    }
  });

  // --- Formulário -------------------------------------------------------------------------

  function abrirForm(usuario = null) {
    fecharFicha();
    esconderSenha();
    const form = $('form-usuario');
    form.reset();
    form.dataset.id = usuario?.id ?? '';
    $('titulo-form-usuario').textContent = usuario ? 'Editar usuário' : 'Novo usuário';
    $('campo-cpf-usuario').hidden = Boolean(usuario); // CPF é imutável
    $('campo-grupos-usuario').hidden = Boolean(usuario) || !pode('grupos');
    $('dica-form-usuario').hidden = Boolean(usuario);
    if (usuario) {
      $('form-usuario-nome').value = usuario.nome;
      $('form-usuario-email').value = usuario.email;
      $('form-usuario-unidade').value = usuario.id_unidade ?? '';
    } else {
      caixasDeGrupo($('form-usuario-grupos'), 'form-grupo');
    }
    definirStatus($('status-form-usuario'), '');
    form.hidden = false;
    form.querySelector('input:not([hidden])')?.focus();
  }

  $('novo-usuario').addEventListener('click', () => abrirForm());
  $('usuario-editar').addEventListener('click', () => abrirForm(usuarioAtual));
  $('cancelar-usuario').addEventListener('click', () => {
    $('form-usuario').hidden = true;
  });
  const cpfNovo = $('form-usuario-cpf');
  cpfNovo.addEventListener('input', () => (cpfNovo.value = formatarCpf(cpfNovo.value)));

  $('form-usuario').addEventListener('submit', async (evento) => {
    evento.preventDefault();
    const form = evento.currentTarget;
    const status = $('status-form-usuario');
    const id = form.dataset.id;
    const unidade = $('form-usuario-unidade').value.trim();
    const dados = {
      nome: $('form-usuario-nome').value.trim(),
      email: $('form-usuario-email').value.trim(),
      id_unidade: unidade ? Number(unidade) : null,
    };
    if (!id && !cpfValido(cpfNovo.value)) {
      definirStatus(status, 'Informe um CPF válido.', 'error');
      return;
    }
    if (dados.nome.length < 2 || !dados.email) {
      definirStatus(status, 'Preencha nome e e-mail.', 'error');
      return;
    }
    try {
      if (id) {
        const salvo = await chamarApi('PATCH', `/usuarios/${encodeURIComponent(id)}`, dados);
        form.reset();
        mostrarFicha(salvo);
        definirStatus($('status-usuario'), 'Dados atualizados.');
      } else {
        const { usuario, senha_temporaria: senha } = await chamarApi('POST', '/usuarios', {
          ...dados,
          cpf: somenteDigitos(cpfNovo.value),
          grupos: pode('grupos') ? gruposMarcados($('form-usuario-grupos')) : [],
        });
        form.reset();
        mostrarFicha(usuario);
        definirStatus($('status-usuario'), 'Usuário cadastrado.');
        mostrarSenha(senha);
      }
      await carregarLista();
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  });

  // --- Lista ------------------------------------------------------------------------------

  function linha(usuario) {
    const legivel = usuario.nome !== null;
    return el(
      'tr',
      {},
      el('td', {}, legivel ? usuario.nome : 'Cadastro ilegível'),
      el('td', {}, el('code', {}, usuario.cpf_mascarado ?? '—')),
      el('td', {}, usuario.grupos.join(', ') || '—'),
      el(
        'td',
        {},
        el(
          'span',
          { class: 'selo', dataset: { status: usuario.status } },
          ROTULO_STATUS[usuario.status] ?? usuario.status,
        ),
      ),
      el(
        'td',
        {},
        el(
          'button',
          {
            type: 'button',
            class: 'link link--botao',
            'aria-label': `Abrir usuário ${legivel ? usuario.nome : 'com cadastro ilegível'}`,
            onclick: () => abrirFicha(usuario.id),
          },
          'Abrir',
        ),
      ),
    );
  }

  async function carregarLista() {
    const status = $('status-lista-usuarios');
    try {
      const { itens, proximo } = await chamarApi('POST', '/usuarios/lista', {
        depois: cursorAtual,
      });
      cursorProximo = proximo;
      $('corpo-usuarios').replaceChildren(...itens.map(linha));
      $('usuarios-anterior').disabled = cursoresAnteriores.length === 0;
      $('usuarios-proxima').disabled = proximo === null;
      definirStatus(status, itens.length === 0 ? 'Nenhum usuário encontrado.' : '');
    } catch (erro) {
      definirStatus(status, erro.message, 'error');
    }
  }

  $('usuarios-proxima').addEventListener('click', () => {
    cursoresAnteriores.push(cursorAtual);
    cursorAtual = cursorProximo;
    carregarLista();
  });
  $('usuarios-anterior').addEventListener('click', () => {
    cursorAtual = cursoresAnteriores.pop() ?? null;
    carregarLista();
  });

  return {
    async abrir() {
      $('novo-usuario').hidden = !pode('criar');
      try {
        if (gruposDisponiveis === null) {
          ({ grupos: gruposDisponiveis } = await chamarApi('GET', '/usuarios/grupos'));
        }
      } catch (erro) {
        definirStatus($('status-lista-usuarios'), erro.message, 'error');
        return;
      }
      await carregarLista();
    },
  };
}
