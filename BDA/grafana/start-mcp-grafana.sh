#!/bin/sh
set -eu

token_file=/run/mcp-secrets/MCP_SERVER_TOKEN
if [ ! -s "$token_file" ]; then
    echo "No existe el token de acceso de clientes MCP." >&2
    exit 1
fi

export MCP_GRAFANA_SERVER_TOKEN="$(cat "$token_file")"
exec /app/mcp-grafana "$@"
