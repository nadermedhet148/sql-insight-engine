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

        # Use semantic chunking
        # Returns list of (chunk_text, chunk_embedding)
        chunks_data = self.semantic_chunk_text(content)
        print(f"Split into {len(chunks_data)} semantic chunks")
        
        ids = []
        documents = []
        metadatas = []
        embeddings = []
        
        for i, (chunk_text, chunk_emb) in enumerate(chunks_data):
            chunk_id = f"{object_name}_{i}"
            
            # If embedding is missing (fallback case), try to generate one last time or skip
            # The semantic chunker tries hard to return valid embeddings calculate from the centroid or similar.
            # But let's check.
            if chunk_emb is None or len(chunk_emb) == 0:
                 print(f"Warning: Empty embedding for chunk {i}, retrying generation.")
                 chunk_emb = self.gemini_client.get_embedding(chunk_text, task_type="retrieval_document")
            
            if not chunk_emb:
                 print(f"Skipping chunk {i} due to empty embedding")
                 continue

            ids.append(chunk_id)
            documents.append(chunk_text)
            embeddings.append(chunk_emb)
            metadatas.append({
                "account_id": account_id,
                "object_name": object_name,
                "filename": filename,
                "chunk_index": i
            })
                
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

    def semantic_chunk_text(self, text, max_chunk_size=1000, similarity_threshold=0.5):
        """
        Splits text into chunks based on semantic similarity of sentences.
        Returns a list of tuples: (chunk_text, chunk_embedding_vector).
        The chunk_embedding_vector is the centroid of the sentences in that chunk.
        """
        import re
        import numpy as np
        
        if not text:
            return []
            
        # 1. Split into sentences
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if not sentences:
            return []
            
        if len(sentences) == 1:
            # Generate single embedding
            emb = self.gemini_client.get_embedding(sentences[0], task_type="retrieval_document")
            return [(sentences[0], emb)]

        # 2. Get embeddings for ALL sentences in a batch
        try:
            embeddings_list = self.gemini_client.get_batch_embeddings(sentences, task_type="retrieval_document")
        except Exception as e:
            print(f"Batch embedding failed: {e}. Falling back to single chunk.")
            # Fallback: return single chunk with no embedding (caller handles regeneration)
            return [(" ".join(sentences), [])]
            
        if not embeddings_list or len(embeddings_list) != len(sentences):
            print("Mismatch or empty embeddings. Falling back to simple size splitting.")
            return [(" ".join(sentences), [])]

        # Convert to numpy for efficiency
        embeddings = [np.array(e) for e in embeddings_list]

        chunks = []
        current_chunk_sentences = [sentences[0]]
        current_chunk_size = len(sentences[0])
        
        # Track the "Topic" (Centroid)
        current_chunk_embedding = embeddings[0]
        current_chunk_count = 1

        for i in range(1, len(sentences)):
            sentence = sentences[i]
            emb = embeddings[i]
            
            # 1. Coarse size check
            if current_chunk_size + len(sentence) > max_chunk_size:
                # Finalize chunk
                chunk_text = " ".join(current_chunk_sentences)
                # Store the centroid as the chunk's representative embedding
                chunks.append((chunk_text, current_chunk_embedding.tolist()))
                
                # Start new
                current_chunk_sentences = [sentence]
                current_chunk_size = len(sentence)
                current_chunk_embedding = emb
                current_chunk_count = 1
                continue
            
            # 2. Semantic check against Centroid
            norm_a = np.linalg.norm(current_chunk_embedding)
            norm_b = np.linalg.norm(emb)
            
            sim = 0
            if norm_a > 0 and norm_b > 0:
                sim = np.dot(current_chunk_embedding, emb) / (norm_a * norm_b)
            
            if sim < similarity_threshold:
                # Topic Shift
                chunk_text = " ".join(current_chunk_sentences)
                chunks.append((chunk_text, current_chunk_embedding.tolist()))
                
                # Start new
                current_chunk_sentences = [sentence]
                current_chunk_size = len(sentence)
                current_chunk_embedding = emb
                current_chunk_count = 1
            else:
                # Continuation
                current_chunk_sentences.append(sentence)
                current_chunk_size += len(sentence)
                
                # Update Centroid
                prev_sum = current_chunk_embedding * current_chunk_count
                current_chunk_count += 1
                current_chunk_embedding = (prev_sum + emb) / current_chunk_count

        if current_chunk_sentences:
            chunk_text = " ".join(current_chunk_sentences)
            chunks.append((chunk_text, current_chunk_embedding.tolist()))
            
        return chunks
