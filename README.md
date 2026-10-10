# Análisis del sistema eléctrico español

Proyecto de análisis de datos de Red Eléctrica de España (REE) para el
periodo 2019–2025. Su objetivo es estudiar la transición energética desde
cuatro perspectivas: generación por tecnología, demanda, equilibrio
territorial e intercambios internacionales.

El proyecto responde preguntas sobre la evolución de las renovables, el peso
de las tecnologías emisoras, el rendimiento aparente de la potencia instalada,
el balance entre generación y demanda por comunidad y la posición importadora
o exportadora de España.

## Tecnologías utilizadas

- Python, pandas y PyArrow: limpieza, transformación y lectura del dataset.
- InfluxDB 2.7: almacenamiento de series temporales y consultas Flux.
- Grafana 12.1: dashboards interactivos y visualización de resultados.
- Docker Compose: despliegue reproducible de todos los servicios.

El dataset analítico se encuentra en
`ree_data/data/dataset_ree_limpio_transicion_energetica_2019_2025.parquet`.
El CSV equivalente está en `ree_data/data/`.

## Requisitos

- Docker Engine.
- Docker Compose v2.
- Git, si se clona el proyecto desde un repositorio.

Para regenerar el dataset desde los ficheros originales también se necesita
Python 3.12 o superior y las dependencias de `BDA/requirements.txt`.

## Despliegue

1. Clonar el proyecto y acceder a su directorio:

   ```bash
   git clone <URL_DEL_REPOSITORIO>
   cd Reto0_Grupo3
   ```

2. Crear la configuración local:

   ```bash
   cp .env.example .env
   ```

3. Editar `.env` y establecer, como mínimo, valores seguros para:

   ```env
   INFLUX_WRITE_TOKEN=token-de-administracion
   INFLUX_INIT_PASSWORD=contraseña-de-influxdb
   GRAFANA_ADMIN_PASSWORD=contraseña-de-grafana
   ```

   Las contraseñas de `GRAFANA_BOOTSTRAP_USERS` son opcionales. El fichero
   `.env` contiene credenciales y no debe subirse al repositorio.

4. Construir las imágenes y arrancar los servicios:

   ```bash
   docker compose up -d --build
   ```

   El arranque inicial crea InfluxDB, carga el dataset, genera un token de
   lectura para Grafana y provisiona los dashboards y usuarios configurados.

## Acceso

- Grafana: <http://localhost:3000>
- InfluxDB: <http://localhost:8086>

El usuario administrador y su contraseña son los definidos en `.env`. Los
usuarios adicionales se configuran con el formato:

```env
GRAFANA_BOOTSTRAP_USERS=login|email|password|equipo|dashboard;...
```

Los equipos válidos son `Direccion`, `Analisis` e `IT`. El equipo `Analisis`
solo recibe los dashboards indicados en `GRAFANA_ANALYSIS_DASHBOARD_UIDS`.

## Comandos habituales

Ver el estado de los servicios:

```bash
docker compose ps
```

Ver los registros:

```bash
docker compose logs -f
```

Reiniciar sin reconstruir las imágenes:

```bash
docker compose up -d
```

Detener los servicios:

```bash
docker compose down
```

Para regenerar el dataset de análisis:

```bash
python -m pip install -r BDA/requirements.txt
python ree_data/download_border_exchanges.py
python ree_data/clean_dataset.py
docker compose up -d --build
```

Los volúmenes de Docker conservan los datos de InfluxDB, Grafana y los
tokens generados entre reinicios.
