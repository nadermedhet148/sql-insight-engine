# Semantic Chunking Implementation

The Semantic Chunking implementation in `knowledgebase/consumer.py` is designed to split text based on **meaning (topics)** rather than just character counts. This ensures that a chunk doesn't cut off in the middle of a thought or combine two unrelated topics.

## Algorithm Breakdown

### 1. Sentence Splitting

First, we break the raw text into individual sentences using a Regular Expression. We operate on sentences because they are the smallest unit of complete meaning.

```python
import re
sentences = re.split(r'(?<=[.!?])\s+', text)
sentences = [s.strip() for s in sentences if s.strip()]
```


### 2. Batch Embedding Generation (Optimization)

To avoid the "N+1 API Problem" (calling the API for every single sentence), we generate embeddings for all sentences in a single batch request using `get_batch_embeddings`. This significantly improves performance.

### 3. Sequential Comparison & Topic Shift (Centroid Matching)

The algorithm iterates through the sentences and decides whether to keep them in the current chunk or start a new one.

**Topic Drift Solution**: Instead of comparing a new sentence to just the _immediately preceding_ sentence (which allows the topic to drift A->B->C->Z), we compare the new sentence to the **Centroid (Average)** of the current chunk. This ensures the chunk stays focused on its core topic.

**The Logic:**

- **Calculate Similarity**: Calculate cosine similarity between the **New Sentence's Embedding** and the **Current Chunk's Centroid**.
- **Threshold Check (`similarity_threshold=0.5`)**:
  - **High Similarity (> 0.5)**: The sentence fits the current topic. We add it to the chunk and **update the centroid** (running average).
  - **Low Similarity (< 0.5)**: A "Topic Shift" is detected. We finalize the current chunk and start a new one with the new sentence as the new centroid.

### 4. Safety Limits

To prevent chunks from growing infinitely, we enforce a `max_chunk_size`. If a sentence would exceed this limit, we force a split and reset the centroid.

### Code Snippet

```python
    def semantic_chunk_text(self, text, max_chunk_size=1000, similarity_threshold=0.5):
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
            # For a single sentence, return it as a chunk with its embedding
            embedding = self.gemini_client.get_embedding(sentences[0], task_type="retrieval_document")
            if embedding:
                return [(sentences[0], np.array(embedding).tolist())]
            return [sentences[0]] # Fallback if embedding fails

        # Helper for cosine similarity
        def cosine_similarity(vec1, vec2):
            norm_a = np.linalg.norm(vec1)
            norm_b = np.linalg.norm(vec2)
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return np.dot(vec1, vec2) / (norm_a * norm_b)

        # 2. Get embeddings for ALL sentences in a batch
        embeddings_list = self.gemini_client.get_batch_embeddings(sentences, task_type="retrieval_document")
        # Ensure all embeddings are numpy arrays, handle potential None from API
        embeddings = [np.array(e) if e is not None else np.zeros(768) for e in embeddings_list]

        chunks = []
        current_chunk_sentences = [sentences[0]]
        current_chunk_size = len(sentences[0])

        # Track the "Topic" (Centroid) to prevent drift
        current_chunk_embedding = embeddings[0]
        current_chunk_count = 1

        for i in range(1, len(sentences)):
            sentence = sentences[i]
            emb = embeddings[i]

            # 1. Coarse size check
            if current_chunk_size + len(sentence) > max_chunk_size:
                # Force split due to size
                chunks.append((" ".join(current_chunk_sentences), current_chunk_embedding.tolist()))
                current_chunk_sentences = [sentence]
                current_chunk_size = len(sentence)
                current_chunk_embedding = emb
                current_chunk_count = 1
                continue

            # 2. Semantic check against Centroid
            sim = cosine_similarity(current_chunk_embedding, emb)

            if sim < similarity_threshold:
                # Topic Shift Detected
                chunks.append((" ".join(current_chunk_sentences), current_chunk_embedding.tolist()))
                current_chunk_sentences = [sentence]
                current_chunk_size = len(sentence)
                current_chunk_embedding = emb
                current_chunk_count = 1
            else:
                # Semantic Continuation
                current_chunk_sentences.append(sentence)
                current_chunk_size += len(sentence)

                # Update Centroid (Running Average)
                prev_sum = current_chunk_embedding * current_chunk_count
                current_chunk_count += 1
                current_chunk_embedding = (prev_sum + emb) / current_chunk_count

        if current_chunk_sentences:
            chunks.append((" ".join(current_chunk_sentences), current_chunk_embedding.tolist()))

        return chunks
```
