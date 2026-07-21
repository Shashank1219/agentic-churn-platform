with source as (
    select * from {{ source('raw', 'raw_invoices') }}
),

casted as (
    select
        "InvoiceNo"                                    as invoice_no,
        "StockCode"                                     as stock_code,
        "Description"                                   as description,
        "Quantity"::number                              as quantity,
        try_to_timestamp_ntz("InvoiceDate")              as invoice_date,
        "UnitPrice"::float                               as unit_price,
        "CustomerID"::number                             as customer_id,
        "Country"                                        as country,
        "source_sheet"                                   as source_sheet,
        case when left("InvoiceNo", 1) = 'C' then true else false end as is_cancelled
    from source
),

deduped as (
    select distinct * from casted
)

select *
from deduped
where customer_id is not null