#!/bin/sh
# Postgres local e de CI com TLS obrigatório (ADR-0013, ADR-0029), sem certificado no host: a cada
# subida o container gera um par autoassinado efêmero, que nunca sai dele. Clientes usam
# DB_SSLMODE=require (canal cifrado). Na AWS o banco é o Aurora, verificado com verify-full e a CA
# do RDS; este script não é usado lá.
set -eu
install -d -m 700 -o postgres -g postgres /tmp/tls
# umask só aqui: herdado pelo entrypoint, quebraria o initdb de um volume novo.
(
  umask 077
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -sha256 -days 30 \
    -subj "/CN=db" -addext "subjectAltName=DNS:db,DNS:localhost,IP:127.0.0.1" \
    -keyout /tmp/tls/db.key -out /tmp/tls/db.crt 2>/dev/null
)
chmod 600 /tmp/tls/db.key
chmod 644 /tmp/tls/db.crt
install -m 644 /postgres/pg_hba.conf /tmp/tls/pg_hba.conf
chown postgres:postgres /tmp/tls/db.key /tmp/tls/db.crt /tmp/tls/pg_hba.conf
exec docker-entrypoint.sh postgres \
  -c ssl=on \
  -c ssl_cert_file=/tmp/tls/db.crt \
  -c ssl_key_file=/tmp/tls/db.key \
  -c ssl_min_protocol_version=TLSv1.2 \
  -c hba_file=/tmp/tls/pg_hba.conf \
  -c password_encryption=scram-sha-256
