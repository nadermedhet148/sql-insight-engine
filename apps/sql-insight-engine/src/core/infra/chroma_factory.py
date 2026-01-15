import os
import threading
from typing import Optional

# Global ChromaDB client cache for connection reuse
_chroma_client = None
_chroma_client_lock = threading.Lock()


class ChromaClientFactory:
    @staticmethod
    def get_client():
        """
        Returns a cached ChromaDB client based on environment variables.
        Supports both HttpClient (self-hosted) and CloudClient.
        Uses a singleton pattern to reuse connections.
        """
        global _chroma_client

        # Fast path: return cached client
        if _chroma_client is not None:
            return _chroma_client

        # Slow path: create client with lock
        with _chroma_client_lock:
            # Double-check after acquiring lock
            if _chroma_client is not None:
                return _chroma_client

            use_cloud = os.getenv("CHROMA_USE_CLOUD", "false").lower() == "true"

            if use_cloud:
                _chroma_client = ChromaClientFactory._create_cloud_client()
            else:
                _chroma_client = ChromaClientFactory._create_http_client()

            return _chroma_client

    @staticmethod
    def _create_cloud_client():
        """Create a ChromaDB Cloud client."""
        import chromadb

        api_key = os.getenv("CHROMA_CLOUD_API_KEY", "")
        tenant = os.getenv("CHROMA_CLOUD_TENANT", "default_tenant")
        database = os.getenv("CHROMA_CLOUD_DATABASE", "default_database")

        print(f"Connecting to ChromaDB Cloud (Tenant: {tenant}, Database: {database})")

        try:
            return chromadb.CloudClient(
                api_key=api_key,
                tenant=tenant,
                database=database
            )
        except AttributeError:
            # Fallback for older chromadb versions
            print("CloudClient not available, using HttpClient with cloud endpoint")
            return chromadb.HttpClient(
                host="api.trychroma.com",
                port=443,
                ssl=True,
                headers={"Authorization": f"Bearer {api_key}"},
                tenant=tenant,
                database=database
            )

    @staticmethod
    def _create_http_client():
        """Create a ChromaDB HTTP client with optimized settings."""
        import chromadb
        from chromadb.config import Settings

        host = os.getenv("CHROMA_HOST", "localhost")
        port = os.getenv("CHROMA_PORT", "8000")

        print(f"Connecting to ChromaDB Self-Hosted at {host}:{port}")

        # Create client with connection pooling settings
        return chromadb.HttpClient(
            host=host,
            port=int(port),
            settings=Settings(
                anonymized_telemetry=False,
            )
        )

    @staticmethod
    def reset_client():
        """Reset the cached client (useful for testing or reconnection)."""
        global _chroma_client
        with _chroma_client_lock:
            _chroma_client = None
