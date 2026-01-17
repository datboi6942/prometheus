import json
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from prometheus.routers.health import get_model_router
from prometheus.services.model_router import ModelRouter

router = APIRouter(prefix="/api/v1/chat")


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: str
    messages: list[ChatMessage]
    api_base: str | None = None
    api_key: str | None = None


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    model_router: Annotated[ModelRouter, Depends(get_model_router)],
) -> StreamingResponse:
    """Server-Sent Events (SSE) endpoint for streaming model responses.

    Args:
        request (ChatRequest): The chat request configuration.
        model_router (ModelRouter): The injected model router.

    Returns:
        StreamingResponse: A stream of events from the model.
    """

    async def event_generator():
        try:
            # Convert ChatMessage objects to dicts for LiteLLM
            messages = [msg.model_dump() for msg in request.messages]

            async for chunk in model_router.stream(
                model=request.model,
                messages=messages,
                api_base=request.api_base,
                api_key=request.api_key,
            ):
                # LiteLLM chunk processing
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    data = json.dumps({"thought": None, "token": content})
                    yield f"data: {data}\n\n"

            yield "data: [DONE]\n\n"
        except Exception as e:
            error_data = json.dumps({"error": str(e)})
            yield f"data: {error_data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
