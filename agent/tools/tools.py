
import os
import json
import logging

import pandas as pd
import snowflake.connector
from openai import OpenAI

from agent.tools.schemas import RetentionIncentive

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
CANDIDATE_PRODUCT_LIMIT = 15


def _get_connection(schema: str = "MARTS"):
    return snowflake.connector.connect(
        user=os.environ["SNOWFLAKE_USER"],
        password=os.environ["SNOWFLAKE_PASSWORD"],
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        role=os.environ.get("SNOWFLAKE_ROLE", "TRANSFORMER_ROLE"),
        warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "CHURN_WH"),
        database="RETAIL_CHURN_DB",
        schema=schema,
    )


def tool_query_customer_profile(customer_id):
    # Reads mart_customer_360 + mart_rfm_segments
    conn = _get_connection("MARTS")
    query = f"""
        SELECT
            c.customer_id, c.country, c.first_order_date, c.last_order_date,
            c.lifetime_order_count, c.lifetime_revenue,
            r.recency_days, r.frequency_lifetime, r.monetary_lifetime,
            r.avg_purchase_interval, r.segment, r.rfm_score
        FROM marts.mart_customer_360 c
        JOIN marts.mart_rfm_segments r ON c.customer_id = r.customer_id
        WHERE c.customer_id = {customer_id}
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        raise ValueError(f"No profile found for customer_id={customer_id}")

    df.columns = [c.lower() for c in df.columns]
    return df.iloc[0].to_dict()


def tool_get_churn_explanation(customer_id, snapshot_date):
    # Wraps the SHAP explainer already built and verified in ml/explain_churn.py
    from ml.explain_churn import load_model_and_features, explain_customer
    from ml.feature_store import load_churn_features
    import shap

    model, feature_list = load_model_and_features()
    df = load_churn_features()
    explainer = shap.TreeExplainer(model)

    return explain_customer(customer_id, snapshot_date, model, feature_list, explainer, df)


def _validate_product_focus(product_id):
    # Existence check against core.dim_products
    conn = _get_connection("CORE")
    query = f"SELECT 1 FROM core.dim_products WHERE product_id = '{product_id}' LIMIT 1"
    df = pd.read_sql(query, conn)
    conn.close()
    return not df.empty


def _get_candidate_products(customer_id, limit = CANDIDATE_PRODUCT_LIMIT):
    # Products this customer has actually purchased, most recent first
    conn = _get_connection("CORE")

    query = f"""
        SELECT product_id, description
        FROM (
            SELECT p.product_id, p.description, MAX(l.invoice_date) AS last_purchased_at
            FROM core.fct_order_lines l
            JOIN core.dim_products p ON l.stock_code = p.product_id
            WHERE l.customer_id = {customer_id}
            GROUP BY p.product_id, p.description
        )
        ORDER BY last_purchased_at DESC
        LIMIT {limit}
    """
    df = pd.read_sql(query, conn)

    if df.empty:
        fallback_query = f"SELECT product_id, description FROM core.dim_products LIMIT {limit}"
        df = pd.read_sql(fallback_query, conn)

    conn.close()
    df.columns = [c.lower() for c in df.columns]
    return df.to_dict("records")


def _call_llm(customer_profile, churn_explanation, candidate_products, error_feedback = None):
    """ 
        Single LLM call proposing a retention incentive. Returns raw parsed JSON,
        not yet validated;validation happens in the caller. Uses OpenAI's direct
        API (gpt-4o-mini) with JSON response mode 
    """
    client = OpenAI()  # reads OPENAI_API_KEY from env automatically

    products_block = "\n".join(
        f"- {p['product_id']} (description: {p['description']})" for p in candidate_products
    )

    system_prompt = f"""You are a retention specialist proposing a customer retention incentive.
Respond with ONLY a JSON object matching this exact shape:
{{
  "customer_id": <int>,
  "discount_pct": <one of 0, 10, 15, 20>,
  "channel": <"email" or "push">,
  "product_focus": <the bare product_id string ONLY, e.g. "22139" — never include the description or a colon>,
  "messaging": <string, under 300 characters, no profanity, no PII>
}}

Allowed product_focus values (choose exactly one product_id — copy ONLY the code before the parentheses, not the description):
{products_block}

Example of a CORRECT product_focus value: "22139"
Example of an INCORRECT product_focus value: "22139: RETROSPOT TEA SET CERAMIC 11 PC" (do not do this — no description, no colon)
"""
    user_prompt = f"""Customer profile: {json.dumps(customer_profile, default=str)}
Churn explanation: {json.dumps(churn_explanation, default=str)}
"""
    if error_feedback:
        user_prompt += (
            f"\nYour previous response was invalid: {error_feedback}\n"
            "You must pick a product_id from the allowed list above, exact match.\n"
            "Please correct it."
        )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    raw_text = response.choices[0].message.content
    if not raw_text:
        raise ValueError("LLM returned empty content")
    raw_text = raw_text.strip()
    return json.loads(raw_text)

def _normalize_product_focus(raw: dict):
    # Defensive cleanup: if the model returns 'id: description' or 'id (description)' extract just the id
    if "product_focus" in raw and isinstance(raw["product_focus"], str):
        value = raw["product_focus"].strip()
        # Take everything before the first colon or opening paren, if present
        for delimiter in [":", "("]:
            if delimiter in value:
                value = value.split(delimiter)[0].strip()
        raw["product_focus"] = value
    return raw

def tool_generate_retention_incentive(customer_profile, churn_explanation):
    """calls the LLM, validates against RetentionIncentive,
    retries with feedback on failure. Never returns unvalidated output."""
    error_feedback = None
    candidate_products = _get_candidate_products(customer_profile["customer_id"])
    valid_ids = {p["product_id"] for p in candidate_products}  # fast local pre-check

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            raw = _call_llm(customer_profile, churn_explanation, candidate_products, error_feedback)
            raw = _normalize_product_focus(raw)
            incentive = RetentionIncentive(**raw)

            if incentive.product_focus not in valid_ids:
                if not _validate_product_focus(incentive.product_focus):
                    raise ValueError(
                        f"product_focus '{incentive.product_focus}' is not in the allowed "
                        f"candidate list and does not exist in core.dim_products"
                    )

            logger.info(f"Validated retention incentive on attempt {attempt}")
            return incentive

        except Exception as e:
            logger.warning(f"Attempt {attempt}/{MAX_RETRIES} failed validation: {e}")
            error_feedback = str(e)

    raise RuntimeError(
        f"Failed to generate a valid retention incentive after {MAX_RETRIES} attempts. "
        "Nothing was written to analytics.churn_interventions."
    )


if __name__ == "__main__":
    # Quick standalone smoke test
    from dotenv import load_dotenv
    load_dotenv()

    TEST_CUSTOMER_ID = 15317
    TEST_SNAPSHOT_DATE = "2025-12-01"

    profile = tool_query_customer_profile(TEST_CUSTOMER_ID)
    print("Profile:", profile)

    explanation = tool_get_churn_explanation(TEST_CUSTOMER_ID, TEST_SNAPSHOT_DATE)
    print("Explanation:", explanation)

    incentive = tool_generate_retention_incentive(profile, explanation)
    print("Incentive:", incentive)