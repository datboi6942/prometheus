import pytest
from prometheus.services.todo_tracker import TodoTracker

def test_todo_tracker_operations():
    tracker = TodoTracker()
    
    # Write todos
    tracker.write_todos([
        {"id": "task1", "content": "Complete plan", "status": "pending"},
        {"id": "task2", "content": "Write code", "status": "pending"}
    ])
    
    assert len(tracker.todos) == 2
    assert tracker.todos[0].id == "task1"
    
    # Update todo
    result = tracker.update_todo("task1", "completed")
    assert result["success"] is True
    assert tracker.todos[0].status == "completed"
    
    # Update non-existent todo
    result = tracker.update_todo("unknown", "completed")
    assert result["success"] is False

def test_todo_context_prompt():
    tracker = TodoTracker()
    tracker.write_todos([
        {"id": "t1", "content": "Task 1", "status": "completed"},
        {"id": "t2", "content": "Task 2", "status": "in_progress"}
    ])
    
    prompt = tracker.get_context_prompt()
    assert "CURRENT TASK LIST" in prompt
    assert "✅ [t1] Task 1 (completed)" in prompt
    assert "🔄 [t2] Task 2 (in_progress)" in prompt
