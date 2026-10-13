"""Ensure that Grafana has a valid read-only InfluxDB token.

The generated token is stored in a persistent Docker volume. This makes the
Compose stack self-contained: a normal `docker compose up` reuses the token,
while a fresh volume gets a new one automatically.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL = os.environ["INFLUX_URL"].rstrip("/")
ORG = os.environ["INFLUX_ORG"]
BUCKET = os.environ["INFLUX_BUCKET"]
ADMIN_TOKEN = os.environ["INFLUX_WRITE_TOKEN"]
TOKEN_FILE = Path(os.environ.get("INFLUX_READ_TOKEN_FILE", "/run/influx-secrets/INFLUX_READ_TOKEN"))


def request(path: str, *, method: str = "GET", token: str = ADMIN_TOKEN, body: dict | None = None) -> dict | str:
    headers = {"Authorization": f"Token {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = Request(f"{URL}{path}", headers=headers, method=method, data=data)
    with urlopen(req, timeout=10) as response:
        raw = response.read()
    if not raw:
        return ""
    content_type = response.headers.get("Content-Type", "")
    return json.loads(raw) if "json" in content_type else raw.decode()


def read_token_works(token: str) -> bool:
    query = f'from(bucket: "{BUCKET}") |> range(start: -1m) |> limit(n: 1)'
    req = Request(
        f"{URL}/api/v2/query?{urlencode({'org': ORG})}",
        headers={
            "Authorization": f"Token {token}",
            "Accept": "application/csv",
            "Content-Type": "application/vnd.flux",
        },
        method="POST",
        data=query.encode(),
    )
    try:
        with urlopen(req, timeout=10):
            return True
    except (HTTPError, URLError):
        return False


def save_token(token: str) -> None:
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=TOKEN_FILE.parent, delete=False) as tmp:
        tmp.write(token + "\n")
        temporary = Path(tmp.name)
    # Grafana runs as UID 472 inside its container. The token volume is
    # mounted read-only there, so the file must be readable by that user.
    temporary.chmod(0o644)
    temporary.replace(TOKEN_FILE)


def main() -> None:
    if TOKEN_FILE.is_file() and read_token_works(TOKEN_FILE.read_text().strip()):
        TOKEN_FILE.chmod(0o644)
        print("Token de lectura existente válido.")
        return

    orgs = request(f"/api/v2/orgs?{urlencode({'org': ORG})}")
    org_id = (orgs.get("orgs") or [{}])[0].get("id")
    if not org_id:
        raise SystemExit(f"No se encontró la organización {ORG!r}.")

    buckets = request(f"/api/v2/buckets?{urlencode({'orgID': org_id, 'name': BUCKET})}")
    bucket_id = (buckets.get("buckets") or [{}])[0].get("id")
    if not bucket_id:
        raise SystemExit(f"No se encontró el bucket {BUCKET!r}.")

    authorization = {
        "status": "active",
        "description": "grafana-read",
        "orgID": org_id,
        "permissions": [
            {
                "action": "read",
                "resource": {"id": bucket_id, "orgID": org_id, "type": "buckets"},
            }
        ],
    }
    created = request("/api/v2/authorizations", method="POST", body=authorization)
    read_token = created.get("token") if isinstance(created, dict) else None
    if not read_token:
        raise SystemExit("InfluxDB no devolvió el token de lectura.")
    save_token(read_token)
    print("Token de lectura creado y guardado en el volumen persistente.")


if __name__ == "__main__":
    main()
