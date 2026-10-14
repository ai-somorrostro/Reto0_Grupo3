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
- Node-RED: integración de datos de ESIOS con InfluxDB.
- Docker Compose: despliegue reproducible de los servicios.

El dataset analítico se encuentra en
`ree_data/data/dataset_ree_limpio_transicion_energetica_2019_2025.parquet`.
El CSV equivalente está en `ree_data/data/`.

## Estructura del proyecto

```text
.
├── BDA/
│   ├── grafana/       Dashboards y configuración de Grafana.
│   ├── node-red/      Flujo de integración con ESIOS.
│   └── scripts/       Carga de datos y configuración de InfluxDB y Grafana.
├── MIA/               Memoria del proyecto.
├── PIA/               Imagen Docker para cargar el dataset.
├── SBD/               Material de la asignatura
├── ree_data/          Descarga, limpieza y datos de REE.
├── requirements.txt   Dependencias Python del proyecto.
├── opencode.json      Conexión de OpenCode al MCP de Grafana.
├── docker-compose.yml Orquestación de InfluxDB, Grafana, Node-RED y cargador.
└── .env.example       Plantilla de configuración local.
```

## Requisitos

- Docker Engine.
- Docker Compose v2.
- Git, si se clona el proyecto desde un repositorio.

Para regenerar el dataset desde los ficheros originales también se necesita
Python 3.12 o superior y las dependencias de `requirements.txt`.

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

3. El arranque local funciona con los valores de desarrollo de `.env.example`,
   sin cuentas externas ni claves de API. Antes de exponer el proyecto en una
   red compartida, cambia las contraseñas y el token local de InfluxDB:

   ```env
   INFLUX_WRITE_TOKEN=un-token-local-seguro
   INFLUX_INIT_PASSWORD=una-clave-segura
   GRAFANA_ADMIN_PASSWORD=otra-clave-segura
   ```

   `ESIOS_TOKEN` solo es necesario para recibir datos en tiempo real desde la
   API de ESIOS/REE; los demás servicios y el MCP funcionan sin él. Los valores
   de ejemplo son para desarrollo local, no para un despliegue expuesto.
   Las contraseñas de `GRAFANA_BOOTSTRAP_USERS` y la configuración SMTP son
   opcionales. El fichero `.env` está excluido de Git.

4. Construir las imágenes y arrancar los servicios:

   ```bash
   docker compose up -d --build
   ```

   El arranque inicial crea InfluxDB, carga el dataset, genera los tokens
   necesarios en volúmenes Docker y provisiona los dashboards, usuarios y el
   servidor MCP de Grafana. No es necesario copiar tokens al `.env`.

## Acceso

- Grafana: <http://localhost:3000>
- InfluxDB: <http://localhost:8086>
- Node-RED: <http://localhost:1880>

El usuario administrador y su contraseña son los definidos en `.env`. Los
usuarios adicionales se configuran con el formato:

```env
GRAFANA_BOOTSTRAP_USERS=login|email|password|equipo|dashboard;...
```

Los equipos válidos son `Direccion`, `Analisis` e `IT`. El equipo `Analisis`
solo recibe los dashboards indicados en `GRAFANA_ANALYSIS_DASHBOARD_UIDS`.

En Node-RED, abre la pestaña **ESIOS tiempo real** para ver el flujo y el panel
**Debug** para inspeccionar las respuestas de la API y los errores. El flujo
consulta 15 indicadores cada minuto y escribe los valores recibidos en
InfluxDB; ESIOS puede publicar los datos con retraso.

## Servidor MCP de Grafana

El servidor se inicia con `docker compose up -d --build`. Para abrir OpenCode
con el token MCP generado automáticamente, ejecuta desde la raíz:

```bash
MCP_GRAFANA_TOKEN="$(docker compose exec -T mcp-grafana cat /run/mcp-secrets/MCP_SERVER_TOKEN)" opencode
```

### Alertas de Grafana

Grafana provisiona automáticamente la alerta `ESIOS sin datos recientes`. Se
activa si no se registra ninguna consulta correcta de Node-RED en InfluxDB
durante 10 minutos y envía un correo mediante Gmail:

También se provisiona la alerta `Demanda real baja en España`, que se activa
cuando la demanda media de los últimos 5 minutos permanece por debajo de
30.000 MW durante 15 minutos. El umbral se puede ajustar en
`BDA/grafana/provisioning/alerting/ree-alerting.yml`.

```env
GF_SMTP_ENABLED=true
GF_SMTP_HOST=smtp.gmail.com:587
GF_SMTP_USER=cuenta-que-envia@gmail.com
GF_SMTP_PASSWORD=contraseña-de-aplicación
GF_SMTP_FROM_ADDRESS=cuenta-que-envia@gmail.com
GRAFANA_ALERT_EMAIL=destinatario@gmail.com
```

La cuenta de Google debe tener activada la verificación en dos pasos y se debe
usar una contraseña de aplicación, no la contraseña habitual. Después de
cambiar estas variables, reinicia Grafana con
`docker compose up -d --force-recreate grafana`.

## Solución de problemas

- **Docker no puede cargar la configuración:** confirma que `.env` existe y
  ejecuta `docker compose config` para detectar errores de YAML o variables.
- **Un servicio no arranca o aparece `unhealthy`:** consulta
  `docker compose ps -a` y `docker compose logs <servicio>`. Revisa también que
  Docker Engine esté en ejecución y que `.env` exista.
- **No se puede abrir un servicio:** comprueba que sus puertos estén libres:
  Grafana `3000`, InfluxDB `8086`, Node-RED `1880` y MCP `8000`.
- **No llegan datos en tiempo real:** configura `ESIOS_TOKEN` en `.env` y
  revisa los logs de Node-RED con `docker compose logs node-red`. El token solo
  es necesario para la API de ESIOS.
- **No aparecen datos, dashboards o alertas en Grafana:** revisa los logs de
  `loader`, `grafana-bootstrap` y `grafana`; confirma que la carga de datos
  terminó correctamente y que InfluxDB está healthy.
- **No se envían alertas por correo:** configura las variables SMTP y
  `GRAFANA_ALERT_EMAIL` en `.env`, y reinicia Grafana.
- **Las credenciales cambiadas no se aplican:** InfluxDB y Grafana guardan su
  configuración en volúmenes persistentes. `docker compose down -v` los
  reinicia, pero también elimina los datos guardados.
