import pytest
import os
from pathlib import Path
from prometheus.services.checkpoint_service import CheckpointService
from prometheus.database import init_db

@pytest.fixture
async def setup_db():
    await init_db()

@pytest.mark.asyncio
async def test_checkpoint_lifecycle(tmp_path, setup_db):
    service = CheckpointService()
    workspace = str(tmp_path)
    
    # Create a file
    test_file = tmp_path / "code.py"
    test_file.write_text("v1 content")
    
    # Create checkpoint
    cp_id = await service.create_checkpoint(workspace, ["code.py"], "Initial version")
    assert cp_id is not None
    
    # Modify file
    test_file.write_text("v2 content")
    
    # List checkpoints
    checkpoints = await service.list_checkpoints(workspace)
    assert len(checkpoints) >= 1
    assert checkpoints[0]["id"] == cp_id
    
    # Restore checkpoint
    result = await service.restore_checkpoint(cp_id)
    assert result["success"] is True
    
    # Verify content restored
    assert test_file.read_text() == "v1 content"
