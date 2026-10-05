"""Download only the country-specific exchange endpoints."""

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

from scraper_ree import (
    BASE_DIR,
    build_url,
    flatten_payload,
    get_json,
    load_config,
    normalize,
    setup_logging,
    yearly_dates,
)


OUTPUT = BASE_DIR / "data" / "intercambios_ree_por_frontera_2019_2025.parquet"


def main() -> None:
    config = load_config()
    logger = setup_logging()
    endpoints = [
        endpoint for endpoint in config["system_endpoints"]
        if endpoint["name"].startswith("intercambios_")
        and endpoint.get("border")
    ]
    rows = []
    session = requests.Session()
    try:
        for year in range(config["start_year"], config["end_year"] + 1):
            start_date, end_date = yearly_dates(year)
            for endpoint in endpoints:
                url = build_url(config["base_url"], endpoint, start_date, end_date, None)
                status, payload, error = get_json(session, url, logger)
                if status != 200 or payload is None:
                    raise RuntimeError(
                        f"Falló {endpoint['name']} ({year}): HTTP {status} - {error}"
                    )
                rows.extend(flatten_payload(
                    payload,
                    endpoint,
                    None,
                    url,
                    datetime.now(timezone.utc).isoformat(),
                ))
                logger.info("OK | %s | %s | filas=%s", endpoint["name"], year, len(rows))
    finally:
        session.close()

    result = normalize(pd.DataFrame(rows))
    result.to_parquet(OUTPUT, index=False)
    print(f"Wrote {len(result):,} border rows to {OUTPUT}")
    print("Borders:", ", ".join(sorted(result["border"].dropna().unique())))


if __name__ == "__main__":
    main()
