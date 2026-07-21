with snapshots as (
    SELECT customer_id, snapshot_date
    FROM {{ ref('customer_snapshot_dates') }}
),

orders AS (
    SELECT customer_id, invoice_date, is_cancelled, total_revenue
    FROM {{ ref('fct_orders') }}
),

order_joined AS (
    SELECT
        s.customer_id,
        s.snapshot_date,
        o.invoice_date,
        o.is_cancelled,
        o.total_revenue
    FROM snapshots s
    LEFT JOIN orders o
        ON o.customer_id = s.customer_id
        AND o.invoice_date >= DATEADD('day', -180, s.snapshot_date)
        AND o.invoice_date <= DATEADD('day', 90, s.snapshot_date)
),

order_features AS (
    SELECT
        customer_id,
        snapshot_date,

        DATEDIFF('day',
            MAX(CASE WHEN invoice_date <= snapshot_date AND is_cancelled = false THEN invoice_date END),
            snapshot_date
        ) AS days_since_last_order,

        COUNT(CASE WHEN invoice_date <= snapshot_date
                     AND invoice_date > DATEADD('day', -180, snapshot_date)
                     AND is_cancelled = false THEN 1 END) AS frequency_180d,

        SUM(CASE WHEN invoice_date <= snapshot_date
                   AND invoice_date > DATEADD('day', -180, snapshot_date)
                   AND is_cancelled = false THEN total_revenue END) AS monetary_180d,

        COUNT(CASE WHEN invoice_date <= snapshot_date
                     AND invoice_date > DATEADD('day', -90, snapshot_date)
                     AND is_cancelled = false THEN 1 END) AS orders_recent_90d,

        COUNT(CASE WHEN invoice_date <= DATEADD('day', -90, snapshot_date)
                     AND invoice_date > DATEADD('day', -180, snapshot_date)
                     AND is_cancelled = false THEN 1 END) AS orders_prior_90d,

        COUNT(CASE WHEN invoice_date <= snapshot_date
                     AND invoice_date > DATEADD('day', -90, snapshot_date) THEN 1 END) AS total_invoices_90d,

        COUNT(CASE WHEN invoice_date <= snapshot_date
                     AND invoice_date > DATEADD('day', -90, snapshot_date)
                     AND is_cancelled = true THEN 1 END) AS cancelled_invoices_90d,

        COALESCE(MAX(CASE WHEN invoice_date > snapshot_date
                            AND invoice_date <= DATEADD('day', 90, snapshot_date)
                            AND is_cancelled = false THEN 1 ELSE 0 END), 0) AS has_future_order

    FROM order_joined
    GROUP BY customer_id, snapshot_date
),

events AS (
    SELECT customer_id, snapshot_date, event_timestamp, event_type
    FROM {{ ref('stg_events') }}
),

event_joined AS (
    SELECT
        s.customer_id,
        s.snapshot_date,
        e.event_timestamp
    FROM snapshots s
    LEFT JOIN events e
        ON e.customer_id = s.customer_id
        AND e.snapshot_date = s.snapshot_date   -- events were generated per-snapshot; this ties them to the right instance
        AND e.event_timestamp <= s.snapshot_date
        AND e.event_timestamp > DATEADD('day', -90, s.snapshot_date)
),

event_features AS (
    SELECT
        customer_id,
        snapshot_date,
        COUNT(CASE WHEN event_timestamp > DATEADD('day', -30, snapshot_date) THEN 1 END) AS events_30d,
        COUNT(CASE WHEN event_timestamp > DATEADD('day', -90, snapshot_date) THEN 1 END) AS events_90d
    FROM event_joined
    GROUP BY customer_id, snapshot_date
),

tickets AS (
    SELECT customer_id, snapshot_date, created_at, resolution_days
    FROM {{ ref('stg_support_tickets') }}
),

ticket_joined AS (
    SELECT
        s.customer_id,
        s.snapshot_date,
        t.created_at,
        t.resolution_days
    FROM snapshots s
    LEFT JOIN tickets t
        ON t.customer_id = s.customer_id
        AND t.snapshot_date = s.snapshot_date
        AND t.created_at <= s.snapshot_date
        AND t.created_at > DATEADD('day', -90, s.snapshot_date)
),

ticket_features AS (
    SELECT
        customer_id,
        snapshot_date,
        COUNT(created_at) AS support_tickets_90d,
        AVG(resolution_days) AS avg_resolution_days_90d,
        DATEDIFF('day', MAX(created_at), snapshot_date) AS days_since_last_ticket
    FROM ticket_joined
    GROUP BY customer_id, snapshot_date
)

SELECT
    o.customer_id,
    o.snapshot_date,

    -- BI-only, excluded from features.churn_features
    o.days_since_last_order,

    o.frequency_180d,
    o.monetary_180d,
    CASE WHEN o.orders_prior_90d = 0 THEN null
         ELSE o.orders_recent_90d::float / o.orders_prior_90d END AS order_trend_90d,
    CASE WHEN o.total_invoices_90d = 0 THEN null
         ELSE o.cancelled_invoices_90d::float / o.total_invoices_90d END AS return_cancel_rate_90d,

    COALESCE(ev.events_30d, 0) AS events_30d,
    COALESCE(ev.events_90d, 0) AS events_90d,
    CASE WHEN COALESCE(ev.events_90d, 0) = 0 THEN null
         ELSE COALESCE(ev.events_30d, 0)::float / (ev.events_90d / 3.0) END AS engagement_decay_30d,

    COALESCE(tk.support_tickets_90d, 0) AS support_tickets_90d,
    tk.avg_resolution_days_90d,
    tk.days_since_last_ticket,

    CASE WHEN o.has_future_order = 1 THEN 0 ELSE 1 END AS churned_next_90d

FROM order_features o
LEFT JOIN event_features ev
    ON o.customer_id = ev.customer_id AND o.snapshot_date = ev.snapshot_date
LEFT JOIN ticket_features tk
    ON o.customer_id = tk.customer_id AND o.snapshot_date = tk.snapshot_date