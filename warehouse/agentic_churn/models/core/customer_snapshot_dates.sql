WITH bounds AS (
    SELECT
        MIN(invoice_date) AS min_date,
        MAX(invoice_date) AS max_date
    FROM {{ ref('fct_orders') }}
    WHERE is_cancelled = false
),

valid_range AS (
    SELECT
        DATEADD('day', 90, min_date) AS range_start,
        DATEADD('day', -90, max_date) AS range_end
    FROM bounds
),

month_offsets AS (
    SELECT ROW_NUMBER() OVER (ORDER BY seq4()) - 1 AS offset
    FROM table(generator(rowcount => 60))
),

snapshot_grid AS (
    SELECT
        DATEADD('month', offset, date_trunc('month', range_start)) AS snapshot_date
    FROM month_offsets, valid_range
    WHERE DATEADD('month', offset, date_trunc('month', range_start))
        BETWEEN range_start AND range_end
),

customers AS (
    SELECT customer_id, first_order_date
    FROM {{ ref('dim_customers') }}
)

SELECT
    c.customer_id,
    s.snapshot_date
FROM customers c
CROSS JOIN snapshot_grid s
WHERE s.snapshot_date >= c.first_order_date