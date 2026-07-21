WITH lines AS (
    SELECT * FROM {{ ref('fct_order_lines') }}
)

SELECT
    invoice_no,
    customer_id,
    MIN(invoice_date) as invoice_date,
    MAX(country) as country,
    BOOLOR_AGG(is_cancelled) AS is_cancelled,
    SUM(quantity) as total_quantity,
    SUM(line_revenue) AS total_revenue,
    COUNT(*) AS line_count
FROM lines
GROUP BY invoice_no, customer_id