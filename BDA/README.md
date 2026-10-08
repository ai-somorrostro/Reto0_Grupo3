# BDA · REE transición energética 2019–2025

Artefactos de Big Data Aplicado para cargar los resultados de P0–P7 en InfluxDB y visualizarlos en Grafana. El `docker-compose` general del proyecto queda fuera de esta carpeta y deberá montar/provisionar estos ficheros.

## Alcance y decisiones

- P0 es un control de calidad previo; las preguntas de negocio desarrolladas son P1–P7.
- La unidad publicada es `ree_analisis` con tags `pregunta`, `metrica`, `tecnologia`, `territorio` y `pais`, y el field numérico `valor`.
- Se publican resultados agregados, no el CSV bruto completo: reduce cardinalidad y hace las consultas de Grafana más sencillas.
- Navarra, Comunidad de Madrid y Región de Murcia se excluyen del análisis territorial hasta validar sus registros con REE.
- Las conclusiones sobre P5 son balances territoriales (`generación - demanda`), no exportaciones físicas; P6 se interpreta como asociación, no causalidad.

## Ficheros

| Ruta | Uso |
|---|---|
| `03_analisis_preguntas_REE_para_Influx_Grafana.ipynb` | Análisis exploratorio y gráficos de las 7 preguntas |
| `04_REE_InfluxDB_Grafana.ipynb` | Preparación de la tabla maestra y escritura opcional en InfluxDB 2.x |
| `scripts/export_line_protocol.py` | Valida la tabla maestra y crea line protocol para ingesta automatizada |
| `scripts/load_ree_parquet.py` | Lee el parquet, calcula P1–P7 y escribe en InfluxDB 2.x |
| `grafana/mcp-config.example.json` | Cliente MCP de Grafana para consultas, dashboards y alertas |
| `node-red/flows_ree_influx.json` | Flujo Node-RED de ingesta por lote/recarga hacia InfluxDB 2.x |
| `grafana/dashboards/ree-transicion-energetica.json` | Dashboard provisionable con 14 paneles, filtros y alertas |
| `grafana/provisioning/` | Datasource y dashboard provider para el compose |

## Flujo recomendado

1. Copiar `BDA/.env.example` a `.env` en la raíz del proyecto y completar las variables con los valores del entorno.
2. Ejecutar `python scripts/load_ree_parquet.py` para calcular y cargar P1–P7 directamente desde el parquet.
3. Configurar en Grafana la organización, el datasource Flux de InfluxDB 2.x y el token de lectura.
4. Conectar `grafana/mcp-config.example.json` a un cliente MCP con un token de cuenta de servicio.
5. Pedir al MCP que cree la carpeta y publique/actualice el dashboard P1–P7, valide las consultas y cree las alertas.
6. Crear manualmente en Grafana los usuarios, equipos y miembros; después pedir al MCP que compruebe sus roles y permisos.
7. El flujo Node-RED queda disponible para recargas/batches posteriores; no contiene credenciales.

## Dependencias locales

```powershell
pip install -r requirements.txt
python scripts/export_line_protocol.py
```

El script acepta `REE_RESULTADOS_CSV` y `REE_LINE_PROTOCOL_OUT`. Las credenciales se suministran por variables de entorno del compose; no se guardan en Git.

## InfluxDB 2.x y Grafana MCP

El reto se implementa con la API Flux de InfluxDB 2.x porque el PDF exige buckets, tokens, tags y consultas Flux. Grafana se conecta a InfluxDB 2.x mediante el datasource provisionado. Si el equipo utiliza un MCP de Grafana, debe configurarse externamente con un token de cuenta de servicio; no se guardan credenciales en este repositorio.

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
