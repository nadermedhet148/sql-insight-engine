from typing import Optional, List
from dataclasses import dataclass
from core.gemini_client import GeminiClient
from core.infra.chroma_factory import ChromaClientFactory
from core.services.database_service import database_service, DatabaseOperationResult


@dataclass
class QueryResult:
    """Result from processing a natural language query"""
    success: bool
    generated_sql: Optional[str] = None
    raw_results: Optional[str] = None
    formatted_response: Optional[str] = None
    reasoning: Optional[str] = None
    error: Optional[str] = None


class QueryService:
    
    def __init__(self):
        self.gemini_client = GeminiClient()
        self.chroma_client = None
    
    def _get_chroma_client(self):
        """Lazy initialization of ChromaDB client"""
        if self.chroma_client is None:
            self.chroma_client = ChromaClientFactory.get_client()
        return self.chroma_client
    
    def retrieve_schema_context(self, account_id: str, question: str, collection_name: str = "account_schema_info") -> List[str]:
        try:
            chroma_client = self._get_chroma_client()
            
            # Get or create collection
            collection = chroma_client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            
            # Generate embedding for the question
            query_embedding = self.gemini_client.get_embedding(question, task_type="retrieval_query")
            
            # Query ChromaDB for relevant schema information
            # Filter by account_id to get only this user's schema
            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=5,
                where={"account_id": account_id}
            )
            
            # Extract documents
            if results and results.get('documents') and len(results['documents']) > 0:
                context_docs = results['documents'][0]
                print(f"Retrieved {len(context_docs)} schema context documents from knowledge base")
                return context_docs
            else:
                print("No schema context found in knowledge base")
                return []
                
        except Exception as e:
            print(f"Error retrieving schema context: {e}")
            return []
    
    def generate_sql_query(self, question: str, schema_context: List[str]) -> str:
        try:
            # Build context string
            if schema_context:
                context_str = "\n\n".join(schema_context)
            else:
                context_str = "No specific schema information available."
            
            # Create prompt for SQL generation
            prompt = f"""You are an expert SQL query generator. Your task is to generate a valid SQL query based on a natural language question and database schema information.

                        Database Schema Information:
                        {context_str}

                        Natural Language Question: "{question}"

                        Instructions:
                        - Generate a valid PostgreSQL SELECT query that answers the question
                        - Use only the tables and columns mentioned in the schema
                        - Include appropriate JOINs if multiple tables are needed
                        - Add ORDER BY and LIMIT clauses when appropriate
                        - Return ONLY the SQL query, no explanations or markdown formatting
                        SQL Query:"""
            
            sql_query = self.gemini_client.generate_content(prompt)
            
            # Clean up the response
            clean_query = sql_query.strip()
            # Remove markdown code blocks if present
            if clean_query.startswith("```sql"):
                clean_query = clean_query[6:]
            if clean_query.startswith("```"):
                clean_query = clean_query[3:]
            if clean_query.endswith("```"):
                clean_query = clean_query[:-3]
            clean_query = clean_query.strip()
            # Remove trailing semicolon if present
            if clean_query.endswith(";"):
                clean_query = clean_query[:-1].strip()
            
            print(f"Generated SQL query: {clean_query}")
            return clean_query
            
        except Exception as e:
            print(f"Error generating SQL query: {e}")
            raise Exception(f"Failed to generate SQL query: {str(e)}")
    
    def format_results(self, question: str, sql_query: str, raw_results: str) -> str:
        """
        Format query results into a human-readable response.
        
        Args:
            question: Original natural language question
            sql_query: SQL query that was executed
            raw_results: Raw query results (markdown table format)
            
        Returns:
            Formatted natural language response
        """
        try:
            prompt = f"""You are a data analyst assistant. Format the following query results into a clear, natural language response.

            Original Question: "{question}"

            SQL Query Executed:
            {sql_query}

            Query Results:
            {raw_results}

            Instructions:
            - Provide a clear, concise answer to the original question
            - If the results contain numeric data, highlight the key insights
            - If it's a list, summarize the top items
            - If there are no results, explain that clearly
            - Keep the response conversational and easy to understand
            - Do not include technical jargon unless necessary

            Response:"""
            
            formatted_response = self.gemini_client.generate_content(prompt)
            return formatted_response.strip()
            
        except Exception as e:
            print(f"Error formatting results: {e}")
            # Fallback to raw results if formatting fails
            return f"Here are the results:\n\n{raw_results}"
    
    def process_nl_query(self, account_id: str, db_config, question: str) -> QueryResult:
        reasoning_steps = []
        
        try:
            # Step 1: Retrieve schema context from knowledge base
            print(f"[QUERY SERVICE] Starting natural language query processing")
            print(f"[QUERY SERVICE] Account ID: {account_id}")
            print(f"[QUERY SERVICE] Question: '{question}'")
            print(f"[QUERY SERVICE] Step 1/4: Retrieving schema context from knowledge base...")
            
            schema_context = self.retrieve_schema_context(account_id, question)
            
            if schema_context:
                print(f"[QUERY SERVICE] ✓ Retrieved {len(schema_context)} relevant schema documents")
                reasoning_steps.append(f"Retrieved {len(schema_context)} relevant schema documents from knowledge base")
                for i, doc in enumerate(schema_context[:2], 1):
                    snippet = doc[:150] + "..." if len(doc) > 150 else doc
                    print(f"[QUERY SERVICE]   Document {i}: {snippet}")
            else:
                print(f"[QUERY SERVICE] ⚠ No schema context found in knowledge base")
                reasoning_steps.append("No specific schema context found, using general SQL knowledge")
            
            # Step 2: Generate SQL query using LLM
            print(f"[QUERY SERVICE] Step 2/4: Generating SQL query using Gemini LLM...")
            sql_query = self.generate_sql_query(question, schema_context)
            
            if not sql_query:
                print(f"[QUERY SERVICE] ✗ Failed to generate SQL query")
                return QueryResult(
                    success=False,
                    error="Failed to generate SQL query",
                    reasoning="\n".join(reasoning_steps)
                )
            
            print(f"[QUERY SERVICE] ✓ Generated SQL query:")
            print(f"[QUERY SERVICE]   {sql_query}")
            reasoning_steps.append(f"Generated SQL query: {sql_query}")
            
            # Step 3: Execute query
            print(f"[QUERY SERVICE] Step 3/4: Executing query on user database...")
            execution_result: DatabaseOperationResult = database_service.execute_query(db_config, sql_query)
            
            if not execution_result.success:
                print(f"[QUERY SERVICE] ✗ Query execution failed: {execution_result.error}")
                reasoning_steps.append(f"Query execution failed: {execution_result.error}")
                return QueryResult(
                    success=False,
                    generated_sql=sql_query,
                    error=f"Query execution failed: {execution_result.error}",
                    reasoning="\n".join(reasoning_steps)
                )
            
            raw_results = execution_result.data
            result_lines = raw_results.split('\n')
            result_preview = '\n'.join(result_lines[:5]) + ('...' if len(result_lines) > 5 else '')
            print(f"[QUERY SERVICE] ✓ Query executed successfully")
            print(f"[QUERY SERVICE]   Results preview:\n{result_preview}")
            reasoning_steps.append(f"Query executed successfully, returned {len(result_lines)} lines of data")
            
            # Step 4: Format results using LLM
            print(f"[QUERY SERVICE] Step 4/4: Formatting results using Gemini LLM...")
            formatted_response = self.format_results(question, sql_query, raw_results)
            print(f"[QUERY SERVICE] ✓ Results formatted successfully")
            print(f"[QUERY SERVICE]   Response preview: {formatted_response[:200]}...")
            reasoning_steps.append(f"Formatted results into natural language response")
            
            print(f"[QUERY SERVICE] ✓ Query processing completed successfully")
            
            return QueryResult(
                success=True,
                generated_sql=sql_query,
                raw_results=raw_results,
                formatted_response=formatted_response,
                reasoning="\n".join(reasoning_steps)
            )
            
        except Exception as e:
            print(f"[QUERY SERVICE] ✗ Error processing natural language query: {e}")
            reasoning_steps.append(f"Error occurred: {str(e)}")
            return QueryResult(
                success=False,
                error=str(e),
                reasoning="\n".join(reasoning_steps)
            )


query_service = QueryService()
