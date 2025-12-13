from minio import Minio
from minio.error import S3Error
import os

def get_minio_client():
    # In a real app, use env vars for host/creds
    client = Minio(
        "localhost:9000",
        access_key="minioadmin",
        secret_key="minioadmin",
        secure=False
    )
    return client

def create_bucket_if_not_exists(bucket_name):
    client = get_minio_client()
    try:
        if not client.bucket_exists(bucket_name):
            client.make_bucket(bucket_name)
            print(f"Bucket '{bucket_name}' created.")
        else:
            print(f"Bucket '{bucket_name}' already exists.")
    except S3Error as err:
        print(err)

if __name__ == "__main__":
    create_bucket_if_not_exists("test-bucket")
