WITH lines AS (
    SELECT stock_code, description
    FROM {{ ref('fct_order_lines') }}
    WHERE stock_code IS NOT NULL
),

deduped AS (
    SELECT
        stock_code,
        -- a stock_code can have minor description variants over time; pick the most common one
        description,
        COUNT(*) AS line_count,
        ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY COUNT(*) DESC) AS rn
    FROM lines
    GROUP BY stock_code, description
)

SELECT
    stock_code AS product_id,
    description
FROM deduped
WHERE rn = 1