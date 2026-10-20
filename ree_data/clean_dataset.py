"""Create the analysis-ready REE parquet used by the project."""

from pathlib import Path
import json
import hashlib

import pandas as pd


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "datos_ree_originales_2019_2025.parquet"
EXCHANGES = ROOT / "data" / "intercambios_ree_por_frontera_2019_2025.parquet"
TARGET = ROOT / "data" / "dataset_ree_limpio_transicion_energetica_2019_2025.parquet"
QUALITY_REPORT = ROOT / "data" / "dataset_ree_calidad.json"


def stable_sample_id(row: pd.Series) -> str:
    """Return an id that distinguishes samples sharing the same timestamp."""
    values = "|".join(str(row.get(column, "")) for column in (
        "datetime", "endpoint", "indicator_id", "geography_id",
        "geography_name", "technology_id", "technology_name", "border",
        "indicator_type", "value",
    ))
    return hashlib.sha1(values.encode("utf-8")).hexdigest()[:20]


def main() -> None:
    data = pd.read_parquet(SOURCE)

    # Replace the aggregate exchange endpoints with the country-specific
    # downloads. The aggregate records do not identify their border reliably.
    data = data[~data["endpoint"].isin([
        "intercambios_todas_fronteras_fisicos",
        "intercambios_todas_fronteras_programados",
    ])].copy()
    if EXCHANGES.exists():
        exchanges = pd.read_parquet(EXCHANGES)
        data = pd.concat([data, exchanges], ignore_index=True)

    # REE timestamps are UTC representations of Spanish local dates.  A value
    # at 23:00 UTC belongs to the following local day in mainland Spain.
    local_datetime = data["datetime"].dt.tz_convert("Europe/Madrid")
    data["datetime"] = local_datetime
    data["date"] = local_datetime.dt.strftime("%Y-%m-%d")
    data["year"] = local_datetime.dt.year.astype("int16")
    data["month"] = local_datetime.dt.month.astype("int8")
    if "border" not in data.columns:
        data["border"] = pd.NA
    data["border"] = data["border"].fillna("No aplica")
    # Canonical units used by the analysis.  The source has missing/inconsistent
    # unit labels, so the endpoint definition is the authoritative mapping.
    data["value_unit"] = data["endpoint"].map(
        lambda endpoint: "MW" if str(endpoint).startswith("potencia_") else "MWh"
    )
    data["quality_flag"] = "ok"
    data["value"] = pd.to_numeric(data["value"], errors="coerce")
    data.loc[data["value"].isna(), "quality_flag"] = "valor_no_numerico"
    data.loc[~data["value"].replace([float("inf"), -float("inf")], pd.NA).notna(), "quality_flag"] = "valor_no_finito"
    suspicious_generation = (
        data["category"].eq("generacion")
        & data["endpoint"].isin([
            "estructura_generacion",
            "estructura_generacion_emisiones",
        ])
        & data["value"].lt(0)
    )
    data.loc[suspicious_generation, "quality_flag"] = "revisar_valor_negativo"

    # Plausibility checks.  We flag anomalies instead of silently deleting them.
    invalid_ranges = data["value"].lt(0) & data["category"].isin(["demanda", "generacion"])
    data.loc[invalid_ranges & data["quality_flag"].eq("ok"), "quality_flag"] = "fuera_de_rango"
    invalid_percentage = data["percentage"].notna() & ~data["percentage"].between(0, 100)
    data.loc[invalid_percentage & data["quality_flag"].eq("ok"), "quality_flag"] = "porcentaje_fuera_de_rango"

    # The project studies demand, generation, balance and cross-border flows.
    # Markets and transport are operationally interesting but outside this
    # question and use different units/interpretations.
    data = data[data["category"].isin(
        ["demanda", "generacion", "balance", "intercambios"]
    )].copy()

    columns = [
        "datetime",
        "date",
        "year",
        "month",
        "time_granularity",
        "geography_type",
        "geography_name",
        "border",
        "system",
        "category",
        "endpoint",
        "indicator_id",
        "indicator_type",
        "indicator_name",
        "technology_id",
        "technology_name",
        "value",
        "value_unit",
        "percentage",
        "quality_flag",
    ]
    data = data[columns].sort_values(
        ["datetime", "geography_name", "category", "endpoint", "indicator_id"]
    ).drop_duplicates().reset_index(drop=True)

    # A timestamp is not a unique key: several indicators/geographies may be
    # sampled at exactly the same instant.  Keep every row and add a stable id.
    data["sample_id"] = data.apply(stable_sample_id, axis=1)
    duplicate_ids = data["sample_id"].duplicated(keep=False)
    if duplicate_ids.any():
        # Hash collisions are extraordinarily unlikely, but make them explicit.
        data.loc[duplicate_ids, "quality_flag"] = "identificador_duplicado"
    data["sample_sequence"] = data.groupby("sample_id", sort=False).cumcount()

    # Validate the invariants expected by downstream analysis.
    assert data["value"].notna().all()
    assert data["datetime"].dt.tz is not None
    assert not data.duplicated().any()

    report = {
        "rows": int(len(data)),
        "columns": int(len(data.columns)),
        "date_min": str(data["date"].min()),
        "date_max": str(data["date"].max()),
        "duplicate_sample_ids": int(data["sample_id"].duplicated().sum()),
        "timestamp_collisions": int(data.duplicated(["datetime"]).sum()),
        "missing_values": {k: int(v) for k, v in data.isna().sum().items() if v},
        "quality_flags": {k: int(v) for k, v in data["quality_flag"].value_counts().items()},
        "units": {k: int(v) for k, v in data["value_unit"].value_counts().items()},
    }
    QUALITY_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(TARGET, index=False)
    print(f"Wrote {len(data):,} rows and {len(data.columns)} columns to {TARGET}")
    print(f"Quality report: {QUALITY_REPORT}")
    print(f"Date range: {data['date'].min()} to {data['date'].max()}")
    print(f"Categories: {', '.join(sorted(data['category'].unique()))}")


if __name__ == "__main__":
    main()
