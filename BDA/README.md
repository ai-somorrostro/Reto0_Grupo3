# BDA · REE transición energética 2019–2025

Artefactos de Big Data Aplicado para cargar los resultados de P1–P7 en InfluxDB 2.x y visualizarlos en Grafana. El flujo operativo se ejecuta con el `docker-compose.yml` de la raíz; el Dockerfile del loader está en `PIA/Dockerfile`.

## Alcance y decisiones

- P0 es un control de calidad previo; las preguntas de negocio desarrolladas son P1–P7.
- La unidad publicada es `ree_analisis` con tags `pregunta`, `metrica`, `tecnologia`, `territorio` y `pais`, y el field numérico `valor`.
- Se publican resultados agregados, no el CSV bruto completo: reduce cardinalidad y hace las consultas de Grafana más sencillas.
- Navarra, Comunidad de Madrid y Región de Murcia se excluyen del análisis territorial hasta validar sus registros con REE.
- Las conclusiones sobre P5 son balances territoriales (`generación - demanda`), no exportaciones físicas; P6 se interpreta como asociación, no causalidad.

## Ficheros

| Ruta | Uso |
|---|---|
| `03_analisis_preguntas_REE_para_Influx_Grafana.ipynb` | Análisis exploratorio y gráficos; no forma parte del flujo operativo |
| `04_REE_InfluxDB_Grafana.ipynb` | Notebook conservado como apoyo; no forma parte del flujo operativo |
| `scripts/export_line_protocol.py` | Valida la tabla maestra y crea line protocol para ingesta automatizada |
| `scripts/load_ree_parquet.py` | Lee el parquet, calcula P1–P7 y escribe en InfluxDB 2.x |
| `grafana/mcp-config.example.json` | Cliente MCP de Grafana para consultas, dashboards y alertas |
| `node-red/flows_ree_influx.json` | Flujo Node-RED de ingesta por lote/recarga hacia InfluxDB 2.x |
| `grafana/dashboards/ree-transicion-energetica.json` | Dashboard provisionable con 14 paneles, filtros y alertas |
| `grafana/provisioning/` | Datasource y dashboard provider para el compose |

## Flujo recomendado

1. Copiar `.env.example` a `.env` en la raíz del proyecto y completar las variables. No crear un `.env` dentro de `BDA`.
2. Ejecutar `python BDA/scripts/load_ree_parquet.py` para calcular y cargar P1–P7 directamente desde el parquet.
3. Configurar en Grafana la organización, el datasource Flux de InfluxDB 2.x y el token de lectura.
4. Conectar `grafana/mcp-config.example.json` a un cliente MCP con un token de cuenta de servicio.
5. Pedir al MCP que cree la carpeta y publique/actualice el dashboard P1–P7, valide las consultas y cree las alertas.
6. Crear manualmente en Grafana los usuarios, equipos y miembros; después pedir al MCP que compruebe sus roles y permisos.
7. El flujo Node-RED queda disponible para recargas/batches posteriores; no contiene credenciales.

## Prueba local sin Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r BDA/requirements.txt
cp .env.example .env
python BDA/scripts/load_ree_parquet.py
```

El servicio InfluxDB 2.x debe estar disponible en `http://localhost:8086` para la prueba local. El script acepta `REE_RESULTADOS_CSV` y `REE_LINE_PROTOCOL_OUT`. Las credenciales se suministran por variables de entorno; no se guardan en Git.

## Docker Compose

```bash
cp .env.example .env
# Completar INFLUX_WRITE_TOKEN e INFLUX_READ_TOKEN en .env
docker compose up --build
```

InfluxDB crea el bucket `ree_analisis` durante el setup inicial. El loader espera el healthcheck de InfluxDB, escribe usando `INFLUX_WRITE_TOKEN` y termina antes de que arranque Grafana. Grafana usa únicamente `INFLUX_READ_TOKEN`. Dentro de la red Compose los servicios se conectan mediante `http://influxdb:8086`; desde el host Grafana queda disponible en `http://localhost:3000`.

## InfluxDB 2.x y Grafana MCP

El reto se implementa con la API Flux de InfluxDB 2.x porque el PDF exige buckets, tokens, tags y consultas Flux. Grafana se conecta a InfluxDB 2.x mediante el datasource provisionado. El MCP oficial de Grafana se configura con `BDA/grafana/mcp-config.example.json` y un token de cuenta de servicio externo; no se guardan credenciales en este repositorio.

## Permisos que debe aplicar Grafana

- `directiva`: lectura de todos los dashboards y sin edición.
- `analisis`: lectura únicamente de los dashboards que el equipo decida asignar y acceso inicial al panel correspondiente.
- `it`: lectura y edición de todos los dashboards.
- Crear tokens distintos de lectura y escritura para InfluxDB. El dashboard debe usar solo el token de lectura.

El MCP de Grafana no expone actualmente operaciones de alta de usuarios, creación de equipos o adición de miembros. Sí expone lectura de usuarios/equipos/roles/permisos y operaciones de dashboards, carpetas, consultas InfluxDB y alertas. Por eso esas altas se hacen una sola vez desde la interfaz de Grafana; el resto del trabajo se realiza mediante MCP.

## Validación rápida

```powershell
python -m json.tool node-red/flows_ree_influx.json > $null
python -m json.tool grafana/dashboards/ree-transicion-energetica.json > $null
```

El datasource y el provider son YAML y deben montarse en las rutas de provisioning de Grafana.
