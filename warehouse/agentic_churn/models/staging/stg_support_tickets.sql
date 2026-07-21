SELECT
    ticket_id,
    customer_id,
    snapshot_date,
    created_at,
    resolved_at,
    status,
    topic,
    DATEDIFF('day', created_at, COALESCE(resolved_at, snapshot_date)) AS resolution_days
FROM {{ source('raw', 'raw_support_tickets') }}
WHERE customer_id IS NOT NULL