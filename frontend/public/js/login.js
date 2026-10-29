// Comportamento da tela de login. A autenticação real (CPF + senha + TOTP) é ligada na T08;
// toda validação definitiva acontece no backend.

const form = document.getElementById('form-login');
const cpfInput = document.getElementById('cpf');
const senhaInput = document.getElementById('senha');
const toggle = document.getElementById('toggle-senha');
const status = document.getElementById('form-status');

function formatCpf(value) {
  const digits = value.replace(/\D/g, '').slice(0, 11);
  return digits
    .replace(/^(\d{3})(\d)/, '$1.$2')
    .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d{1,2})$/, '.$1-$2');
}

function setStatus(message, kind = 'info') {
  status.textContent = message;
  status.dataset.kind = kind;
}

cpfInput.addEventListener('input', () => {
  cpfInput.value = formatCpf(cpfInput.value);
  cpfInput.removeAttribute('aria-invalid');
});

toggle.addEventListener('click', () => {
  const show = senhaInput.type === 'password';
  senhaInput.type = show ? 'text' : 'password';
  toggle.textContent = show ? 'Ocultar' : 'Mostrar';
  toggle.setAttribute('aria-pressed', String(show));
});

form.addEventListener('submit', (event) => {
  event.preventDefault();
  if (cpfInput.value.replace(/\D/g, '').length !== 11) {
    cpfInput.setAttribute('aria-invalid', 'true');
    setStatus('Informe um CPF com 11 dígitos.', 'error');
    cpfInput.focus();
    return;
  }
  if (senhaInput.value.length === 0) {
    setStatus('Informe sua senha.', 'error');
    senhaInput.focus();
    return;
  }
  setStatus('O acesso ao sistema será habilitado em breve.');
});
