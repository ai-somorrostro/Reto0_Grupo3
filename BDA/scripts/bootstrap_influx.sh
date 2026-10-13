#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="$ROOT_DIR/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "No existe $ENV_FILE. Cópialo desde .env.example y completa los valores." >&2
  exit 1
fi

# Compose también lee este archivo, pero el script necesita sus valores para
# consultar la API de InfluxDB desde el host.
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${INFLUX_URL:?Falta INFLUX_URL en .env}"
: "${INFLUX_ORG:?Falta INFLUX_ORG en .env}"
: "${INFLUX_BUCKET:?Falta INFLUX_BUCKET en .env}"
: "${INFLUX_WRITE_TOKEN:?Falta INFLUX_WRITE_TOKEN en .env}"

for command in curl jq docker; do
  command -v "$command" >/dev/null || {
    echo "Falta el comando requerido: $command" >&2
    exit 1
  }
done

echo "Arrancando InfluxDB..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d influxdb

for attempt in $(seq 1 60); do
  if curl -fsS "$INFLUX_URL/health" >/dev/null 2>&1; then
    break
  fi
  if [[ "$attempt" == 60 ]]; then
    echo "InfluxDB no está disponible después de 60 segundos." >&2
    exit 1
  fi
  sleep 1
done

api_headers=(
  -H "Authorization: Token $INFLUX_WRITE_TOKEN"
  -H "Accept: application/json"
  -H "Content-Type: application/json"
)

org_id=$(curl -fsS "${api_headers[@]}" --get \
  --data-urlencode "org=$INFLUX_ORG" \
  "$INFLUX_URL/api/v2/orgs" | jq -r '.orgs[0].id // empty')

if [[ -z "$org_id" ]]; then
  echo "No se encontró la organización '$INFLUX_ORG'." >&2
  echo "El volumen de InfluxDB puede pertenecer a otra instalación." >&2
  exit 1
fi

bucket_id=$(curl -fsS "${api_headers[@]}" --get \
  --data-urlencode "orgID=$org_id" \
  --data-urlencode "name=$INFLUX_BUCKET" \
  "$INFLUX_URL/api/v2/buckets" | jq -r '.buckets[0].id // empty')

if [[ -z "$bucket_id" ]]; then
  echo "No se encontró el bucket '$INFLUX_BUCKET'." >&2
  exit 1
fi

# Si el token configurado ya puede consultar el bucket, no se crea otro.
read_token_works=false
if [[ -n "${INFLUX_READ_TOKEN:-}" && "$INFLUX_READ_TOKEN" != replace-with-* ]]; then
  query="from(bucket: \"$INFLUX_BUCKET\") |> range(start: -1m) |> limit(n: 1)"
  if curl -fsS -o /dev/null -X POST \
    -H "Authorization: Token $INFLUX_READ_TOKEN" \
    -H 'Accept: application/csv' \
    -H 'Content-Type: application/vnd.flux' \
    --data-binary "$query" \
    "$INFLUX_URL/api/v2/query?org=$(printf '%s' "$INFLUX_ORG" | jq -sRr @uri)"; then
    read_token_works=true
  fi
fi

if [[ "$read_token_works" == true ]]; then
  echo "El token de lectura ya es válido; se conserva."
else
  echo "Creando token de lectura para '$INFLUX_BUCKET'..."
  payload=$(jq -n \
    --arg org_id "$org_id" \
    --arg bucket_id "$bucket_id" \
    '{status:"active", description:"grafana-read", orgID:$org_id,
      permissions:[{action:"read", resource:{id:$bucket_id, orgID:$org_id, type:"buckets"}}]}')

  new_read_token=$(curl -fsS -X POST \
    "${api_headers[@]}" \
    --data "$payload" \
    "$INFLUX_URL/api/v2/authorizations" | jq -r '.token // empty')

  if [[ -z "$new_read_token" ]]; then
    echo "InfluxDB no devolvió el token de lectura." >&2
    exit 1
  fi

  tmp_file=$(mktemp)
  awk -v token="$new_read_token" '
    BEGIN { found = 0 }
    /^INFLUX_READ_TOKEN=/ { print "INFLUX_READ_TOKEN=" token; found = 1; next }
    { print }
    END { if (!found) print "INFLUX_READ_TOKEN=" token }
  ' "$ENV_FILE" > "$tmp_file"
  chmod --reference="$ENV_FILE" "$tmp_file" 2>/dev/null || true
  mv "$tmp_file" "$ENV_FILE"
  echo "Token de lectura creado y guardado en .env."
fi

echo "Cargando datos y arrancando Grafana..."
docker compose -f "$ROOT_DIR/docker-compose.yml" up --build --force-recreate loader
docker compose -f "$ROOT_DIR/docker-compose.yml" up -d --force-recreate grafana
echo "Bootstrap completado."
