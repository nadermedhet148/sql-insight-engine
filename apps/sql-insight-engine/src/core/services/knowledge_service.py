import json
import io
import os
from core.infra.minio_client import get_minio_client
from core.infra.producer import BaseProducer

BUCKET_NAME = "knowledgebase"
QUEUE_NAME = "document_ingestion"

def index_text_content(account_id: str, filename: str, content: str, collection_name: str = "knowledgebase"):
    """
    Indexes a piece of text into the knowledge base.
    1. Saves content to MinIO
    2. Sends a message to RabbitMQ for processing
    """
    minio_client = get_minio_client()
    mq_host = os.getenv("RABBITMQ_HOST", "localhost")
    # Fallback to localhost if running outside docker and host is set to service name
    if mq_host == "rabbitmq" and not os.path.exists('/.dockerenv'):
        mq_host = "localhost"
    
    producer = BaseProducer(queue_name=QUEUE_NAME, host=mq_host)

    try:
        # Create bucket if it doesn't exist
        if not minio_client.bucket_exists(BUCKET_NAME):
            minio_client.make_bucket(BUCKET_NAME)

        object_name = f"{account_id}/{filename}"
        
        # Prepare data
        content_bytes = content.encode('utf-8')
        file_data = io.BytesIO(content_bytes)
        file_size = len(content_bytes)

        # Upload to MinIO
        minio_client.put_object(
            BUCKET_NAME,
            object_name,
            file_data,
            file_size,
            content_type="text/markdown"
        )
        
        # Publish message for indexing
        message = {
            "action": "add",
            "account_id": account_id,
            "object_name": object_name,
            "filename": filename,
            "collection_name": collection_name
        }
        producer.publish(json.dumps(message))
        
        return object_name
    finally:
        try:
            producer.close()
        except:
            pass
