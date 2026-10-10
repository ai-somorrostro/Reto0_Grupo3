"""Build P1-P7 from the REE parquet and write them to InfluxDB 2.x.

The notebooks are intentionally not used by this pipeline. All connection
settings come from BDA/.env or the process environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS


ROOT = Path(__file__).resolve().parents[1]
# The deployment owns one project-level .env. BDA/.env is intentionally ignored.
load_dotenv(ROOT.parent / ".env")
DATASET = Path(os.getenv("REE_PARQUET", ROOT.parent / "ree_data" / "data" / "dataset_ree_limpio_transicion_energetica_2019_2025.parquet"))
MEASUREMENT = os.getenv("INFLUX_MEASUREMENT", "ree_analisis")
def national(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    return df.groupby(date_col, as_index=False, dropna=False)["value"].sum()


def rows(frame: pd.DataFrame, question: str, metric: str, *, technology: str = "", territory_col: str | None = None, country: str = "") -> pd.DataFrame:
    out = frame[["date", "value"]].copy()
    out["pregunta"] = question
    out["metrica"] = metric
    out["tecnologia"] = technology
    out["territorio"] = frame[territory_col].fillna("") if territory_col else ""
    out["pais"] = country
    out["valor"] = pd.to_numeric(out.pop("value"), errors="coerce")
    return out[["date", "pregunta", "metrica", "tecnologia", "territorio", "pais", "valor"]].dropna(subset=["date", "valor"])


def build(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["quality_flag"].fillna("ok").eq("ok") & df["date"].notna()].copy()
    df["year"] = df["date"].dt.year
    df["month_date"] = df["date"].dt.to_period("M").dt.to_timestamp()
    result: list[pd.DataFrame] = []

    # P1: renewable and nuclear components of zero-emission generation.
    renewable = df[(df.endpoint == "estructura_renovables") & (df.indicator_name == "Generación renovable")].groupby("month_date", as_index=False).value.sum().rename(columns={"month_date": "date"})
    nuclear = df[(df.endpoint == "estructura_generacion") & (df.indicator_name == "Nuclear")].groupby("month_date", as_index=False).value.sum().rename(columns={"month_date": "date"})
    p1 = renewable.merge(nuclear, on="date", how="outer", suffixes=("_renewable", "_nuclear")).fillna(0)
    p1["value"] = p1.value_renewable; result.append(rows(p1, "P1", "Generación renovable", technology="Renovable"))
    p1["value"] = p1.value_nuclear; result.append(rows(p1, "P1", "Generación nuclear", technology="Nuclear"))
    p1["value"] = p1.value_renewable + p1.value_nuclear; result.append(rows(p1, "P1", "Sin emisiones total"))
    p1["value"] = (p1.value_renewable / p1["value"].replace(0, pd.NA)).fillna(0); result.append(rows(p1, "P1", "Participación renovable en sin emisiones"))

    # P2: renewable share versus emissions.
    p2 = df[df.endpoint.isin(["evolucion_renovable_no_renovable", "evolucion_generacion_emisiones"])].copy()
    p2 = p2[p2.indicator_name.isin(["Renovable", "Con emisiones de CO2 eq."])].groupby(["month_date", "indicator_name"], as_index=False).value.sum()
    p2 = p2.pivot(index="month_date", columns="indicator_name", values="value").fillna(0).reset_index().rename(columns={"month_date": "date"})
    p2["value"] = p2.get("Renovable", 0); result.append(rows(p2, "P2", "Generación renovable"))
    p2["value"] = p2.get("Con emisiones de CO2 eq.", 0); result.append(rows(p2, "P2", "Generación con emisiones"))
    p2["value"] = (p2.get("Renovable", 0) / (p2.get("Renovable", 0) + p2.get("Con emisiones de CO2 eq.", 0)).replace(0, pd.NA)).fillna(0); result.append(rows(p2, "P2", "Participación renovable"))

    # P3: annual generation, accumulated growth and interannual variability.
    p3 = df[(df.endpoint == "estructura_generacion") & (df.value_unit == "MWh")].groupby(["year", "indicator_name"], as_index=False).value.sum()
    p3 = p3.sort_values(["indicator_name", "year"])
    p3["growth_acumulado"] = p3.groupby("indicator_name").value.transform(lambda s: (s / s.iloc[0] - 1).replace([float("inf"), -float("inf")], pd.NA).fillna(0))
    p3["yoy"] = p3.groupby("indicator_name").value.pct_change().fillna(0)
    p3["date"] = pd.to_datetime(p3.year.astype(str) + "-01-01")
    p3["value"] = p3.value; result.append(rows(p3, "P3", "Generación anual", technology=p3.indicator_name))
    p3["value"] = p3.growth_acumulado; result.append(rows(p3, "P3", "Crecimiento acumulado", technology=p3.indicator_name))
    p3["value"] = p3.yoy; result.append(rows(p3, "P3", "Variación interanual", technology=p3.indicator_name))
    volatility = p3.groupby("indicator_name").yoy.transform("std").fillna(0); p3["value"] = volatility; result.append(rows(p3, "P3", "Desviación variación interanual", technology=p3.indicator_name))

    # P4: annual generation per installed MW for wind and photovoltaic solar.
    gen = df[(df.endpoint == "estructura_generacion") & df.indicator_name.isin(["Eólica", "Solar fotovoltaica"])].groupby(["year", "indicator_name"], as_index=False).value.sum().rename(columns={"value": "generation"})
    power = df[(df.endpoint == "potencia_instalada") & df.indicator_name.isin(["Eólica", "Solar fotovoltaica"])].groupby(["year", "indicator_name"], as_index=False).value.mean().rename(columns={"value": "power"})
    p4 = gen.merge(power, on=["year", "indicator_name"], how="inner"); p4["date"] = pd.to_datetime(p4.year.astype(str) + "-01-01")
    p4["value"] = p4.generation; result.append(rows(p4, "P4", "Generación", technology=p4.indicator_name))
    p4["value"] = p4.power; result.append(rows(p4, "P4", "Potencia instalada", technology=p4.indicator_name))
    p4["value"] = p4.generation / p4.power.replace(0, pd.NA); result.append(rows(p4, "P4", "MWh por MW instalado", technology=p4.indicator_name))

    # P5: generation-demand balance by territory.
    gen5 = df[(df.endpoint == "estructura_generacion") & (df.indicator_name == "Generación total")].groupby(["year", "geography_name"], as_index=False).value.sum().rename(columns={"value": "generation"})
    dem5 = df[(df.endpoint == "demanda_evolucion") & (df.indicator_name == "Demanda")].groupby(["year", "geography_name"], as_index=False).value.sum().rename(columns={"value": "demand"})
    p5 = gen5.merge(dem5, on=["year", "geography_name"], how="inner"); p5["date"] = pd.to_datetime(p5.year.astype(str) + "-01-01")
    p5["value"] = p5.generation - p5.demand; result.append(rows(p5, "P5", "Saldo generación-demanda", territory_col="geography_name"))
    p5["value"] = p5.generation / p5.demand.replace(0, pd.NA); result.append(rows(p5, "P5", "Ratio generación-demanda", territory_col="geography_name"))
    p5["value"] = p5.generation; result.append(rows(p5, "P5", "Generación total", territory_col="geography_name"))
    p5["value"] = p5.demand; result.append(rows(p5, "P5", "Demanda", territory_col="geography_name"))

    # P6: monthly changes in hydro and emitting generation.
    hydro = df[(df.endpoint == "estructura_generacion") & (df.indicator_name == "Hidráulica")].groupby("month_date", as_index=False).value.sum().rename(columns={"month_date": "date", "value": "hydro"})
    emissions = df[(df.endpoint == "evolucion_generacion_emisiones") & (df.indicator_name == "Con emisiones de CO2 eq.")].groupby("month_date", as_index=False).value.sum().rename(columns={"month_date": "date", "value": "emissions"})
    p6 = hydro.merge(emissions, on="date", how="outer").sort_values("date").fillna(0); p6["hydro_change"] = p6.hydro.diff().fillna(0); p6["emissions_change"] = p6.emissions.diff().fillna(0)
    p6["value"] = p6.hydro; result.append(rows(p6, "P6", "Generación hidráulica"))
    p6["value"] = p6.emissions; result.append(rows(p6, "P6", "Generación con emisiones"))
    p6["value"] = p6.hydro_change; result.append(rows(p6, "P6", "Variación hidráulica"))
    p6["value"] = p6.emissions_change; result.append(rows(p6, "P6", "Variación con emisiones"))

    # P9: monthly generation mix by territory and technology.
    # Keep the technology in the tag so Grafana can draw one series per energy
    # source after the user changes the territory selector.
    p9 = df[
        (df.endpoint == "estructura_generacion")
        & (df.indicator_name != "Generación total")
        & df.geography_name.notna()
        & df.indicator_name.notna()
    ].groupby(["month_date", "geography_name", "indicator_name"], as_index=False).value.sum()
    p9 = p9.rename(columns={"month_date": "date", "indicator_name": "technology", "value": "generation"})
    p9["value"] = p9.generation
    result.append(rows(p9, "P9", "Generación mensual por tecnología", technology=p9.technology, territory_col="geography_name"))
    p9["value"] = p9.generation.groupby([p9.geography_name, p9.technology]).transform("sum")
    result.append(rows(p9, "P9", "Generación acumulada por tecnología", technology=p9.technology, territory_col="geography_name"))

    # P7: physical daily balance by international interconnection.
    countries = {"francia": "Francia", "portugal": "Portugal", "marruecos": "Marruecos", "andorra": "Andorra"}
    for key, country in countries.items():
        p7 = df[(df.endpoint == f"intercambios_{key}_fisicos") & df.indicator_name.isin(["Importación", "Exportación", "saldo"])].copy()
        p7 = p7.groupby(["date", "indicator_name"], as_index=False).value.sum().pivot(index="date", columns="indicator_name", values="value").fillna(0).reset_index()
        p7["value"] = p7.get("saldo", p7.get("Exportación", 0) - p7.get("Importación", 0)); result.append(rows(p7, "P7", "Saldo", country=country))
        for metric in ["Importación", "Exportación"]:
            if metric in p7: p7["value"] = p7[metric]; result.append(rows(p7, "P7", metric, country=country))

    # P8: monthly demand and seasonality, both by territory and nationally.
    p8 = df[(df.endpoint == "demanda_evolucion") & (df.indicator_name == "Demanda")].copy()
    p8 = p8.groupby(["month_date", "geography_name"], as_index=False).value.sum().rename(columns={"month_date": "date", "value": "demand"})
    p8 = p8.sort_values(["geography_name", "date"])
    p8["value"] = p8.demand; result.append(rows(p8, "P8", "Demanda mensual", territory_col="geography_name"))
    p8["value"] = p8.groupby("geography_name").demand.pct_change(12).fillna(0); result.append(rows(p8, "P8", "Variación interanual", territory_col="geography_name"))
    p8["value"] = p8.demand / p8.groupby("geography_name").demand.transform("mean").replace(0, pd.NA); result.append(rows(p8, "P8", "Índice estacional", territory_col="geography_name"))

    national_p8 = p8.groupby("date", as_index=False).demand.sum().sort_values("date")
    national_p8["territorio"] = "Nacional"
    national_p8["value"] = national_p8.demand; result.append(rows(national_p8, "P8", "Demanda nacional", territory_col="territorio"))
    national_p8["value"] = national_p8.demand.pct_change(12).fillna(0); result.append(rows(national_p8, "P8", "Variación interanual", territory_col="territorio"))
    national_p8["value"] = national_p8.demand / national_p8.demand.mean(); result.append(rows(national_p8, "P8", "Índice estacional", territory_col="territorio"))

    output = pd.concat(result, ignore_index=True)
    output["valor"] = pd.to_numeric(output["valor"], errors="coerce")
    return output.dropna(subset=["date", "valor"])


def main() -> None:
    required = ["INFLUX_URL", "INFLUX_ORG", "INFLUX_BUCKET", "INFLUX_WRITE_TOKEN"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise SystemExit(f"Faltan variables de entorno: {', '.join(missing)}")
    if not DATASET.exists():
        raise SystemExit(f"No existe el parquet: {DATASET}")
    source = pd.read_parquet(DATASET)
    result = build(source)
    result.to_csv(ROOT / "ree_resultados_p1_p7.csv", index=False, encoding="utf-8")
    with InfluxDBClient(url=os.environ["INFLUX_URL"], token=os.environ["INFLUX_WRITE_TOKEN"], org=os.environ["INFLUX_ORG"]) as client:
        writer = client.write_api(write_options=SYNCHRONOUS)
        points = []
        for row in result.itertuples(index=False):
            point = Point(MEASUREMENT).tag("pregunta", row.pregunta).tag("metrica", row.metrica).tag("tecnologia", row.tecnologia or "sin_valor").tag("territorio", row.territorio or "sin_valor").tag("pais", row.pais or "sin_valor").field("valor", float(row.valor)).time(row.date.to_pydatetime(), WritePrecision.NS)
            points.append(point)
        for start in range(0, len(points), 5000):
            writer.write(bucket=os.environ["INFLUX_BUCKET"], record=points[start:start + 5000])
    print(f"Cargados {len(result)} puntos en {MEASUREMENT} desde {DATASET}")


if __name__ == "__main__":
    main()
