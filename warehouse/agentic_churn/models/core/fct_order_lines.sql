WITH stg AS (
    SELECT * FROM {{ ref('stg_invoices') }}
)

SELECT
    {{ dbt_utils.generate_surrogate_key(['invoice_no', 'stock_code', 'invoice_date', 'customer_id']) }} as order_line_id,
    invoice_no,
    stock_code,
    description,
    quantity,
    invoice_date,
    unit_price,
    customer_id,
    country,
    is_cancelled,
    quantity * unit_price as line_revenue
FROM stg