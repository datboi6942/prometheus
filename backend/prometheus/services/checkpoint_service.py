import uuid
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import aiosqlite
from prometheus.database import DB_PATH

class CheckpointService:
    """Manages file checkpoints for undo/rollback functionality."""

    async def create_checkpoint(self, workspace_path: str, file_paths: List[str], description: Optional[str] = None, conversation_id: Optional[str] = None, auto_prune: bool = True, keep_last: int = 5) -> str:
        """Create a checkpoint for one or more files.
        
        Args:
            workspace_path: Path to workspace.
            file_paths: List of file paths relative to workspace.
            description: Optional description.
            conversation_id: Optional conversation ID.
            auto_prune: Automatically prune old checkpoints after creation.
            keep_last: Number of recent checkpoints to keep if auto_prune is True.
            
        Returns:
            str: Checkpoint ID.
        """
        checkpoint_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        
        async with aiosqlite.connect(DB_PATH) as db:
            for path in file_paths:
                try:
                    # Read current content
                    full_path = (self.workspace_path(workspace_path) / path).resolve()
                    if not full_path.exists():
                        continue
                        
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    
                    await db.execute(
                        """
                        INSERT INTO checkpoints (id, workspace_path, file_path, content, created_at, description, conversation_id)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (checkpoint_id, workspace_path, path, content, now, description, conversation_id)
                    )
                except Exception as e:
                    import structlog
                    structlog.get_logger().error("Failed to create checkpoint for file", file=path, error=str(e))
            
            await db.commit()
        
        # Auto-prune old checkpoints to prevent database bloat
        if auto_prune:
            await self.prune_old_checkpoints(workspace_path, keep_last)
        
        return checkpoint_id

    async def restore_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """Restore files from a checkpoint."""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM checkpoints WHERE id = ?", (checkpoint_id,)) as cursor:
                rows = await cursor.fetchall()
                if not rows:
                    return {"success": False, "error": f"Checkpoint {checkpoint_id} not found"}
                
                restored_files = []
                for row in rows:
                    workspace_path = row["workspace_path"]
                    file_path = row["file_path"]
                    content = row["content"]
                    
                    try:
                        full_path = (self.workspace_path(workspace_path) / file_path).resolve()
                        full_path.parent.mkdir(parents=True, exist_ok=True)
                        with open(full_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        restored_files.append(file_path)
                    except Exception as e:
                        return {"success": False, "error": f"Failed to restore {file_path}: {str(e)}"}
                
                return {"success": True, "restored_files": restored_files}

    async def list_checkpoints(self, workspace_path: str, limit: int = 20) -> List[Dict[str, Any]]:
        """List recent checkpoints for a workspace."""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            # Use DISTINCT id to get unique checkpoints (a checkpoint can have multiple files)
            async with db.execute(
                """
                SELECT id, description, created_at, conversation_id, GROUP_CONCAT(file_path) as files
                FROM checkpoints 
                WHERE workspace_path = ? 
                GROUP BY id 
                ORDER BY created_at DESC 
                LIMIT ?
                """,
                (workspace_path, limit)
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def prune_old_checkpoints(self, workspace_path: str, keep_last: int = 5) -> int:
        """Delete old checkpoints, keeping only the most recent ones.
        
        Args:
            workspace_path: Workspace path to prune checkpoints for.
            keep_last: Number of most recent checkpoints to keep.
            
        Returns:
            int: Number of checkpoints deleted.
        """
        if keep_last < 0:
            keep_last = 5
            
        async with aiosqlite.connect(DB_PATH) as db:
            # Get checkpoint IDs ordered by creation time (newest first)
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT id, MAX(created_at) as latest_created
                FROM checkpoints 
                WHERE workspace_path = ? 
                GROUP BY id 
                ORDER BY latest_created DESC
                """,
                (workspace_path,)
            ) as cursor:
                rows = list(await cursor.fetchall())
                
            if len(rows) <= keep_last:
                return 0
                
            # IDs to delete (all except first keep_last)
            ids_to_delete = [row["id"] for row in rows[keep_last:]]
            
            if not ids_to_delete:
                return 0
                
            # Delete checkpoints (cascade deletes all files for each checkpoint)
            placeholders = ",".join("?" * len(ids_to_delete))
            await db.execute(
                f"DELETE FROM checkpoints WHERE id IN ({placeholders})",
                ids_to_delete
            )
            await db.commit()
            return len(ids_to_delete)

    def workspace_path(self, path: str):
        from pathlib import Path
        return Path(path)
