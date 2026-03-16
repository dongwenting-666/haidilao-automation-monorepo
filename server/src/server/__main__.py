import uvicorn

from server.config import settings

uvicorn.run(
    "server.app:app",
    host=settings.server_host,
    port=settings.server_port,
    log_level="info",
)
