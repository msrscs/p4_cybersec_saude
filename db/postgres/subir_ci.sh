#!/usr/bin/env bash
# Postgres efêmero do CI com a mesma configuração do compose (TLS obrigatório, ADR-0029). Usa
# `docker run` porque um `services:` do GitHub Actions sobe antes do checkout e não veria a
# configuração. Espera POSTGRES_USER, POSTGRES_PASSWORD e POSTGRES_DB no ambiente.
#
# Com DB_SSLROOTCERT definido, copia para lá o certificado efêmero do container: assim o CI testa
# o caminho verify-full (o mesmo da AWS) contra o nome "localhost".
set -euo pipefail

DIR_DB="$(cd "$(dirname "$0")" && pwd)"
PORTA="${DB_PORT:-5432}"
NOME="${PG_CONTAINER:-postgres-ci}"

docker run -d --name "$NOME" \
  -e POSTGRES_USER -e POSTGRES_PASSWORD -e POSTGRES_DB \
  -p "127.0.0.1:$PORTA:5432" \
  -v "$DIR_DB:/postgres:ro" \
  --entrypoint /postgres/iniciar.sh \
  postgres:18 >/dev/null

for _ in $(seq 1 30); do
  # Pela porta TCP: durante o initdb o servidor temporário só atende no socket local.
  if docker exec "$NOME" pg_isready -q -h 127.0.0.1 -U "$POSTGRES_USER"; then
    if [[ -n "${DB_SSLROOTCERT:-}" ]]; then
      docker cp "$NOME:/tmp/tls/db.crt" "$DB_SSLROOTCERT" >/dev/null
    fi
    exit 0
  fi
  sleep 2
done
docker logs "$NOME" >&2
exit 1
