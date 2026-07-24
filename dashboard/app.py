"""
Streamlit dashboard. KPI/table views read from the cached
Parquet snapshot (dashboard/export_cache.py), never live Snowflake.
"""

import requests
import pandas as pd
import streamlit as st

CACHE_DIR = "dashboard/cache"
FASTAPI_URL = "http://localhost:8000"

st.set_page_config(page_title="Agentic Churn Platform", layout="wide")


@st.cache_data
def load_predictions():
    return pd.read_parquet(f"{CACHE_DIR}/churn_predictions.parquet")


@st.cache_data
def load_interventions():
    return pd.read_parquet(f"{CACHE_DIR}/churn_interventions.parquet")


st.title("Agentic E-Commerce Customer 360 & Churn Analysis Platform")

predictions = load_predictions()
interventions = load_interventions()

# --- KPI row ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total customers scored", len(predictions))
col2.metric("High risk", (predictions["risk_band"] == "high").sum())
col3.metric("Avg churn probability", f"{predictions['churn_probability'].mean():.2%}")
col4.metric("Interventions generated", len(interventions))

st.divider()

# --- Filterable churn risk table ---
st.subheader("Churn Risk Table")
col_a, col_b = st.columns(2)
segment_filter = col_a.multiselect("Segment", options=predictions["segment"].unique())
risk_filter = col_b.multiselect("Risk band", options=predictions["risk_band"].unique())

filtered = predictions.copy()
if segment_filter:
    filtered = filtered.loc[filtered["segment"].isin(segment_filter)]
if risk_filter:
    filtered = filtered.loc[filtered["risk_band"].isin(risk_filter)]

table_cols = [
    "customer_id",
    "country",
    "segment",
    "risk_band",
    "churn_probability",
    "lifetime_revenue",
]
table_df = filtered.loc[:, table_cols].sort_values(by="churn_probability", ascending=False)
st.dataframe(table_df, use_container_width=True)

st.divider()

# Individual customer explanation (live agent call)
st.subheader("Customer Explanation & Retention Plan")
st.caption("This section calls the live agent pipeline via FastAPI — not cached.")

customer_id_input = st.number_input("Customer ID", min_value=1, step=1, value=int(predictions.iloc[0]["customer_id"]))

if st.button("Run agent explanation"):
    with st.spinner("Running SHAP explanation + retention agent..."):
        try:
            resp = requests.get(f"{FASTAPI_URL}/agent/explain/{customer_id_input}", timeout=30)
            resp.raise_for_status()
            result = resp.json()
            profile = result["profile"]
            explanation = result["explanation"]
            plan = result["retention_plan"]

            st.markdown("#### Customer Profile")
            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Segment", profile["segment"].title())
            p2.metric("Lifetime Orders", profile["lifetime_order_count"])
            p3.metric("Lifetime Revenue", f"${profile['lifetime_revenue']:,.2f}")
            p4.metric("Recency (days)", profile["recency_days"])

            p5, p6, p7, p8 = st.columns(4)
            p5.metric("Country", profile["country"])
            p6.metric("RFM Score", profile["rfm_score"])
            p7.metric("Avg Purchase Interval", f"{profile['avg_purchase_interval']:.1f} days")
            p8.metric("First Order", profile["first_order_date"][:10])

            st.divider()

            st.markdown("#### Churn Risk Assessment")
            prob = explanation["churn_probability"]
            risk_color = "🔴" if prob >= 0.66 else "🟡" if prob >= 0.33 else "🟢"
            risk_label = "High Risk" if prob >= 0.66 else "Medium Risk" if prob >= 0.33 else "Low Risk"

            rc1, rc2 = st.columns([1, 3])
            rc1.metric("Churn Probability", f"{prob:.1%}")
            rc2.markdown(f"### {risk_color} {risk_label}")

            st.markdown("**Top factors driving this prediction:**")
            features_df = pd.DataFrame(explanation["top_features"])
            features_df["direction"] = features_df["impact"].apply(
                lambda x: "increases risk" if x > 0 else "decreases risk"
            )
            for row in features_df.to_dict("records"):
                impact = float(row["impact"])
                name = str(row["name"]).replace("_", " ").title()
                icon = "⬆️" if impact > 0 else "⬇️"
                st.write(
                    f"{icon} **{name}** — {row['direction']} "
                    f"(impact: {impact:+.2f})"
                )

            st.divider()

            st.markdown("#### Proposed Retention Plan")
            plan_col1, plan_col2, plan_col3 = st.columns(3)
            plan_col1.metric("Discount", f"{plan['discount_pct']}%")
            plan_col2.metric("Channel", plan["channel"].title())
            plan_col3.metric("Featured Product", plan["product_focus"])

            st.info(f"✉️ **Message:**\n\n{plan['messaging']}")

        except requests.exceptions.HTTPError as e:
            detail = str(e)
            if e.response is not None:
                try:
                    detail = e.response.json().get("detail", detail)
                except ValueError:
                    detail = e.response.text or detail
            st.error(f"Agent pipeline failed: {detail}")
        except requests.exceptions.ConnectionError:
            st.error("Could not reach FastAPI backend — is `uvicorn backend.main:app` running?")