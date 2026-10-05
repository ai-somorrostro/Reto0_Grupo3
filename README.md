# Reto 0 - Grupo 3

## Propósito del estudio

Este dataset se estudia para analizar la evolución del sistema eléctrico
español entre 2019 y 2025: cómo cambia la demanda, qué tecnologías aportan la
generación, cuánto pesa la generación renovable y cómo evoluciona el balance y
el intercambio de electricidad entre España y otros países. La dimensión
territorial permite comparar el comportamiento de las comunidades autónomas,
Ceuta, Melilla y el sistema eléctrico.

Este propósito permite formular preguntas como:

- ¿Cómo ha evolucionado la demanda mensual por territorio?
- ¿Qué tecnologías explican el cambio en la generación y cuál es la proporción
  renovable?
- ¿Qué territorios dependen más de una tecnología concreta?
- ¿España es importadora o exportadora neta y cómo cambia ese saldo con el
  tiempo?

## Dataset limpiado

El fichero de análisis es
`ree_data/data/dataset_ree_limpio_transicion_energetica_2019_2025.parquet`.

Para los intercambios se descargan por separado Francia, Portugal, Marruecos
y Andorra. Los endpoints agregados `todas-fronteras-fisicos` y
`todas-fronteras-programados` no se incorporan al fichero final porque no
identifican de forma fiable el país en cada fila. La descarga específica se
puede repetir con:

```bash
python ree_data/download_border_exchanges.py
python ree_data/clean_dataset.py
```

Se conservan las categorías `demanda`, `generacion`, `balance` e
`intercambios`. Se excluyen `mercados` y `transporte` porque responden a otras
preguntas y mezclan métricas operativas distintas.

Campos conservados:

| Campo | Uso |
|---|---|
| `datetime`, `date`, `year`, `month` | Análisis temporal |
| `time_granularity` | Distinguir datos diarios y mensuales |
| `geography_type`, `geography_name`, `border`, `system` | Comparación territorial y por frontera |
| `category`, `endpoint` | Tipo de medida y fuente temática |
| `indicator_id`, `indicator_type`, `indicator_name` | Indicador analizado |
| `technology_id`, `technology_name` | Tecnología o componente |
| `value`, `value_unit`, `percentage` | Medida numérica, unidad y proporción |
| `quality_flag` | Marca valores de generación negativos para revisión |

La fecha se recalcula convirtiendo `datetime` de UTC a `Europe/Madrid`. El
fichero original registraba, por ejemplo, las 23:00 UTC como el día anterior,
lo que desplazaba las columnas `date`, `year` y `month`.

`value_unit` se deriva del endpoint: la potencia instalada se expresa en MW y
el resto de medidas eléctricas en MWh. `percentage` se conserva como proporción
entre 0 y 1. Los valores negativos detectados en algunos registros de
generación no se modifican; quedan marcados como `revisar_valor_negativo` para
no ocultar datos publicados que requieren una decisión metodológica.

Para regenerarlo:

```bash
python ree_data/clean_dataset.py
```
