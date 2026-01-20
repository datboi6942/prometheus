import json
import asyncio
import numpy as np
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import aiosqlite
import structlog
from prometheus.database import DB_PATH
from prometheus.services.embeddings import EmbeddingsService

logger = structlog.get_logger()

# Global lock to prevent concurrent indexing of the same workspace
_indexing_locks: Dict[str, asyncio.Lock] = {}

class CodebaseIndex:
    """Indexes workspace files using embeddings and provides semantic search."""

    def __init__(self, workspace_path: str, api_key: Optional[str] = None):
        self.workspace_path = Path(workspace_path).resolve()
        self.embeddings_service = EmbeddingsService(api_key=api_key)

    async def is_indexed(self) -> bool:
        """Check if this workspace has any indexed embeddings."""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM codebase_embeddings WHERE workspace_path = ?",
                    (str(self.workspace_path),)
                ) as cursor:
                    count = (await cursor.fetchone())[0]
                    return count > 0
        except Exception:
            return False

    async def get_index_count(self) -> int:
        """Get the number of indexed chunks for this workspace."""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM codebase_embeddings WHERE workspace_path = ?",
                    (str(self.workspace_path),)
                ) as cursor:
                    return (await cursor.fetchone())[0]
        except Exception:
            return 0

    async def index_workspace(self, force: bool = False, progress_callback: Optional[Callable[[Dict[str, Any]], Any]] = None) -> Dict[str, Any]:
        """Index all files in the workspace (skipping ignored files)."""
        workspace_key = str(self.workspace_path)
        
        if workspace_key not in _indexing_locks:
            _indexing_locks[workspace_key] = asyncio.Lock()
            
        lock = _indexing_locks[workspace_key]
        
        if lock.locked():
            logger.info("Indexing already in progress for workspace", path=workspace_key)
            if progress_callback:
                msg = {"status": "error", "error": "Indexing already in progress"}
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(msg)
                else:
                    progress_callback(msg)
            return {"success": False, "error": "Indexing already in progress"}

        async with lock:
            logger.info("Starting workspace indexing", path=workspace_key)
            
            # In a real app, we'd respect .gitignore. For now, we'll exclude common noise.
            supported_extensions = {".py", ".js", ".ts", ".tsx", ".jsx", ".md", ".txt", ".html", ".css", ".json"}
            ignored_dirs = {
                "node_modules", ".venv", "venv", "env", ".env", 
                "__pycache__", ".git", ".hg", ".svn", ".vscode", 
                ".idea", "dist", "build", "target", ".cache",
                ".pytest_cache", ".mypy_cache", ".ruff_cache",
                "site-packages", "bin", "lib", "lib64", "include", "share"
            }
            
            # Use rglob to find all files
            all_files = []
            try:
                for file_path in self.workspace_path.rglob("*"):
                    if not file_path.is_file():
                        continue
                    
                    # Skip based on extensions
                    if file_path.suffix.lower() not in supported_extensions:
                        continue
                    
                    # Skip hidden files/dirs and ignored directories
                    try:
                        relative_path = file_path.relative_to(self.workspace_path)
                        parts = relative_path.parts
                        if any(part.startswith('.') for part in parts) or any(part in ignored_dirs for part in parts):
                            continue
                    except ValueError:
                        # Path is not relative to workspace (shouldn't happen with rglob)
                        continue
                    
                    all_files.append(file_path)
            except Exception as e:
                logger.error("Failed to list files for indexing", error=str(e))
                return {"success": False, "error": str(e)}
                
            total_files = len(all_files)
            indexed_count = 0
            skipped_count = 0
            already_indexed_count = 0
            
            if total_files == 0:
                result = {
                    "success": True,
                    "total_files": 0,
                    "indexed_files": 0,
                    "already_indexed": 0,
                    "skipped_files": 0
                }
                if progress_callback:
                    msg = {"status": "completed", "result": result, "total": 0, "current": 0, "percent": 100}
                    if asyncio.iscoroutinefunction(progress_callback):
                        await progress_callback(msg)
                    else:
                        progress_callback(msg)
                return result

            if progress_callback:
                msg = {"status": "starting", "total": total_files, "current": 0, "percent": 0}
                if asyncio.iscoroutinefunction(progress_callback):
                    await progress_callback(msg)
                else:
                    progress_callback(msg)

            # Process in batches to avoid overwhelming the DB and API
            async with aiosqlite.connect(DB_PATH) as db:
                for file_path in all_files:
                    try:
                        relative_path = str(file_path.relative_to(self.workspace_path))
                        
                        # Check if file has changed since last indexing
                        if not force:
                            async with db.execute("SELECT COUNT(*) FROM codebase_embeddings WHERE workspace_path = ? AND file_path = ?", (str(self.workspace_path), relative_path)) as cursor:
                                count = (await cursor.fetchone())[0]
                                if count > 0:
                                    already_indexed_count += 1
                                    indexed_count += 1
                                    
                                    # Update progress occasionally for large projects, or always for very small ones
                                    if progress_callback and (indexed_count % 10 == 0 or total_files <= 10):
                                        percent = int((indexed_count / total_files) * 100)
                                        msg = {"status": "indexing", "total": total_files, "current": indexed_count, "percent": percent, "file": relative_path}
                                        if asyncio.iscoroutinefunction(progress_callback):
                                            await progress_callback(msg)
                                        else:
                                            progress_callback(msg)
                                    continue

                        await self.index_file(relative_path, db=db)
                        indexed_count += 1
                        
                        if progress_callback:
                            percent = int((indexed_count / total_files) * 100)
                            msg = {"status": "indexing", "total": total_files, "current": indexed_count, "percent": percent, "file": relative_path}
                            if asyncio.iscoroutinefunction(progress_callback):
                                await progress_callback(msg)
                            else:
                                progress_callback(msg)
                                
                    except Exception as e:
                        logger.error("Failed to index file", file=str(file_path), error=str(e))
                        skipped_count += 1

            result = {
                "success": True,
                "total_files": total_files,
                "indexed_files": indexed_count - already_indexed_count,
                "already_indexed": already_indexed_count,
                "skipped_files": skipped_count
            }
            
        if progress_callback:
            final_msg = {
                "status": "completed", 
                "result": result,
                "total": total_files,
                "current": total_files,
                "percent": 100
            }
            if asyncio.iscoroutinefunction(progress_callback):
                await progress_callback(final_msg)
            else:
                progress_callback(final_msg)
                
        return result

    async def index_file(self, relative_path: str, db: Optional[aiosqlite.Connection] = None):
        """Index a single file."""
        full_path = (self.workspace_path / relative_path).resolve()
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        if not content.strip():
            return

        chunks = await self.embeddings_service.embed_file(content)
        now = datetime.now(timezone.utc).isoformat()
        
        should_close = False
        if db is None:
            db = await aiosqlite.connect(DB_PATH)
            should_close = True
            
        try:
            # Delete old embeddings for this file
            await db.execute("DELETE FROM codebase_embeddings WHERE workspace_path = ? AND file_path = ?", (str(self.workspace_path), relative_path))
            
            for chunk in chunks:
                # Store embedding as BLOB
                embedding_blob = np.array(chunk["embedding"], dtype=np.float32).tobytes()
                await db.execute(
                    """
                    INSERT INTO codebase_embeddings (workspace_path, file_path, chunk_start, chunk_end, content, embedding, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (str(self.workspace_path), relative_path, chunk["start"], chunk["end"], chunk["content"], embedding_blob, now)
                )
            await db.commit()
        finally:
            if should_close:
                await db.close()

    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for code snippets semantically similar to the query."""
        query_embedding = (await self.embeddings_service.embed([query]))[0]
        query_vec = np.array(query_embedding, dtype=np.float32)
        
        results = []
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM codebase_embeddings WHERE workspace_path = ?", (str(self.workspace_path),)) as cursor:
                async for row in cursor:
                    stored_vec = np.frombuffer(row["embedding"], dtype=np.float32)
                    
                    # Cosine similarity
                    similarity = np.dot(query_vec, stored_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(stored_vec))
                    
                    results.append({
                        "file_path": row["file_path"],
                        "content": row["content"],
                        "start": row["chunk_start"],
                        "end": row["chunk_end"],
                        "similarity": float(similarity)
                    })
        
        # Sort by similarity descending
        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results[:limit]

    async def invalidate(self, relative_path: str):
        """Remove embeddings for a specific file (e.g. after it was deleted)."""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM codebase_embeddings WHERE workspace_path = ? AND file_path = ?", (str(self.workspace_path), relative_path))
            await db.commit()
