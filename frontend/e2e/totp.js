// TOTP (RFC 6238, SHA-1, 6 dígitos, 30 s) só para o teste gerar códigos como o celular faria.
import { createHmac } from 'node:crypto';

const ALFABETO = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';

function base32(texto) {
  let bits = '';
  for (const c of texto.replace(/[\s=]/g, '').toUpperCase()) {
    const valor = ALFABETO.indexOf(c);
    if (valor < 0) throw new Error('Chave base32 inválida.');
    bits += valor.toString(2).padStart(5, '0');
  }
  const bytes = [];
  for (let i = 0; i + 8 <= bits.length; i += 8)
    bytes.push(Number.parseInt(bits.slice(i, i + 8), 2));
  return Buffer.from(bytes);
}

export const passoAtual = () => Math.floor(Date.now() / 1000 / 30);

export function totp(chave, passo = passoAtual()) {
  const contador = Buffer.alloc(8);
  contador.writeBigUInt64BE(BigInt(passo));
  const hash = createHmac('sha1', base32(chave)).update(contador).digest();
  const deslocamento = hash[hash.length - 1] & 0xf;
  const numero = (hash.readUInt32BE(deslocamento) & 0x7fffffff) % 1_000_000;
  return String(numero).padStart(6, '0');
}
