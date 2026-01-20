import pytest
from prometheus.services.failure_memory import FailureMemory

def test_failure_memory_recording():
    memory = FailureMemory()
    memory.record_failure("test_action", "test_error", "test.py")
    
    assert len(memory.failures) == 1
    assert memory.failures[0].action == "test_action"
    assert memory.failures[0].error == "test_error"
    assert memory.failures[0].file == "test.py"

def test_failure_memory_prompt():
    memory = FailureMemory()
    memory.record_failure("write", "Permission denied", "config.json")
    
    prompt = memory.get_context_prompt()
    assert "RECENT FAILURES" in prompt
    assert "write in config.json" in prompt
    assert "Permission denied" in prompt

def test_has_similar_failure():
    memory = FailureMemory()
    memory.record_failure("test", "err", "file.py")
    
    assert memory.has_similar_failure("test", "file.py") is True
    assert memory.has_similar_failure("test", "other.py") is False
    assert memory.has_similar_failure("other", "file.py") is False
