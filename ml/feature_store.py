"""
Loads model-eligible features from features.churn_features.
Includes a defense-in-depth check that leakage-prone columns are absent,
even though they're already excluded at the dbt layer (Section 6.6).
"""

import os
import logging

import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FORBIDDEN_COLUMNS = {"days_since_last_order", "avg_purchase_interval"}

ID_COLUMNS = ["customer_id", "snapshot_date"]
LABEL_COLUMN = "churned_next_90d"


def load_churn_features():
    load_dotenv()
    conn = snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database="RETAIL_CHURN_DB",
        schema="FEATURES",
    )
    df = pd.read_sql("SELECT * FROM features.churn_features", conn)
    conn.close()

    df.columns = [c.lower() for c in df.columns]

    present_forbidden = FORBIDDEN_COLUMNS & set(df.columns)
    if present_forbidden:
        raise ValueError(
            f"Leakage-prone column(s) found in features.churn_features: {present_forbidden}."
        )

    logger.info(f"Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


def split_features_labels(df):
    """Separate identifiers, features, and label. Returns (ids, X, y)."""
    ids = df[ID_COLUMNS]
    y = df[LABEL_COLUMN]
    X = df.drop(columns=ID_COLUMNS + [LABEL_COLUMN])
    return ids, X, y


if __name__ == "__main__":
    df = load_churn_features()
    ids, X, y = split_features_labels(df)
    print(f"Features: {list(X.columns)}")
    print(f"Label balance:\n{y.value_counts(normalize=True)}")