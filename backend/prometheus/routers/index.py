import json
import asyncio
from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import structlog
from prometheus.services.codebase_index import CodebaseIndex
from prometheus.config import settings, translate_host_path_to_container
from prometheus.database import get_all_settings

router = APIRouter(prefix="/api/v1/index")
logger = structlog.get_logger()

@router.get("/stream")
async def stream_index_progress(workspace_path: str = Query(...)):
    """Trigger workspace indexing and stream progress via SSE."""
    if not workspace_path:
        return {"error": "Workspace path is required"}
        
    translated_workspace = translate_host_path_to_container(workspace_path)
    logger.info("Indexing stream requested", workspace_path=workspace_path, translated=translated_workspace)
    
    # Get API key from DB
    db_settings = await get_all_settings()
    api_key = db_settings.get("openai_api_key")
    
    index = CodebaseIndex(translated_workspace, api_key=api_key)

    async def event_generator():
        queue = asyncio.Queue()
        
        async def async_callback(msg):
            await queue.put(msg)
            
        # Start indexing in background
        indexing_task = asyncio.create_task(index.index_workspace(progress_callback=async_callback))
        
        try:
            while not indexing_task.done() or not queue.empty():
                try:
                    # Wait for messages with a timeout to check if task is done
                    # We use a shorter timeout for better responsiveness
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield f"data: {json.dumps(msg)}\n\n"
                    queue.task_done()
                    
                    # If we got an "already in progress" error, we can stop here
                    if msg.get("status") == "error" and "already in progress" in msg.get("error", ""):
                        break
                except asyncio.TimeoutError:
                    # Just a way to check if indexing_task is done while waiting for queue
                    continue
                except Exception as e:
                    logger.error("Error in indexing progress stream", error=str(e))
                    yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
                    break
            
            # Ensure we send the final result if it wasn't already sent by the task
            if indexing_task.done():
                try:
                    result = indexing_task.result()
                    if result.get("success"):
                        # Ensure final status includes counts for the UI
                        final_data = {
                            'status': 'completed', 
                            'result': result,
                            'total': result.get('total_files', 0),
                            'current': result.get('total_files', 0),
                            'percent': 100
                        }
                        yield f"data: {json.dumps(final_data)}\n\n"
                except Exception as e:
                    # Task might have failed or been cancelled
                    if not str(e).startswith("Indexing already in progress"):
                        logger.error("Indexing task failed", error=str(e))
                        yield f"data: {json.dumps({'status': 'error', 'error': str(e)})}\n\n"
        finally:
            if not indexing_task.done():
                indexing_task.cancel()

    return StreamingResponse(
        event_generator(), 
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
