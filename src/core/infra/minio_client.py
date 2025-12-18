from minio import Minio
from minio.error import S3Error
import os

def get_minio_client():
    # In a real app, use env vars for host/creds
    minio_host = os.getenv("MINIO_HOST", "localhost")
    minio_port = os.getenv("MINIO_PORT", "9000")
    
    # Fallback to localhost if running outside docker and host is set to service name
    if minio_host == "minio" and not os.path.exists('/.dockerenv'):
        minio_host = "localhost"
    
    minio_user = os.getenv("MINIO_ROOT_USER", "minioadmin")
    minio_password = os.getenv("MINIO_ROOT_PASSWORD", "minioadmin")
    
    # Construct endpoint
    endpoint = f"{minio_host}:{minio_port}"
    
    client = Minio(
        endpoint,
        access_key=minio_user,
        secret_key=minio_password,
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
