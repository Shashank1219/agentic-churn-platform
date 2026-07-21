WITH lines AS (
    SELECT * FROM {{ ref('fct_order_lines') }}
)

SELECT
    customer_id,
    MAX(country) AS country,
    MIN(invoice_date) AS first_order_date,
    MAX(invoice_date) AS last_order_date,
    COUNT(DISTINCT invoice_no) AS lifetime_order_count
FROM lines
GROUP BY customer_id