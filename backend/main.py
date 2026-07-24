
# FastAPI layer exposing model scoring and the full agent pipeline.

import logging

from fastapi import FastAPI, HTTPException
from dotenv import load_dotenv

from ml.explain_churn import load_model_and_features, explain_customer
from ml.feature_store import load_churn_features
from agent.tools.tools import (
    tool_query_customer_profile,
    tool_get_churn_explanation,
    tool_generate_retention_incentive,
)

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Agentic Churn Platform API")

# Loaded once at startup, not per-request so it avoids reloading the model/feature dataframe on every call
_model, _feature_list = load_model_and_features()
_df = load_churn_features()
_explainer = None


def _get_explainer():
    global _explainer
    if _explainer is None:
        import shap
        _explainer = shap.TreeExplainer(_model)
    return _explainer


@app.get("/score/{customer_id}")
def get_score(customer_id: int):
    # Latest churn probability and risk band for a customer.
    import snowflake.connector
    import os
    import pandas as pd

    conn = snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE", "TRANSFORMER_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CHURN_WH"),
        database="RETAIL_CHURN_DB",
        schema="ANALYTICS",
    )
    query = f"""
        SELECT customer_id, snapshot_date, churn_probability, risk_band, scored_at
        FROM analytics.churn_predictions
        WHERE customer_id = {customer_id}
    """
    result = pd.read_sql(query, conn)
    conn.close()

    if result.empty:
        raise HTTPException(status_code=404, detail=f"No score found for customer_id={customer_id}")

    result.columns = [c.lower() for c in result.columns]
    return result.iloc[0].to_dict()


@app.get("/agent/explain/{customer_id}")
def get_agent_explanation(customer_id: int):
    # Runs the full agent tool pipeline: profile, SHAP explanation, and a validated retention plan.
    try:
        profile = tool_query_customer_profile(customer_id)
    except ValueError:
        raise HTTPException(
            status_code=404,
            detail=f"No BI profile for customer_id={customer_id} (likely no completed orders)",
        )

    # Reusing the module-level model/explainer/df rather than tool_get_churn_explanation's own reload
    snapshot_date = str(_df[_df["customer_id"] == customer_id]["snapshot_date"].max())
    if snapshot_date == "NaT":
        raise HTTPException(status_code=404, detail=f"No feature panel row for customer_id={customer_id}")

    explanation = explain_customer(customer_id, snapshot_date, _model, _feature_list, _get_explainer(), _df)

    try:
        incentive = tool_generate_retention_incentive(profile, explanation)
    except RuntimeError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "profile": profile,
        "explanation": explanation,
        "retention_plan": incentive.model_dump(),
    }


@app.get("/health")
def health():
    return {"status": "ok"}