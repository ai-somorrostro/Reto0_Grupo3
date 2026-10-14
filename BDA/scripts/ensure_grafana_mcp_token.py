"""Create or repair the Grafana service account token used by the MCP server."""

from __future__ import annotations

import base64
import json
import os
import secrets
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


URL = os.environ.get("GRAFANA_URL", "http://grafana:3000").rstrip("/")
ADMIN_USER = os.environ["GRAFANA_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["GRAFANA_ADMIN_PASSWORD"]
ORG_ID = os.environ.get("GRAFANA_ORG_ID", "1")
SERVICE_ACCOUNT_NAME = os.environ.get("GRAFANA_MCP_SERVICE_ACCOUNT_NAME", "mcp-grafana")
SERVICE_ACCOUNT_ROLE = os.environ.get("GRAFANA_MCP_SERVICE_ACCOUNT_ROLE", "Viewer")
TOKEN_FILE = Path(os.environ.get("GRAFANA_MCP_TOKEN_FILE", "/run/mcp-secrets/GRAFANA_MCP_TOKEN"))
MCP_SERVER_TOKEN_FILE = Path(
    os.environ.get("MCP_GRAFANA_SERVER_TOKEN_FILE", "/run/mcp-secrets/MCP_SERVER_TOKEN")
)


def request(
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    bearer_token: str | None = None,
    allow_status: tuple[int, ...] = (),
) -> tuple[int, dict | list]:
    headers = {"Accept": "application/json", "X-Grafana-Org-Id": ORG_ID}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    else:
        raw = f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = Request(f"{URL}{path}", headers=headers, method=method, data=data)
    try:
        with urlopen(req, timeout=10) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else {}
    except HTTPError as error:
        if error.code in allow_status:
            return error.code, {}
        raise RuntimeError(f"Grafana {method} {path} devolvió HTTP {error.code}.") from error
    except URLError as error:
        raise RuntimeError(f"No se pudo conectar con Grafana en {URL}.") from error


def find_service_account() -> dict | None:
    query = urlencode(
        {"perpage": 1000, "page": 1, "query": SERVICE_ACCOUNT_NAME}
    )
    _, result = request(f"/api/serviceaccounts/search?{query}")
    accounts = result.get("serviceAccounts", []) if isinstance(result, dict) else []
    return next(
        (
            account
            for account in accounts
            if account.get("name") == SERVICE_ACCOUNT_NAME
        ),
        None,
    )


def ensure_service_account() -> int:
    account = find_service_account()
    if account is None:
        _, account = request(
            "/api/serviceaccounts",
            method="POST",
            body={
                "name": SERVICE_ACCOUNT_NAME,
                "role": SERVICE_ACCOUNT_ROLE,
                "isDisabled": False,
            },
        )
    elif account.get("role") != SERVICE_ACCOUNT_ROLE or account.get("isDisabled"):
        _, account = request(
            f"/api/serviceaccounts/{account['id']}",
            method="PATCH",
            body={"name": SERVICE_ACCOUNT_NAME, "role": SERVICE_ACCOUNT_ROLE, "isDisabled": False},
        )
    account_id = account.get("id") if isinstance(account, dict) else None
    if not account_id:
        raise RuntimeError("Grafana no devolvió el ID de la service account.")
    return int(account_id)


def token_is_valid(token: str) -> bool:
    status, result = request(
        "/api/user",
        bearer_token=token,
        allow_status=(401, 403),
    )
    return status == 200 and isinstance(result, dict)


def save_secret(path: Path, secret: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as tmp:
        tmp.write(secret + "\n")
        temporary = Path(tmp.name)
    temporary.chmod(0o444)
    temporary.replace(path)


def ensure_mcp_server_token() -> None:
    if MCP_SERVER_TOKEN_FILE.is_file():
        if MCP_SERVER_TOKEN_FILE.read_text().strip():
            MCP_SERVER_TOKEN_FILE.chmod(0o444)
            return
    save_secret(MCP_SERVER_TOKEN_FILE, secrets.token_urlsafe(32))


def rotate_token(account_id: int) -> str:
    _, tokens = request(f"/api/serviceaccounts/{account_id}/tokens")
    if not isinstance(tokens, list):
        raise RuntimeError("Grafana devolvió un listado de tokens inesperado.")
    for token in tokens:
        token_id = token.get("id")
        if token_id is not None:
            request(
                f"/api/serviceaccounts/{account_id}/tokens/{token_id}",
                method="DELETE",
                allow_status=(404,),
            )
    _, created = request(
        f"/api/serviceaccounts/{account_id}/tokens",
        method="POST",
        body={"name": f"{SERVICE_ACCOUNT_NAME}-managed"},
    )
    token = created.get("key") if isinstance(created, dict) else None
    if not token:
        raise RuntimeError("Grafana no devolvió la clave del token de service account.")
    return token


def main() -> None:
    account_id = ensure_service_account()
    if TOKEN_FILE.is_file():
        saved_token = TOKEN_FILE.read_text().strip()
        if saved_token and token_is_valid(saved_token):
            TOKEN_FILE.chmod(0o444)
            ensure_mcp_server_token()
            print("Cuenta de servicio MCP y token existente verificados.")
            return

    save_secret(TOKEN_FILE, rotate_token(account_id))
    ensure_mcp_server_token()
    print("Cuenta de servicio MCP creada/verificada y token guardado en el volumen.")


if __name__ == "__main__":
    main()
