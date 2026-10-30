#!/bin/sh
# Copia certificado e chave para um diretório do usuário postgres com as permissões que o
# Postgres exige (a chave montada pertence ao usuário do host) e sobe com TLS obrigatório.
set -eu
install -d -m 700 -o postgres -g postgres /tmp/tls
install -m 600 -o postgres -g postgres /certs/db.key /tmp/tls/db.key
install -m 644 -o postgres -g postgres /certs/db.crt /tmp/tls/db.crt
install -m 644 -o postgres -g postgres /infra/pg_hba.conf /tmp/tls/pg_hba.conf
exec docker-entrypoint.sh postgres \
  -c ssl=on \
  -c ssl_cert_file=/tmp/tls/db.crt \
  -c ssl_key_file=/tmp/tls/db.key \
  -c ssl_min_protocol_version=TLSv1.2 \
  -c hba_file=/tmp/tls/pg_hba.conf \
  -c password_encryption=scram-sha-256
