from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from typing import Any
import json
import io
from core.infra.minio_client import get_minio_client
from core.infra.producer import BaseProducer
from minio.error import S3Error

router = APIRouter(
    prefix="/knowledgebase",
    tags=["knowledgebase"],
    responses={404: {"description": "Not found"}},
)

BUCKET_NAME = "knowledgebase"
QUEUE_NAME = "document_ingestion"

try:
    minio_client = get_minio_client()
    if not minio_client.bucket_exists(BUCKET_NAME):
        minio_client.make_bucket(BUCKET_NAME)
except Exception as e:
    print(f"Warning checking Minio bucket: {e}")

from core.services.knowledge_service import index_text_content, BUCKET_NAME, QUEUE_NAME

@router.post("/", response_model=Any)
async def add_document(
    account_id: str = Form(...),
    file: UploadFile = File(...)
):
    if not (file.filename.lower().endswith(".md") or file.filename.lower().endswith(".txt")):
        raise HTTPException(status_code=400, detail="Only Markdown (.md) and Text (.txt) files are allowed.")

    try:
        content = await file.read()
        text_content = content.decode('utf-8')
        
        object_name = index_text_content(account_id, file.filename, text_content)
        
        return {
            "status": "queued", 
            "message": "Document uploaded and queued for processing", 
            "object_name": object_name
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.delete("/", response_model=Any)
async def delete_document(
    account_id: str,
    filename: str
):
    object_name = f"{account_id}/{filename}"
    client = get_minio_client()
    producer = BaseProducer(queue_name=QUEUE_NAME)
    
    try:
        client.remove_object(BUCKET_NAME, object_name)
        
        message = {
            "action": "delete",
            "account_id": account_id,
            "object_name": object_name
        }
        producer.publish(json.dumps(message))
        
        return {"status": "deleted", "object_name": object_name}
        
    except S3Error as e:
        raise HTTPException(status_code=500, detail=f"Minio Error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    finally:
        try:
            producer.close()
        except:
            pass
