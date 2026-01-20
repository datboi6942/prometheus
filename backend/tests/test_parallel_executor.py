import pytest
import asyncio
from prometheus.services.parallel_executor import ParallelExecutor

def test_dependency_classification():
    executor = ParallelExecutor(max_parallel=2)
    tool_calls = [
        {"tool": "filesystem_read", "args": {"path": "file1.py"}},
        {"tool": "filesystem_read", "args": {"path": "file2.py"}},
        {"tool": "filesystem_write", "args": {"path": "file3.py", "content": "..."}},
        {"tool": "filesystem_write", "args": {"path": "file3.py", "content": "overlap"}},
        {"tool": "shell_execute", "args": {"command": "ls"}},
    ]
    
    batches, sequential = executor.classify_dependencies(tool_calls)
    
    # Batch 1: first two reads
    assert len(batches) >= 1
    assert len(batches[0]) == 2
    assert batches[0][0]["tool"] == "filesystem_read"
    
    # The overlapping write and shell_execute should be sequential
    assert len(sequential) >= 2
    assert any(tc["tool"] == "shell_execute" for tc in sequential)

@pytest.mark.asyncio
async def test_execute_parallel():
    executor = ParallelExecutor()
    tool_calls = [
        {"tool": "test", "id": 1},
        {"tool": "test", "id": 2},
    ]
    
    async def mock_execute(tc):
        await asyncio.sleep(0.01)
        return tc["id"]
        
    results = await executor.execute_parallel(tool_calls, mock_execute)
    assert len(results) == 2
    assert 1 in results
    assert 2 in results
