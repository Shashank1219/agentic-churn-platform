"""Load UCI Online Retail II to S3 landing zone with YEARS_OFFSET date shift."""

import os
import logging
from datetime import datetime

import boto3
import pandas as pd
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

S3_KEY = "raw/invoices/online_retail_ii.parquet"

def load_retail_data():
    logger.info(f"Reading source file")
    df1 = pd.read_csv("./data/online_retail_09_10.csv")
    df2 = pd.read_csv("./data/online_retail_10_11.csv")
    
    df = pd.concat([df1, df2], ignore_index=True)
    
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    
    return df


def apply_date_shift(df):
    logger.info(f"Calculating date shift")
    current_year = datetime.now().year
    max_invoice_date = df["InvoiceDate"].max()
    years_offset = current_year - max_invoice_date.year

    logger.info(f"InvoiceDate before shift: {df['InvoiceDate'].min()} to {df['InvoiceDate'].max()}")
    logger.info(f"YEARS_OFFSET computed: {years_offset}")

    df = df.copy()

    logger.info(f"Applying date shift")
    df["InvoiceDate"] = df["InvoiceDate"].apply(
        lambda d: d + relativedelta(years=years_offset)
    )

    logger.info(f"InvoiceDate after shift: {df['InvoiceDate'].min()} to {df['InvoiceDate'].max()}")
    
    return df, years_offset


def write_parquet(df, path):
    logger.info(f"Writing parquet file to {path}")
    df.to_parquet(path, engine="pyarrow", index=False)
    
    return path


def upload_to_s3(local_path, bucket: str, key: str = S3_KEY):
    logger.info(f"Creating S3 client")
    s3 = boto3.client(
        "s3",
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ["AWS_REGION"],
    )
    
    logger.info(f"Uploading file to S3")
    s3.upload_file(str(local_path), bucket, key)
    uri = f"s3://{bucket}/{key}"
    
    logger.info(f"File uploaded to {uri}")
    
    return uri


def main():
    load_dotenv()
    parquet_path = "./online_retail_ii.parquet"
    df = load_retail_data()
    df, _ = apply_date_shift(df)
    parquet_path = write_parquet(df, parquet_path)
    upload_to_s3(parquet_path, os.environ["S3_BUCKET"])


if __name__ == "__main__":
    main()
