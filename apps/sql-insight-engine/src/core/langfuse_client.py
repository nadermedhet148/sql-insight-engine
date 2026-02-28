import os
from langfuse import Langfuse

_client: "Langfuse | None" = None


def get_langfuse() -> "Langfuse | None":
    global _client
    if _client is None:
        secret = os.getenv("LANGFUSE_SECRET_KEY")
        public = os.getenv("LANGFUSE_PUBLIC_KEY")
        if not secret or not public:
            return None
        _client = Langfuse(
            secret_key=secret,
            public_key=public,
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        )
    return _client
