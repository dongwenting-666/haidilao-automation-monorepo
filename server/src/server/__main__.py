import uvicorn

from server.config import settings

uvicorn.run(
    "server.app:app",
    host=settings.server_host,
    port=settings.server_port,
    log_level="info",
    proxy_headers=True,
    forwarded_allow_ips="127.0.0.1",
)
