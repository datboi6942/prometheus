from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel

class FailureRecord(BaseModel):
    action: str
    error: str
    file: Optional[str] = None
    context: Optional[str] = None
    timestamp: datetime = datetime.now()

class FailureMemory:
    """Session-scoped memory of failed operations to prevent repeating mistakes."""

    def __init__(self):
        self.failures: List[FailureRecord] = []

    def record_failure(self, action: str, error: str, file: Optional[str] = None, context: Optional[str] = None):
        """Record a failed operation."""
        record = FailureRecord(
            action=action,
            error=error,
            file=file,
            context=context,
            timestamp=datetime.now()
        )
        self.failures.append(record)

    def get_recent_failures(self, limit: int = 5) -> List[FailureRecord]:
        """Get the most recent failures."""
        return self.failures[-limit:]

    def get_context_prompt(self) -> str:
        """Get a formatted string for inclusion in the system prompt."""
        if not self.failures:
            return ""

        recent = self.get_recent_failures()
        prompt = "\n\n⚠️ RECENT FAILURES (Do not repeat these mistakes):\n"
        for f in recent:
            file_info = f" in {f.file}" if f.file else ""
            prompt += f"- Action: {f.action}{file_info}\n"
            prompt += f"  Error: {f.error}\n"
        
        return prompt

    def has_similar_failure(self, action: str, file: Optional[str]) -> bool:
        """Check if a similar failure has occurred recently."""
        for f in self.failures[-10:]:
            if f.action == action and f.file == file:
                return True
        return False

    def clear(self):
        """Clear the failure memory."""
        self.failures = []
