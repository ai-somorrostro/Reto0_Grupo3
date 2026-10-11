FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY BDA/scripts /app/BDA/scripts
COPY ree_data/data/dataset_ree_limpio_transicion_energetica_2019_2025.parquet \
     /app/ree_data/data/dataset_ree_limpio_transicion_energetica_2019_2025.parquet

CMD ["python", "BDA/scripts/load_ree_parquet.py"]
