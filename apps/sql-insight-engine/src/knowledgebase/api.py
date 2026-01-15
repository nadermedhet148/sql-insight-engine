from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Any, Optional
import json
import io
from core.infra.minio_client import get_minio_client
from core.infra.producer import BaseProducer
from minio.error import S3Error
import logging
from core.gemini_client import GeminiClient
from core.infra.chroma_factory import ChromaClientFactory

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/knowledgebase",
    tags=["knowledgebase"],
    responses={404: {"description": "Not found"}},
)

class QueryRequest(BaseModel):
    account_id: str
    query: str
    n_results: int = 5
    collection_name: str = "knowledgebase"

from core.services.knowledge_service import index_text_content, BUCKET_NAME, QUEUE_NAME

try:
    minio_client = get_minio_client()
    if not minio_client.bucket_exists(BUCKET_NAME):
        minio_client.make_bucket(BUCKET_NAME)
except Exception as e:
    logger.warning(f"Warning checking Minio bucket: {e}")

@router.post("/query", response_model=Any)
async def query_knowledgebase(request: QueryRequest):
    """
    Simple endpoint to query Chroma DB with account_id and query.
    Returns raw chunks.
    """
    try:
        gemini_client = GeminiClient()
        chroma_client = ChromaClientFactory.get_client()
        collection = chroma_client.get_or_create_collection(name=request.collection_name)
        
        # Generate embedding
        query_embedding = gemini_client.get_embedding(request.query, task_type="retrieval_query")
        
        # Query Chroma
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=request.n_results,
            where={"account_id": request.account_id}
        )
        
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@router.post("/ask", response_model=Any)
async def ask_knowledgebase(request: QueryRequest):
    """
    Synchronous RAG endpoint.
    Retrieves context and generates an answer using Gemini.
    """
    try:
        gemini_client = GeminiClient()
        chroma_client = ChromaClientFactory.get_client()
        collection = chroma_client.get_or_create_collection(name=request.collection_name)
        
        # 1. Retrieve Context
        query_embedding = gemini_client.get_embedding(request.query, task_type="retrieval_query")
        
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=request.n_results,
            where={"account_id": request.account_id}
        )
        
        documents = results['documents'][0] if results['documents'] else []
        
        if not documents:
            return {
                "answer": "I couldn't find any relevant information in your uploaded documents to answer that question.",
                "context": []
            }
            
        # 2. Construct Prompt
        context_text = "\n\n".join(documents)
        prompt = f"""You are a helpful assistant. Use the following context to answer the user's question.
If the answer is not in the context, say you don't know.

Context:
{context_text}

Question: {request.query}

Answer:"""

        # 3. Generate Answer
        response = gemini_client.generate_content(prompt)
        answer = response.text if response else "Failed to generate answer."
        
        return {
            "answer": answer,
            "context": documents
        }
        
    except Exception as e:
        logger.exception(f"Error in ask_knowledgebase: {e}")
        raise HTTPException(status_code=500, detail=f"Error processing RAG request: {str(e)}")


@router.get("/files", response_model=Any)
async def list_files(account_id: str):
    """
    List uploaded files for an account from MinIO.
    """
    try:
        client = get_minio_client()
        # List objects with prefix account_id/
        objects = client.list_objects(BUCKET_NAME, prefix=f"{account_id}/", recursive=True)
        
        files = []
        for obj in objects:
            # obj.object_name is like account_id/filename
            filename = obj.object_name.split('/', 1)[1] if '/' in obj.object_name else obj.object_name
            files.append({
                "filename": filename,
                "size": obj.size,
                "last_modified": obj.last_modified,
                "object_name": obj.object_name
            })
            
        return files
    except Exception as e:
        logger.exception(f"Error listing files: {e}")
        # If bucket doesn't exist, return empty list
        if "NoSuchBucket" in str(e):
            return []
        raise HTTPException(status_code=500, detail=f"Error listing files: {str(e)}")

@router.post("/", response_model=Any)
async def add_document(
    account_id: str = Form(...),
    file: UploadFile = File(...)
):
    print(f"[DEBUG] Uploading document: {file.filename} for account: {account_id}")
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
        logger.exception(f"Error in add_document: {str(e)}")
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
