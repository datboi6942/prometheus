import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from prometheus.config import settings
from prometheus.database import init_db
from prometheus.routers import chat, conversations, files, health

# Configure structlog
structlog.configure(
    processors=[
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

app = FastAPI(
    title="Prometheus API",
    description="Backend for the Prometheus AI Agent IDE",
    version="0.1.0",
    debug=settings.debug,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health.router)
app.include_router(chat.router)
app.include_router(files.router)
app.include_router(conversations.router)


@app.on_event("startup")
async def startup_event() -> None:
    """Run startup tasks."""
    logger.info("Starting Prometheus API", log_level=settings.log_level)
    # Initialize database
    await init_db()
    logger.info("Database initialized")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
