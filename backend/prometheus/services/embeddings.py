import asyncio
from typing import List, Optional
import numpy as np
import litellm
import structlog
from prometheus.config import settings

logger = structlog.get_logger()

class EmbeddingsService:
    """Generates embeddings using local models or remote APIs."""

    def __init__(self, use_openai: Optional[bool] = None, api_key: Optional[str] = None):
        self.use_openai = use_openai if use_openai is not None else settings.use_openai_embeddings
        self.api_key = api_key
        self._local_model = None

    async def embed(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of strings."""
        if not texts:
            return []

        if self.use_openai:
            # Try to get API key from database if not provided
            if not self.api_key:
                from prometheus.database import get_all_settings
                db_settings = await get_all_settings()
                self.api_key = db_settings.get("openai_api_key")

            return await self._embed_openai(texts)
        else:
            return await self._embed_local(texts)

    async def _embed_openai(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using OpenAI via LiteLLM."""
        try:
            response = await litellm.aembedding(
                model=settings.openai_embedding_model,
                input=texts,
                api_key=self.api_key
            )
            return [data["embedding"] for data in response.data]
        except Exception as e:
            logger.error("OpenAI embedding failed, falling back to local", error=str(e))
            # Only fallback if local dependencies are actually installed
            try:
                return await self._embed_local(texts)
            except Exception:
                raise e

    async def _embed_local(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using sentence-transformers (local)."""
        try:
            if self._local_model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError:
                    logger.error("sentence-transformers not installed. Install with 'pip install .[local-models]'")
                    raise RuntimeError(
                        "Local embeddings are not available. Please install the required dependencies "
                        "with 'pip install .[local-models]' or configure OpenAI embeddings in settings."
                    )
                
                # Run in a separate thread to avoid blocking the event loop
                self._local_model = await asyncio.to_thread(
                    SentenceTransformer, settings.local_embedding_model
                )
            
            embeddings = await asyncio.to_thread(self._local_model.encode, texts)
            return embeddings.tolist()
        except Exception as e:
            logger.error("Local embedding failed", error=str(e))
            raise

    async def embed_file(self, file_content: str, chunk_size: int = 1000, chunk_overlap: int = 200):
        """Chunk a file and generate embeddings for each chunk."""
        # Simple character-based chunking for now
        chunks = []
        for i in range(0, len(file_content), chunk_size - chunk_overlap):
            chunk = file_content[i:i + chunk_size]
            if chunk:
                chunks.append(chunk)
        
        if not chunks:
            return []
            
        embeddings = await self.embed(chunks)
        return [{"content": chunks[i], "embedding": embeddings[i], "start": i*(chunk_size-chunk_overlap), "end": i*(chunk_size-chunk_overlap)+len(chunks[i])} for i in range(len(chunks))]
