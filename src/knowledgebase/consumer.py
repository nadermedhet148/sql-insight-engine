import json
import os
import sys
import io

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.infra.consumer import BaseConsumer
from core.infra.minio_client import get_minio_client
import chromadb
from core.gemini_client import GeminiClient
from minio.error import S3Error

class KnowledgeBaseActionConsumer(BaseConsumer):
    def __init__(self, host='localhost', queue_name='document_ingestion'):
        super().__init__(queue_name=queue_name, host=host)
        
        self.minio_client = get_minio_client()
        
        from core.infra.chroma_factory import ChromaClientFactory
        self.chroma_client = ChromaClientFactory.get_client()
        self.collection = self.chroma_client.get_or_create_collection(name="knowledgebase")
        
        self.gemini_client = GeminiClient()

    def process_message(self, ch, method, properties, body):
        print(f"Received message: {body}")
        try:
            data = json.loads(body)
            action = data.get("action")
            
            if action == "add":
                self.handle_add(data)
            elif action == "delete":
                self.handle_delete(data)
            else:
                print(f"Unknown action: {action}")
            
            # Acknowledge success
            ch.basic_ack(delivery_tag=method.delivery_tag)
            
        except Exception as e:
            print(f"Error processing message: {e}")
            # BaseConsumer's callback will handle the nack
            raise e

    def handle_add(self, data):
        account_id = data.get("account_id")
        object_name = data.get("object_name")
        filename = data.get("filename")
        collection_name = data.get("collection_name", "knowledgebase")
        
        print(f"Processing ADD for object: {object_name} into collection: {collection_name}")
        
        try:
            response = self.minio_client.get_object("knowledgebase", object_name)
            content_bytes = response.read()
            content = content_bytes.decode('utf-8')
            response.close()
            response.release_conn()
        except Exception as e:
            print(f"Failed to download from Minio: {e}")
            return

        chunks = self.chunk_text(content)
        print(f"Split into {len(chunks)} chunks")
        
        ids = []
        documents = []
        metadatas = []
        embeddings = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{object_name}_{i}"
            
            try:
                emb = self.gemini_client.get_embedding(chunk, task_type="retrieval_document")
                if not emb:
                    print(f"Skipping chunk {i} due to empty embedding")
                    continue
                
                ids.append(chunk_id)
                documents.append(chunk)
                embeddings.append(emb)
                metadatas.append({
                    "account_id": account_id,
                    "object_name": object_name,
                    "filename": filename,
                    "chunk_index": i
                })
            except Exception as e:
                print(f"Error generating embedding for chunk {i}: {e}")
                
        if ids:
            try:
                collection = self.chroma_client.get_or_create_collection(name=collection_name)
                collection.add(
                    ids=ids,
                    documents=documents,
                    embeddings=embeddings,
                    metadatas=metadatas
                )
                print(f"Successfully indexed {len(ids)} chunks for {object_name} in {collection_name}")
            except Exception as e:
                print(f"Error indexing to ChromaDB: {e}")
        else:
            print("No chunks to index.")

    def handle_delete(self, data):
        object_name = data.get("object_name")
        collection_name = data.get("collection_name", "knowledgebase")
        print(f"Processing DELETE for object: {object_name} from collection: {collection_name}")
        
        try:
            collection = self.chroma_client.get_or_create_collection(name=collection_name)
            collection.delete(
                where={"object_name": object_name}
            )
            print(f"Deleted documents for {object_name} from {collection_name}")
        except Exception as e:
            print(f"Error deleting from ChromaDB: {e}")

    # [todo] use better parser later 
    def chunk_text(self, text, chunk_size=1000, overlap=100):
        if not text:
            return []
        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += (chunk_size - overlap)
        return chunks

