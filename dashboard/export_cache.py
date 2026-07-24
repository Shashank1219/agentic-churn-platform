"""
Writes a small cached snapshot of KPI data for Streamlit to read from
directly as it avoids waking a suspended Snowflake warehouse on
every dashboard page load.
"""

import os
import logging

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = "dashboard/cache"


def _get_connection(schema = "ANALYTICS"):
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE", "TRANSFORMER_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CHURN_WH"),
        database="RETAIL_CHURN_DB",
        schema=schema,
    )


def main():
    load_dotenv()
    os.makedirs(CACHE_DIR, exist_ok=True)

    conn = _get_connection("ANALYTICS")
    predictions = pd.read_sql("""
        SELECT p.customer_id, p.snapshot_date, p.churn_probability, p.risk_band,
               c.country, c.lifetime_revenue,
               r.segment, r.frequency_lifetime
        FROM analytics.churn_predictions p
        JOIN marts.mart_customer_360 c ON p.customer_id = c.customer_id
        JOIN marts.mart_rfm_segments r ON p.customer_id = r.customer_id
    """, conn)
    conn.close()
    predictions.columns = [c.lower() for c in predictions.columns]
    predictions.to_parquet(f"{CACHE_DIR}/churn_predictions.parquet", index=False)
    logger.info(f"Cached {len(predictions)} prediction rows")

    conn = _get_connection("ANALYTICS")
    interventions = pd.read_sql("SELECT * FROM analytics.churn_interventions", conn)
    conn.close()
    interventions.columns = [c.lower() for c in interventions.columns]
    interventions.to_parquet(f"{CACHE_DIR}/churn_interventions.parquet", index=False)
    logger.info(f"Cached {len(interventions)} intervention rows")


if __name__ == "__main__":
    main()