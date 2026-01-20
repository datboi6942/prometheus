import pytest
import numpy as np
from unittest.mock import patch, MagicMock
from prometheus.services.codebase_index import CodebaseIndex
from prometheus.database import init_db

@pytest.fixture
async def setup_db():
    await init_db()

@pytest.mark.asyncio
async def test_indexing_and_search(tmp_path, setup_db):
    # Mock EmbeddingsService to avoid calling real APIs/loading large models
    with patch("prometheus.services.codebase_index.EmbeddingsService") as mock_service_class:
        mock_service = mock_service_class.return_value
        # Mock embedding return value (384-dim vector for all-MiniLM-L6-v2)
        mock_embedding = [0.1] * 384
        mock_service.embed.return_value = [mock_embedding]
        mock_service.embed_file.return_value = [
            {"content": "def hello(): print('world')", "embedding": mock_embedding, "start": 0, "end": 20}
        ]
        
        index = CodebaseIndex(str(tmp_path))
        
        # Create a test file
        test_file = tmp_path / "hello.py"
        test_file.write_text("def hello(): print('world')")
        
        # Index file
        await index.index_file("hello.py")
        
        # Search
        results = await index.search("hello function")
        assert len(results) >= 1
        assert results[0]["file_path"] == "hello.py"
        assert "hello" in results[0]["content"]
        assert results[0]["similarity"] > 0.99 # Same embedding
