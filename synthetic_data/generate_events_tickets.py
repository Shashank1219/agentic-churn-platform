"""
Generates label-conditional synthetic clickstream events and support tickets,
timestamped strictly within each snapshot's pre-window.
"""

import os
import logging
import uuid
from datetime import timedelta

import numpy as np
import pandas as pd
import boto3
import snowflake.connector
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

EVENT_TYPES = ["page_view", "product_view", "add_to_cart", "login"]
TICKET_TOPICS = ["shipping", "product_quality", "billing", "returns", "other"]

EVENTS_S3_KEY = "raw/events/synthetic_events.parquet"
TICKETS_S3_KEY = "raw/support_tickets/synthetic_tickets.parquet"


def fetch_snapshot_panel():
    """Read (customer_id, snapshot_date, churned_next_90d) from Snowflake."""
    conn = snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database="RETAIL_CHURN_DB",
        schema="CORE",
    )
    query = """
        SELECT customer_id, snapshot_date, churned_next_90d
        FROM core.churn_feature_panel
    """
    df = pd.read_sql(query, conn)
    conn.close()
    df.columns = [c.lower() for c in df.columns]
    df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
    logger.info(f"Fetched {len(df)} snapshot rows")
    return df


def generate_events(panel, seed: int = 42):
    """Generate synthetic clickstream events in the 90 days before each snapshot.

    label=0 (stable): higher, roughly flat engagement across the window.
    label=1 (churned): engagement decays across the window (fewer events near snapshot_date).
    """
    rng = np.random.default_rng(seed)
    rows = []

    for row in panel.itertuples(index=False):
        window_start = row.snapshot_date - timedelta(days=90)
        is_churn = row.churned_next_90d == 1

        # Split window into 3 x 30-day buckets; sample a per-bucket event rate
        # that trends down for churners, stays flat (with noise) for stable customers.
        if is_churn:
            bucket_lambdas = [rng.poisson(9), rng.poisson(5), rng.poisson(2)]  # early -> late decay
        else:
            base = rng.poisson(7)
            bucket_lambdas = [max(base + rng.integers(-2, 3), 0) for _ in range(3)]

        for bucket_idx, lam in enumerate(bucket_lambdas):
            n_events = rng.poisson(lam)
            for _ in range(n_events):
                offset_days = bucket_idx * 30 + rng.integers(0, 30)
                event_ts = window_start + timedelta(
                    days=int(offset_days), seconds=int(rng.integers(0, 86400))
                )
                rows.append({
                    "event_id": str(uuid.uuid4()),
                    "customer_id": row.customer_id,
                    "snapshot_date": row.snapshot_date,
                    "event_timestamp": event_ts,
                    "event_type": rng.choice(EVENT_TYPES, p=[0.5, 0.25, 0.15, 0.10]),
                })

    df = pd.DataFrame(rows)
    logger.info(f"Generated {len(df)} synthetic events")
    return df


def generate_tickets(panel, seed: int = 43):
    """Generate synthetic support tickets in the 90 days before each snapshot.

    label=1 (churned): more tickets, longer resolution times.
    label=0 (stable): fewer tickets, faster resolution.
    """
    rng = np.random.default_rng(seed)
    rows = []

    for row in panel.itertuples(index=False):
        window_start = row.snapshot_date - timedelta(days=90)
        is_churn = row.churned_next_90d == 1

        n_tickets = rng.poisson(1.8 if is_churn else 0.4)
        for _ in range(n_tickets):
            created_offset = int(rng.integers(0, 90))
            created_at = window_start + timedelta(
                days=created_offset, seconds=int(rng.integers(0, 86400))
            )
            resolution_days = rng.exponential(5 if is_churn else 1.5)
            resolved_at = created_at + timedelta(days=float(resolution_days))
            resolved_at = min(resolved_at, row.snapshot_date)
            status = "resolved" if resolved_at < row.snapshot_date else "open"

            rows.append({
                "ticket_id": str(uuid.uuid4()),
                "customer_id": row.customer_id,
                "snapshot_date": row.snapshot_date,
                "created_at": created_at,
                "resolved_at": resolved_at if status == "resolved" else None,
                "status": status,
                "topic": rng.choice(TICKET_TOPICS, p=[0.3, 0.25, 0.2, 0.15, 0.1]),
            })

    df = pd.DataFrame(rows)
    logger.info(f"Generated {len(df)} synthetic support tickets")
    return df


def upload_to_s3(df, bucket, key, local_path):
    df.to_parquet(local_path, engine="pyarrow", index=False)

    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ["AWS_REGION"],
    )
    s3.upload_file(local_path, bucket, key)
    logger.info(f"Uploaded to s3://{bucket}/{key}")


def main():
    load_dotenv()
    bucket = os.environ["S3_BUCKET"]

    panel = fetch_snapshot_panel()

    events_df = generate_events(panel)
    upload_to_s3(events_df, bucket, EVENTS_S3_KEY, "/tmp/synthetic_events.parquet")

    tickets_df = generate_tickets(panel)
    upload_to_s3(tickets_df, bucket, TICKETS_S3_KEY, "/tmp/synthetic_tickets.parquet")


if __name__ == "__main__":
    main()