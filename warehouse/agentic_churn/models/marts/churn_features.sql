SELECT
    customer_id,
    snapshot_date,
    frequency_180d,
    monetary_180d,
    order_trend_90d,
    return_cancel_rate_90d,
    events_30d,
    events_90d,
    engagement_decay_30d,
    support_tickets_90d,
    avg_resolution_days_90d,
    days_since_last_ticket,
    churned_next_90d
FROM {{ ref('churn_feature_panel') }}