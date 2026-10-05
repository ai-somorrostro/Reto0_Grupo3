"""Create the analysis-ready REE parquet used by the project."""

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data" / "datos_ree_originales_2019_2025.parquet"
EXCHANGES = ROOT / "data" / "intercambios_ree_por_frontera_2019_2025.parquet"
TARGET = ROOT / "data" / "dataset_ree_limpio_transicion_energetica_2019_2025.parquet"


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
    data["value_unit"] = data["endpoint"].map(
        lambda endpoint: "MW" if endpoint.startswith("potencia_") else "MWh"
    )
    data["quality_flag"] = "ok"
    suspicious_generation = (
        data["category"].eq("generacion")
        & data["endpoint"].isin([
            "estructura_generacion",
            "estructura_generacion_emisiones",
        ])
        & data["value"].lt(0)
    )
    data.loc[suspicious_generation, "quality_flag"] = "revisar_valor_negativo"

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

    # Validate the invariants expected by downstream analysis.
    assert data["value"].notna().all()
    assert data["percentage"].notna().all()
    assert data["datetime"].dt.tz is not None
    assert not data.duplicated().any()

    TARGET.parent.mkdir(parents=True, exist_ok=True)
    data.to_parquet(TARGET, index=False)
    print(f"Wrote {len(data):,} rows and {len(data.columns)} columns to {TARGET}")
    print(f"Date range: {data['date'].min()} to {data['date'].max()}")
    print(f"Categories: {', '.join(sorted(data['category'].unique()))}")


if __name__ == "__main__":
    main()
