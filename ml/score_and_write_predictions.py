"""
Scores the latest snapshot per customer using the trained model, writes
analytics.churn_predictions so the agent layer has real risk_band data to query. 
Also creates the empty analytics.churn_interventions table the agent writes validated output into.

risk_band uses terciles of the actual predicted probability distribution,
not fixed cutoffs.The class balance here (59.7% churn) skews probabilities
high enough that fixed 0.33/0.66 cutoffs would misleadingly bucket most
customers as 'high'.
"""

import os
import logging
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from dotenv import load_dotenv

from ml.feature_store import load_churn_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_ML_DIR = Path(__file__).resolve().parent
MODEL_PATH = _ML_DIR / "models" / "churn_model.pkl"
FEATURE_LIST_PATH = _ML_DIR / "models" / "feature_list.pkl"


def _get_connection():
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE"),
        database="RETAIL_CHURN_DB",
        schema="ANALYTICS",
    )


def load_model_and_features():
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(FEATURE_LIST_PATH, "rb") as f:
        feature_list = pickle.load(f)
    return model, feature_list


def get_latest_snapshot_per_customer(df):
    # Keep only each customer's most recent snapshot_date row
    idx = df.groupby("customer_id")["snapshot_date"].idxmax()
    return df.loc[idx].reset_index(drop=True)


def score(df: pd.DataFrame, model, feature_list: list) -> pd.DataFrame:
    X = df[feature_list]
    probs = pd.Series(model.predict_proba(X)[:, 1], index=df.index, dtype=float)

    result = df[["customer_id", "snapshot_date"]].copy()
    result["churn_probability"] = probs

    edges = probs.quantile([0, 1 / 3, 2 / 3, 1]).to_numpy(copy=True)
    edges[0] -= 1e-9  # ensure the minimum value is included (cut's lower bound is exclusive by default)

    result["risk_band"] = pd.cut(
        result["churn_probability"],
        bins=edges,
        labels=["low", "medium", "high"],
        include_lowest=True,
    )
    result["scored_at"] = datetime.utcnow()

    assert isinstance(result, pd.DataFrame)
    return result


def ensure_interventions_table_exists(conn):
    """Creates the empty target table the agent layer 
    writes validated incentives into"""
    conn.cursor().execute("""
        CREATE OR REPLACE TABLE analytics.churn_interventions (
            customer_id       NUMBER,
            discount_pct      NUMBER,
            channel           VARCHAR,
            product_focus     VARCHAR,
            messaging         VARCHAR,
            generated_at      TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
        )
    """)


def write_predictions(df, conn):
    conn.cursor().execute("""
        CREATE OR REPLACE TABLE analytics.churn_predictions (
            customer_id       NUMBER,
            snapshot_date     DATE,
            churn_probability FLOAT,
            risk_band         VARCHAR,
            scored_at         TIMESTAMP_NTZ
        )
    """)
    conn.commit()

    df_upload = df.copy()
    df_upload.columns = [c.upper() for c in df_upload.columns]
    df_upload["RISK_BAND"] = df_upload["RISK_BAND"].astype(str)
    # write_pandas mis-handles pandas datetime64 as nanoseconds unless stringified
    df_upload["SNAPSHOT_DATE"] = pd.to_datetime(df_upload["SNAPSHOT_DATE"]).dt.strftime("%Y-%m-%d")
    df_upload["SCORED_AT"] = pd.to_datetime(df_upload["SCORED_AT"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    success, nchunks, nrows, _ = write_pandas(conn, df_upload, "CHURN_PREDICTIONS", schema="ANALYTICS")
    conn.commit()
    logger.info(f"Wrote {nrows} rows to analytics.churn_predictions")


def main():
    load_dotenv()

    model, feature_list = load_model_and_features()
    df = load_churn_features()
    latest = get_latest_snapshot_per_customer(df)

    logger.info(f"Scoring {len(latest)} customers (latest snapshot each)")
    scored = score(latest, model, feature_list)

    conn = _get_connection()
    ensure_interventions_table_exists(conn)
    write_predictions(scored, conn)
    conn.close()

    logger.info(f"Risk band distribution:\n{scored['risk_band'].value_counts()}")


if __name__ == "__main__":
    main()