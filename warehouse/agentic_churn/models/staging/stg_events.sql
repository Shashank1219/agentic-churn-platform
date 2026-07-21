SELECT
    event_id,
    customer_id,
    snapshot_date,
    event_timestamp,
    event_type
FROM {{ source('raw', 'raw_events') }}
WHERE customer_id IS NOT NULL