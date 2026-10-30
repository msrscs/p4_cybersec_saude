#!/usr/bin/env bash
# Postgres efêmero do CI com a mesma configuração de TLS do compose (ADR-0013). Usa `docker run`
# porque um `services:` do GitHub Actions sobe antes do checkout e não veria certificados nem
# configuração. Espera POSTGRES_USER, POSTGRES_PASSWORD e POSTGRES_DB no ambiente.
set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/../.." && pwd)"
PORTA="${DB_PORT:-5432}"
NOME="${PG_CONTAINER:-postgres-ci}"

docker run -d --name "$NOME" \
  -e POSTGRES_USER -e POSTGRES_PASSWORD -e POSTGRES_DB \
  -p "127.0.0.1:$PORTA:5432" \
  -v "$RAIZ/infra/postgres:/infra:ro" \
  -v "$RAIZ/certs/db.crt:/certs/db.crt:ro" \
  -v "$RAIZ/certs/db.key:/certs/db.key:ro" \
  --entrypoint /infra/iniciar.sh \
  postgres:18 >/dev/null

for _ in $(seq 1 30); do
  # Pela porta TCP: durante o initdb o servidor temporário só atende no socket local.
  if docker exec "$NOME" pg_isready -q -h 127.0.0.1 -U "$POSTGRES_USER"; then
    exit 0
  fi
  sleep 2
done
docker logs "$NOME" >&2
exit 1
