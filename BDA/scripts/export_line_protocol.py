"""Validate the notebook output and export InfluxDB 2.x line protocol.

This script intentionally does not write to InfluxDB. It produces a portable
artifact that can be ingested by Python, Node-RED or the Influx CLI.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import math
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "salidas_influx_ree" / "REE_resultados_para_InfluxDB.csv"
DEFAULT_OUTPUT = ROOT / "salidas_influx_ree" / "ree_analisis.lp"
REQUIRED = {"fecha", "pregunta", "metrica", "tecnologia", "territorio", "pais", "valor"}
TAGS = ("pregunta", "metrica", "tecnologia", "territorio", "pais")


def escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(" ", "\\ ").replace(",", "\\,").replace("=", "\\=")


def main() -> None:
    source = Path(os.getenv("REE_RESULTADOS_CSV", DEFAULT_INPUT))
    target = Path(os.getenv("REE_LINE_PROTOCOL_OUT", DEFAULT_OUTPUT))
    if not source.exists():
        raise SystemExit(f"No existe {source}. Ejecuta antes el notebook 04 hasta generar la tabla maestra.")

    target.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    rejected = 0
    with source.open("r", encoding="utf-8-sig", newline="") as handle, target.open("w", encoding="utf-8") as output:
        reader = csv.DictReader(handle)
        missing = REQUIRED - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"Faltan columnas obligatorias: {sorted(missing)}")
        for row in reader:
            try:
                value = float(row["valor"])
                if not math.isfinite(value):
                    raise ValueError
                raw_timestamp = row["fecha"].strip()
                if not raw_timestamp:
                    raise ValueError
                timestamp = datetime.fromisoformat(raw_timestamp.replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                timestamp_ns = int(timestamp.timestamp() * 1_000_000_000)
            except (TypeError, ValueError):
                rejected += 1
                continue
            tags = ",".join(f"{tag}={escape(row.get(tag, '') or 'sin_valor')}" for tag in TAGS)
            # Unix nanoseconds are unambiguous for the InfluxDB 2.x write API.
            output.write(f"ree_analisis,{tags} valor={value:.15g} {timestamp_ns}\n")
            count += 1

    print(f"Generadas {count} líneas en {target}; rechazadas {rejected}.")


if __name__ == "__main__":
    main()
