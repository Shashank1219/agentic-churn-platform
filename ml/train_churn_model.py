"""
Trains an XGBoost churn classifier with a time-based split by snapshot_date
never a random row split, which would leak a customer's
future snapshots into training.
"""

import logging
import pickle

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import roc_auc_score, precision_recall_curve, classification_report

from feature_store import load_churn_features, split_features_labels

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

MODEL_OUTPUT_PATH = "./models/churn_model.pkl"
FEATURE_LIST_PATH = "./models/feature_list.pkl"

TEST_HOLDOUT_FRACTION = 0.2  # most recent ~20% of snapshot dates held out for test


def time_based_split(df, holdout_fraction = TEST_HOLDOUT_FRACTION):
    
    unique_dates = sorted(df["snapshot_date"].unique())
    cutoff_idx = int(len(unique_dates) * (1 - holdout_fraction))
    cutoff_date = unique_dates[cutoff_idx]

    train_df = df[df["snapshot_date"] < cutoff_date]
    test_df = df[df["snapshot_date"] >= cutoff_date]

    logger.info(f"Cutoff date: {cutoff_date}")
    logger.info(f"Train: {len(train_df)} rows ({train_df['snapshot_date'].min()} to {train_df['snapshot_date'].max()})")
    logger.info(f"Test:  {len(test_df)} rows ({test_df['snapshot_date'].min()} to {test_df['snapshot_date'].max()})")

    return train_df, test_df


def train_model(X_train, y_train, X_test, y_test):
    # Class imbalance handling
    scale_pos_weight = (y_train == 0).sum() / (y_train == 1).sum()
    logger.info(f"scale_pos_weight: {scale_pos_weight:.3f}")

    model = xgb.XGBClassifier(
        n_estimators=300,
        max_depth=4,
        learning_rate=0.05,
        scale_pos_weight=scale_pos_weight,
        eval_metric="auc",
        early_stopping_rounds=20,
        random_state=42,
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False,
    )
    return model


def evaluate_model(model, X_test, y_test):
    y_pred_proba = model.predict_proba(X_test)[:, 1]
    y_pred = (y_pred_proba >= 0.5).astype(int)

    auc = roc_auc_score(y_test, y_pred_proba)
    logger.info(f"ROC-AUC: {auc:.4f}")
    logger.info(f"\n{classification_report(y_test, y_pred)}")

    calib_df = pd.DataFrame({"pred": y_pred_proba, "actual": y_test.values})
    calib_df["bucket"] = pd.qcut(calib_df["pred"], 10, duplicates="drop")
    calibration = calib_df.groupby("bucket", observed=True).agg(
        mean_pred=("pred", "mean"), mean_actual=("actual", "mean"), n=("actual", "size")
    )
    logger.info(f"\nCalibration:\n{calibration}")

    return auc


def main():
    df = load_churn_features()
    train_df, test_df = time_based_split(df)

    _, X_train, y_train = split_features_labels(train_df)
    _, X_test, y_test = split_features_labels(test_df)

    model = train_model(X_train, y_train, X_test, y_test)
    evaluate_model(model, X_test, y_test)

    with open(MODEL_OUTPUT_PATH, "wb") as f:
        pickle.dump(model, f)
    with open(FEATURE_LIST_PATH, "wb") as f:
        pickle.dump(list(X_train.columns), f)

    logger.info(f"Model saved to {MODEL_OUTPUT_PATH}")


if __name__ == "__main__":
    main()