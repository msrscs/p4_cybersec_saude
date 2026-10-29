// Formatação e checagem de CPF na interface. A validação que vale é a do backend.

export function somenteDigitos(valor) {
  return String(valor).replace(/\D/g, '');
}

export function formatarCpf(valor) {
  const digitos = somenteDigitos(valor).slice(0, 11);
  return digitos
    .replace(/^(\d{3})(\d)/, '$1.$2')
    .replace(/^(\d{3})\.(\d{3})(\d)/, '$1.$2.$3')
    .replace(/\.(\d{3})(\d{1,2})$/, '.$1-$2');
}

function digito(base) {
  let soma = 0;
  for (let i = 0; i < base.length; i += 1) soma += Number(base[i]) * (base.length + 1 - i);
  const resto = soma % 11;
  return resto < 2 ? 0 : 11 - resto;
}

export function cpfValido(valor) {
  const cpf = somenteDigitos(valor);
  if (cpf.length !== 11 || /^(\d)\1{10}$/.test(cpf)) return false;
  return digito(cpf.slice(0, 9)) === Number(cpf[9]) && digito(cpf.slice(0, 10)) === Number(cpf[10]);
}
