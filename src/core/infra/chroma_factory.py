import os

class ChromaClientFactory:
    @staticmethod
    def get_client():
        """
        Returns a ChromaDB client based on environment variables.
        Supports both HttpClient (self-hosted) and CloudClient.
        """
        use_cloud = os.getenv("CHROMA_USE_CLOUD", "false").lower() == "true"

        if use_cloud:
            # Use chromadb-client package for cloud connections (newer API)
            import chromadb
            
            api_key = os.getenv("CHROMA_CLOUD_API_KEY", "")
            tenant = os.getenv("CHROMA_CLOUD_TENANT", "default_tenant")
            database = os.getenv("CHROMA_CLOUD_DATABASE", "default_database")

            print(f"Connecting to ChromaDB Cloud (Tenant: {tenant}, Database: {database})")
            
            # CloudClient requires chromadb >= 0.5.0
            # For 0.4.x, use HttpClient with cloud URL
            try:
                return chromadb.CloudClient(
                    api_key=api_key,
                    tenant=tenant,
                    database=database
                )
            except AttributeError:
                # Fallback for older chromadb versions - use HttpClient with cloud endpoint
                print("CloudClient not available, using HttpClient with cloud endpoint")
                return chromadb.HttpClient(
                    host="api.trychroma.com",
                    port=443,
                    ssl=True,
                    headers={"Authorization": f"Bearer {api_key}"},
                    tenant=tenant,
                    database=database
                )
        else:
            import chromadb
            
            host = os.getenv("CHROMA_HOST", "localhost")
            port = os.getenv("CHROMA_PORT", "8000")

            print(f"Connecting to ChromaDB Self-Hosted at {host}:{port}")
            
            # Simple connection without authentication
            return chromadb.HttpClient(
                host=host,
                port=int(port)
            )
