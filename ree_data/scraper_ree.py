#!/usr/bin/env python3
"""
REData / Red Eléctrica -> un único Parquet tidy-long.

Estructura esperada:
    ree_data/
    ├── scraper_ree.py
    ├── ree_config.json
    ├── ree_endpoints.txt
    ├── data/
    │   ├── datos_ree_originales_2019_2025.parquet
    │   └── ree_control_2019_2025.parquet
    └── logs/
        └── scraper.log

El scraper consulta 2019-2025 por bloques anuales para reducir el tamaño
individual de las respuestas de la API y escribe incrementalmente en un único
Parquet analítico. El TXT de endpoints es documentación; la configuración
operativa se lee del JSON.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "ree_config.json"
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"

REQUEST_TIMEOUT = 120
MAX_RETRIES = 5
SLEEP_SECONDS = 0.4

HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Host": "apidatos.ree.es",
    "User-Agent": "ree-redata-tidy-long-research/1.0",
}

COLUMNS = [
    "datetime", "date", "year", "month", "time_granularity",
    "geography_id", "geography_type", "geography_name", "border", "geo_limit",
    "system", "category", "endpoint", "widget",
    "indicator_id", "indicator_type", "indicator_group_id",
    "indicator_name", "indicator_description",
    "technology_id", "technology_name",
    "value", "unit", "percentage", "status",
    "source_url", "retrieved_at",
]

ARROW_SCHEMA = pa.schema([
    pa.field("datetime", pa.timestamp("ns", tz="UTC")),
    pa.field("date", pa.string()),
    pa.field("year", pa.int16()),
    pa.field("month", pa.int8()),
    pa.field("time_granularity", pa.string()),
    pa.field("geography_id", pa.string()),
    pa.field("geography_type", pa.string()),
    pa.field("geography_name", pa.string()),
    pa.field("border", pa.string()),
    pa.field("geo_limit", pa.string()),
    pa.field("system", pa.string()),
    pa.field("category", pa.string()),
    pa.field("endpoint", pa.string()),
    pa.field("widget", pa.string()),
    pa.field("indicator_id", pa.string()),
    pa.field("indicator_type", pa.string()),
    pa.field("indicator_group_id", pa.string()),
    pa.field("indicator_name", pa.string()),
    pa.field("indicator_description", pa.string()),
    pa.field("technology_id", pa.string()),
    pa.field("technology_name", pa.string()),
    pa.field("value", pa.float64()),
    pa.field("unit", pa.string()),
    pa.field("percentage", pa.float64()),
    pa.field("status", pa.string()),
    pa.field("source_url", pa.string()),
    pa.field("retrieved_at", pa.string()),
])


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("ree_scraper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(
        LOG_DIR / "scraper.log", encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    return logger


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def yearly_dates(year: int) -> tuple[str, str]:
    return f"{year}-01-01T00:00", f"{year}-12-31T23:59"


def build_url(base_url: str, endpoint: dict, start_date: str,
              end_date: str, geo: dict | None) -> str:
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "time_trunc": endpoint["time_trunc"],
    }

    if geo is not None:
        params.update({
            "geo_trunc": "electric_system",
            "geo_limit": geo["geo_limit"],
            "geo_ids": str(geo["geo_id"]),
        })
    if endpoint.get("border_select"):
        params["borderSelect"] = endpoint["border_select"]

    return (
        f"{base_url}/{endpoint['category']}/{endpoint['widget']}"
        f"?{urlencode(params)}"
    )


def extract_error(response: requests.Response) -> str:
    text = response.text.strip()
    if not text:
        return f"HTTP {response.status_code}"
    try:
        body = response.json()
        errors = body.get("errors")
        if errors:
            return "HTTP %s: %s" % (response.status_code, " | ".join(
                f"code={e.get('code')}, title={e.get('title')}, detail={e.get('detail')}"
                for e in errors
            ))
    except ValueError:
        pass
    return f"HTTP {response.status_code}: {text[:1500]}"


def get_json(session: requests.Session, url: str, logger: logging.Logger):
    last_error = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                try:
                    return response.status_code, response.json(), None
                except ValueError as exc:
                    return response.status_code, None, f"JSON inválido: {exc}"

            last_error = extract_error(response)

            # Estos códigos suelen indicar un problema de parámetros o ruta.
            if response.status_code in {400, 404, 422}:
                return response.status_code, None, last_error

            logger.warning(
                "HTTP %s; intento %s/%s",
                response.status_code, attempt, MAX_RETRIES,
            )

        except requests.RequestException as exc:
            last_error = repr(exc)
            logger.warning(
                "Error de conexión; intento %s/%s: %s",
                attempt, MAX_RETRIES, exc,
            )

        if attempt < MAX_RETRIES:
            time.sleep(min(2 ** attempt, 15))

    return 0, None, last_error


def infer_technology(item: dict, title: str | None) -> tuple[str | None, str | None]:
    """Extrae la tecnología directamente del indicador REData cuando existe.

    En respuestas como potencia-estructura-renovables, el propio item de
    `included` contiene el id y el título de la tecnología (p.ej. Hidráulica).
    """
    technology_id = item.get("id")
    technology_name = title
    return (str(technology_id) if technology_id is not None else None, technology_name)


def iter_value_containers(obj):
    if isinstance(obj, dict):
        attrs = obj.get("attributes")
        if isinstance(attrs, dict):
            values = attrs.get("values")
            if isinstance(values, list):
                yield obj, attrs, values
            content = attrs.get("content")
            if isinstance(content, list):
                for child in content:
                    yield from iter_value_containers(child)
        for key, value in obj.items():
            if key != "attributes":
                yield from iter_value_containers(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_value_containers(item)


def flatten_payload(payload: dict, endpoint: dict, geo: dict | None,
                    url: str, retrieved_at: str) -> list[dict]:
    rows = []
    for top_item in payload.get("included", []) or []:
        for item, attrs, values in iter_value_containers(top_item):
            parent_attrs = top_item.get("attributes", {}) or {}
            indicator_id = item.get("id", top_item.get("id"))
            indicator_type = item.get("type", top_item.get("type"))
            group_id = item.get("groupId", top_item.get("groupId"))
            title = attrs.get("title") or parent_attrs.get("title")
            description = attrs.get("description") or parent_attrs.get("description")
            magnitude = attrs.get("magnitude") or parent_attrs.get("magnitude")
            technology_id, technology_name = infer_technology(item, title)
            for value_item in values:
                if not isinstance(value_item, dict):
                    continue
                dt = pd.to_datetime(value_item.get("datetime"), errors="coerce", utc=True)
                if pd.isna(dt):
                    date_value = None; year = None; month = None
                else:
                    date_value = dt.strftime("%Y-%m-%d"); year = int(dt.year); month = int(dt.month)
                rows.append({
                    "datetime": dt, "date": date_value, "year": year, "month": month,
                    "time_granularity": endpoint["time_trunc"],
                    "geography_id": str(geo["geo_id"]) if geo else None,
                    "geography_type": geo["geo_limit"] if geo else "system",
                    "geography_name": geo["name"] if geo else "Sistema eléctrico",
                    "border": endpoint.get("border"),
                    "geo_limit": geo["geo_limit"] if geo else None,
                    "system": "CCAA" if geo else "Sistema eléctrico",
                    "category": endpoint["category"], "endpoint": endpoint["name"], "widget": endpoint["widget"],
                    "indicator_id": str(indicator_id) if indicator_id is not None else None,
                    "indicator_type": indicator_type,
                    "indicator_group_id": str(group_id) if group_id is not None else None,
                    "indicator_name": title, "indicator_description": description,
                    "technology_id": technology_id,
                    "technology_name": technology_name, "value": value_item.get("value"),
                    "unit": magnitude, "percentage": value_item.get("percentage"),
                    "status": value_item.get("status"), "source_url": url, "retrieved_at": retrieved_at,
                })
    return rows


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    for col in COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[COLUMNS].copy()
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["percentage"] = pd.to_numeric(df["percentage"], errors="coerce")
    df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int16")
    df["month"] = pd.to_numeric(df["month"], errors="coerce").astype("Int8")

    text_columns = [
        "date", "time_granularity", "geography_id", "geography_type",
        "geography_name", "border", "geo_limit", "system", "category", "endpoint",
        "widget", "indicator_id", "indicator_type", "indicator_group_id",
        "indicator_name", "indicator_description", "technology_id",
        "technology_name", "unit", "status", "source_url", "retrieved_at",
    ]
    for col in text_columns:
        df[col] = df[col].astype("string")

    return df


def make_table(df: pd.DataFrame) -> pa.Table:
    df = normalize(df)
    return pa.Table.from_pandas(
        df,
        schema=ARROW_SCHEMA,
        preserve_index=False,
    )


def validate(session, config, logger) -> bool:
    # Validación pequeña pero representativa: todos los widgets territoriales
    # en dos CCAA y todos los widgets de sistema. Siempre usando un solo año,
    # porque ya hemos comprobado que los rangos de 7 años pueden devolver 400.
    territorial_names = ["Andalucía", "Aragón"]
    tests = [(geo_name, endpoint_name)
             for geo_name in territorial_names
             for endpoint_name in [e["name"] for e in config["territorial_endpoints"]]]
    tests += [(None, e["name"]) for e in config["system_endpoints"]]
    endpoints = {e["name"]: e for e in config["territorial_endpoints"] + config["system_endpoints"]}
    geos = {g["name"]: g for g in config["geographies"]}
    ok_all = True
    logger.info("VALIDACIÓN PREVIA: %s peticiones de prueba", len(tests))
    for geo_name, endpoint_name in tests:
        geo = geos[geo_name] if geo_name else None
        endpoint = endpoints[endpoint_name]
        start_date,end_date=yearly_dates(config["start_year"])
        url=build_url(config["base_url"],endpoint,start_date,end_date,geo)
        status,payload,error=get_json(session,url,logger)
        rows=flatten_payload(payload,endpoint,geo,url,datetime.now(timezone.utc).isoformat()) if payload is not None and error is None else []
        label = geo_name or "Sistema eléctrico"
        if status == 200 and rows:
            logger.info("VALIDACIÓN OK | %s | %s | HTTP 200 | filas=%s", endpoint_name, label, len(rows))
        else:
            ok_all = False
            logger.error("VALIDACIÓN FALLIDA | %s | %s | HTTP %s | filas=%s | %s", endpoint_name, label, status, len(rows), error)
    return ok_all


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()

    logger = setup_logging()
    config = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    start_year = int(config["start_year"])
    end_year = int(config["end_year"])
    observations_path = DATA_DIR / f"datos_ree_originales_{start_year}_{end_year}.parquet"
    control_path = DATA_DIR / f"ree_control_{start_year}_{end_year}.parquet"

    # Una ejecución limpia: si vuelves a lanzar el scraper, reemplaza el dataset.
    for path in (observations_path, control_path):
        if path.exists():
            path.unlink()

    jobs = []
    for year in range(start_year, end_year + 1):
        for geo in config["geographies"]:
            for endpoint in config["territorial_endpoints"]:
                jobs.append((year, endpoint, geo))
        for endpoint in config["system_endpoints"]:
            jobs.append((year, endpoint, None))

    total = len(jobs)
    logger.info("Periodo: %s-%s", start_year, end_year)
    logger.info("Peticiones planificadas: %s", total)
    logger.info("Salida principal: %s", observations_path)

    session = requests.Session()

    if args.validate:
        ok = validate(session, config, logger)
        session.close()
        raise SystemExit(0 if ok else 1)

    if not validate(session, config, logger):
        session.close()
        raise SystemExit("La validación ha fallado. No se inicia la descarga completa.")

    writer = None
    control_rows = []
    total_observations = 0

    try:
        for n, (year, endpoint, geo) in enumerate(jobs, start=1):
            start_date, end_date = yearly_dates(year)
            url = build_url(
                config["base_url"], endpoint, start_date, end_date, geo
            )
            retrieved_at = datetime.now(timezone.utc).isoformat()
            status, payload, error = get_json(session, url, logger)

            rows = []
            if payload is not None and error is None:
                rows = flatten_payload(
                    payload, endpoint, geo, url, retrieved_at
                )
                if rows:
                    table = make_table(pd.DataFrame(rows))
                    if writer is None:
                        writer = pq.ParquetWriter(
                            observations_path,
                            ARROW_SCHEMA,
                            compression="zstd",
                        )
                    writer.write_table(table)
                    total_observations += table.num_rows

            control_rows.append({
                "job": n,
                "total_jobs": total,
                "year": year,
                "endpoint": endpoint["name"],
                "category": endpoint["category"],
                "widget": endpoint["widget"],
                "time_trunc": endpoint["time_trunc"],
                "geography_name": geo["name"] if geo else "Sistema eléctrico",
                "geo_limit": geo["geo_limit"] if geo else None,
                "geo_id": str(geo["geo_id"]) if geo else None,
                "url": url,
                "http_status": status,
                "ok": bool(status == 200 and rows),
                "observations": len(rows),
                "error": error,
                "retrieved_at": retrieved_at,
            })

            if status == 200 and not rows:
                logger.warning("HTTP 200 pero el parser no encontró observaciones")

            logger.info(
                "[%04d/%04d] %s | %s | %s | HTTP %s | filas=%s",
                n,
                total,
                year,
                endpoint["name"],
                geo["name"] if geo else "Sistema",
                status,
                len(rows),
            )
            time.sleep(SLEEP_SECONDS)

    finally:
        if writer is not None:
            writer.close()
        session.close()

    pd.DataFrame(control_rows).to_parquet(
        control_path,
        index=False,
        engine="pyarrow",
        compression="zstd",
    )

    successful = sum(1 for x in control_rows if x["ok"])
    failed = len(control_rows) - successful

    logger.info("=" * 70)
    logger.info("FINALIZADO")
    logger.info("Peticiones: %s", total)
    logger.info("Correctas: %s", successful)
    logger.info("Fallidas: %s", failed)
    logger.info("Observaciones: %s", total_observations)
    logger.info("Parquet: %s", observations_path)
    logger.info("Control: %s", control_path)


if __name__ == "__main__":
    main()
