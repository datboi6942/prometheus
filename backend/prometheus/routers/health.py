from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from prometheus.config import settings
from prometheus.services.model_router import ModelRouter

router = APIRouter()


def get_model_router() -> ModelRouter:
    """Dependency provider for ModelRouter.

    Returns:
        ModelRouter: An instance of ModelRouter.
    """
    return ModelRouter(settings)


@router.get("/ping")
async def ping() -> dict[str, str]:
    """Health check endpoint.

    Returns:
        dict[str, str]: A dictionary indicating the status is 'ok'.
    """
    return {"status": "ok"}


@router.get("/health/ollama")
async def health_ollama(
    model_router: Annotated[ModelRouter, Depends(get_model_router)]
) -> dict[str, str]:
    """Verify connectivity to local Ollama instance.

    Args:
        model_router (Annotated[ModelRouter, Depends(get_model_router)]):
            The injected ModelRouter service.

    Returns:
        dict[str, str]: A dictionary with the status and Ollama's response.

    Raises:
        HTTPException: If connectivity to Ollama fails.
    """
    try:
        result = await model_router.complete(
            model="ollama/llama3.2",
            messages=[{"role": "user", "content": "Say 'pong'"}],
        )
        return {"status": "ok", "response": result}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Ollama connectivity failed: {str(e)}") from e
