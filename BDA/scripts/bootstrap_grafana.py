"""Idempotently configure Grafana organizations, users, teams and dashboards.

Grafana OSS cannot grant datasource query permission to a team with the
granularity required here. The bootstrap therefore uses two organizations:

* organization 1: Direccion and IT, with every dashboard;
* REE Análisis: Analisis users, its own datasource, and selected dashboards.

GRAFANA_BOOTSTRAP_USERS format::

    login|email|password|team|home_dashboard_uid;...

Passwords belong only in the local .env file, never in the repository.
"""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


URL = os.environ.get("GRAFANA_URL", "http://grafana:3000").rstrip("/")
ADMIN_USER = os.environ["GRAFANA_ADMIN_USER"]
ADMIN_PASSWORD = os.environ["GRAFANA_ADMIN_PASSWORD"]
MAIN_ORG_ID = os.environ.get("GRAFANA_ORG_ID", "1")
ANALYSIS_ORG_NAME = "REE Análisis"
ANALYSIS_UIDS = {
    item.strip()
    for item in os.environ.get("GRAFANA_ANALYSIS_DASHBOARD_UIDS", "").split(",")
    if item.strip()
}
USER_SPEC = os.environ.get("GRAFANA_BOOTSTRAP_USERS", "").strip()
INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
INFLUX_ORG = os.environ.get("INFLUX_ORG", "red_electrica")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "ree_analisis")
INFLUX_TOKEN_FILE = Path(os.environ.get("INFLUX_READ_TOKEN_FILE", "/run/influx-secrets/INFLUX_READ_TOKEN"))
DASHBOARD_DIR = Path(os.environ.get("GRAFANA_DASHBOARD_DIR", "/dashboards"))
TEAM_NAMES = ("Direccion", "Analisis", "IT")


def auth_header() -> str:
    raw = f"{ADMIN_USER}:{ADMIN_PASSWORD}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def request(path: str, *, method: str = "GET", body: dict | None = None,
            org_id: str | int | None = None,
            allow_status: tuple[int, ...] = ()) -> tuple[int, object]:
    headers = {"Authorization": auth_header(), "Accept": "application/json"}
    if org_id is not None:
        headers["X-Grafana-Org-Id"] = str(org_id)
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
        detail = error.read().decode(errors="replace")
        raise RuntimeError(f"Grafana {method} {path} devolvió {error.code}: {detail}") from error


def wait_for_grafana() -> None:
    for _ in range(60):
        try:
            status, _ = request("/api/health")
            if status == 200:
                return
        except (HTTPError, URLError, OSError, RuntimeError):
            pass
        time.sleep(2)
    raise SystemExit("Grafana no estuvo disponible después de 120 segundos.")


def find_user(login: str) -> dict | None:
    status, data = request(f"/api/users/lookup?loginOrEmail={quote(login)}", allow_status=(404,))
    return data if status == 200 and isinstance(data, dict) else None


def ensure_user(login: str, email: str, password: str) -> dict:
    existing = find_user(login)
    if existing:
        return existing
    _, created = request(
        "/api/admin/users",
        method="POST",
        body={"name": login, "login": login, "email": email, "password": password},
    )
    return created


def ensure_org(name: str) -> dict:
    status, org = request(f"/api/orgs/name/{quote(name)}", allow_status=(404,))
    if status == 200:
        return org
    _, created = request("/api/orgs", method="POST", body={"name": name})
    # POST /api/orgs devuelve orgId; GET /api/orgs/name/:name devuelve id.
    if "id" not in created and "orgId" in created:
        created["id"] = created["orgId"]
    return created


def ensure_org_membership(user_id: int, login: str, org_id: int | str, role: str) -> None:
    request(
        f"/api/orgs/{org_id}/users",
        method="POST",
        body={"loginOrEmail": login, "role": role},
        allow_status=(400, 409),
    )
    request(
        f"/api/orgs/{org_id}/users/{user_id}",
        method="PATCH",
        body={"role": role},
    )


def remove_from_org(user_id: int, org_id: int | str) -> None:
    request(f"/api/orgs/{org_id}/users/{user_id}", method="DELETE", allow_status=(404,))


def find_team(name: str, org_id: int | str) -> dict | None:
    _, data = request(f"/api/teams/search?query={quote(name)}", org_id=org_id)
    for team in data.get("teams", []):
        if team.get("name") == name:
            return team
    return None


def ensure_team(name: str, org_id: int | str) -> dict:
    existing = find_team(name, org_id)
    if existing:
        return existing
    _, created = request("/api/teams", method="POST", org_id=org_id, body={"name": name})
    # POST /api/teams devuelve teamId; las respuestas de búsqueda usan id.
    if "id" not in created and "teamId" in created:
        created["id"] = created["teamId"]
    return created


def ensure_member(team_id: int, user_id: int, org_id: int | str) -> None:
    request(
        f"/api/teams/{team_id}/members",
        method="POST",
        org_id=org_id,
        body={"userId": user_id},
        allow_status=(400, 409),
    )


def read_influx_token() -> str:
    if not INFLUX_TOKEN_FILE.is_file():
        raise RuntimeError(f"No existe el token de InfluxDB: {INFLUX_TOKEN_FILE}")
    token = INFLUX_TOKEN_FILE.read_text().strip()
    if not token:
        raise RuntimeError("El token de lectura de InfluxDB está vacío.")
    return token


def ensure_analysis_datasource(analysis_org_id: int, token: str) -> None:
    datasource = {
        "name": "REE InfluxDB",
        "uid": "ree-influxdb",
        "type": "influxdb",
        "access": "proxy",
        "url": INFLUX_URL,
        "isDefault": True,
        "editable": False,
        "jsonData": {
            "version": "Flux",
            "organization": INFLUX_ORG,
            "defaultBucket": INFLUX_BUCKET,
            "tlsSkipVerify": False,
        },
        "secureJsonData": {"token": token},
    }
    status, existing = request(
        "/api/datasources/uid/ree-influxdb",
        org_id=analysis_org_id,
        allow_status=(404,),
    )
    if status == 404:
        request("/api/datasources", method="POST", org_id=analysis_org_id, body=datasource)
    else:
        datasource["id"] = existing["id"]
        request(
            "/api/datasources/uid/ree-influxdb",
            method="PUT",
            org_id=analysis_org_id,
            body=datasource,
        )


def dashboard_file(uid: str) -> Path:
    for path in DASHBOARD_DIR.glob("*.json"):
        try:
            if json.loads(path.read_text()).get("uid") == uid:
                return path
        except (OSError, json.JSONDecodeError):
            continue
    raise RuntimeError(f"No se encontró el JSON del dashboard {uid!r}.")


def ensure_analysis_dashboard(analysis_org_id: int, uid: str) -> None:
    dashboard = json.loads(dashboard_file(uid).read_text())
    dashboard["id"] = None
    request(
        "/api/dashboards/db",
        method="POST",
        org_id=analysis_org_id,
        body={
            "dashboard": dashboard,
            "folderId": 0,
            "overwrite": True,
            "message": "Bootstrap de permisos de departamentos",
        },
    )


def set_org_home_dashboard(org_id: int, uid: str) -> None:
    request(
        "/api/org/preferences",
        method="PUT",
        org_id=org_id,
        body={"homeDashboardUID": uid},
    )


def parse_users() -> list[tuple[str, str, str, str, str]]:
    users = []
    for raw in USER_SPEC.split(";") if USER_SPEC else []:
        parts = raw.strip().split("|")
        if len(parts) != 5:
            raise SystemExit(
                "Cada usuario de GRAFANA_BOOTSTRAP_USERS debe tener "
                "login|email|password|equipo|dashboard-inicial."
            )
        login, email, password, team, home_uid = parts
        if team not in TEAM_NAMES:
            raise SystemExit(f"Equipo no válido para {login!r}: {team!r}")
        users.append((login, email, password, team, home_uid))
    return users


def main() -> None:
    wait_for_grafana()
    users = parse_users()
    main_org_id = int(MAIN_ORG_ID)
    analysis_org = ensure_org(ANALYSIS_ORG_NAME)
    analysis_org_id = int(analysis_org["id"])
    influx_token = read_influx_token()

    teams = {
        "Direccion": ensure_team("Direccion", main_org_id),
        "IT": ensure_team("IT", main_org_id),
        "Analisis": ensure_team("Analisis", analysis_org_id),
    }
    ensure_analysis_datasource(analysis_org_id, influx_token)
    for uid in ANALYSIS_UIDS:
        ensure_analysis_dashboard(analysis_org_id, uid)

    home_by_org: dict[int, str] = {}
    for login, email, password, team, home_uid in users:
        user = ensure_user(login, email, password)
        user_id = int(user["id"])
        if team == "Analisis":
            ensure_org_membership(user_id, login, analysis_org_id, "Viewer")
            remove_from_org(user_id, main_org_id)
            ensure_member(int(teams["Analisis"]["id"]), user_id, analysis_org_id)
            home_by_org.setdefault(analysis_org_id, home_uid)
        else:
            role = "Editor" if team == "IT" else "Viewer"
            ensure_org_membership(user_id, login, main_org_id, role)
            ensure_member(int(teams[team]["id"]), user_id, main_org_id)
            home_by_org.setdefault(main_org_id, home_uid)

    for org_id, home_uid in home_by_org.items():
        set_org_home_dashboard(org_id, home_uid)

    print("Bootstrap de Grafana completado correctamente.")
    print(f"Organización de análisis: {ANALYSIS_ORG_NAME} (id={analysis_org_id})")
    print(f"Usuarios configurados: {len(users)}")
    print(f"Dashboards de Analisis: {', '.join(sorted(ANALYSIS_UIDS)) or '(ninguno)'}")


if __name__ == "__main__":
    main()
