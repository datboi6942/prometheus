from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Todo(BaseModel):
    id: str
    content: str
    status: str  # "pending", "in_progress", "completed", "cancelled"

class TodoTracker:
    """Agent-controllable task tracking for multi-step operations."""

    def __init__(self):
        self.todos: List[Todo] = []

    def write_todos(self, todos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Overwrite the entire todo list."""
        self.todos = [Todo(**t) for t in todos]
        return {"success": True, "todos": [t.dict() for t in self.todos]}

    def update_todo(self, todo_id: str, status: str) -> Dict[str, Any]:
        """Update the status of a specific todo."""
        for todo in self.todos:
            if todo.id == todo_id:
                todo.status = status
                return {"success": True, "todo": todo.dict()}
        return {"success": False, "error": f"Todo with id {todo_id} not found"}

    def get_todos(self) -> List[Todo]:
        """Get the current list of todos."""
        return self.todos

    def get_context_prompt(self) -> str:
        """Get a formatted string for inclusion in the system prompt."""
        if not self.todos:
            return ""

        prompt = "\n\n📋 CURRENT TASK LIST:\n"
        for t in self.todos:
            status_icon = "⏳" if t.status == "pending" else "🔄" if t.status == "in_progress" else "✅" if t.status == "completed" else "❌"
            prompt += f"- {status_icon} [{t.id}] {t.content} ({t.status})\n"
        
        return prompt

    def clear(self):
        """Clear all todos."""
        self.todos = []
