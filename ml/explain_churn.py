# SHAP TreeExplainer producing per-customer churn explanations.

import json
import logging
import pickle

import pandas as pd
import shap

from feature_store import load_churn_features, split_features_labels

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_PATH = "./models/churn_model.pkl"
FEATURE_LIST_PATH = "./models/feature_list.pkl"

TOP_N_FEATURES = 3


def load_model_and_features():
    with open(MODEL_PATH, "rb") as f:
        model = pickle.load(f)
    with open(FEATURE_LIST_PATH, "rb") as f:
        feature_list = pickle.load(f)
    return model, feature_list


def explain_customer(customer_id, snapshot_date, model, feature_list, explainer, df):
    row = df[
        (df["customer_id"] == customer_id) & (df["snapshot_date"] == pd.Timestamp(snapshot_date))
    ]
    if row.empty:
        raise ValueError(f"No row found for customer_id={customer_id}, snapshot_date={snapshot_date}")

    X_row = row[feature_list]

    churn_probability = float(model.predict_proba(X_row)[:, 1][0])

    shap_values = explainer.shap_values(X_row)
    # shap_values shape: (1, n_features) for a single row
    feature_impacts = list(zip(feature_list, shap_values[0]))
    feature_impacts.sort(key=lambda x: abs(x[1]), reverse=True)
    top_features = [
        {"name": name, "impact": round(float(impact), 4)}
        for name, impact in feature_impacts[:TOP_N_FEATURES]
    ]

    return {
        "customer_id": int(customer_id),
        "snapshot_date": str(pd.Timestamp(snapshot_date).date()),
        "churn_probability": round(churn_probability, 4),
        "top_features": top_features,
    }


def main():
    model, feature_list = load_model_and_features()
    df = load_churn_features()

    explainer = shap.TreeExplainer(model)

    _, X_full, y_full = split_features_labels(df)
    probs = model.predict_proba(X_full[feature_list])[:, 1]
    df = df.reset_index(drop=True)
    df["_pred_prob"] = probs

    sample_row = df.sort_values("_pred_prob", ascending=False).iloc[0]

    result = explain_customer(
        customer_id=sample_row["customer_id"],
        snapshot_date=sample_row["snapshot_date"],
        model=model,
        feature_list=feature_list,
        explainer=explainer,
        df=df,
    )

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()