"""
Orchestrates the full agent flow: identifying high-risk customers,
run the three tools per customer, write validated retention incentives.
"""

import os
import logging

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

from agent.tools.tools import (
    tool_query_customer_profile,
    tool_get_churn_explanation,
    tool_generate_retention_incentive,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


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


def get_high_risk_customers():
    """Identify customers with risk_band = 'high'
    from the latest analytics.churn_predictions snapshot."""
    conn = _get_connection("ANALYTICS")
    df = pd.read_sql("""
        SELECT customer_id, snapshot_date, churn_probability
        FROM analytics.churn_predictions
        WHERE risk_band = 'high'
        ORDER BY churn_probability DESC
    """, conn)
    conn.close()
    df.columns = [c.lower() for c in df.columns]
    return df


def write_intervention(incentive, conn):
    """Persist a validated RetentionIncentive to analytics.churn_interventions.
    Only called with output that already passed the Pydantic validation."""
    conn.cursor().execute(
        """
        INSERT INTO analytics.churn_interventions
            (customer_id, discount_pct, channel, product_focus, messaging)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            incentive.customer_id,
            int(incentive.discount_pct),
            incentive.channel.value,
            incentive.product_focus,
            incentive.messaging,
        ),
    )


def run_agent_flow(limit = None):
    """limit caps how many customers to process in one run for testing"""
    load_dotenv()

    high_risk = get_high_risk_customers()
    if limit:
        high_risk = high_risk.head(limit)

    logger.info(f"Processing {len(high_risk)} high-risk customers")

    conn = _get_connection("ANALYTICS")
    succeeded, failed = 0, 0

    for row in high_risk.to_dict("records"):
        customer_id = row["customer_id"]
        snapshot_date = str(row["snapshot_date"])

        try:
            profile = tool_query_customer_profile(customer_id)
        except ValueError as e:
            logger.warning(f"customer_id={customer_id}: no BI profile (likely all-cancelled order history) — skipping. {e}")
            failed += 1
            continue

        try:
            explanation = tool_get_churn_explanation(customer_id, snapshot_date)
            incentive = tool_generate_retention_incentive(profile, explanation)
            write_intervention(incentive, conn)
            conn.commit()
            logger.info(f"customer_id={customer_id}: wrote intervention successfully")
            succeeded += 1
        except Exception as e:
            logger.error(f"customer_id={customer_id}: failed — {e}")
            failed += 1

    conn.close()
    logger.info(f"Done. Succeeded: {succeeded}, Failed: {failed}")


if __name__ == "__main__":
    # Bounded test run 
    run_agent_flow(limit=5)