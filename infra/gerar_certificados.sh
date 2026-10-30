#!/usr/bin/env bash
# Gera a CA interna e os certificados TLS de cada serviço (ADR-0013). Só openssl.
#
#   infra/gerar_certificados.sh            # cria o que faltar em certs/
#   infra/gerar_certificados.sh --renovar  # recria os certificados dos serviços (mantém a CA)
#
# A CA só pode assinar nomes locais (name constraints): confiar nela no navegador não permite
# que, se a chave vazar, alguém emita certificado para outros sites.
# Chaves: 0600 (CA) e 0640 (serviços, lidas pelo grupo via group_add no compose). Nunca no git.
set -euo pipefail

DIR="${CERTS_DIR:-$(cd "$(dirname "$0")/.." && pwd)/certs}"
RENOVAR="${1:-}"
DIAS_CA=1825
DIAS_SERVICO=397 # limite aceito pelos navegadores para certificados de servidor

mkdir -p "$DIR"
chmod 750 "$DIR"
cd "$DIR"
umask 027

if [[ ! -f ca.key ]]; then
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out ca.key
  chmod 600 ca.key
  openssl req -x509 -new -key ca.key -sha256 -days "$DIAS_CA" -out ca.crt \
    -subj "/O=CyberSec Saude/CN=CyberSec Saude CA local" \
    -addext "basicConstraints=critical,CA:TRUE,pathlen:0" \
    -addext "keyUsage=critical,keyCertSign,cRLSign" \
    -addext "nameConstraints=critical,permitted;DNS:localhost,permitted;DNS:frontend,permitted;DNS:backend,permitted;DNS:db,permitted;IP:127.0.0.0/255.0.0.0"
  echo "CA criada: $DIR/ca.crt"
fi

emitir() {
  local nome="$1" san="$2"
  if [[ -f "$nome.crt" && "$RENOVAR" != "--renovar" ]]; then
    return
  fi
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$nome.key"
  chmod 640 "$nome.key"
  openssl req -new -key "$nome.key" -subj "/O=CyberSec Saude/CN=$nome" -out "$nome.csr"
  openssl x509 -req -in "$nome.csr" -CA ca.crt -CAkey ca.key -sha256 -days "$DIAS_SERVICO" \
    -set_serial "0x$(openssl rand -hex 16)" -out "$nome.crt" \
    -extfile <(printf '%s\n' \
      "basicConstraints=critical,CA:FALSE" \
      "keyUsage=critical,digitalSignature" \
      "extendedKeyUsage=serverAuth" \
      "subjectAltName=$san")
  rm -f "$nome.csr"
  chmod 644 "$nome.crt"
  echo "Certificado emitido: $nome ($san)"
}

emitir edge "DNS:cybersec.localhost,DNS:localhost,IP:127.0.0.1"
emitir frontend "DNS:frontend,DNS:localhost,IP:127.0.0.1"
emitir backend "DNS:backend,DNS:localhost,IP:127.0.0.1"
emitir db "DNS:db,DNS:localhost,IP:127.0.0.1"
chmod 644 ca.crt
