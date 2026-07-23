WITH completed_orders AS (
    SELECT customer_id, invoice_no, invoice_date, total_revenue
    from {{ ref('fct_orders') }}
    WHERE is_cancelled = false
),

ref_date AS (
    SELECT MAX(invoice_date) AS as_of_date FROM completed_orders
),

customer_stats AS (
    SELECT
        customer_id,
        MIN(invoice_date) AS first_order_date,
        MAX(invoice_date) AS last_order_date,
        COUNT(DISTINCT invoice_no) AS frequency_lifetime,
        SUM(total_revenue) AS monetary_lifetime
    FROM completed_orders
    GROUP BY customer_id
),

with_recency AS (
    SELECT
        cs.*,
        r.as_of_date,
        DATEDIFF('day', cs.last_order_date, r.as_of_date) AS recency_days,
        DATEDIFF('day', cs.first_order_date, cs.last_order_date) AS lifespan_days
    FROM customer_stats cs
    CROSS JOIN ref_date r
),

with_api AS (
    SELECT
        *,
        CASE WHEN frequency_lifetime <= 1 THEN null
             ELSE lifespan_days::FLOAT / NULLIF(frequency_lifetime - 1, 0)
        END AS avg_purchase_interval
    FROM with_recency
),

scored AS (
    SELECT
        *,
        NTILE(5) OVER (ORDER BY recency_days DESC) AS r_score,   -- 1=worst(stale), 5=best(recent)
        NTILE(5) OVER (ORDER BY frequency_lifetime ASC) AS f_score,
        NTILE(5) OVER (ORDER BY monetary_lifetime ASC) AS m_score
    FROM with_api
)

SELECT
    customer_id,
    recency_days,
    frequency_lifetime,
    monetary_lifetime,
    avg_purchase_interval,
    r_score,
    f_score,
    m_score,
    r_score + f_score + m_score AS rfm_score,
    CASE
        WHEN r_score >= 4 AND f_score >= 4 THEN 'champions'
        WHEN f_score >= 4 AND r_score < 4 THEN 'loyal'
        WHEN r_score <= 2 AND f_score >= 3 THEN 'at_risk'
        WHEN r_score <= 2 AND f_score <= 2 THEN 'hibernating'
        WHEN r_score >= 4 AND f_score <= 2 THEN 'new'
        ELSE 'standard'
    END AS segment
FROM scored