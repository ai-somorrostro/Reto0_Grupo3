# Control de calidad e integridad de datos

La ingesta y el análisis aplican estas comprobaciones antes de escribir en
InfluxDB:

- Cada fila del dataset histórico recibe un `sample_id` estable calculado a
  partir del timestamp, indicador, geografía, tecnología, frontera y valor.
  El timestamp deja de utilizarse como identificador único.
- Se conservan las muestras que comparten timestamp. El informe distingue
  entre `timestamp_collisions` y `duplicate_sample_ids`, de modo que una
  coincidencia temporal no se interpreta como una pérdida.
- Las unidades se normalizan según el endpoint: potencia instalada en `MW` y
  energía, demanda e intercambios en `MWh`.
- Se validan valores numéricos, finitos, negativos no permitidos para demanda
  y generación, y porcentajes entre 0 y 100. Los valores sospechosos quedan
  marcados en `quality_flag` y no se borran silenciosamente.
- Node-RED valida las muestras en tiempo real y añade `muestra` como etiqueta
  en la copia de auditoría `generacion_ingestion`. Esto evita que dos puntos
  escritos durante el mismo milisegundo se sobrescriban en InfluxDB.
- El flujo registra `values_count`, `valid_count` e `invalid_count` por
  consulta y continúa funcionando aunque una muestra concreta sea inválida.

## Evidencias generadas

Al ejecutar:

```bash
python ree_data/clean_dataset.py
```

se genera `ree_data/data/dataset_ree_calidad.json`, con recuentos de filas,
colisiones temporales, identificadores duplicados, nulos, unidades y estados
de calidad. El cargador de pandas detiene la carga si faltan las columnas de
calidad o si existen identificadores duplicados.
