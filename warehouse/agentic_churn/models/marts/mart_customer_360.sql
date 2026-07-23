WITH completed_orders AS (
    SELECT customer_id, invoice_no, invoice_date, total_revenue
    FROM {{ ref('fct_orders') }}
    WHERE is_cancelled = false
),

customer_agg AS (
    SELECT
        customer_id,
        COUNT(DISTINCT invoice_no) AS lifetime_order_count,
        SUM(total_revenue) AS lifetime_revenue,
        MIN(invoice_date) AS first_order_date,
        MAX(invoice_date) AS last_order_date
    FROM completed_orders
    GROUP BY customer_id
),

customers AS (
    SELECT customer_id, country
    FROM {{ ref('dim_customers') }}
)

SELECT
    c.customer_id,
    c.country,
    a.first_order_date,
    a.last_order_date,
    a.lifetime_order_count,
    a.lifetime_revenue
FROM customers c
LEFT JOIN customer_agg a ON c.customer_id = a.customer_id